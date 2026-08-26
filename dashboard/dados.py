"""Carregamento e validacao do dataset que alimenta o dashboard.

Fronteira
---------
Este modulo e o unico ponto de entrada de dados da camada de visualizacao, e
ele so sabe ler CSV. Nao existe conexao com o Data Warehouse, com a bronze,
com a silver, com a gold nem com API de plataforma — nao ha driver de banco
importado aqui, e isso e proposital: a impossibilidade e estrutural, nao
disciplinar.

Duas origens sao aceitas:

- `data/exposicao/metricas.csv` — superficie oficial de exposicao, produzida
  por `scripts/exportar_dataset_exposicao.py`. Modo `pseudonimizado`.
- `dashboard/dados_demo/metricas.csv` — dataset SINTETICO versionado, gerado
  por `dashboard/gerar_dados_demo.py`. Modo `demonstracao`.

Fail closed
-----------
O contrato e verificado antes de qualquer renderizacao, no mesmo espirito de
`verificar_schema_de_origem` no exportador:

1. as 20 colunas obrigatorias v2 tem de existir, na ordem do contrato;
2. nenhuma coluna pode terminar em `_nk`, `_sk`, `_external_id` ou `_nome`;
3. os quatro identificadores tem de casar com o formato de pseudonimo;
4. coluna extra e **ignorada de proposito** e reportada — coluna nova na
   origem nao vira coluna nova no dashboard por inercia.

Falha de contrato levanta `ContratoInvalido` com mensagem legivel, sem
reproduzir valor algum: aponta coluna e contagem, nunca conteudo.

Precisao
--------
As metricas viram `Decimal`, nao `float`. `conversions` e fracionaria no
Google (modelagem de atribuicao) e converter para inteiro ja custou ~1% das
conversoes no ETL legado deste projeto. Conversao para `float` acontece
apenas na apresentacao, dentro dos graficos.
"""

import csv
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent.parent

# Superficie oficial de exposicao. Gitignorada: nao existe num clone limpo.
CAMINHO_PSEUDONIMIZADO: Path = BASE_DIR / "data" / "exposicao" / "metricas.csv"

# Dataset sintetico versionado. Existe para o repositorio continuar
# demonstravel sem nenhum dado de cliente.
CAMINHO_DEMONSTRACAO: Path = BASE_DIR / "dashboard" / "dados_demo" / "metricas.csv"

NOME_MANIFESTO: str = "manifesto.json"

MODO_PSEUDONIMIZADO: str = "pseudonimizado"
MODO_DEMONSTRACAO: str = "demonstracao"

ROTULO_MODO: dict[str, str] = {
    MODO_PSEUDONIMIZADO: "DADOS PSEUDONIMIZADOS",
    MODO_DEMONSTRACAO: "DADOS DE DEMONSTRACAO",
}

# Variaveis de ambiente aceitas. Nenhuma delas carrega segredo: apontam
# arquivo ou escolhem modo.
VARIAVEL_DATASET: str = "DASHBOARD_DATASET"
VARIAVEL_MODO: str = "DASHBOARD_MODO"

NIVEIS: tuple[str, ...] = ("conta", "campanha", "adset", "anuncio")

METRICAS: tuple[str, ...] = (
    "spend", "impressions", "link_clicks", "conversions",
    "conversion_value", "video_views", "reach", "profile_views", "purchases",
    "purchase_value",
)

# Contrato da superficie de exposicao, declarado aqui de proposito. Se o
# exportador mudar as colunas sem que esta lista mude junto, o dashboard
# recusa o arquivo em vez de renderizar algo diferente do que promete —
# mesma razao pela qual o auditor redeclara o schema em vez de importa-lo.
COLUNAS_OBRIGATORIAS: tuple[str, ...] = (
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
)

# Campos ja compreendidos pelo dashboard para a futura superficie v3. Nesta
# etapa continuam opcionais porque o artefato real v2 nao sera regenerado nem
# tera sua versao alterada. O grupo entra inteiro ou nao entra: aceitar metade
# faria o consumidor inventar a outra metade do pareamento oficial.
COLUNAS_RESULTADO_OPCIONAIS: tuple[str, ...] = (
    "result_type",
    "result_count",
    "result_attribution_window",
    "cost_per_result",
)

SUFIXOS_PROIBIDOS: tuple[str, ...] = ("_nk", "_sk", "_external_id", "_nome")

FORMATO_ID: dict[str, re.Pattern] = {
    "conta_id": re.compile(r"^Cliente-[0-9A-F]{8}$"),
    "campanha_id": re.compile(r"^Campanha-[0-9A-F]{8}$"),
    "adset_id": re.compile(r"^AdSet-[0-9A-F]{8}$"),
    "anuncio_id": re.compile(r"^Anuncio-[0-9A-F]{8}$"),
}

# `plataforma` e o unico campo textual livre do artefato. O padrao nao decide
# quais plataformas existem — nao trava a entrada de uma terceira fonte —, so
# impede que texto arbitrario (e portanto identificavel) passe por ali.
FORMATO_PLATAFORMA: re.Pattern = re.compile(r"^[A-Za-z0-9 ._-]{1,30}$")

PLATAFORMAS_CONHECIDAS: tuple[str, ...] = ("Meta Ads", "Google Ads")

FORMATO_RESULT_TYPE: re.Pattern = re.compile(r"^[A-Za-z0-9_.:]{1,120}$")
FORMATO_ATTRIBUTION_WINDOW: re.Pattern = re.compile(r"^[A-Za-z0-9_|]{1,120}$")


class ContratoInvalido(Exception):
    """O arquivo apresentado nao satisfaz o contrato de exposicao.

    A mensagem aponta coluna, contagem ou nivel. Nunca reproduz valor de
    celula: um arquivo errado pode conter exatamente o que nao deve vazar.
    """


@dataclass(frozen=True)
class Fonte:
    """Origem escolhida para esta execucao do dashboard.

    Attributes:
        caminho: Caminho absoluto do CSV.
        modo: ``pseudonimizado`` ou ``demonstracao``.
    """

    caminho: Path
    modo: str

    @property
    def caminho_relativo(self) -> str:
        """Caminho relativo a raiz do projeto, para exibicao.

        Returns:
            Texto do caminho relativo, ou o nome do arquivo quando ele estiver
            fora da arvore do projeto.
        """
        try:
            return str(self.caminho.resolve().relative_to(BASE_DIR))
        except ValueError:
            return self.caminho.name


@dataclass(frozen=True)
class Dataset:
    """Dataset carregado e validado, pronto para consumo.

    Attributes:
        linhas: Registros no grao de 1 anuncio x 1 dia, ja tipados.
        fonte: Origem de onde vieram.
        manifesto: Conteudo do `manifesto.json` vizinho, se existir.
        colunas_ignoradas: Colunas presentes no arquivo e fora do contrato.
            Sao deliberadamente descartadas: coluna nova na origem nao vira
            coluna nova no dashboard sem alguem decidir.
    """

    linhas: list[dict]
    fonte: Fonte
    manifesto: dict = field(default_factory=dict)
    colunas_ignoradas: tuple[str, ...] = ()

    @property
    def modo(self) -> str:
        """Modo de operacao do dataset.

        Returns:
            ``pseudonimizado`` ou ``demonstracao``.
        """
        return self.fonte.modo

    @property
    def rotulo_modo(self) -> str:
        """Selo textual do modo, para exibicao.

        Returns:
            ``DADOS PSEUDONIMIZADOS`` ou ``DADOS DE DEMONSTRACAO``.
        """
        return ROTULO_MODO[self.fonte.modo]


def escolher_fonte(
    dataset: str | None = None, modo: str | None = None
) -> Fonte:
    """Decide qual arquivo alimenta o dashboard.

    Precedencia: caminho explicito, modo forcado, superficie de exposicao
    local, dataset de demonstracao. Nao ha fallback para banco: a ausencia dos
    dois arquivos e um erro, nao um convite a consultar o Gold.

    Args:
        dataset: Caminho explicito de CSV. Default: `DASHBOARD_DATASET`.
        modo: ``demo``/``demonstracao`` forca o dataset sintetico.
            Default: `DASHBOARD_MODO`.

    Returns:
        A fonte escolhida.

    Raises:
        ContratoInvalido: Se nenhum arquivo utilizavel existir.
    """
    dataset = dataset if dataset is not None else os.environ.get(VARIAVEL_DATASET)
    modo = modo if modo is not None else os.environ.get(VARIAVEL_MODO)

    if dataset:
        caminho = Path(dataset).expanduser()
        if not caminho.is_file():
            raise ContratoInvalido(
                f"{VARIAVEL_DATASET} aponta para um arquivo inexistente: "
                f"{caminho.name}."
            )
        resolvido = caminho.resolve()
        forcado = (modo or "").strip().lower() in {"demo", "demonstracao"}
        eh_demo = forcado or resolvido == CAMINHO_DEMONSTRACAO.resolve()
        return Fonte(
            resolvido, MODO_DEMONSTRACAO if eh_demo else MODO_PSEUDONIMIZADO
        )

    if (modo or "").strip().lower() in {"demo", "demonstracao"}:
        if not CAMINHO_DEMONSTRACAO.is_file():
            raise ContratoInvalido(
                "Modo de demonstracao pedido, mas "
                f"{CAMINHO_DEMONSTRACAO.name} nao existe. Gere com "
                "`python dashboard/gerar_dados_demo.py`."
            )
        return Fonte(CAMINHO_DEMONSTRACAO, MODO_DEMONSTRACAO)

    if CAMINHO_PSEUDONIMIZADO.is_file():
        return Fonte(CAMINHO_PSEUDONIMIZADO, MODO_PSEUDONIMIZADO)

    if CAMINHO_DEMONSTRACAO.is_file():
        return Fonte(CAMINHO_DEMONSTRACAO, MODO_DEMONSTRACAO)

    raise ContratoInvalido(
        "Nenhum dataset disponivel. Gere a superficie de exposicao com "
        "`python scripts/exportar_dataset_exposicao.py`, ou o dataset "
        "sintetico com `python dashboard/gerar_dados_demo.py`."
    )


def validar_cabecalho(cabecalho: list[str]) -> tuple[str, ...]:
    """Confere o cabecalho contra o contrato de exposicao.

    Args:
        cabecalho: Colunas lidas do arquivo.

    Returns:
        Colunas extras, que serao ignoradas.

    Raises:
        ContratoInvalido: Se faltar coluna obrigatoria, se a ordem divergir ou
            se houver coluna com sufixo proibido.
    """
    if not cabecalho:
        raise ContratoInvalido("Arquivo sem cabecalho.")

    proibidas = sorted(
        coluna
        for coluna in cabecalho
        if any(coluna.endswith(sufixo) for sufixo in SUFIXOS_PROIBIDOS)
    )
    if proibidas:
        raise ContratoInvalido(
            "O arquivo carrega coluna(s) de identidade real e foi recusado: "
            f"{', '.join(proibidas)}. O dashboard so consome a superficie de "
            "exposicao pseudonimizada."
        )

    faltando = [c for c in COLUNAS_OBRIGATORIAS if c not in cabecalho]
    if faltando:
        raise ContratoInvalido(
            "Coluna(s) obrigatoria(s) ausente(s) no dataset: "
            f"{', '.join(faltando)}. Regenere o artefato com "
            "`python scripts/exportar_dataset_exposicao.py`."
        )

    opcionais_presentes = [
        c for c in COLUNAS_RESULTADO_OPCIONAIS if c in cabecalho
    ]
    if opcionais_presentes and tuple(opcionais_presentes) != COLUNAS_RESULTADO_OPCIONAIS:
        faltando_resultado = [
            c for c in COLUNAS_RESULTADO_OPCIONAIS if c not in cabecalho
        ]
        raise ContratoInvalido(
            "Contrato de Resultado incompleto: coluna(s) ausente(s): "
            f"{', '.join(faltando_resultado)}."
        )

    conhecidas = COLUNAS_OBRIGATORIAS + (
        COLUNAS_RESULTADO_OPCIONAIS if opcionais_presentes else ()
    )
    presentes = [c for c in cabecalho if c in conhecidas]
    if tuple(presentes) != conhecidas:
        raise ContratoInvalido(
            "A ordem das colunas diverge do contrato de exposicao. Regenere o "
            "artefato em vez de reordenar o arquivo a mao."
        )

    return tuple(c for c in cabecalho if c not in conhecidas)


def _converter(bruto: dict, numero_linha: int) -> dict:
    """Tipa uma linha do CSV.

    Args:
        bruto: Linha como texto.
        numero_linha: Posicao no arquivo, usada apenas em mensagem de erro.

    Returns:
        Linha tipada: `data` como `date`, versoes como `int`, metricas como
        `Decimal`, identificadores como texto.

    Raises:
        ContratoInvalido: Se algum campo nao respeitar o tipo do contrato.
    """
    linha: dict = {}

    try:
        linha["data"] = date.fromisoformat(bruto["data"])
    except (TypeError, ValueError):
        raise ContratoInvalido(
            f"Data invalida na linha {numero_linha}: esperado YYYY-MM-DD."
        ) from None

    plataforma = (bruto.get("plataforma") or "").strip()
    if not FORMATO_PLATAFORMA.fullmatch(plataforma):
        raise ContratoInvalido(
            f"Valor de plataforma fora do formato aceito na linha "
            f"{numero_linha}."
        )
    linha["plataforma"] = plataforma

    for nivel in NIVEIS:
        coluna = f"{nivel}_id"
        valor = (bruto.get(coluna) or "").strip()
        if not FORMATO_ID[coluna].fullmatch(valor):
            raise ContratoInvalido(
                f"{coluna} fora do formato de pseudonimo na linha "
                f"{numero_linha}. O dashboard so aceita identificadores da "
                "superficie de exposicao."
            )
        linha[coluna] = valor

        try:
            versao = int(bruto[f"{nivel}_versao"])
        except (TypeError, ValueError, KeyError):
            raise ContratoInvalido(
                f"{nivel}_versao nao e inteiro na linha {numero_linha}."
            ) from None
        if versao < 1:
            raise ContratoInvalido(
                f"{nivel}_versao menor que 1 na linha {numero_linha}."
            )
        linha[f"{nivel}_versao"] = versao

    for metrica in METRICAS:
        texto = (bruto.get(metrica) or "").strip()
        try:
            linha[metrica] = Decimal(texto) if texto else Decimal(0)
        except InvalidOperation:
            raise ContratoInvalido(
                f"{metrica} nao e numero na linha {numero_linha}."
            ) from None

    # Superficie v2: as colunas nao existem e os quatro valores permanecem
    # semanticamente ausentes. Superficie futura: o grupo inteiro existe e
    # cada linha traz um par completo ou quatro vazios.
    for coluna in COLUNAS_RESULTADO_OPCIONAIS:
        linha[coluna] = None

    if all(coluna in bruto for coluna in COLUNAS_RESULTADO_OPCIONAIS):
        tipo = (bruto.get("result_type") or "").strip()
        janela = (bruto.get("result_attribution_window") or "").strip()
        quantidade_texto = (bruto.get("result_count") or "").strip()
        custo_texto = (bruto.get("cost_per_result") or "").strip()
        preenchidos = [bool(tipo), bool(quantidade_texto), bool(janela), bool(custo_texto)]

        if any(preenchidos) and not all(preenchidos):
            raise ContratoInvalido(
                f"Par de Resultado incompleto na linha {numero_linha}."
            )

        if all(preenchidos):
            if not FORMATO_RESULT_TYPE.fullmatch(tipo):
                raise ContratoInvalido(
                    f"result_type fora do formato aceito na linha {numero_linha}."
                )
            if not FORMATO_ATTRIBUTION_WINDOW.fullmatch(janela):
                raise ContratoInvalido(
                    "result_attribution_window fora do formato aceito na linha "
                    f"{numero_linha}."
                )
            try:
                quantidade = Decimal(quantidade_texto)
                custo = Decimal(custo_texto)
            except InvalidOperation:
                raise ContratoInvalido(
                    f"Resultado nao numerico na linha {numero_linha}."
                ) from None
            if quantidade < 0 or custo < 0:
                raise ContratoInvalido(
                    f"Resultado negativo na linha {numero_linha}."
                )
            linha.update({
                "result_type": tipo,
                "result_count": quantidade,
                "result_attribution_window": janela,
                "cost_per_result": custo,
            })

    return linha


def ler_manifesto(caminho_csv: Path) -> dict:
    """Le o manifesto vizinho ao CSV, se houver.

    O manifesto e opcional: um CSV valido sem manifesto continua utilizavel,
    apenas sem data de geracao e sem cardinalidades declaradas.

    Args:
        caminho_csv: Caminho do CSV carregado.

    Returns:
        Conteudo do manifesto, ou dicionario vazio.
    """
    caminho = caminho_csv.parent / NOME_MANIFESTO
    if not caminho.is_file():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def carregar(fonte: Fonte) -> Dataset:
    """Le, valida e tipa o dataset inteiro.

    Args:
        fonte: Origem escolhida por :func:`escolher_fonte`.

    Returns:
        O dataset validado.

    Raises:
        ContratoInvalido: Em qualquer violacao do contrato de exposicao.
    """
    try:
        texto = fonte.caminho.read_text(encoding="utf-8")
    except OSError as erro:
        raise ContratoInvalido(
            f"Nao foi possivel ler {fonte.caminho.name}: {type(erro).__name__}."
        ) from None

    leitor = csv.reader(texto.splitlines())
    cabecalho = next(leitor, [])
    ignoradas = validar_cabecalho(cabecalho)

    linhas: list[dict] = []
    for numero, campos in enumerate(leitor, start=2):
        if not campos:
            continue
        if len(campos) != len(cabecalho):
            raise ContratoInvalido(
                f"Linha {numero} tem {len(campos)} campos, esperados "
                f"{len(cabecalho)}."
            )
        linhas.append(_converter(dict(zip(cabecalho, campos)), numero))

    return Dataset(
        linhas=linhas,
        fonte=fonte,
        manifesto=ler_manifesto(fonte.caminho),
        colunas_ignoradas=ignoradas,
    )


def carregar_padrao(
    dataset: str | None = None, modo: str | None = None
) -> Dataset:
    """Escolhe a fonte e carrega, em um passo.

    Args:
        dataset: Caminho explicito de CSV.
        modo: ``demo`` para forcar o dataset sintetico.

    Returns:
        O dataset validado.

    Raises:
        ContratoInvalido: Se nao houver fonte utilizavel ou o contrato falhar.
    """
    return carregar(escolher_fonte(dataset, modo))


def resumo(dataset: Dataset) -> dict:
    """Descreve o dataset carregado, sem revelar identidade.

    Args:
        dataset: Dataset validado.

    Returns:
        Dicionario com contagens, intervalo de datas e plataformas presentes.
    """
    linhas = dataset.linhas
    datas = sorted({linha["data"] for linha in linhas})
    return {
        "linhas": len(linhas),
        "plataformas": sorted({linha["plataforma"] for linha in linhas}),
        "data_min": datas[0] if datas else None,
        "data_max": datas[-1] if datas else None,
        "dias": len(datas),
        **{
            f"{nivel}s": len({linha[f"{nivel}_id"] for linha in linhas})
            for nivel in NIVEIS
        },
        "entidades_multiversao": {
            nivel: len(
                {
                    linha[f"{nivel}_id"]
                    for linha in linhas
                    if linha[f"{nivel}_versao"] > 1
                }
            )
            for nivel in NIVEIS
        },
    }
