"""Audita o artefato de exposicao antes de qualquer material sair daqui.

Independencia deliberada
------------------------
Este script **nao** importa `pseudonimos.py` nem nada do exportador. Ele
recebe o artefato pronto e nao sabe como foi produzido: declara por conta
propria o schema esperado, os padroes proibidos e os invariantes, e prova que
o arquivo os respeita.

E a mesma razao pela qual `scripts/verificar_paridade.py` mantem a travessia
SCD2 escrita a mao em vez de ler a view oficial. Um auditor que compartilha
codigo com o produtor valida a si mesmo: um erro na pseudonimizacao passaria
nos dois lados e a auditoria daria verde. Duplicar aqui e o certo.

O que verifica
--------------
Sem banco (roda em qualquer maquina, inclusive no dia da Defesa):
schema exato, formato dos identificadores publicos, grao, hierarquia,
colisao, ausencia de URL/dominio/e-mail/telefone/CNPJ/tratamento pessoal,
ausencia de coluna proibida, versoes e datas validas, sha256 do manifesto.

Com banco: deriva do Gold, por conta propria, os valores que **nao** podem
aparecer — nomes, external IDs, chaves naturais e substitutas — e prova que
nenhum deles esta no artefato. Confere ainda contagem, datas, agregados por
(plataforma, data), cardinalidade dos quatro niveis e distribuicao de versoes
SCD2.

Uso
---
    python scripts/auditar_dataset_exposicao.py
    python scripts/auditar_dataset_exposicao.py --sem-dw

Exit 0 = aprovado. Exit 1 = qualquer violacao. Nenhuma mensagem de falha
reproduz valor identificavel: aponta coluna, contagem e quantidade.
"""

import argparse
import csv
import hashlib
import json
import logging
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import config  # noqa: F401  — importar carrega o .env (unico load_dotenv)
from config import configurar_logging, get_db_url

BASE_DIR: Path = Path(__file__).resolve().parent.parent

DIRETORIO_PADRAO: Path = BASE_DIR / "data" / "exposicao"
NOME_CSV: str = "metricas.csv"
NOME_MANIFESTO: str = "manifesto.json"

# Schema esperado, declarado AQUI de proposito. Se o exportador mudar o
# contrato sem que esta lista mude junto, a auditoria reprova — que e o
# comportamento desejado.
COLUNAS_ESPERADAS: tuple[str, ...] = (
    "data",
    "plataforma",
    "conta_id",
    "conta_versao",
    "campanha_id",
    "campanha_versao",
    "adset_id",
    "adset_versao",
    "anuncio_id",
    "anuncio_versao",
    "spend",
    "impressions",
    "link_clicks",
    "conversions",
    "conversion_value",
    "video_views",
    "reach",
    "profile_views",
    "purchases",
)

NIVEIS: tuple[str, ...] = ("conta", "campanha", "adset", "anuncio")

METRICAS: tuple[str, ...] = (
    "spend", "impressions", "link_clicks", "conversions",
    "conversion_value", "video_views", "reach", "profile_views", "purchases",
)

PLATAFORMAS_ACEITAS: frozenset[str] = frozenset({"Meta Ads", "Google Ads"})

# Formato dos identificadores publicos. E o que impede um nome real de se
# esconder dentro de uma celula de texto: se a celula casa com isto, nao ha
# espaco para carregar outra coisa.
FORMATO_ID: dict[str, re.Pattern] = {
    "conta_id": re.compile(r"^Cliente-[0-9A-F]{8}$"),
    "campanha_id": re.compile(r"^Campanha-[0-9A-F]{8}$"),
    "adset_id": re.compile(r"^AdSet-[0-9A-F]{8}$"),
    "anuncio_id": re.compile(r"^Anuncio-[0-9A-F]{8}$"),
}

# Sufixos de coluna que jamais podem aparecer no cabecalho.
SUFIXOS_PROIBIDOS: tuple[str, ...] = ("_nk", "_sk", "_external_id", "_nome")

PADROES_PROIBIDOS: dict[str, re.Pattern] = {
    "url": re.compile(r"https?://", re.I),
    "www": re.compile(r"\bwww\.", re.I),
    "dominio": re.compile(
        r"\b[\w-]+\.(com|com\.br|net|org|app|io|shop|store|med|adv|br)\b", re.I
    ),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "telefone": re.compile(r"\(?\d{2}\)?\s?9?\d{4}-?\d{4}"),
    "cnpj": re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}"),
    "tratamento_pessoal": re.compile(r"\b(dr|dra|drª)\.?\s", re.I),
    "arroba": re.compile(r"@[\w.]+"),
}

# Comprimento minimo para procurar um valor real dentro do artefato. Abaixo
# disso o teste vira ruido: uma sigla de duas letras casa com qualquer coisa.
TAMANHO_MINIMO_BUSCA: int = 4

logger = logging.getLogger(__name__)


def _conectar():
    """Abre conexao com o Data Warehouse.

    Returns:
        Conexao psycopg2 aberta, ou ``None`` se nao houver URL configurada.
    """
    import psycopg2

    url = get_db_url()
    if not url:
        return None
    return psycopg2.connect(url)


def carregar_csv(caminho: Path) -> tuple[list[str], list[dict], str]:
    """Le o artefato preservando o texto exato.

    Args:
        caminho: Caminho do CSV.

    Returns:
        Tupla ``(cabecalho, linhas, texto_bruto)``. As linhas mantem os
        valores como texto — a auditoria nunca converte antes de comparar.
    """
    texto = caminho.read_text(encoding="utf-8")
    leitor = csv.reader(texto.splitlines())
    cabecalho = next(leitor, [])
    linhas = [dict(zip(cabecalho, campos)) for campos in leitor]
    return cabecalho, linhas, texto


def _decimal(valor: str):
    """Converte para Decimal quando possivel.

    Args:
        valor: Texto da celula.

    Returns:
        ``Decimal`` ou ``None`` se nao for numero.
    """
    try:
        return Decimal(valor)
    except (InvalidOperation, ValueError):
        return None


def checar_schema(cabecalho: list[str]) -> list[str]:
    """Confere o cabecalho contra o contrato.

    Args:
        cabecalho: Colunas lidas do CSV.

    Returns:
        Lista de falhas.
    """
    falhas: list[str] = []

    if tuple(cabecalho) != COLUNAS_ESPERADAS:
        extras = sorted(set(cabecalho) - set(COLUNAS_ESPERADAS))
        faltando = sorted(set(COLUNAS_ESPERADAS) - set(cabecalho))
        if extras:
            falhas.append(f"coluna inesperada no artefato: {extras}")
        if faltando:
            falhas.append(f"coluna obrigatoria ausente: {faltando}")
        if not extras and not faltando:
            falhas.append("ordem das colunas diverge do contrato")

    for coluna in cabecalho:
        for sufixo in SUFIXOS_PROIBIDOS:
            if coluna.endswith(sufixo):
                falhas.append(f"coluna proibida no artefato: termina em {sufixo}")

    return falhas


def checar_conteudo(linhas: list[dict]) -> list[str]:
    """Verifica formato, grao, hierarquia, colisao, versoes e datas.

    Args:
        linhas: Linhas do artefato, como texto.

    Returns:
        Lista de falhas, sem reproduzir valor algum.
    """
    falhas: list[str] = []
    if not linhas:
        return ["artefato sem linhas"]

    # Formato dos identificadores publicos.
    for coluna, padrao in FORMATO_ID.items():
        fora = sum(1 for l in linhas if not padrao.fullmatch(l.get(coluna, "")))
        if fora:
            falhas.append(
                f"{fora} valor(es) de {coluna} fora do formato de pseudonimo"
            )

    # Plataforma.
    fora = sum(1 for l in linhas if l["plataforma"] not in PLATAFORMAS_ACEITAS)
    if fora:
        falhas.append(f"{fora} linha(s) com plataforma fora do dominio aceito")

    # Grao unico.
    graos = {(l["anuncio_id"], l["data"]) for l in linhas}
    if len(graos) != len(linhas):
        falhas.append(
            f"grao duplicado: {len(linhas)} linhas para {len(graos)} pares "
            "(anuncio_id, data)"
        )

    # Hierarquia: cada filho com exatamente um pai.
    for pai, filho in (("conta", "campanha"), ("campanha", "adset"),
                       ("adset", "anuncio")):
        mapa: dict = {}
        for linha in linhas:
            mapa.setdefault(linha[f"{filho}_id"], set()).add(linha[f"{pai}_id"])
        quebrados = sum(1 for v in mapa.values() if len(v) > 1)
        if quebrados:
            falhas.append(
                f"hierarquia invalida: {quebrados} {filho}(s) com mais de um {pai}"
            )

    # Versoes: inteiro positivo.
    for nivel in NIVEIS:
        ruins = 0
        for linha in linhas:
            bruto = linha[f"{nivel}_versao"]
            if not bruto.isdigit() or int(bruto) < 1:
                ruins += 1
        if ruins:
            falhas.append(f"{ruins} valor(es) de {nivel}_versao nao inteiro >= 1")

    # Datas validas.
    invalidas = 0
    for linha in linhas:
        try:
            datetime.strptime(linha["data"], "%Y-%m-%d")
        except ValueError:
            invalidas += 1
    if invalidas:
        falhas.append(f"{invalidas} data(s) fora do formato YYYY-MM-DD")

    # Metricas numericas.
    for metrica in METRICAS:
        ruins = sum(1 for l in linhas if _decimal(l[metrica]) is None)
        if ruins:
            falhas.append(f"{ruins} valor(es) nao numerico(s) em {metrica}")

    # Conversoes fracionarias: o Google reporta conversao fracionada por
    # modelagem de atribuicao. Se TODAS forem inteiras, alguem converteu para
    # int no caminho — erro que ja custou ~1% das conversoes no ETL legado.
    valores = [_decimal(l["conversions"]) for l in linhas]
    valores = [v for v in valores if v is not None]
    if valores and all(v == v.to_integral_value() for v in valores):
        falhas.append(
            "nenhuma conversao fracionaria no artefato: indicio de conversao "
            "para inteiro"
        )

    return falhas


def checar_padroes(texto: str) -> list[str]:
    """Procura padroes de identificacao no texto inteiro do artefato.

    Args:
        texto: Conteudo bruto do CSV.

    Returns:
        Lista de falhas, nomeando o padrao e a quantidade — nunca o valor.
    """
    falhas: list[str] = []
    for nome, padrao in PADROES_PROIBIDOS.items():
        ocorrencias = len(padrao.findall(texto))
        if ocorrencias:
            falhas.append(
                f"padrao proibido '{nome}' aparece {ocorrencias} vez(es) no artefato"
            )
    return falhas


def checar_manifesto(manifesto: dict, texto_csv: str, linhas: list[dict]) -> list[str]:
    """Confere o manifesto contra o artefato.

    Args:
        manifesto: Manifesto carregado.
        texto_csv: Conteudo bruto do CSV.
        linhas: Linhas do artefato.

    Returns:
        Lista de falhas.
    """
    falhas: list[str] = []

    obrigatorios = (
        "versao_contrato", "gerado_em", "artefato", "sha256", "linhas",
        "data_min", "data_max", "colunas", "tipos", "grao",
        "fingerprint_chave", "avisos",
    )
    ausentes = [c for c in obrigatorios if c not in manifesto]
    if ausentes:
        falhas.append(f"manifesto sem campo(s) obrigatorio(s): {ausentes}")
        return falhas

    sha = hashlib.sha256(texto_csv.encode("utf-8")).hexdigest()
    if sha != manifesto["sha256"]:
        falhas.append("sha256 do CSV nao confere com o declarado no manifesto")

    if manifesto["linhas"] != len(linhas):
        falhas.append(
            f"manifesto declara {manifesto['linhas']} linhas, artefato tem "
            f"{len(linhas)}"
        )

    if list(manifesto["colunas"]) != list(COLUNAS_ESPERADAS):
        falhas.append("lista de colunas do manifesto diverge do contrato")

    datas = sorted(l["data"] for l in linhas)
    if datas and (manifesto["data_min"] != datas[0]
                  or manifesto["data_max"] != datas[-1]):
        falhas.append("janela de datas do manifesto diverge do artefato")

    if "video_views" not in manifesto.get("avisos", {}):
        falhas.append("manifesto sem o aviso semantico de video_views")

    return falhas


def _valores_proibidos(conn) -> dict[str, set[str]]:
    """Deriva do Gold os valores que nao podem aparecer no artefato.

    Consulta as dimensoes diretamente, sem reconstruir a transformacao do
    exportador: o auditor precisa saber o que e proibido, nao como o artefato
    foi produzido.

    Args:
        conn: Conexao aberta com o Data Warehouse.

    Returns:
        Dict ``categoria -> conjunto de valores proibidos``.
    """
    proibidos: dict[str, set[str]] = {
        "nome": set(), "external_id": set(), "nk": set(), "sk": set(),
    }
    tabelas = (
        ("gold.dim_conta", "conta"),
        ("gold.dim_campanha", "campanha"),
        ("gold.dim_adset", "adset"),
        ("gold.dim_anuncio", "anuncio"),
    )
    with conn.cursor() as cur:
        for tabela, entidade in tabelas:
            cur.execute(
                f"select nome, external_id::text, {entidade}_nk, {entidade}_sk "
                f"from {tabela}"
            )
            for nome, external_id, nk, sk in cur.fetchall():
                if nome:
                    proibidos["nome"].add(nome)
                if external_id:
                    proibidos["external_id"].add(external_id)
                if nk:
                    proibidos["nk"].add(nk)
                if sk:
                    proibidos["sk"].add(sk)
    return proibidos


def checar_identidade_contra_dw(conn, linhas: list[dict]) -> list[str]:
    """Prova que nenhum valor real do Gold aparece no artefato.

    A busca e feita em dois regimes, e a distincao veio de dois falsos
    positivos medidos contra o DW real em 18/08/2026:

    1. **Celula estruturada** — identificador que casa com o formato do
       pseudonimo, ou plataforma dentro do dominio fechado. Aqui vale apenas
       IGUALDADE. `AdSet-1A2B3C4D` sao oito digitos hexadecimais atras de um
       prefixo fixo: nao ha espaco para esconder texto, e procurar substring
       dentro disso acusa coincidencia aritmetica. Foi o que aconteceu — um
       anuncio cujo nome real tem quatro caracteres hexadecimais apareceu
       "dentro" de um pseudonimo, sem que o pseudonimo carregasse nada dele.
    2. **Celula livre** — qualquer valor textual que NAO casa com o formato
       esperado. Essa e suspeita por definicao (o check de formato ja a
       reprovou) e recebe busca por substring, que e onde um nome real
       realmente poderia se esconder.

    As colunas nao textuais ficam de fora das duas buscas: datas, versoes e
    metricas ja estao restringidas a formato, inteiro e numero pelos checks
    anteriores. Varrer o texto bruto do CSV, como esta funcao fazia antes,
    acusava qualquer sequencia de digitos presente numa data ou numa metrica.

    Args:
        conn: Conexao aberta com o Data Warehouse.
        linhas: Linhas do artefato.

    Returns:
        Lista de falhas. Reporta categoria e quantidade, nunca o valor.
    """
    estruturadas: set[str] = set()
    livres: set[str] = set()

    for linha in linhas:
        plataforma = linha.get("plataforma", "")
        (estruturadas if plataforma in PLATAFORMAS_ACEITAS else livres).add(
            plataforma
        )
        for coluna, padrao in FORMATO_ID.items():
            valor = linha.get(coluna, "")
            (estruturadas if padrao.fullmatch(valor) else livres).add(valor)

    falhas: list[str] = []
    for categoria, valores in _valores_proibidos(conn).items():
        encontrados = 0
        for valor in valores:
            if not valor:
                continue
            if valor in estruturadas:
                encontrados += 1
                continue
            if len(valor) >= TAMANHO_MINIMO_BUSCA and any(
                valor in celula for celula in livres
            ):
                encontrados += 1
        if encontrados:
            falhas.append(
                f"{encontrados} valor(es) reais da categoria '{categoria}' "
                "encontrados nas colunas textuais do artefato"
            )
    return falhas


def checar_invariantes_contra_dw(conn, linhas: list[dict]) -> list[str]:
    """Compara contagem, datas, agregados, cardinalidade e SCD2 com o Gold.

    Args:
        conn: Conexao aberta com o Data Warehouse.
        linhas: Linhas do artefato.

    Returns:
        Lista de falhas.
    """
    falhas: list[str] = []
    somas = ",\n                   ".join(f"sum({m})::text" for m in METRICAS)

    with conn.cursor() as cur:
        cur.execute("select count(*) from gold.vw_metricas_completas")
        total_gold = cur.fetchone()[0]
        if total_gold != len(linhas):
            falhas.append(
                f"contagem divergente: Gold tem {total_gold}, artefato tem "
                f"{len(linhas)}"
            )

        cur.execute(
            "select distinct data::text from gold.vw_metricas_completas"
        )
        datas_gold = {linha[0] for linha in cur.fetchall()}
        datas_artefato = {l["data"] for l in linhas}
        if datas_gold != datas_artefato:
            falhas.append(
                f"conjunto de datas divergente: {len(datas_gold)} no Gold, "
                f"{len(datas_artefato)} no artefato"
            )

        cur.execute(f"""
            select plataforma, data::text, count(*)::text,
                   {somas}
            from gold.vw_metricas_completas
            group by plataforma, data
        """)
        agregados_gold = {
            (linha[0], linha[1]): [linha[2]] + list(linha[3:])
            for linha in cur.fetchall()
        }

        cur.execute("""
            select count(distinct conta_nk), count(distinct campanha_nk),
                   count(distinct adset_nk), count(distinct anuncio_nk)
            from gold.vw_metricas_completas
        """)
        cardinalidade_gold = dict(zip(NIVEIS, cur.fetchone()))

        cur.execute("""
            select 'conta', conta_versao, count(*) from gold.vw_metricas_completas group by 1,2
            union all
            select 'campanha', campanha_versao, count(*) from gold.vw_metricas_completas group by 1,2
            union all
            select 'adset', adset_versao, count(*) from gold.vw_metricas_completas group by 1,2
            union all
            select 'anuncio', anuncio_versao, count(*) from gold.vw_metricas_completas group by 1,2
        """)
        versoes_gold: dict = {}
        for nivel, versao, quantidade in cur.fetchall():
            versoes_gold.setdefault(nivel, {})[int(versao)] = quantidade

    # Agregados do artefato, somados como Decimal a partir do texto.
    agregados_artefato: dict = {}
    for linha in linhas:
        chave = (linha["plataforma"], linha["data"])
        alvo = agregados_artefato.setdefault(
            chave, [0] + [Decimal(0)] * len(METRICAS)
        )
        alvo[0] += 1
        for i, metrica in enumerate(METRICAS, start=1):
            alvo[i] += Decimal(linha[metrica])

    chaves = set(agregados_gold) | set(agregados_artefato)
    divergentes = 0
    for chave in chaves:
        no_gold = agregados_gold.get(chave)
        no_artefato = agregados_artefato.get(chave)
        if no_gold is None or no_artefato is None:
            divergentes += 1
            continue
        esperado = [int(no_gold[0])] + [Decimal(v) for v in no_gold[1:]]
        if esperado != no_artefato:
            divergentes += 1
    if divergentes:
        falhas.append(
            f"{divergentes} chave(s) (plataforma, data) com agregados "
            "divergentes do Gold"
        )

    cardinalidade_artefato = {
        nivel: len({l[f"{nivel}_id"] for l in linhas}) for nivel in NIVEIS
    }
    for nivel in NIVEIS:
        if cardinalidade_gold[nivel] != cardinalidade_artefato[nivel]:
            falhas.append(
                f"cardinalidade de {nivel} divergente: "
                f"{cardinalidade_gold[nivel]} no Gold, "
                f"{cardinalidade_artefato[nivel]} no artefato"
            )

    versoes_artefato: dict = {}
    for nivel in NIVEIS:
        for linha in linhas:
            versao = int(linha[f"{nivel}_versao"])
            versoes_artefato.setdefault(nivel, {})[versao] = (
                versoes_artefato.setdefault(nivel, {}).get(versao, 0) + 1
            )
    if versoes_gold != versoes_artefato:
        falhas.append("distribuicao de versoes SCD2 divergente do Gold")

    return falhas


def auditar(diretorio: Path, usar_dw: bool = True) -> int:
    """Roda a auditoria completa.

    Args:
        diretorio: Diretorio com ``metricas.csv`` e ``manifesto.json``.
        usar_dw: Se ``False``, roda apenas os checks que dispensam banco.

    Returns:
        ``0`` se aprovado, ``1`` em qualquer violacao.
    """
    caminho_csv = diretorio / NOME_CSV
    caminho_manifesto = diretorio / NOME_MANIFESTO

    for caminho in (caminho_csv, caminho_manifesto):
        if not caminho.exists():
            logger.error("FALHA: arquivo ausente: %s", caminho.name)
            return 1

    cabecalho, linhas, texto = carregar_csv(caminho_csv)
    try:
        manifesto = json.loads(caminho_manifesto.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.error("FALHA: manifesto.json nao e JSON valido")
        return 1

    falhas: list[str] = []

    # Schema errado interrompe a auditoria: os checks de conteudo pressupoem
    # as colunas do contrato, e o certo e reprovar com a causa raiz — nao
    # estourar KeyError em cima de um artefato ja invalido.
    falhas += checar_schema(cabecalho)
    if falhas:
        logger.error("AUDITORIA REPROVADA — %d violacao(oes):", len(falhas))
        for falha in falhas:
            logger.error("  FALHA: %s", falha)
        return 1

    falhas += checar_conteudo(linhas)
    falhas += checar_padroes(texto)
    falhas += checar_manifesto(manifesto, texto, linhas)

    checou_dw = False
    if usar_dw:
        conn = None
        try:
            conn = _conectar()
        except Exception:
            conn = None
        if conn is None:
            falhas.append(
                "Data Warehouse indisponivel: os checks de identidade e de "
                "invariantes nao rodaram (use --sem-dw para auditar so o "
                "artefato)"
            )
        else:
            with conn:
                falhas += checar_identidade_contra_dw(conn, linhas)
                falhas += checar_invariantes_contra_dw(conn, linhas)
            checou_dw = True

    if falhas:
        logger.error("AUDITORIA REPROVADA — %d violacao(oes):", len(falhas))
        for falha in falhas:
            logger.error("  FALHA: %s", falha)
        return 1

    escopo = "artefato + Data Warehouse" if checou_dw else "somente artefato"
    logger.info(
        "AUDITORIA APROVADA — %d linhas, %d colunas, escopo: %s.",
        len(linhas), len(cabecalho), escopo,
    )
    logger.info(
        "Aprovacao cobre uso em Defesa, dashboard local e screenshot. NAO "
        "autoriza publicar, versionar nem hospedar download."
    )
    return 0


def main() -> None:
    """Entry point da CLI."""
    parser = argparse.ArgumentParser(
        description="Audita o artefato de exposicao antes de expor.",
    )
    parser.add_argument(
        "--diretorio",
        default=str(DIRETORIO_PADRAO),
        help=f"Diretorio do artefato. Default: {DIRETORIO_PADRAO}",
    )
    parser.add_argument(
        "--sem-dw",
        action="store_true",
        help="Roda apenas os checks que dispensam o Data Warehouse.",
    )
    args = parser.parse_args()

    configurar_logging()
    sys.exit(auditar(Path(args.diretorio), usar_dw=not args.sem_dw))


if __name__ == "__main__":
    main()
