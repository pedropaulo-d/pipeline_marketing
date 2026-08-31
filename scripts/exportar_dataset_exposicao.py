"""Exporta a superficie oficial de exposicao a partir do Gold.

O que e
-------
A unica origem autorizada de material exposto — dashboard, screenshot, slide,
dataset entregue. Le `gold.vw_metricas_completas`, troca a identidade por
pseudonimo e grava `metricas.csv` + `manifesto.json` em `data/exposicao/`.

Metricas e datas saem **reais e intactas**. O que sai e a identidade: nenhum
nome, nenhum external ID, nenhuma chave natural (`_nk`) e nenhuma chave
substituta (`_sk`) chegam ao artefato.

Por que consome a view, e nao as dimensoes
------------------------------------------
Juntar dimensao SCD Tipo 2 pela chave natural sem resolver a versao vigente
transforma o join em 1:N e infla os agregados **sem erro nenhum** — ja custou
7,8% de investimento inventado neste projeto (R$ 20.216,73 -> R$ 21.795,17), e
o numero errado chegou a entrar na tabela de resultados do TCC.
`gold.vw_metricas_completas` e a travessia oficial, escrita uma vez. Este
exportador **nao** reimplementa nada disso: ele projeta o que a view ja
resolveu, inclusive os quatro numeros de versao SCD2.

Fail closed
-----------
A classificacao em `CLASSIFICACAO` cobre **todas** as colunas da view. Coluna
nova que apareca la e nao esteja classificada aborta a exportacao. Escrever
`select` com as 19 colunas certas nao detectaria alguem acrescentando
`landing_page_url` a view amanha — a checagem de contrato detecta.

Uso
---
    python scripts/exportar_dataset_exposicao.py
    python scripts/exportar_dataset_exposicao.py --destino data/exposicao

Exige `PSEUDONIMIZACAO_CHAVE` no `.env` (ver `pseudonimos.py`). Sem chave
valida nao ha artefato: nao existe fallback nem chave default.

Gerar o artefato **nao** autoriza publicar. `data/exposicao/` e material de
Defesa/dashboard local; publicacao continua exigindo autorizacao da agencia.
"""

import argparse
import csv
import hashlib
import io
import json
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import config  # noqa: F401  — importar carrega o .env (unico load_dotenv)
import pseudonimos
from config import configurar_logging, get_db_url

BASE_DIR: Path = Path(__file__).resolve().parent.parent

DESTINO_PADRAO: Path = BASE_DIR / "data" / "exposicao"

# Diretorio reservado a material efetivamente autorizado a publicar. Escrever
# nele exige flag explicita: ninguem deve publicar por inercia de caminho.
DIRETORIO_PUBLICACAO: Path = BASE_DIR / "data" / "publico"

NOME_CSV: str = "metricas.csv"
NOME_MANIFESTO: str = "manifesto.json"
SUFIXO_PARCIAL: str = ".parcial"

# Versao 2 desde 26/08/2026: `purchase_value` entrou como coluna publica.
# Versao 3 desde 31/08/2026: as quatro colunas de Resultado do Meta entraram,
# depois que a reextracao autorizada trouxe `results`/`cost_per_result` para a
# bronze e o `dbt build` as materializou no Gold. Antes disso elas existiam na
# view mas ficavam fora do artefato de proposito (ver `RESERVADA_EXPOSICAO`).
#
# Acrescentar coluna E mudanca de schema neste contrato — os consumidores
# declaram a lista esperada e comparam por igualdade, nao por conjunto: o
# dashboard (`dados.COLUNAS_OBRIGATORIAS` mais o grupo opcional de Resultado) e
# o auditor (`SCHEMAS`) recusam o artefato inteiro se a lista nao bater. Um
# artefato v3 lido por um consumidor v2 falha fechado, que e o comportamento
# desejado; o numero e o que permite dizer POR QUE falhou.
VERSAO_CONTRATO: int = 3

VIEW: str = "gold.vw_metricas_completas"

# Classificacao de TODAS as colunas da view. E o contrato de fail closed:
# `verificar_schema_de_origem` compara esta tabela com o schema real e aborta
# se aparecer coluna nao classificada.
#
# - USADA            entra na consulta e produz coluna de saida (direta ou via
#                    pseudonimo)
# - PROIBIDA         identifica cliente; nunca sai, nem transformada
# - IGNORADA_SEGURA  inofensiva, mas desnecessaria: derivavel de `data`
# - RESERVADA_EXPOSICAO campo aprovado para uma versao futura do contrato, mas
#                    ainda fora da superficie: classificar sem exportar mantem
#                    o fail closed verde sem mudar o artefato. Sem ocupante
#                    desde a v3 — os quatro campos de Resultado que estavam
#                    aqui viraram USADA
# - SOMENTE_DW       contexto util para diagnostico interno, desnecessario ao
#                    dashboard pela politica de minimizacao
USADA: str = "USADA"
PROIBIDA: str = "PROIBIDA"
IGNORADA_SEGURA: str = "IGNORADA_SEGURA"
RESERVADA_EXPOSICAO: str = "RESERVADA_EXPOSICAO"
SOMENTE_DW: str = "SOMENTE_DW"

CLASSIFICACAO: dict[str, str] = {
    "data": USADA,
    "plataforma": USADA,
    "conta_nk": USADA,          # so como entrada do HMAC
    "conta_versao": USADA,
    "campanha_nk": USADA,       # idem
    "campanha_versao": USADA,
    "adset_nk": USADA,          # idem
    "adset_versao": USADA,
    "anuncio_nk": USADA,        # idem
    "anuncio_versao": USADA,
    "spend": USADA,
    "impressions": USADA,
    "link_clicks": USADA,
    "conversions": USADA,
    "conversion_value": USADA,
    "video_views": USADA,
    # Somada nos pos-checks apenas como CHECKSUM linha a linha contra o Gold.
    # Nao e alcance total: pessoas unicas nao somam entre anuncios nem entre
    # dias. Quem apresenta o numero (o dashboard) trata a metrica como nao
    # aditiva.
    "reach": USADA,
    "profile_views": USADA,
    "purchases": USADA,
    # Valor monetario canonico das compras atribuidas pelo Meta. Metrica
    # agregavel; zero no Google por ausencia de suporte da GAQL neste grao.
    # Nao e identificador nem carrega informacao reidentificavel.
    "purchase_value": USADA,

    # Resultado Meta, publico desde a v3. O par (quantidade, custo) e o
    # Resultado oficial escolhido pela propria Meta; o dashboard o consome como
    # grupo indivisivel. Nenhum dos quatro identifica cliente: sao um rotulo de
    # indicador, uma contagem, uma janela de atribuicao e um custo unitario.
    #
    # `result_count` NULL nao e zero — zero e quantidade declarada, NULL e
    # ausencia de contrato. `cost_per_result` e `result_attribution_window`
    # NULL sao estados legitimos (sem denominador, janela nao aplicavel). O
    # exportador nao preenche nenhum deles: transporta o que o Gold resolveu.
    "result_type": USADA,
    "result_count": USADA,
    "result_attribution_window": USADA,
    "cost_per_result": USADA,

    # Contexto operacional oficial, sem funcao no consumidor. Mantido no DW
    # para diagnostico; minimizacao evita expor coluna que a UI nao usa.
    "objective": SOMENTE_DW,
    "optimization_goal": SOMENTE_DW,

    # Identidade real: os 4 nomes e os 4 external IDs. As 4 chaves naturais
    # aparecem como USADA acima porque sao a ENTRADA do HMAC — o teste
    # `test_nk_nao_sai` afirma que nenhuma delas chega a saida.
    "conta_nome": PROIBIDA,
    "conta_external_id": PROIBIDA,
    "campanha_nome": PROIBIDA,
    "campanha_external_id": PROIBIDA,
    "adset_nome": PROIBIDA,
    "adset_external_id": PROIBIDA,
    "anuncio_nome": PROIBIDA,
    "anuncio_external_id": PROIBIDA,

    # Derivados de `data`. Qualquer ferramenta os recalcula.
    "dia": IGNORADA_SEGURA,
    "mes": IGNORADA_SEGURA,
    "ano": IGNORADA_SEGURA,
    "trimestre": IGNORADA_SEGURA,
    "dia_semana": IGNORADA_SEGURA,
    "ano_mes": IGNORADA_SEGURA,
}

# Colunas lidas da view, nesta ordem. Explicito de proposito: nunca `select *`.
COLUNAS_ORIGEM: tuple[str, ...] = (
    "data",
    "plataforma",
    "conta_nk",
    "conta_versao",
    "campanha_nk",
    "campanha_versao",
    "adset_nk",
    "adset_versao",
    "anuncio_nk",
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
    "purchase_value",
    "result_type",
    "result_count",
    "result_attribution_window",
    "cost_per_result",
)

# O grupo de Resultado, nomeado porque entra e sai inteiro. Meia colunagem
# obrigaria o consumidor a inventar a outra metade do par oficial da Meta —
# `dados.COLUNAS_RESULTADO_OPCIONAIS` afirma a mesma regra do outro lado.
COLUNAS_RESULTADO: tuple[str, ...] = (
    "result_type",
    "result_count",
    "result_attribution_window",
    "cost_per_result",
)

# As 24 colunas do artefato. Nao ha coluna de nome publico: o proprio ID e o
# rotulo. Nao ha `linha_id`: o grao ja e `(anuncio_id, data)`. As quatro de
# Resultado vao no FIM: o prefixo v2 permanece na mesma ordem, entao um leitor
# posicional antigo nao troca coluna de lugar em silencio.
COLUNAS_SAIDA: tuple[str, ...] = (
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
    "purchase_value",
    "result_type",
    "result_count",
    "result_attribution_window",
    "cost_per_result",
)

TIPOS_SAIDA: dict[str, str] = {
    "data": "date (YYYY-MM-DD)",
    "plataforma": "text",
    "conta_id": "text (Cliente-XXXXXXXX)",
    "conta_versao": "integer >= 1",
    "campanha_id": "text (Campanha-XXXXXXXX)",
    "campanha_versao": "integer >= 1",
    "adset_id": "text (AdSet-XXXXXXXX)",
    "adset_versao": "integer >= 1",
    "anuncio_id": "text (Anuncio-XXXXXXXX)",
    "anuncio_versao": "integer >= 1",
    "spend": "decimal",
    "impressions": "integer",
    "link_clicks": "integer",
    "conversions": "decimal (fracionario no Google, nunca inteiro)",
    "conversion_value": "decimal",
    "video_views": "integer",
    "reach": "integer",
    "profile_views": "integer",
    "purchases": "integer",
    "purchase_value": "decimal",
    "result_type": "text nullable (indicador oficial da Meta)",
    "result_count": "decimal nullable (NULL = ausencia, nao zero)",
    "result_attribution_window": "text nullable (NULL = janela nao aplicavel)",
    "cost_per_result": "decimal nullable (NULL = sem denominador)",
}

# Os 12 campos que NUNCA podem aparecer no artefato: 4 nomes, 4 external IDs
# e 4 chaves naturais. As `_nk` sao classificadas como USADA acima porque o
# exportador as consome — mas so como ENTRADA do HMAC. A distincao importa:
# "e lido da view" e "pode sair no artefato" sao duas perguntas diferentes, e
# confundi-las e exatamente como um identificador escaparia.
CAMPOS_NUNCA_EXPOSTOS: frozenset[str] = frozenset({
    "conta_nome", "campanha_nome", "adset_nome", "anuncio_nome",
    "conta_external_id", "campanha_external_id",
    "adset_external_id", "anuncio_external_id",
    "conta_nk", "campanha_nk", "adset_nk", "anuncio_nk",
})

METRICAS: tuple[str, ...] = (
    "spend", "impressions", "link_clicks", "conversions",
    "conversion_value", "video_views", "reach", "profile_views", "purchases",
    "purchase_value",
)

NIVEIS: tuple[str, ...] = ("conta", "campanha", "adset", "anuncio")

GRAO: str = "1 anuncio x 1 dia — chave (anuncio_id, data)"

AVISO_VIDEO_VIEWS: str = (
    "video_views tem definicao diferente em cada plataforma: TrueView de 30s, "
    "video completo ou interacao no Google; a partir de 3s no Meta. A metrica "
    "e valida dentro de cada plataforma e o total cross-platform NAO tem "
    "interpretacao analitica comum — nao somar entre plataformas."
)

AVISO_METRICAS_AUSENTES: str = (
    "reach, profile_views, purchases e purchase_value sao zero no Google por "
    "ausencia de suporte da GAQL neste grao — ausencia de suporte, nao "
    "ausencia de dado. purchase_value NAO e o equivalente Meta de "
    "conversion_value: um mede compra, o outro mede todas as conversion "
    "actions da conta."
)

logger = logging.getLogger(__name__)


class ContratoQuebrado(Exception):
    """A exportacao violou o contrato e nao pode produzir artefato.

    A mensagem nunca contem valor identificavel: aponta coluna, contagem ou
    nivel, nunca nome de cliente, external ID ou chave natural.
    """


def _conectar():
    """Abre conexao com o Data Warehouse.

    Returns:
        Conexao psycopg2 aberta.

    Raises:
        ContratoQuebrado: Se a URL do banco nao estiver configurada.
    """
    import psycopg2

    url = get_db_url()
    if not url:
        raise ContratoQuebrado("DW_DB_URL nao configurada.")
    return psycopg2.connect(url)


def verificar_schema_de_origem(conn) -> None:
    """Confere que toda coluna da view esta classificada.

    E o fail closed do contrato. Coluna nova na origem — um campo textual
    recem-extraido, por exemplo — nao pode escorregar para a exposicao por
    omissao, e tambem nao pode ser ignorada em silencio: alguem precisa
    decidir explicitamente sua classificacao antes de o exportador continuar.

    Args:
        conn: Conexao aberta com o Data Warehouse.

    Raises:
        ContratoQuebrado: Se houver coluna nao classificada, ou se uma coluna
            que o exportador consome tiver sumido da view.
    """
    schema, tabela = VIEW.split(".")
    with conn.cursor() as cur:
        cur.execute(
            """
            select column_name
            from information_schema.columns
            where table_schema = %s and table_name = %s
            """,
            (schema, tabela),
        )
        reais = {linha[0] for linha in cur.fetchall()}

    if not reais:
        raise ContratoQuebrado(f"{VIEW} nao existe ou esta vazia de colunas.")

    nao_classificadas = sorted(reais - set(CLASSIFICACAO))
    if nao_classificadas:
        raise ContratoQuebrado(
            f"{VIEW} tem coluna(s) nao classificada(s): "
            f"{', '.join(nao_classificadas)}. Classifique em CLASSIFICACAO "
            f"como {USADA}, {PROIBIDA}, {IGNORADA_SEGURA}, "
            f"{RESERVADA_EXPOSICAO} ou {SOMENTE_DW} antes de exportar."
        )

    faltando = sorted(set(COLUNAS_ORIGEM) - reais)
    if faltando:
        raise ContratoQuebrado(
            f"{VIEW} nao tem mais a(s) coluna(s): {', '.join(faltando)}."
        )


def consultar(conn) -> list[dict]:
    """Le da view exatamente as colunas necessarias.

    Args:
        conn: Conexao aberta com o Data Warehouse.

    Returns:
        Lista de dicionarios, uma entrada por linha da view.
    """
    colunas = ",\n           ".join(COLUNAS_ORIGEM)
    with conn.cursor() as cur:
        cur.execute(f"select {colunas}\n    from {VIEW}")
        nomes = [d[0] for d in cur.description]
        return [dict(zip(nomes, linha)) for linha in cur.fetchall()]


def transformar(linhas: list[dict]) -> list[dict]:
    """Troca identidade por pseudonimo e ordena de forma deterministica.

    Metricas, datas, plataforma e numeros de versao passam sem tocar. As
    chaves naturais entram no HMAC e **nao** sao copiadas para a saida.

    Args:
        linhas: Linhas lidas da view.

    Returns:
        Linhas no schema de exposicao, ordenadas por
        ``(data, plataforma, conta_id, campanha_id, adset_id, anuncio_id)``.

    Raises:
        pseudonimos.ChaveInvalida: Se a chave de pseudonimizacao nao servir.
    """
    saida: list[dict] = []
    for linha in linhas:
        registro = {
            "data": linha["data"],
            "plataforma": linha["plataforma"],
        }
        for nivel in NIVEIS:
            registro[f"{nivel}_id"] = pseudonimos.gerar_id_publico(
                nivel, linha[f"{nivel}_nk"]
            )
            registro[f"{nivel}_versao"] = linha[f"{nivel}_versao"]
        for metrica in METRICAS:
            registro[metrica] = linha[metrica]
        # Resultado: copia direta, sem coalesce e sem default. `None` chega ao
        # CSV como campo vazio (`_texto`), que e como a ausencia se escreve
        # neste contrato — trocar por 0 afirmaria quantidade que a fonte nao
        # declarou, e trocar por texto ("N/A") inventaria um valor de dominio.
        for coluna in COLUNAS_RESULTADO:
            registro[coluna] = linha[coluna]
        saida.append(registro)

    saida.sort(
        key=lambda r: (
            str(r["data"]), r["plataforma"], r["conta_id"],
            r["campanha_id"], r["adset_id"], r["anuncio_id"],
        )
    )
    return saida


def _texto(valor) -> str:
    """Serializa um valor para o CSV sem perder precisao.

    ``Decimal`` vira o proprio texto: converter para float introduziria
    diferenca de representacao onde nao houve mudanca de dado, e truncar
    `conversions` transformaria a conversao fracionada do Google em inteiro
    — erro que ja custou ~1% das conversoes no ETL legado.

    Args:
        valor: Valor vindo do banco.

    Returns:
        Representacao textual exata.
    """
    if valor is None:
        return ""
    # `str` de Decimal preserva a escala exata do banco; nao ha conversao
    # numerica em nenhum ponto do caminho.
    return str(valor)


def serializar_csv(linhas: list[dict]) -> str:
    """Monta o CSV inteiro em memoria.

    Args:
        linhas: Linhas ja no schema de exposicao.

    Returns:
        Conteudo do CSV, com cabecalho explicito e sem indice implicito.
    """
    buffer = io.StringIO(newline="")
    escritor = csv.writer(buffer, lineterminator="\n")
    escritor.writerow(COLUNAS_SAIDA)
    for linha in linhas:
        escritor.writerow([_texto(linha[coluna]) for coluna in COLUNAS_SAIDA])
    return buffer.getvalue()


def agregados(linhas: list[dict], chave_data=str) -> dict:
    """Agrega as 9 metricas por (plataforma, data).

    Args:
        linhas: Linhas com plataforma, data e as metricas.
        chave_data: Funcao aplicada a data para formar a chave.

    Returns:
        Dict ``(plataforma, data) -> {linhas, <metrica>: Decimal}``.
    """
    resultado: dict = {}
    for linha in linhas:
        chave = (linha["plataforma"], chave_data(linha["data"]))
        alvo = resultado.setdefault(
            chave, {"linhas": 0, **{m: Decimal(0) for m in METRICAS}}
        )
        alvo["linhas"] += 1
        for metrica in METRICAS:
            alvo[metrica] += Decimal(str(linha[metrica]))
    return resultado


def versoes_por_nivel(linhas: list[dict]) -> dict:
    """Conta, por nivel, quantas linhas caem em cada numero de versao.

    Serve para provar que o versionamento SCD2 sobreviveu a exposicao sem
    revelar qual entidade foi renomeada. Le apenas as colunas de versao, que
    tem o mesmo nome nos dois lados.

    Args:
        linhas: Linhas do artefato ou da origem.

    Returns:
        Dict ``nivel -> {versao: quantidade de linhas}``.
    """
    resultado: dict = {}
    for nivel in NIVEIS:
        contagem: dict = {}
        for linha in linhas:
            versao = int(linha[f"{nivel}_versao"])
            contagem[versao] = contagem.get(versao, 0) + 1
        resultado[nivel] = contagem
    return resultado


def cardinalidades(linhas: list[dict], sufixo: str) -> dict:
    """Conta entidades distintas por nivel.

    Args:
        linhas: Linhas do artefato ou da origem.
        sufixo: ``_id`` no artefato, ``_nk`` na origem.

    Returns:
        Dict ``nivel -> quantidade de entidades distintas``.
    """
    return {
        nivel: len({linha[f"{nivel}{sufixo}"] for linha in linhas})
        for nivel in NIVEIS
    }


def _conferir_estrutura_de_identidade(
    origem: list[dict], artefato: list[dict]
) -> list[str]:
    """Confere pseudonimos, hierarquia, schema e ausencia de chaves naturais.

    Args:
        origem: Linhas lidas da view, ainda com chaves naturais.
        artefato: Linhas transformadas, apenas com identidade publica.

    Returns:
        Problemas estruturais de identidade, na ordem dos pos-checks.
    """
    problemas: list[str] = []

    # 3-6. Colisao de pseudonimo: duas entidades distintas na origem nao podem
    #      virar o mesmo ID publico. A comparacao e por CARDINALIDADE, e nao
    #      linha a linha, porque o artefato sai reordenado — parear por
    #      posicao produziria par errado (a mesma armadilha do `zip` que ja
    #      custou um diagnostico inteiro no verificador de paridade).
    distintas_origem = cardinalidades(origem, "_nk")
    distintas_artefato = cardinalidades(artefato, "_id")
    for nivel in NIVEIS:
        if distintas_origem[nivel] != distintas_artefato[nivel]:
            problemas.append(
                f"colisao de pseudonimo em {nivel}: "
                f"{distintas_origem[nivel]} entidades na origem para "
                f"{distintas_artefato[nivel]} identificadores publicos"
            )

    # 7. Hierarquia: cada filho com exatamente um pai.
    for pai, filho in (("conta", "campanha"), ("campanha", "adset"),
                       ("adset", "anuncio")):
        pais_por_filho: dict = {}
        for linha in artefato:
            pais_por_filho.setdefault(linha[f"{filho}_id"], set()).add(
                linha[f"{pai}_id"]
            )
        quebrados = sum(1 for v in pais_por_filho.values() if len(v) > 1)
        if quebrados:
            problemas.append(
                f"hierarquia quebrada: {quebrados} {filho}(s) com mais de um "
                f"{pai}"
            )

    # 8-9. Schema exato e ausencia de coluna proibida.
    for linha in artefato:
        if tuple(linha) != COLUNAS_SAIDA:
            problemas.append(
                f"schema do artefato tem {len(linha)} colunas, esperadas "
                f"{len(COLUNAS_SAIDA)}"
            )
            break
    vazadas = sorted(CAMPOS_NUNCA_EXPOSTOS & set(COLUNAS_SAIDA))
    if vazadas:
        problemas.append(f"campo proibido no schema de saida: {vazadas}")

    # As chaves naturais entram no HMAC; nenhum valor delas pode sobreviver no
    # artefato. A checagem e por VALOR, nao por nome de coluna — coluna com
    # outro nome carregando o mesmo conteudo tambem e vazamento.
    valores_saida = {
        str(valor) for linha in artefato for valor in linha.values()
    }
    for nivel in NIVEIS:
        naturais = {linha[f"{nivel}_nk"] for linha in origem}
        if naturais & valores_saida:
            problemas.append(
                f"chave natural de {nivel} encontrada entre os valores do "
                "artefato"
            )

    return problemas


def conferir(origem: list[dict], artefato: list[dict]) -> list[str]:
    """Roda os pos-checks do exportador.

    Nenhum deles confia na transformacao: todos comparam o artefato produzido
    com a origem lida, ou verificam propriedades do proprio artefato.

    Args:
        origem: Linhas lidas da view.
        artefato: Linhas ja transformadas.

    Returns:
        Lista de problemas. Vazia quando o artefato pode ser publicado no
        diretorio de exposicao.
    """
    problemas: list[str] = []

    # 1. Contagem.
    if len(artefato) != len(origem):
        problemas.append(
            f"contagem divergente: {len(origem)} na origem, "
            f"{len(artefato)} no artefato"
        )

    # 2. Grao unico.
    graos = {(linha["anuncio_id"], str(linha["data"])) for linha in artefato}
    if len(graos) != len(artefato):
        problemas.append(
            f"grao nao e unico: {len(artefato)} linhas para {len(graos)} "
            "pares (anuncio_id, data)"
        )

    problemas += _conferir_estrutura_de_identidade(origem, artefato)

    # 10. Agregados por (plataforma, data).
    if agregados(origem) != agregados(artefato):
        problemas.append("agregados por (plataforma, data) divergem da origem")

    # 11. Conjunto de datas.
    if {str(o["data"]) for o in origem} != {str(a["data"]) for a in artefato}:
        problemas.append("conjunto de datas diverge da origem")

    # 12. Versoes SCD2.
    if versoes_por_nivel(origem) != versoes_por_nivel(artefato):
        problemas.append("distribuicao de versoes SCD2 diverge da origem")

    return problemas


def montar_manifesto(
    linhas: list[dict], conteudo_csv: str, nome_csv: str
) -> dict:
    """Monta o manifesto que acompanha o artefato.

    Args:
        linhas: Linhas do artefato.
        conteudo_csv: Conteudo exato gravado.
        nome_csv: Nome do arquivo de dados.

    Returns:
        Dicionario serializavel do manifesto.
    """
    datas = sorted(str(linha["data"]) for linha in linhas)
    return {
        "versao_contrato": VERSAO_CONTRATO,
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "artefato": nome_csv,
        "sha256": hashlib.sha256(conteudo_csv.encode("utf-8")).hexdigest(),
        "linhas": len(linhas),
        "data_min": datas[0] if datas else None,
        "data_max": datas[-1] if datas else None,
        "grao": GRAO,
        "colunas": list(COLUNAS_SAIDA),
        "tipos": dict(TIPOS_SAIDA),
        "cardinalidades": cardinalidades(linhas, "_id"),
        "fingerprint_chave": pseudonimos.fingerprint_chave(),
        "origem": VIEW,
        "avisos": {
            "video_views": AVISO_VIDEO_VIEWS,
            "metricas_ausentes_no_google": AVISO_METRICAS_AUSENTES,
        },
        "uso": (
            "Material de Defesa, dashboard local e screenshot. Gerar este "
            "artefato NAO autoriza publicar, versionar nem hospedar download."
        ),
    }


def _gravar_atomico(destino: Path, conteudo: str) -> None:
    """Grava um arquivo por `.parcial` + `os.replace`.

    Args:
        destino: Caminho final.
        conteudo: Texto a gravar.
    """
    parcial = destino.with_name(destino.name + SUFIXO_PARCIAL)
    parcial.write_text(conteudo, encoding="utf-8")
    os.replace(parcial, destino)


def exportar(destino: Path, permitir_publicacao: bool = False) -> int:
    """Gera o artefato de exposicao.

    Args:
        destino: Diretorio de saida.
        permitir_publicacao: Libera gravar em ``data/publico/``.

    Returns:
        ``0`` em sucesso, ``1`` em qualquer violacao de contrato.
    """
    try:
        destino = destino.resolve()
        if (
            not permitir_publicacao
            and DIRETORIO_PUBLICACAO in (destino, *destino.parents)
        ):
            raise ContratoQuebrado(
                f"{DIRETORIO_PUBLICACAO} e reservado a material autorizado a "
                "publicar. Use --destino data/exposicao, ou passe "
                "--permitir-publicacao de proposito."
            )

        # A chave e validada antes de tocar no banco: falhar cedo evita ler
        # dado real sem ter como pseudonimizar.
        pseudonimos.fingerprint_chave()

        with _conectar() as conn:
            verificar_schema_de_origem(conn)
            origem = consultar(conn)

        if not origem:
            raise ContratoQuebrado(f"{VIEW} nao devolveu nenhuma linha.")

        artefato = transformar(origem)

        problemas = conferir(origem, artefato)
        if problemas:
            raise ContratoQuebrado(
                "pos-checks falharam:\n  - " + "\n  - ".join(problemas)
            )

        conteudo_csv = serializar_csv(artefato)
        manifesto = montar_manifesto(artefato, conteudo_csv, NOME_CSV)

        destino.mkdir(parents=True, exist_ok=True)
        _gravar_atomico(destino / NOME_CSV, conteudo_csv)
        _gravar_atomico(
            destino / NOME_MANIFESTO,
            json.dumps(manifesto, indent=2, ensure_ascii=False) + "\n",
        )

    except (ContratoQuebrado, pseudonimos.ChaveInvalida) as erro:
        logger.error("Exportacao abortada: %s", erro)
        return 1

    logger.info(
        "Artefato gravado em %s: %d linhas, %s a %s.",
        destino, manifesto["linhas"], manifesto["data_min"],
        manifesto["data_max"],
    )
    logger.info("sha256 do CSV: %s", manifesto["sha256"])
    logger.info("fingerprint da chave: %s", manifesto["fingerprint_chave"])
    logger.info(
        "Gerar o artefato nao autoriza publicar. Rode "
        "scripts/auditar_dataset_exposicao.py antes de expor."
    )
    return 0


def main() -> None:
    """Entry point da CLI."""
    parser = argparse.ArgumentParser(
        description="Exporta a superficie de exposicao a partir do Gold.",
    )
    parser.add_argument(
        "--destino",
        default=str(DESTINO_PADRAO),
        help=f"Diretorio de saida. Default: {DESTINO_PADRAO}",
    )
    parser.add_argument(
        "--permitir-publicacao",
        action="store_true",
        help=(
            "Libera gravar em data/publico/. Exige autorizacao da agencia; "
            "nao use por conveniencia."
        ),
    )
    args = parser.parse_args()

    configurar_logging()
    sys.exit(exportar(Path(args.destino), args.permitir_publicacao))


if __name__ == "__main__":
    main()
