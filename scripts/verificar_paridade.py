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
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent.parent

GOLDEN_PATH: Path = BASE_DIR / "tests" / "golden" / "agregados_gold.json"

# As metricas sao somadas com `round(...)::text` porque a comparacao precisa
# ser exata: converter para float introduziria diferenca de representacao onde
# nao houve mudanca de dado.
_METRICAS: list[str] = [
    "spend", "impressions", "link_clicks", "conversions",
    "conversion_value", "video_views", "reach", "profile_views", "purchases",
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
    """Compara duas estruturas e descreve cada divergencia encontrada.

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

    problemas = _diferencas(golden["agregados"], atual)

    if not problemas:
        linhas = atual["totais_fato"]["linhas"]
        print(f"PARIDADE OK — {linhas} linhas no fato, todos os agregados batem.")
        print(f"  golden de {golden['gerado_em']}")
        return 0

    print(f"PARIDADE QUEBRADA — {len(problemas)} divergencia(s):", file=sys.stderr)
    for problema in problemas:
        print(f"  - {problema}", file=sys.stderr)
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
