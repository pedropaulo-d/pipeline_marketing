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


# Como uma metrica se comporta quando varias linhas factuais entram no mesmo
# recorte.
#
# `SOMAVEL` e o caso comum: investimento, impressoes, cliques e conversoes sao
# contagens de eventos, e somar eventos de linhas distintas produz o total
# certo.
#
# `NAO_ADITIVA` e o caso de `reach`: contagem de PESSOAS UNICAS. A mesma pessoa
# alcancada por dois anuncios, ou pelo mesmo anuncio em dois dias, aparece uma
# vez em cada linha — somar conta essa pessoa duas vezes. E a sobreposicao NAO
# e derivavel do dado: a API entrega o resultado ja deduplicado do recorte que
# ela mesma calculou, nunca os identificadores nem as intersecoes.
#
# Nao existe estimativa honesta a oferecer no lugar. `SUM(MAX(reach))` por
# anuncio tambem nao e um limite inferior garantido, porque anuncios distintos
# tambem se sobrepoem. A unica resposta correta sem informacao de deduplicacao
# e a ausencia de resposta.
SOMAVEL: str = "somavel"
NAO_ADITIVA: str = "nao_aditiva"


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
        agregacao: `SOMAVEL` quando somar linhas factuais produz um total
            valido; `NAO_ADITIVA` quando nao produz. Ver
            :data:`NAO_ADITIVA` e :func:`agregar`.
        observacao: Ressalva exibida junto do numero, quando houver.
        ajuda: Definicao da metrica, exibida na ajuda contextual do cartao.
            Responde "o que este numero conta", nao a ressalva de cobertura.
    """

    chave: str
    rotulo: str
    formato: str
    plataformas_sem_suporte: frozenset = frozenset()
    comparavel_entre_plataformas: bool = True
    agregacao: str = SOMAVEL
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
        "link_clicks", "Cliques", INTEIRO,
        # Segue consolidavel de proposito: CTR e CPC dependem dela e valem
        # como aproximacao no recorte misto. A ressalva abaixo e o que impede
        # ler o total como se fosse uma definicao unica, e os cartoes de
        # entrega mostram Meta e Google separados justamente por isso.
        observacao=(
            "Definição diferente por plataforma: cliques no link no Meta "
            "(`inline_link_clicks`); todos os cliques no Google "
            "(`metrics.clicks`). Não somar entre plataformas."
        ),
        ajuda=(
            "Quantidade de cliques reportada pela plataforma. O rótulo "
            "genérico é proposital: o recorte exato aparece nos cartões por "
            "plataforma."
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
        ajuda=(
            "Quantidade de visualizações de vídeo contabilizadas pela "
            "plataforma, cada uma pelo seu próprio critério de duração."
        ),
    ),
    "reach": Metrica(
        "reach", "Alcance", INTEIRO,
        plataformas_sem_suporte=frozenset({"Google Ads"}),
        comparavel_entre_plataformas=False,
        agregacao=NAO_ADITIVA,
        observacao=(
            "Não disponibilizado pela GAQL neste grão. Métrica não aditiva: "
            "só é exata na observação original (um anúncio em um dia)."
        ),
        ajuda=(
            "Quantidade de pessoas únicas alcançadas pelos anúncios, "
            "reportada pelo Meta Ads. Alcance é uma métrica não aditiva: o "
            "dataset armazena alcance por anúncio e dia e não contém "
            "informação para deduplicar pessoas entre anúncios ou períodos."
        ),
    ),
    "profile_views": Metrica(
        "profile_views", "Visitas ao perfil", INTEIRO,
        plataformas_sem_suporte=frozenset({"Google Ads"}),
        comparavel_entre_plataformas=False,
        observacao="Não disponibilizado pela GAQL neste grão.",
        ajuda=(
            "Visitas ao perfil do Instagram originadas dos anúncios, "
            "reportadas pelo Meta Ads."
        ),
    ),
    "purchase_value": Metrica(
        "purchase_value", "Valor de compras", MOEDA,
        plataformas_sem_suporte=frozenset({"Google Ads"}),
        comparavel_entre_plataformas=False,
        observacao=(
            "Não disponibilizado pela GAQL neste grão. Não é o equivalente "
            "Meta de Valor de conversão: um mede compra, o outro mede todas "
            "as conversion actions da conta."
        ),
        ajuda=(
            "Valor monetário das compras atribuídas pelo Meta Ads."
        ),
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

# Metricas que um componente de agregacao (ranking, serie consolidada) pode
# oferecer. Metrica nao aditiva fica de fora: ranquear entidades por um valor
# que so existe na linha factual, ou desenhar uma serie que ficaria vazia em
# todo ponto com mais de um anuncio, seria oferecer uma pergunta sem resposta.
METRICAS_AGREGAVEIS: tuple[str, ...] = tuple(
    chave for chave, m in CATALOGO.items() if m.agregacao == SOMAVEL
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


# ── Indicadores por plataforma ───────────────────────────────
# Meta e Google nao medem a mesma coisa sob o mesmo nome. `conversions` do
# Meta conta LEAD; `conversions` do Google agrega todas as conversion actions
# da conta. `purchase_value` so existe no Meta; `conversion_value` util so
# existe no Google. Somar os dois lados sob um rotulo generico produz um
# numero que nao responde pergunta nenhuma.
#
# Por isso os indicadores abaixo carregam a plataforma no nome e sao
# calculados a partir das SOMAS do recorte — nunca de media de indicador por
# anuncio, campanha ou plataforma, que e a forma classica de um ROAS mentir.

META: str = "Meta Ads"
GOOGLE: str = "Google Ads"

# Camada de apresentacao deliberadamente pequena: so os indicators validados
# pelos probes reais recebem rotulo amigavel. Valor desconhecido permanece
# tecnico internamente, mas nao ganha quantidade/custo agregado por inferencia.
ROTULOS_RESULTADO: dict[str, str] = {
    "lead": "Lead",
    "video_thruplay_watched_actions": "ThruPlay",
}

RESULTADO_MULTIPLOS: str = "Múltiplos"
RESULTADO_NAO_MAPEADO: str = "Resultado não mapeado"
RESULTADO_DISPONIVEL: str = "disponivel"
RESULTADO_AUSENTE: str = "ausente"
RESULTADO_INCOMPATIVEL: str = "incompativel"
RESULTADO_SEM_SUPORTE: str = "sem_suporte"
RESULTADO_DESCONHECIDO: str = "desconhecido"


@dataclass(frozen=True)
class Painel:
    """Indicador do painel de resultado/valor, com plataforma explicita.

    Attributes:
        chave: Identificador interno.
        rotulo: Nome exibido no cartao quando o recorte tem mais de uma
            plataforma e o sufixo e necessario para desambiguar.
        formato: Formato de exibicao.
        ajuda: Definicao e formula, exibidas na ajuda contextual.
        rotulo_curto: Nome exibido quando a plataforma ja esta isolada pelo
            filtro. Vazio significa usar `rotulo` sempre. Existe porque
            "CTR — Meta" num painel que so tem Meta e ruido: o sufixo informa
            no recorte misto e atrapalha no exclusivo.
    """

    chave: str
    rotulo: str
    formato: str
    ajuda: str
    rotulo_curto: str = ""


PAINEL: dict[str, Painel] = {
    "investimento_total": Painel(
        "investimento_total", "Investimento total", MOEDA,
        "Soma do investimento de todas as origens do recorte.",
    ),
    "investimento_meta": Painel(
        "investimento_meta", "Investimento", MOEDA,
        "Investimento no Meta Ads no período selecionado.",
    ),
    "investimento_google": Painel(
        "investimento_google", "Investimento", MOEDA,
        "Investimento no Google Ads no período selecionado.",
    ),
    "leads_meta": Painel(
        "leads_meta", "Leads — Meta", INTEIRO,
        "Quantidade de leads atribuídos pelo Meta Ads.",
        rotulo_curto="Leads",
    ),
    "cpl_meta": Painel(
        "cpl_meta", "CPL — Meta", MOEDA,
        "Custo médio por lead: investimento Meta dividido pelos leads "
        "atribuídos.",
        rotulo_curto="CPL",
    ),
    "conversoes_google": Painel(
        "conversoes_google", "Conversões — Google", DECIMAL,
        "Conversões reportadas pelo Google Ads. Fracionária por modelagem "
        "de atribuição; o valor não é arredondado.",
        rotulo_curto="Conversões",
    ),
    "cpa_google": Painel(
        "cpa_google", "CPA — Google", MOEDA,
        "Custo por aquisição: investimento Google dividido pelas conversões "
        "reportadas.",
        rotulo_curto="CPA",
    ),
    "compras_meta": Painel(
        "compras_meta", "Compras — Meta", INTEIRO,
        "Quantidade de compras atribuídas pelo Meta Ads.",
        rotulo_curto="Compras",
    ),
    "valor_compras_meta": Painel(
        "valor_compras_meta", "Valor de compras — Meta", MOEDA,
        "Valor monetário das compras atribuídas pelo Meta Ads.",
        rotulo_curto="Valor de compras",
    ),
    "valor_conversoes_google": Painel(
        "valor_conversoes_google", "Valor de conversões — Google", MOEDA,
        "Valor monetário atribuído às conversões pelo Google Ads. Agrega "
        "todas as conversion actions da conta, não apenas compras.",
        rotulo_curto="Valor de conversões",
    ),
    "valor_atribuido_total": Painel(
        "valor_atribuido_total", "Valor atribuído total", MOEDA,
        "Soma do valor de compras atribuído pelo Meta Ads e do valor de "
        "conversões reportado pelo Google Ads. As plataformas possuem "
        "definições próprias de conversão e atribuição.",
    ),
    "roas_meta": Painel(
        "roas_meta", "ROAS Meta", MULTIPLICADOR,
        "Valor de compras Meta dividido pelo investimento Meta.",
        rotulo_curto="ROAS",
    ),
    "roas_google": Painel(
        "roas_google", "ROAS Google", MULTIPLICADOR,
        "Valor de conversões Google dividido pelo investimento Google.",
        rotulo_curto="ROAS",
    ),
    "roas_total": Painel(
        "roas_total", "ROAS total", MULTIPLICADOR,
        "Valor atribuído total dividido pelo investimento total. Calculado "
        "pelas somas do recorte, nunca pela média dos ROAS por plataforma.",
    ),
    "ctr_meta": Painel(
        "ctr_meta", "CTR — Meta", PERCENTUAL,
        "Cliques no link Meta divididos pelas impressões Meta × 100.",
        rotulo_curto="CTR",
    ),
    "cpc_meta": Painel(
        "cpc_meta", "CPC — Meta", MOEDA,
        "Investimento Meta dividido pelos cliques no link Meta.",
        rotulo_curto="CPC",
    ),
    "ctr_google": Painel(
        "ctr_google", "CTR — Google", PERCENTUAL,
        "Cliques Google divididos pelas impressões Google × 100. O Google "
        "conta todos os cliques (`metrics.clicks`), recorte mais largo que o "
        "do Meta.",
        rotulo_curto="CTR",
    ),
    "cpc_google": Painel(
        "cpc_google", "CPC — Google", MOEDA,
        "Investimento Google dividido pelos cliques Google.",
        rotulo_curto="CPC",
    ),
    "cliques_meta": Painel(
        "cliques_meta", "Cliques no link — Meta", INTEIRO,
        "Cliques no link contabilizados pelo Meta Ads "
        "(`inline_link_clicks`).",
        rotulo_curto="Cliques no link",
    ),
    "cliques_google": Painel(
        "cliques_google", "Cliques — Google", INTEIRO,
        "Todos os cliques contabilizados pelo Google Ads "
        "(`metrics.clicks`). Recorte mais largo que o do Meta: as duas "
        "métricas não são equivalentes e não devem ser somadas.",
        rotulo_curto="Cliques",
    ),
}


# Hierarquia dos KPIs: RESULTADO primeiro, VOLUME por ultimo.
#
# O layout anterior abria com investimento, impressoes e cliques — volume de
# entrega ocupando o primeiro viewport. Quem gerencia trafego pergunta antes
# quanto custou o resultado, nao quantas vezes o anuncio apareceu. E os
# cartoes genericos `Conversoes` e `Valor de conversao` somavam Meta com
# Google sob o mesmo rotulo, escondendo que `conversions` do Meta conta LEAD e
# a do Google agrega todas as conversion actions da conta.
#
# Agora cada bloco e montado a partir das plataformas realmente presentes no
# recorte, e as metricas cuja definicao difere entre plataformas aparecem
# nomeadas por plataforma. As formulas vivem em `metricas.painel`.

PAINEL_RESULTADOS: dict[str, tuple[str, ...]] = {
    "meta": ("investimento_meta", "leads_meta", "cpl_meta", "compras_meta"),
    "google": ("investimento_google", "conversoes_google", "cpa_google"),
    "ambas": (
        "investimento_total", "leads_meta", "cpl_meta",
        "conversoes_google", "cpa_google", "compras_meta",
    ),
}

PAINEL_VALOR: dict[str, tuple[str, ...]] = {
    "meta": ("valor_compras_meta", "roas_meta"),
    "google": ("valor_conversoes_google", "roas_google"),
    # Os tres KPIs de valor na primeira linha; os ROAS na segunda, com o total
    # a frente. Ler valor e retorno na mesma secao evita comparar um ROAS com
    # o valor de outra plataforma sem perceber.
    "ambas": (
        "valor_atribuido_total", "valor_compras_meta",
        "valor_conversoes_google",
        "roas_total", "roas_meta", "roas_google",
    ),
}

# Entrega mistura metricas do catalogo com indicadores nomeados por
# plataforma: `link_clicks` tem definicao diferente nas duas origens e por
# isso nunca aparece somado sob um rotulo unico.
ENTREGA: dict[str, tuple[str, ...]] = {
    "meta": (
        "@impressions", "@reach", "cliques_meta",
        "@video_views", "@profile_views",
    ),
    "google": ("@impressions", "cliques_google", "@video_views"),
    "ambas": (
        "@impressions", "cliques_meta", "cliques_google",
        "@video_views", "@reach", "@profile_views",
    ),
}

# Eficiencia: CTR e CPC nunca consolidam, CPM sim.
#
# Investimento e impressao tem semantica compativel entre as duas plataformas,
# entao `spend / impressions * 1000` continua valendo no recorte misto. Ja
# `link_clicks` nao: somar `inline_link_clicks` do Meta com `metrics.clicks`
# do Google produziria um CTR e um CPC sem definicao.
#
# `#` prefixa indicador do catalogo de derivadas; sem prefixo, vem do painel
# por plataforma.
EFICIENCIA: dict[str, tuple[str, ...]] = {
    "meta": ("ctr_meta", "cpc_meta", "#cpm"),
    "google": ("ctr_google", "cpc_google", "#cpm"),
    "ambas": (
        "ctr_meta", "cpc_meta", "ctr_google", "cpc_google", "#cpm",
    ),
}


def recorte(plataformas: list[str]) -> str:
    """Traduz as plataformas presentes na chave de layout.

    Args:
        plataformas: Plataformas presentes nas linhas filtradas.

    Returns:
        ``"meta"``, ``"google"`` ou ``"ambas"``.
    """
    tem_meta = META in plataformas
    tem_google = GOOGLE in plataformas
    if tem_meta and not tem_google:
        return "meta"
    if tem_google and not tem_meta:
        return "google"
    return "ambas"


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
    """Agrega as metricas do conjunto informado, respeitando a aditividade.

    Metrica `SOMAVEL` e somada. Metrica `NAO_ADITIVA` — hoje so `reach` — so
    tem valor quando o conjunto e **uma unica linha factual**, que e a
    observacao original da API: um anuncio, um dia. A partir de duas linhas o
    valor vira ``None``, porque a sobreposicao de audiencia entre elas nao e
    derivavel do dado.

    A regra vale para qualquer eixo, nao so o tempo. Dois anuncios no MESMO
    dia tambem nao somam: alcance 1.000 e 800 nao dao 1.800, e nada no dataset
    diz quantas pessoas foram alcancadas pelos dois.

    Linha unica de plataforma que nao suporta a metrica tambem devolve
    ``None``: ali o zero armazenado significa ausencia de suporte, e exibi-lo
    como alcance seria apresentar indisponibilidade como desempenho.

    Args:
        linhas: Linhas ja filtradas, no grao de anuncio x dia.

    Returns:
        Dicionario com `linhas` (contagem) e uma entrada por metrica —
        `Decimal` quando ha valor, ``None`` quando a agregacao nao e valida.
    """
    total: dict = {"linhas": len(linhas)}
    for metrica in METRICAS:
        total[metrica] = Decimal(0)
    for linha in linhas:
        for metrica in METRICAS:
            total[metrica] += linha[metrica]

    for metrica in METRICAS:
        if CATALOGO[metrica].agregacao != NAO_ADITIVA:
            continue
        if len(linhas) == 1 and suportada(metrica, linhas[0]["plataforma"]):
            total[metrica] = linhas[0][metrica]
        else:
            total[metrica] = None
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


def resultado_campanha(linhas: list[dict]) -> dict:
    """Agrega Resultado Meta no grao campanha x periodo filtrado.

    O custo factual vindo da API e guardado para auditoria, mas nao participa
    desta conta: somar ou tirar media de razoes seria incorreto. Para um unico
    `result_type` + `result_attribution_window` validado, o custo agregado e
    `SUM(spend de toda a campanha) / SUM(result_count reportado)`. Linhas sem
    Resultado ainda carregam investimento e portanto participam do numerador.

    Mais de um tipo/janela, indicador desconhecido, Google ou ausencia total
    devolvem valores indisponiveis. Objective e optimization_goal nao entram
    na decisao.

    Args:
        linhas: Linhas factuais de uma unica campanha no recorte.

    Returns:
        Dicionario com tipo tecnico, rotulo, janela, quantidade, custo e
        estado semantico.
    """
    base = {
        "result_type": None,
        "result_count": None,
        "result_attribution_window": None,
        "cost_per_result": None,
        "tipo_resultado": None,
        "status_resultado": RESULTADO_AUSENTE,
    }
    if not linhas:
        return base

    if {linha["plataforma"] for linha in linhas} != {META}:
        return {**base, "status_resultado": RESULTADO_SEM_SUPORTE}

    com_resultado = [
        linha for linha in linhas
        if linha.get("result_type") is not None
    ]
    if not com_resultado:
        return base

    pares = {
        (linha.get("result_type"), linha.get("result_attribution_window"))
        for linha in com_resultado
    }
    if len(pares) != 1:
        return {
            **base,
            "tipo_resultado": RESULTADO_MULTIPLOS,
            "status_resultado": RESULTADO_INCOMPATIVEL,
        }

    result_type, janela = next(iter(pares))
    rotulo = ROTULOS_RESULTADO.get(result_type)
    if rotulo is None:
        return {
            **base,
            "result_type": result_type,
            "result_attribution_window": janela,
            "tipo_resultado": RESULTADO_NAO_MAPEADO,
            "status_resultado": RESULTADO_DESCONHECIDO,
        }

    quantidades = [linha.get("result_count") for linha in com_resultado]
    if any(valor is None for valor in quantidades):
        return {
            **base,
            "tipo_resultado": RESULTADO_MULTIPLOS,
            "status_resultado": RESULTADO_INCOMPATIVEL,
        }

    result_count = sum(quantidades, Decimal(0))
    spend = sum((linha["spend"] for linha in linhas), Decimal(0))
    return {
        "result_type": result_type,
        "result_count": result_count,
        "result_attribution_window": janela,
        "cost_per_result": dividir(spend, result_count),
        "tipo_resultado": rotulo,
        "status_resultado": RESULTADO_DISPONIVEL,
    }


def formatar_quantidade_resultado(valor) -> str:
    """Formata contagem inteira como inteira e preserva eventual fracao.

    Args:
        valor: Quantidade agregada ou ``None``.

    Returns:
        Texto pt-BR ou o marcador de indisponibilidade.
    """
    if valor is None:
        return INDISPONIVEL
    decimal = Decimal(str(valor))
    formato = INTEIRO if decimal == decimal.to_integral_value() else DECIMAL
    return formatar(decimal, formato)


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


def totais_por_plataforma(linhas: list[dict]) -> dict[str, dict]:
    """Agrega as metricas separadamente por plataforma.

    Args:
        linhas: Linhas ja filtradas, no grao de anuncio x dia.

    Returns:
        Dicionario ``plataforma -> agregado``. Plataforma ausente do recorte
        simplesmente nao aparece — nao vira zero.
    """
    return agregar_por(linhas, lambda linha: linha["plataforma"])


def _total(por_plataforma: dict[str, dict], plataforma: str, metrica: str):
    """Soma de uma metrica numa plataforma, ou ``None`` se ela nao esta no
    recorte.

    A distincao importa: ausencia da plataforma no filtro nao e desempenho
    zero, e um indicador calculado sobre ela nao deve ser exibido como 0.

    Args:
        por_plataforma: Saida de :func:`totais_por_plataforma`.
        plataforma: Nome da plataforma.
        metrica: Chave da metrica base.

    Returns:
        `Decimal` com a soma, ou ``None``.
    """
    agregado = por_plataforma.get(plataforma)
    return None if agregado is None else agregado[metrica]


def _soma(*valores):
    """Soma ignorando ausencias, devolvendo ``None`` se tudo for ausente.

    Args:
        *valores: Parcelas, cada uma `Decimal` ou ``None``.

    Returns:
        `Decimal` com a soma das parcelas presentes, ou ``None``.
    """
    presentes = [valor for valor in valores if valor is not None]
    if not presentes:
        return None
    return sum(presentes, Decimal(0))


def painel(linhas: list[dict]) -> dict:
    """Calcula todos os indicadores do painel a partir das SOMAS do recorte.

    Ponto unico das formulas de resultado e de valor. Os componentes leem
    daqui e nao recalculam nada — formula espalhada pela camada de
    apresentacao e como um numero saiu errado neste projeto antes.

    ROAS e CPL/CPA saem sempre da razao entre somas globais. Media de ROAS por
    plataforma, campanha ou anuncio daria outro numero, e um numero sem
    significado: cada parcela teria peso igual independentemente do
    investimento.

    Args:
        linhas: Linhas ja filtradas, no grao de anuncio x dia.

    Returns:
        Dicionario com uma entrada por chave de :data:`PAINEL`. O valor e
        ``None`` quando o indicador nao e calculavel — plataforma fora do
        recorte ou denominador invalido.
    """
    por_plataforma = totais_por_plataforma(linhas)

    investimento_meta = _total(por_plataforma, META, "spend")
    investimento_google = _total(por_plataforma, GOOGLE, "spend")
    cliques_meta = _total(por_plataforma, META, "link_clicks")
    cliques_google = _total(por_plataforma, GOOGLE, "link_clicks")
    valor_compras_meta = _total(por_plataforma, META, "purchase_value")
    valor_conversoes_google = _total(por_plataforma, GOOGLE, "conversion_value")

    investimento_total = _soma(investimento_meta, investimento_google)
    valor_atribuido_total = _soma(valor_compras_meta, valor_conversoes_google)

    return {
        "investimento_total": investimento_total,
        "investimento_meta": investimento_meta,
        "investimento_google": investimento_google,
        "leads_meta": _total(por_plataforma, META, "conversions"),
        "cpl_meta": dividir(
            investimento_meta, _total(por_plataforma, META, "conversions")
        ),
        "conversoes_google": _total(por_plataforma, GOOGLE, "conversions"),
        "cpa_google": dividir(
            investimento_google, _total(por_plataforma, GOOGLE, "conversions")
        ),
        "compras_meta": _total(por_plataforma, META, "purchases"),
        "valor_compras_meta": valor_compras_meta,
        "valor_conversoes_google": valor_conversoes_google,
        "valor_atribuido_total": valor_atribuido_total,
        "roas_meta": dividir(valor_compras_meta, investimento_meta),
        "roas_google": dividir(valor_conversoes_google, investimento_google),
        "roas_total": dividir(valor_atribuido_total, investimento_total),
        "cliques_meta": cliques_meta,
        "cliques_google": cliques_google,
        # CTR e CPC ficam SEMPRE isolados por plataforma. `link_clicks` guarda
        # `inline_link_clicks` no Meta e `metrics.clicks` no Google: recortes
        # diferentes. Um CTR calculado sobre a soma dos dois divide cliques de
        # duas definicoes por impressoes de duas definicoes e nao responde
        # pergunta nenhuma.
        "ctr_meta": dividir(
            cliques_meta, _total(por_plataforma, META, "impressions"),
            Decimal(100),
        ),
        "cpc_meta": dividir(investimento_meta, cliques_meta),
        "ctr_google": dividir(
            cliques_google, _total(por_plataforma, GOOGLE, "impressions"),
            Decimal(100),
        ),
        "cpc_google": dividir(investimento_google, cliques_google),
    }


def formatar_painel(chave: str, valor) -> str:
    """Formata um indicador do painel conforme o formato declarado.

    Args:
        chave: Chave em :data:`PAINEL`.
        valor: Valor calculado, ou ``None``.

    Returns:
        Texto formatado; o vazio padrao quando o valor e ``None``.

    Raises:
        KeyError: Se a chave nao existir no painel.
    """
    return formatar(valor, PAINEL[chave].formato)


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
    # Um ponto da serie e (serie, dia). Ele pode reunir varios anuncios — e
    # metrica nao aditiva nao pode ser somada entre eles. Guardamos tambem
    # quantas linhas factuais formaram cada ponto: com exatamente uma, o valor
    # armazenado e a propria observacao da API e vale; com mais de uma, o
    # ponto fica sem valor em vez de virar uma soma sem significado. E o que
    # permite ao grafico do detalhe de UM anuncio continuar mostrando alcance
    # por dia, sem abrir a porta para somar anuncios distintos.
    nao_aditiva = CATALOGO[metrica].agregacao == NAO_ADITIVA
    acumulado: dict = {}
    contagem: dict = {}
    suporte: dict = {}
    for linha in linhas:
        serie = linha["plataforma"] if por_plataforma else "Total"
        chave = linha["data"]
        acumulado.setdefault(serie, {})
        contagem.setdefault(serie, {})
        suporte.setdefault(serie, {})
        acumulado[serie][chave] = acumulado[serie].get(chave, Decimal(0)) + linha[metrica]
        contagem[serie][chave] = contagem[serie].get(chave, 0) + 1
        suporte[serie][chave] = (
            suporte[serie].get(chave, True)
            and suportada(metrica, linha["plataforma"])
        )

    if nao_aditiva:
        for serie, valores in acumulado.items():
            for chave in valores:
                if contagem[serie][chave] != 1 or not suporte[serie][chave]:
                    valores[chave] = None

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
        os pais na hierarquia, as metricas agregadas e os derivados. Metrica
        nao aditiva vem como ``None`` quando a entidade reune mais de uma
        linha factual.

    Raises:
        ValueError: Se a ordenacao pedir uma metrica nao aditiva. O ranking
            agrupa varias linhas por entidade, entao esse valor nao existe —
            ordenar por ele exigiria inventar um numero.
    """
    if CATALOGO[metrica].agregacao == NAO_ADITIVA:
        raise ValueError(
            f"ranking nao pode ordenar por '{metrica}': metrica nao aditiva "
            "nao tem valor agregado por entidade."
        )

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
        if nivel == "campanha":
            registro.update(resultado_campanha(membros))
        for pai in ("conta", "campanha", "adset"):
            if pai == nivel:
                break
            registro[pai] = ", ".join(sorted({m[f"{pai}_id"] for m in membros}))
        resultado.append(registro)

    resultado.sort(key=lambda r: (r[metrica], r["id"]), reverse=True)
    return resultado[:topo] if topo else resultado
