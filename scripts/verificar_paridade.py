"""Congela e confere os numeros do Data Warehouse — rede de seguranca da refatoracao.

Por que existe
--------------
Os 72 testes do dbt verificam ESTRUTURA: unicidade, nao-nulidade, dominio,
integridade referencial. Nenhum deles verifica se o numero continua o mesmo.
Este repositorio ja demonstrou tres vezes que "os testes passaram" nao e
evidencia de correcao:

- o `union all` casando colunas por posicao trocou metricas do Google entre si
  e passou nos 65 testes de entao;
- o filtro `campaign.status` apagou R$ 210,57 de uma reextracao sem falhar
  nada;
- o join pela chave natural sem resolver a versao SCD2 inflou o investimento
  total em 7,8% — e o resultado continuava sendo uma tabela plausivel.

Refatoracao nao pode mudar numero. Este script torna isso verificavel: congela
os agregados canonicos antes de mexer no codigo e confere depois.

Uso
---
    python scripts/verificar_paridade.py congelar   # grava o golden
    python scripts/verificar_paridade.py verificar  # compara; exit 1 se divergir

Como a comparacao funciona
--------------------------
`verificar` continua saindo com 0 quando tudo bate e 1 quando qualquer numero
diverge. O que mudou e o RELATORIO.

As colecoes com identidade natural (`_CHAVES_NATURAIS`) sao comparadas por
chave, e cada chave e classificada:

- NOVO      — chave presente agora e ausente no golden;
- REMOVIDO  — chave que existia no golden e sumiu;
- ALTERADO  — chave nos dois lados, com pelo menos um campo diferente (o
              relatorio mostra campo, valor do golden, valor atual e delta);
- IDENTICO  — chave nos dois lados sem nenhuma diferenca (so contada).

Consequencia pratica: **ordem de lista nao e divergencia**. Antes, um dia novo
em `por_plataforma_dia` deslocava todas as posicoes seguintes e produzia
dezenas de "era X, agora Y" falsos — foi o que aconteceu no primeiro DagRun
real (17/08/2026), com 77 diferencas relatadas enquanto as 10 chaves
historicas estavam intactas. As estruturas sem chave natural continuam na
comparacao recursiva de `_diferencas`.

A deteccao nao arredonda nem converte para float: compara os valores como
estao gravados. Arredondamento existe so na apresentacao do delta.

Quando o dado muda de verdade
-----------------------------
Uma extracao nova legitimamente altera os numeros (metricas mudam
retroativamente). Nesse caso o golden deve ser recongelado DE PROPOSITO, com
`congelar`, e a mudanca aparece no diff do commit — que e exatamente onde ela
deve ser revisada. O que o script impede e a alteracao silenciosa.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent.parent

GOLDEN_PATH: Path = BASE_DIR / "tests" / "golden" / "agregados_gold.json"

# Colecoes do golden que tem identidade natural — comparadas POR CHAVE, nunca
# por posicao. Ordem de lista deixa de ser diferenca; dia novo vira NOVO em vez
# de deslocar todo o resto.
#
# Sao so estas duas de proposito: `totais_fato` e `travessia` sao dicts
# escalares, e nada mais no golden tem chave inequivoca. Nao existe framework
# de diff aqui — o que nao esta nesta tabela cai na comparacao recursiva de
# `_diferencas`.
_CHAVES_NATURAIS: dict[str, tuple[str, ...]] = {
    "por_plataforma_dia": ("plataforma", "data"),
    "contagens": ("objeto",),
}

# As metricas sao somadas com `round(...)::text` porque a comparacao precisa
# ser exata: converter para float introduziria diferenca de representacao onde
# nao houve mudanca de dado.
_METRICAS: list[str] = [
    "spend", "impressions", "link_clicks", "conversions",
    "conversion_value", "video_views", "reach", "profile_views", "purchases",
    # `purchase_value` entra na paridade porque e metrica financeira exibida
    # no dashboard: valor que aparece em tela precisa estar coberto pela rede
    # de seguranca, senao uma mudanca de mapeamento passa sem ninguem notar —
    # que foi exatamente o que aconteceu com `conversion_value` do Meta.
    "purchase_value",
]

# Travessia da hierarquia resolvendo a versao vigente pela data do fato.
# A clausula de validade em cada nivel NAO e opcional: sem ela o join vira
# 1:N e infla os agregados. Ver `assert_join_dimensional_nao_infla`.
#
# NAO SUBSTITUIR por `from gold.vw_metricas_completas`. Desde a Fase 6 essa
# view e a travessia oficial e todos os consumidores usam ela — este script e
# a excecao deliberada. Ele e o oraculo da rede de seguranca: seu valor esta em
# ser uma SEGUNDA implementacao, independente, que precisa concordar com a
# primeira. Se passasse a ler a view, um erro na view viraria um erro no
# verificador e a divergencia deixaria de ser detectavel — o golden validaria
# a si mesmo. E o unico lugar do repositorio onde duplicar e o certo.
_TRAVESSIA: str = """
    from gold.fato_metricas f
    join gold.dim_tempo t
        on t.tempo_sk = f.tempo_sk
    join gold.dim_anuncio a
        on a.anuncio_sk = f.anuncio_sk
    join gold.dim_adset s
        on  s.adset_nk = a.adset_nk
        and t.data between s.valido_de and s.valido_ate
    join gold.dim_campanha c
        on  c.campanha_nk = s.campanha_nk
        and t.data between c.valido_de and c.valido_ate
    join gold.dim_conta ct
        on  ct.conta_nk = c.conta_nk
        and t.data between ct.valido_de and ct.valido_ate
    join gold.dim_plataforma p
        on p.plataforma_sk = ct.plataforma_sk
"""


def _conectar():
    """Abre conexao com o Data Warehouse.

    Returns:
        Conexao psycopg2 aberta.

    Raises:
        SystemExit: Se a URL do banco nao estiver configurada.
    """
    import psycopg2

    from config import get_db_url

    url = get_db_url()
    if not url:
        sys.exit("Defina DW_DB_URL com a URL do Data Warehouse.")
    return psycopg2.connect(url)


def _somas_sql() -> str:
    """Monta a lista de somas das 9 metricas como texto exato.

    Returns:
        Trecho SQL com uma soma por metrica, ja arredondada e convertida.
    """
    return ",\n           ".join(
        f"round(sum(f.{m}), 6)::text as {m}" for m in _METRICAS
    )


def coletar(conn) -> dict:
    """Coleta os agregados canonicos da camada gold.

    Cobre tres angulos deliberadamente redundantes: o agregado por plataforma
    e dia (o resultado analitico do trabalho), os totais lidos direto do fato
    (sem join, imunes a erro de travessia) e as contagens estruturais. Uma
    refatoracao que quebre a travessia e mantenha o fato intacto aparece na
    divergencia entre o primeiro e o segundo.

    Args:
        conn: Conexao aberta com o Data Warehouse.

    Returns:
        Dict serializavel com os blocos ``por_plataforma_dia``,
        ``totais_fato``, ``contagens`` e ``travessia``.
    """
    somas = _somas_sql()
    resultado: dict = {}

    with conn.cursor() as cur:
        # 1. Resultado analitico: plataforma x dia, pela travessia completa.
        cur.execute(f"""
            select p.nome as plataforma,
                   t.data::text as data,
                   count(*) as linhas,
                   {somas}
            {_TRAVESSIA}
            group by p.nome, t.data
            order by p.nome, t.data
        """)
        colunas = [d[0] for d in cur.description]
        resultado["por_plataforma_dia"] = [
            dict(zip(colunas, linha)) for linha in cur.fetchall()
        ]

        # 2. Totais direto do fato, sem nenhum join.
        cur.execute(f"""
            select count(*) as linhas,
                   {somas}
            from gold.fato_metricas f
        """)
        colunas = [d[0] for d in cur.description]
        resultado["totais_fato"] = dict(zip(colunas, cur.fetchone()))

        # 3. Contagens estruturais: entidades e versoes de cada dimensao.
        cur.execute("""
            select 'silver.stg_ads_unified' as objeto,
                   count(*) as linhas, null::bigint as entidades
            from silver.stg_ads_unified
            union all select 'gold.fato_metricas', count(*), null
            from gold.fato_metricas
            union all select 'gold.dim_plataforma', count(*),
                   count(distinct plataforma_sk) from gold.dim_plataforma
            union all select 'gold.dim_conta', count(*),
                   count(distinct conta_nk) from gold.dim_conta
            union all select 'gold.dim_campanha', count(*),
                   count(distinct campanha_nk) from gold.dim_campanha
            union all select 'gold.dim_adset', count(*),
                   count(distinct adset_nk) from gold.dim_adset
            union all select 'gold.dim_anuncio', count(*),
                   count(distinct anuncio_nk) from gold.dim_anuncio
            union all select 'gold.dim_tempo', count(*),
                   count(distinct data) from gold.dim_tempo
            order by 1
        """)
        colunas = [d[0] for d in cur.description]
        resultado["contagens"] = [
            dict(zip(colunas, linha)) for linha in cur.fetchall()
        ]

        # 4. A travessia devolve exatamente uma linha por linha do fato?
        #    Redundante com o teste dbt de mesmo nome, de proposito: aqui o
        #    numero fica gravado, la ele so precisa ser zero.
        cur.execute(f"""
            select (select count(*) {_TRAVESSIA}) as via_hierarquia,
                   (select count(*) from gold.fato_metricas) as no_fato
        """)
        colunas = [d[0] for d in cur.description]
        resultado["travessia"] = dict(zip(colunas, cur.fetchone()))

    return _normalizar(resultado)


def _normalizar(valor):
    """Converte Decimal e datas em tipos serializaveis, recursivamente.

    Args:
        valor: Estrutura arbitraria vinda do banco.

    Returns:
        A mesma estrutura, com ``Decimal`` viradas texto.
    """
    if isinstance(valor, dict):
        return {k: _normalizar(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_normalizar(v) for v in valor]
    if isinstance(valor, Decimal):
        return str(valor)
    return valor


def congelar() -> None:
    """Grava o estado atual da gold como referencia (golden snapshot)."""
    with _conectar() as conn:
        dados = coletar(conn)

    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    conteudo = {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "agregados": dados,
    }
    GOLDEN_PATH.write_text(
        json.dumps(conteudo, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    linhas = dados["totais_fato"]["linhas"]
    print(f"Golden gravado em {GOLDEN_PATH.relative_to(BASE_DIR)}")
    print(f"  fato: {linhas} linhas | investimento: {dados['totais_fato']['spend']}")


def _diferencas(esperado, obtido, caminho: str = "") -> list[str]:
    """Compara duas estruturas por posicao/recursao e descreve as divergencias.

    Usada nas estruturas SEM chave natural (``totais_fato``, ``travessia`` e
    qualquer bloco novo que apareca no golden). Para as colecoes listadas em
    ``_CHAVES_NATURAIS`` quem compara e ``_comparar_por_chave``.

    Args:
        esperado: Valor do golden.
        obtido: Valor lido do banco agora.
        caminho: Prefixo usado na mensagem, montado na recursao.

    Returns:
        Lista de descricoes legiveis. Vazia se forem iguais.
    """
    if isinstance(esperado, dict) and isinstance(obtido, dict):
        problemas: list[str] = []
        for chave in sorted(set(esperado) | set(obtido)):
            sub = f"{caminho}.{chave}" if caminho else str(chave)
            if chave not in esperado:
                problemas.append(f"{sub}: surgiu (agora {obtido[chave]!r})")
            elif chave not in obtido:
                problemas.append(f"{sub}: sumiu (era {esperado[chave]!r})")
            else:
                problemas += _diferencas(esperado[chave], obtido[chave], sub)
        return problemas

    if isinstance(esperado, list) and isinstance(obtido, list):
        problemas = []
        if len(esperado) != len(obtido):
            problemas.append(
                f"{caminho}: {len(esperado)} registros no golden, "
                f"{len(obtido)} agora"
            )
        for i, (e, o) in enumerate(zip(esperado, obtido)):
            problemas += _diferencas(e, o, f"{caminho}[{i}]")
        return problemas

    if esperado != obtido:
        return [f"{caminho}: era {esperado!r}, agora {obtido!r}"]
    return []


class _Ausente:
    """Marcador para campo que existe de um lado so."""

    def __repr__(self) -> str:
        return "<ausente>"


_AUSENTE = _Ausente()


@dataclass(frozen=True)
class CampoAlterado:
    """Um campo que mudou dentro de um item identificado por chave."""

    campo: str
    golden: object
    atual: object


@dataclass(frozen=True)
class ItemAlterado:
    """Item presente nos dois lados, com pelo menos um campo diferente."""

    chave: tuple[str, ...]
    campos: tuple[CampoAlterado, ...]


@dataclass(frozen=True)
class DiffKeyed:
    """Resultado da comparacao por chave natural de uma colecao."""

    nome: str
    chave: tuple[str, ...]
    novas: tuple[tuple[str, ...], ...]
    removidas: tuple[tuple[str, ...], ...]
    alteradas: tuple[ItemAlterado, ...]
    identicas: int

    @property
    def divergencias(self) -> int:
        """Quantas chaves divergem: novas + removidas + alteradas."""
        return len(self.novas) + len(self.removidas) + len(self.alteradas)


@dataclass(frozen=True)
class Divergencias:
    """Tudo o que difere entre o golden e o estado atual."""

    keyed: tuple[DiffKeyed, ...]
    outros: tuple[str, ...]

    @property
    def total(self) -> int:
        """Numero de divergencias, somando as keyed e as demais."""
        return sum(d.divergencias for d in self.keyed) + len(self.outros)

    def houve(self) -> bool:
        """Diz se existe qualquer divergencia."""
        return self.total > 0


def _indexar(colecao, campos: tuple[str, ...]) -> dict | None:
    """Indexa uma colecao pela chave natural.

    Args:
        colecao: Valor vindo do golden ou do banco.
        campos: Campos que formam a chave.

    Returns:
        Dict ``chave -> item``, ou ``None`` se a colecao nao for indexavel
        (nao e lista de dicts, falta campo de chave ou a chave se repete).
        ``None`` nunca e sucesso silencioso: quem chama cai para a comparacao
        posicional e registra o aviso.
    """
    if not isinstance(colecao, list):
        return None

    indice: dict[tuple[str, ...], dict] = {}
    for item in colecao:
        if not isinstance(item, dict):
            return None
        if any(campo not in item for campo in campos):
            return None
        # Chave sempre como texto, na ordem declarada em `_CHAVES_NATURAIS`.
        chave = tuple(str(item[campo]) for campo in campos)
        if chave in indice:
            return None
        indice[chave] = item
    return indice


def _campos_alterados(
    esperado: dict, obtido: dict, campos_chave: tuple[str, ...]
) -> tuple[CampoAlterado, ...]:
    """Lista os campos que mudaram entre duas versoes do mesmo item.

    A comparacao usa os valores originais — sem arredondar, sem converter para
    float. Formatacao e assunto do relatorio, nao da deteccao.

    Args:
        esperado: Item do golden.
        obtido: Item atual.
        campos_chave: Campos que formam a chave (nao entram na comparacao,
            por definicao sao iguais dos dois lados).

    Returns:
        Tupla ordenada por nome de campo, para o relatorio ser deterministico.
    """
    alterados: list[CampoAlterado] = []
    for campo in sorted(set(esperado) | set(obtido)):
        if campo in campos_chave:
            continue
        antes = esperado.get(campo, _AUSENTE)
        agora = obtido.get(campo, _AUSENTE)
        if antes != agora:
            alterados.append(CampoAlterado(campo, antes, agora))
    return tuple(alterados)


def _comparar_por_chave(
    nome: str, esperado, obtido, campos: tuple[str, ...]
) -> tuple[DiffKeyed | None, str | None]:
    """Compara uma colecao por chave natural, ignorando a ordem dos itens.

    Args:
        nome: Nome do bloco no golden.
        esperado: Colecao do golden.
        obtido: Colecao atual.
        campos: Campos que formam a chave.

    Returns:
        ``(DiffKeyed, None)`` em caso normal; ``(None, aviso)`` quando a
        colecao nao pode ser indexada e a comparacao precisa cair para o
        modo posicional.
    """
    indice_esperado = _indexar(esperado, campos)
    indice_obtido = _indexar(obtido, campos)
    if indice_esperado is None or indice_obtido is None:
        return None, (
            f"{nome}: nao foi possivel indexar por "
            f"({', '.join(campos)}) — item sem campo de chave, chave "
            "repetida ou formato inesperado; comparado por posicao"
        )

    chaves_esperadas = set(indice_esperado)
    chaves_obtidas = set(indice_obtido)

    alteradas: list[ItemAlterado] = []
    identicas = 0
    for chave in sorted(chaves_esperadas & chaves_obtidas):
        campos_alterados = _campos_alterados(
            indice_esperado[chave], indice_obtido[chave], campos
        )
        if campos_alterados:
            alteradas.append(ItemAlterado(chave, campos_alterados))
        else:
            identicas += 1

    diff = DiffKeyed(
        nome=nome,
        chave=tuple(campos),
        novas=tuple(sorted(chaves_obtidas - chaves_esperadas)),
        removidas=tuple(sorted(chaves_esperadas - chaves_obtidas)),
        alteradas=tuple(alteradas),
        identicas=identicas,
    )
    return diff, None


def comparar(esperado: dict, obtido: dict) -> Divergencias:
    """Compara o golden com o estado atual e devolve as diferencas.

    Nao imprime, nao decide exit code e nao altera nenhum dos dois lados:
    a deteccao fica separada da apresentacao (`formatar`) e da CLI.

    Args:
        esperado: Bloco ``agregados`` do golden.
        obtido: Agregados coletados agora.

    Returns:
        Estrutura ``Divergencias``, vazia quando os dois lados sao iguais.
    """
    keyed: list[DiffKeyed] = []
    outros: list[str] = []

    for nome in sorted(set(esperado) | set(obtido)):
        if nome not in esperado:
            outros.append(f"{nome}: surgiu (agora {obtido[nome]!r})")
            continue
        if nome not in obtido:
            outros.append(f"{nome}: sumiu (era {esperado[nome]!r})")
            continue

        campos = _CHAVES_NATURAIS.get(nome)
        if campos is None:
            outros += _diferencas(esperado[nome], obtido[nome], nome)
            continue

        diff, aviso = _comparar_por_chave(
            nome, esperado[nome], obtido[nome], campos
        )
        if diff is None:
            outros.append(aviso)
            outros += _diferencas(esperado[nome], obtido[nome], nome)
        else:
            keyed.append(diff)

    return Divergencias(keyed=tuple(keyed), outros=tuple(outros))


def _numero(valor) -> Decimal | None:
    """Converte para Decimal quando o valor for numerico de verdade.

    Args:
        valor: Valor do golden ou atual.

    Returns:
        ``Decimal`` finito, ou ``None`` quando o valor nao e numerico.
    """
    if isinstance(valor, bool) or isinstance(valor, _Ausente) or valor is None:
        return None
    if isinstance(valor, Decimal):
        numero = valor
    elif isinstance(valor, (int, float)):
        numero = Decimal(str(valor))
    elif isinstance(valor, str):
        try:
            numero = Decimal(valor)
        except InvalidOperation:
            return None
    else:
        return None
    return numero if numero.is_finite() else None


def _texto_numero(numero: Decimal) -> str:
    """Formata um Decimal sem notacao exponencial e sem zeros a direita.

    Args:
        numero: Valor a apresentar.

    Returns:
        Texto legivel: ``1568.96``, ``170``, ``-11.16``.
    """
    texto = format(numero, "f")
    if "." in texto:
        texto = texto.rstrip("0").rstrip(".")
    return texto or "0"


def _apresentar(valor) -> str:
    """Devolve a forma legivel de um valor para o relatorio.

    Args:
        valor: Valor do golden ou atual.

    Returns:
        Numero enxuto quando for numerico; ``repr`` caso contrario.
    """
    numero = _numero(valor)
    return _texto_numero(numero) if numero is not None else repr(valor)


def _delta(golden, atual) -> str | None:
    """Descreve a variacao entre dois valores numericos.

    Apresentacao apenas: a divergencia ja foi detectada com os valores
    originais, na precisao em que o projeto os grava.

    Args:
        golden: Valor do golden.
        atual: Valor atual.

    Returns:
        Texto como ``+11.16 (+0.71%)``, ou ``None`` se algum lado nao for
        numerico. O percentual sai fora quando o golden e zero — nao ha
        variacao relativa a partir de zero — e vira ``<0.01%`` quando a
        variacao existe mas some no arredondamento.
    """
    antes = _numero(golden)
    agora = _numero(atual)
    if antes is None or agora is None:
        return None

    diferenca = agora - antes
    texto = f"{'+' if diferenca > 0 else ''}{_texto_numero(diferenca)}"
    if antes != 0:
        percentual = (diferenca / abs(antes) * Decimal(100)).quantize(
            Decimal("0.01")
        )
        if percentual == 0:
            # Houve mudanca, mas ela some no arredondamento. Escrever "0%"
            # sugeriria que nada mudou — a divergencia e real.
            texto += f" ({'+' if diferenca > 0 else '-'}<0.01%)"
        else:
            sinal = "+" if percentual > 0 else ""
            texto += f" ({sinal}{_texto_numero(percentual)}%)"
    return texto


def formatar(divergencias: Divergencias) -> list[str]:
    """Transforma as divergencias em relatorio legivel.

    Args:
        divergencias: Estrutura devolvida por `comparar`.

    Returns:
        Linhas do relatorio. A ordem depende so do conteudo, nunca da ordem
        em que os itens chegaram.
    """
    linhas = [f"PARIDADE DIVERGENTE — {divergencias.total} divergencia(s)"]

    for diff in divergencias.keyed:
        if diff.divergencias == 0:
            continue
        linhas.append("")
        linhas.append(f"{diff.nome} (chave: {' | '.join(diff.chave)}):")
        linhas.append(f"  novas:     {len(diff.novas)}")
        linhas.append(f"  removidas: {len(diff.removidas)}")
        linhas.append(f"  alteradas: {len(diff.alteradas)}")
        linhas.append(f"  identicas: {diff.identicas}")

        if diff.novas:
            linhas.append("  NOVO:")
            linhas += [f"    + {' | '.join(chave)}" for chave in diff.novas]
        if diff.removidas:
            linhas.append("  REMOVIDO:")
            linhas += [f"    - {' | '.join(chave)}" for chave in diff.removidas]
        if diff.alteradas:
            linhas.append("  ALTERADO:")
            for item in diff.alteradas:
                linhas.append(f"    ~ {' | '.join(item.chave)}")
                for campo in item.campos:
                    linhas.append(f"        {campo.campo}:")
                    linhas.append(f"          golden: {_apresentar(campo.golden)}")
                    linhas.append(f"          atual:  {_apresentar(campo.atual)}")
                    delta = _delta(campo.golden, campo.atual)
                    if delta is not None:
                        linhas.append(f"          delta:  {delta}")

    if divergencias.outros:
        linhas.append("")
        linhas.append("outros:")
        linhas += [f"  - {problema}" for problema in divergencias.outros]

    return linhas


def verificar() -> int:
    """Compara o estado atual da gold com o golden gravado.

    Returns:
        ``0`` se identico, ``1`` se houver qualquer divergencia.
    """
    if not GOLDEN_PATH.exists():
        print(
            f"Golden nao encontrado em {GOLDEN_PATH.relative_to(BASE_DIR)}.\n"
            "Rode `python scripts/verificar_paridade.py congelar` primeiro.",
            file=sys.stderr,
        )
        return 1

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    with _conectar() as conn:
        atual = coletar(conn)

    divergencias = comparar(golden["agregados"], atual)

    if not divergencias.houve():
        linhas = atual["totais_fato"]["linhas"]
        print(f"PARIDADE OK — {linhas} linhas no fato, todos os agregados batem.")
        print(f"  golden de {golden['gerado_em']}")
        return 0

    for linha in formatar(divergencias):
        print(linha, file=sys.stderr)
    print(
        "\nSe a mudanca for legitima (extracao nova, correcao deliberada), "
        "recongele com `congelar` e revise o diff no commit.",
        file=sys.stderr,
    )
    return 1


def main() -> None:
    """Entry point da CLI."""
    parser = argparse.ArgumentParser(
        description="Congela e confere os agregados da camada gold.",
    )
    parser.add_argument(
        "acao",
        choices=["congelar", "verificar"],
        help="congelar: grava o golden. verificar: compara com o golden.",
    )
    args = parser.parse_args()

    if args.acao == "congelar":
        congelar()
    else:
        sys.exit(verificar())


if __name__ == "__main__":
    main()
