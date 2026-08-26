"""Catalogo de metricas, agregacoes e indicadores derivados do dashboard.

O que este modulo protege
-------------------------
As nove metricas do pipeline **nao** sao intercambiaveis, e tratar todas como
"numero somavel" produz grafico bonito com significado errado:

- `reach`, `profile_views` e `purchases` nao existem na GAQL neste grao. O
  zero do Google e **ausencia de suporte, nao ausencia de desempenho** —
  soma-lo ao Meta produz um total que subestima uma plataforma e sugere que a
  outra teve alcance nulo.
- `video_views` existe nas duas, com definicoes diferentes: TrueView de 30s,
  video completo ou interacao no Google; a partir de 3s no Meta. Valida dentro
  de cada plataforma, sem interpretacao comum quando somada entre elas.
- `reach` e contagem de pessoas unicas: somar dias distintos conta a mesma
  pessoa varias vezes. O total diario acumulado nao e alcance unico do periodo.

O catalogo abaixo declara essas propriedades uma vez, e o restante do
dashboard as consulta em vez de reencontra-las.

Precisao
--------
Toda agregacao acontece em `Decimal`. `conversions` e fracionaria no Google e
truncar ja custou ~1% das conversoes no ETL legado deste projeto. `float` so
aparece na fronteira de apresentacao (Plotly).

Divisao segura
--------------
Nenhum indicador derivado devolve `NaN` ou `Infinity`. Denominador zero,
ausente ou negativo devolve `None`, que a camada de formatacao exibe como
`--` — indisponivel e diferente de zero.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

INDISPONIVEL: str = "--"

MOEDA: str = "moeda"
INTEIRO: str = "inteiro"
DECIMAL: str = "decimal"
PERCENTUAL: str = "percentual"
MULTIPLICADOR: str = "multiplicador"

# Abaixo deste valor um multiplicador arredondado viraria `0,000x` e seria
# lido como zero. Zero e resultado legitimo; "muito pequeno" nao e zero.
PISO_MULTIPLICADOR: Decimal = Decimal("0.001")


@dataclass(frozen=True)
class Metrica:
    """Descreve uma metrica base do pipeline.

    Attributes:
        chave: Nome da coluna no dataset de exposicao.
        rotulo: Nome exibido.
        formato: Um de `moeda`, `inteiro`, `decimal`, `percentual`.
        plataformas_sem_suporte: Plataformas em que a metrica nao e coletada
            neste grao. O zero delas nao representa desempenho.
        comparavel_entre_plataformas: Se somar Meta com Google produz um total
            interpretavel.
        aditiva_no_tempo: Se somar dias distintos produz um total valido.
        observacao: Ressalva exibida junto do numero, quando houver.
        ajuda: Definicao da metrica, exibida na ajuda contextual do cartao.
            Responde "o que este numero conta", nao a ressalva de cobertura.
    """

    chave: str
    rotulo: str
    formato: str
    plataformas_sem_suporte: frozenset = frozenset()
    comparavel_entre_plataformas: bool = True
    aditiva_no_tempo: bool = True
    observacao: str = ""
    ajuda: str = ""


CATALOGO: dict[str, Metrica] = {
    "spend": Metrica(
        "spend", "Investimento", MOEDA,
        ajuda="Total gasto em mídia no período selecionado.",
    ),
    "impressions": Metrica(
        "impressions", "Impressões", INTEIRO,
        ajuda="Quantidade de vezes em que os anúncios foram exibidos.",
    ),
    "link_clicks": Metrica(
        "link_clicks", "Cliques no link", INTEIRO,
        ajuda=(
            "Quantidade de cliques contabilizados na métrica consolidada de "
            "cliques do pipeline."
        ),
    ),
    "conversions": Metrica(
        "conversions", "Conversões", DECIMAL,
        observacao=(
            "Fracionária no Google Ads por modelagem de atribuição; o valor "
            "não é arredondado."
        ),
        ajuda=(
            "Quantidade de conversões reportadas pela plataforma para o "
            "recorte utilizado."
        ),
    ),
    "conversion_value": Metrica(
        "conversion_value", "Valor de conversão", MOEDA,
        observacao=(
            "Depende de o valor de conversão estar configurado na conta de "
            "origem; conta sem valor configurado reporta zero."
        ),
        ajuda=(
            "Soma do valor monetário atribuído às conversões pela "
            "plataforma. Não representa custo por conversão."
        ),
    ),
    "video_views": Metrica(
        "video_views", "Visualizações de vídeo", INTEIRO,
        comparavel_entre_plataformas=False,
        observacao=(
            "Definição diferente por plataforma: TrueView de 30s, vídeo "
            "completo ou interação no Google; a partir de 3s no Meta. Não "
            "somar entre plataformas."
        ),
    ),
    "reach": Metrica(
        "reach", "Alcance", INTEIRO,
        plataformas_sem_suporte=frozenset({"Google Ads"}),
        comparavel_entre_plataformas=False,
        aditiva_no_tempo=False,
        observacao=(
            "Não disponibilizado pela GAQL neste grão. Além disso conta "
            "pessoas únicas: a soma de dias não é o alcance único do período."
        ),
    ),
    "profile_views": Metrica(
        "profile_views", "Visitas ao perfil", INTEIRO,
        plataformas_sem_suporte=frozenset({"Google Ads"}),
        comparavel_entre_plataformas=False,
        observacao="Não disponibilizado pela GAQL neste grão.",
    ),
    "purchases": Metrica(
        "purchases", "Compras", INTEIRO,
        plataformas_sem_suporte=frozenset({"Google Ads"}),
        comparavel_entre_plataformas=False,
        observacao="Não disponibilizado pela GAQL neste grão.",
        ajuda=(
            "Quantidade de eventos classificados como compra quando "
            "disponibilizados pela origem."
        ),
    ),
}

METRICAS: tuple[str, ...] = tuple(CATALOGO)

# Metricas que podem ser somadas entre plataformas sem inventar equivalencia.
METRICAS_CONSOLIDAVEIS: tuple[str, ...] = tuple(
    chave for chave, m in CATALOGO.items() if m.comparavel_entre_plataformas
)

AVISO_NAO_DISPONIVEL: str = "não disponibilizado nesta origem"


@dataclass(frozen=True)
class Derivada:
    """Indicador calculado a partir de duas metricas base.

    Attributes:
        chave: Identificador interno.
        rotulo: Nome exibido.
        numerador: Metrica base do numerador.
        denominador: Metrica base do denominador.
        fator: Multiplicador aplicado ao quociente.
        formato: Formato de exibicao.
        descricao: Formula, em texto, para a tela "Sobre os dados".
        ajuda: Definicao e formula em texto corrido, exibida na ajuda
            contextual do cartao.
    """

    chave: str
    rotulo: str
    numerador: str
    denominador: str
    fator: Decimal
    formato: str
    descricao: str
    ajuda: str = ""


# Todos os operandos abaixo sao metricas consolidaveis: os indicadores valem
# para uma plataforma isolada e para o conjunto filtrado.
DERIVADAS: dict[str, Derivada] = {
    "ctr": Derivada(
        "ctr", "CTR", "link_clicks", "impressions", Decimal(100), PERCENTUAL,
        "cliques no link / impressões x 100",
        ajuda=(
            "Click-Through Rate: taxa de cliques sobre impressões. "
            "Fórmula: cliques / impressões × 100."
        ),
    ),
    "cpc": Derivada(
        "cpc", "CPC", "spend", "link_clicks", Decimal(1), MOEDA,
        "investimento / cliques no link",
        ajuda=(
            "Custo por Clique: custo médio por clique. "
            "Fórmula: investimento / cliques."
        ),
    ),
    "cpm": Derivada(
        "cpm", "CPM", "spend", "impressions", Decimal(1000), MOEDA,
        "investimento / impressoes x 1000",
        ajuda=(
            "Custo por Mil Impressões: custo médio para cada mil "
            "impressões. Fórmula: investimento / impressões × 1.000."
        ),
    ),
    "cpa": Derivada(
        "cpa", "CPA", "spend", "conversions", Decimal(1), MOEDA,
        "investimento / conversões",
        ajuda=(
            "Custo por Aquisição: custo médio para gerar uma conversão. "
            "Fórmula: investimento / conversões. No Google Ads, corresponde "
            "conceitualmente à métrica Custo / conv."
        ),
    ),
    # A apresentacao do ROAS e de multiplicador ("2,00x"); o calculo segue
    # sendo valor de conversao / investimento, com fator 1.
    "roas": Derivada(
        "roas", "ROAS", "conversion_value", "spend", Decimal(1),
        MULTIPLICADOR, "valor de conversão / investimento",
        ajuda=(
            "Return on Ad Spend: relação entre o valor atribuído às "
            "conversões e o investimento. Fórmula: valor de conversão / "
            "investimento. Um ROAS de 2,00x representa R$ 2,00 de valor de "
            "conversão para cada R$ 1,00 investido."
        ),
    ),
}


def suportada(metrica: str, plataforma: str) -> bool:
    """Diz se a plataforma coleta a metrica neste grao.

    Args:
        metrica: Chave da metrica base.
        plataforma: Nome da plataforma.

    Returns:
        ``False`` quando o zero da plataforma significa ausencia de suporte.
    """
    definicao = CATALOGO.get(metrica)
    if definicao is None:
        return False
    return plataforma not in definicao.plataformas_sem_suporte


def agregar(linhas: list[dict]) -> dict:
    """Soma as nove metricas do conjunto informado.

    Args:
        linhas: Linhas ja filtradas, no grao de anuncio x dia.

    Returns:
        Dicionario com `linhas` (contagem) e uma entrada `Decimal` por metrica.
    """
    total: dict = {"linhas": len(linhas)}
    for metrica in METRICAS:
        total[metrica] = Decimal(0)
    for linha in linhas:
        for metrica in METRICAS:
            total[metrica] += linha[metrica]
    return total


def agregar_por(linhas: list[dict], chave) -> dict:
    """Agrupa e soma as metricas por uma chave qualquer.

    Args:
        linhas: Linhas ja filtradas.
        chave: Funcao que extrai a chave de agrupamento de uma linha.

    Returns:
        Dicionario ``chave -> agregado``, na forma devolvida por
        :func:`agregar`.
    """
    grupos: dict = {}
    for linha in linhas:
        grupos.setdefault(chave(linha), []).append(linha)
    return {k: agregar(v) for k, v in grupos.items()}


def dividir(numerador, denominador, fator: Decimal = Decimal(1)):
    """Divisao que nunca devolve `NaN` nem `Infinity`.

    Args:
        numerador: Valor do numerador.
        denominador: Valor do denominador.
        fator: Multiplicador aplicado ao quociente.

    Returns:
        `Decimal` com o resultado, ou ``None`` quando o calculo nao e valido —
        denominador zero, ausente ou negativo, ou numerador ausente.
    """
    if numerador is None or denominador is None:
        return None
    numerador = Decimal(str(numerador))
    denominador = Decimal(str(denominador))
    if denominador <= 0:
        return None
    return numerador / denominador * fator


def calcular_derivada(chave: str, totais: dict):
    """Calcula um indicador derivado a partir de um agregado.

    Args:
        chave: Chave em :data:`DERIVADAS`.
        totais: Agregado devolvido por :func:`agregar`.

    Returns:
        `Decimal` com o indicador, ou ``None`` se nao for calculavel.

    Raises:
        KeyError: Se a chave nao existir no catalogo de derivadas.
    """
    definicao = DERIVADAS[chave]
    return dividir(
        totais.get(definicao.numerador),
        totais.get(definicao.denominador),
        definicao.fator,
    )


def calcular_derivadas(totais: dict) -> dict:
    """Calcula todos os indicadores derivados de um agregado.

    Args:
        totais: Agregado devolvido por :func:`agregar`.

    Returns:
        Dicionario ``chave -> Decimal | None``.
    """
    return {chave: calcular_derivada(chave, totais) for chave in DERIVADAS}


def variacao(atual, anterior):
    """Variacao percentual entre dois valores.

    Nao classifica a variacao como boa ou ruim: aumento de investimento e de
    CPA nao tem a mesma leitura, e o dashboard nao decide isso pelo usuario.

    Args:
        atual: Valor do periodo selecionado.
        anterior: Valor do periodo de comparacao.

    Returns:
        `Decimal` com a variacao em pontos percentuais, ou ``None`` quando a
        base e zero, negativa ou ausente.
    """
    if atual is None or anterior is None:
        return None
    atual = Decimal(str(atual))
    anterior = Decimal(str(anterior))
    if anterior <= 0:
        return None
    return (atual - anterior) / anterior * Decimal(100)


def periodo_anterior(inicio: date, fim: date) -> tuple[date, date]:
    """Calcula o periodo imediatamente anterior, de mesma duracao.

    Args:
        inicio: Primeiro dia do periodo selecionado.
        fim: Ultimo dia do periodo selecionado.

    Returns:
        Tupla ``(inicio_anterior, fim_anterior)``. Para 10/08 a 16/08 (7 dias)
        devolve 03/08 a 09/08.

    Raises:
        ValueError: Se `fim` for anterior a `inicio`.
    """
    if fim < inicio:
        raise ValueError("Periodo invalido: fim anterior ao inicio.")
    duracao = (fim - inicio).days + 1
    fim_anterior = inicio - timedelta(days=1)
    return fim_anterior - timedelta(days=duracao - 1), fim_anterior


# ── Formatacao (pt-BR) ────────────────────────────────────────────────────
# Apresentacao apenas. Nenhuma agregacao usa estas funcoes: arredondar antes
# de comparar e o erro que a politica de paridade do projeto proibe.


def _separar_milhar(inteiro: str) -> str:
    """Insere ponto a cada tres digitos.

    Args:
        inteiro: Parte inteira, so digitos.

    Returns:
        Texto com separador de milhar.
    """
    partes = []
    while len(inteiro) > 3:
        partes.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    partes.insert(0, inteiro)
    return ".".join(partes)


def _numero(valor: Decimal, casas: int) -> str:
    """Formata um `Decimal` no padrao brasileiro.

    Args:
        valor: Valor a formatar.
        casas: Casas decimais.

    Returns:
        Texto formatado, com sinal quando negativo.
    """
    quantizado = Decimal(str(valor)).quantize(
        Decimal(1) if casas == 0 else Decimal("1." + "0" * casas),
        rounding=ROUND_HALF_UP,
    )
    sinal = "-" if quantizado < 0 else ""
    texto = str(abs(quantizado))
    inteiro, _, decimal = texto.partition(".")
    inteiro = _separar_milhar(inteiro)
    return f"{sinal}{inteiro},{decimal}" if casas else f"{sinal}{inteiro}"


def _casas_multiplicador(valor: Decimal) -> int:
    """Escolhe as casas decimais de um multiplicador pela ordem de grandeza.

    Duas casas fixas achatariam `0,028x` em `0,03x` — uma diferenca de
    interpretacao, nao de arredondamento. A regra tem duas faixas:

    ===============  ======  ==========
    Faixa            Casas   Exemplo
    ===============  ======  ==========
    ``< 0,1``        3       ``0,028x``
    ``>= 0,1``       2       ``12,54x``
    ===============  ======  ==========

    Args:
        valor: Multiplicador ja calculado.

    Returns:
        Quantidade de casas decimais.
    """
    absoluto = abs(valor)
    if absoluto == 0:
        # Zero e resultado legitimo, nao valor minusculo: exibi-lo com tres
        # casas (`0,000x`) sugeriria uma precisao que nao esta em jogo.
        return 2
    if absoluto < Decimal("0.1"):
        return 3
    return 2


def _multiplicador(valor: Decimal, casas: int | None) -> str:
    """Formata um multiplicador com o sufixo `x`.

    Args:
        valor: Multiplicador ja calculado.
        casas: Sobrescreve a regra de magnitude quando informado.

    Returns:
        Texto como ``2,00x`` ou ``0,028x``. Valor nao nulo pequeno demais
        para as tres casas sai como ``< 0,001x``, nunca como ``0,000x``.
    """
    valor = Decimal(str(valor))
    if casas is not None:
        return f"{_numero(valor, casas)}x"
    if valor != 0 and abs(valor) < PISO_MULTIPLICADOR:
        return "< 0,001x" if valor > 0 else "> -0,001x"
    return f"{_numero(valor, _casas_multiplicador(valor))}x"


def formatar(valor, formato: str, casas: int | None = None) -> str:
    """Formata um valor conforme o formato declarado no catalogo.

    Args:
        valor: Valor a formatar, ou ``None``.
        formato: Um de `moeda`, `inteiro`, `decimal`, `percentual`,
            `multiplicador`.
        casas: Sobrescreve as casas decimais padrao do formato.

    Returns:
        Texto pronto para exibicao. ``None`` vira `--`, nunca `NaN`, `inf`
        ou `0`.
    """
    if valor is None:
        return INDISPONIVEL
    if formato == MOEDA:
        return f"R$ {_numero(valor, 2 if casas is None else casas)}"
    if formato == INTEIRO:
        return _numero(valor, 0 if casas is None else casas)
    if formato == PERCENTUAL:
        return f"{_numero(valor, 2 if casas is None else casas)}%"
    if formato == MULTIPLICADOR:
        return _multiplicador(valor, casas)
    return _numero(valor, 2 if casas is None else casas)


def formatar_metrica(metrica: str, valor) -> str:
    """Formata o valor de uma metrica base.

    Args:
        metrica: Chave da metrica.
        valor: Valor agregado.

    Returns:
        Texto formatado segundo o catalogo.
    """
    return formatar(valor, CATALOGO[metrica].formato)


def formatar_derivada(chave: str, valor) -> str:
    """Formata o valor de um indicador derivado.

    Args:
        chave: Chave em :data:`DERIVADAS`.
        valor: Valor calculado, possivelmente ``None``.

    Returns:
        Texto formatado, ou `--` quando indisponivel.
    """
    return formatar(valor, DERIVADAS[chave].formato)


def formatar_variacao(valor) -> str:
    """Formata a variacao percentual com seta neutra.

    Args:
        valor: Variacao em pontos percentuais, ou ``None``.

    Returns:
        Texto como ``^ 12,34%`` ou ``v 3,10%``; `--` quando nao calculavel.
        A seta indica direcao, nao julgamento.
    """
    if valor is None:
        return INDISPONIVEL
    valor = Decimal(str(valor))
    seta = "▲" if valor > 0 else ("▼" if valor < 0 else "▬")
    return f"{seta} {_numero(abs(valor), 2)}%"


def serie_diaria(
    linhas: list[dict], metrica: str, por_plataforma: bool = True
) -> dict:
    """Monta a serie temporal de uma metrica.

    Args:
        linhas: Linhas ja filtradas.
        metrica: Chave da metrica base.
        por_plataforma: Se `True`, uma serie por plataforma; se `False`, uma
            unica serie consolidada.

    Returns:
        Dicionario ``serie -> [(data, valor)]``, com as datas ordenadas e
        preenchidas apenas onde ha dado.
    """
    acumulado: dict = {}
    for linha in linhas:
        serie = linha["plataforma"] if por_plataforma else "Total"
        chave = linha["data"]
        acumulado.setdefault(serie, {})
        acumulado[serie][chave] = acumulado[serie].get(chave, Decimal(0)) + linha[metrica]
    return {
        serie: sorted(valores.items()) for serie, valores in sorted(acumulado.items())
    }


def ranking(
    linhas: list[dict], nivel: str, metrica: str, topo: int | None = None
) -> list[dict]:
    """Ordena entidades de um nivel por uma metrica.

    Args:
        linhas: Linhas ja filtradas.
        nivel: `conta`, `campanha`, `adset` ou `anuncio`.
        metrica: Chave da metrica base usada na ordenacao.
        topo: Quantidade maxima de entidades devolvidas.

    Returns:
        Lista de dicionarios com o identificador pseudonimizado, a plataforma,
        os pais na hierarquia, as metricas agregadas e os derivados.
    """
    coluna = f"{nivel}_id"
    grupos: dict = {}
    for linha in linhas:
        grupos.setdefault(linha[coluna], []).append(linha)

    resultado: list[dict] = []
    for identificador, membros in grupos.items():
        totais = agregar(membros)
        registro = {
            "id": identificador,
            "plataforma": ", ".join(sorted({m["plataforma"] for m in membros})),
            "versoes": len({m[f"{nivel}_versao"] for m in membros}),
            **{m: totais[m] for m in METRICAS},
            **calcular_derivadas(totais),
            "linhas": totais["linhas"],
        }
        for pai in ("conta", "campanha", "adset"):
            if pai == nivel:
                break
            registro[pai] = ", ".join(sorted({m[f"{pai}_id"] for m in membros}))
        resultado.append(registro)

    resultado.sort(key=lambda r: (r[metrica], r["id"]), reverse=True)
    return resultado[:topo] if topo else resultado
