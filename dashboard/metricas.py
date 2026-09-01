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
from decimal import Decimal

from dashboard.contratos import LinhaDataset
# A formatacao vem de `dashboard.formatacao`, que nao conhece o catalogo. Os
# nomes ficam visiveis aqui porque este modulo e a fachada unica que o painel
# consome (`m.formatar`, `m.MOEDA`, ...): os consumidores nao precisam saber
# de qual lado da fronteira cada simbolo mora. `formatar_variacao` e o unico
# reexportado sem uso interno — `app.py` e os testes o consomem por esta via.
from dashboard.formatacao import (  # noqa: F401
    DECIMAL,
    INDISPONIVEL,
    INTEIRO,
    MOEDA,
    MULTIPLICADOR,
    PERCENTUAL,
    formatar,
    formatar_variacao,
)


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

# Rotulo amigavel dos indicators de Resultado OBSERVADOS na superficie. Cada
# chave saiu de `results[].indicator` em dado real; nenhum rotulo foi inventado
# para um indicator que a fonte nunca devolveu. Indicator desconhecido continua
# sem rotulo — e continua sem quantidade e sem custo agregados por inferencia.
#
# Os dez rotulos abaixo cobrem os dez indicators presentes no artefato atual. A
# escolha de nome nao e cosmetica: cada `result_type` e um EIXO DE COMPARACAO
# diferente na classificacao de campanhas, e dois eixos com o mesmo nome na
# tela levariam o leitor a comparar numeros medidos contra referencias
# distintas.
#
# Por isso os dois indicators de Lead NAO colapsam mais em "Lead": pixel
# offsite e formulario onsite agrupado sao origens diferentes e grupos de
# comparacao diferentes.
#
# `reach` e `...fb_pixel_purchase` carregam o sufixo de origem de proposito:
# - "Alcance (resultado Meta)" e o resultado que a Meta reporta para a
#   campanha. Nao e a metrica `reach` da tabela, que e NAO ADITIVA e continua
#   indisponivel em qualquer agregado com mais de uma linha;
# - "Compra (resultado Pixel)" e um indicator de Resultado, distinto da metrica
#   canonica `purchases` usada nos KPIs. Os dois nao se convertem um no outro.
#
# `lead` sem prefixo NAO entra. Ele existiu aqui enquanto o unico material
# disponivel era fixture sintetica escrita antes de observar o contrato real;
# nenhuma das 901 observacoes reais devolveu `results[].indicator = "lead"`.
# Rotulo derivado de fixture propria e o dashboard confirmando a si mesmo, nao
# evidencia da fonte.
#
# CUIDADO — contrato diferente, nome igual: a metrica `conversions` do Meta
# continua sendo `actions[action_type = "lead"]`, e nada aqui a toca.
# `actions[].action_type` e `results[].indicator` sao dois vocabularios
# distintos da mesma resposta da API.
ROTULOS_RESULTADO: dict[str, str] = {
    "actions:offsite_conversion.fb_pixel_lead": "Lead (Pixel)",
    "actions:onsite_conversion.lead_grouped": "Lead (formulário)",
    "actions:onsite_conversion.messaging_conversation_started_7d":
        "Conversas iniciadas (7 dias)",
    "video_thruplay_watched_actions": "ThruPlay",
    "profile_visit_view": "Visitas ao perfil",
    "actions:post_engagement": "Engajamento com a publicação",
    "actions:omni_landing_page_view": "Visualizações da página de destino",
    "estimated_ad_recallers": "Lembrança do anúncio (estimada)",
    "reach": "Alcance (resultado Meta)",
    "actions:offsite_conversion.fb_pixel_purchase": "Compra (resultado Pixel)",
}

RESULTADO_MULTIPLOS: str = "Múltiplos"
RESULTADO_INCOMPLETO: str = "Dados incompletos"
RESULTADO_NAO_MAPEADO: str = "Resultado não mapeado"
RESULTADO_DISPONIVEL: str = "disponivel"
RESULTADO_AUSENTE: str = "ausente"
RESULTADO_INCOMPATIVEL: str = "incompativel"
RESULTADO_SEM_SUPORTE: str = "sem_suporte"
RESULTADO_DESCONHECIDO: str = "desconhecido"
RESULTADO_PARCIAL: str = "parcial"


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


def agregar(linhas: list[LinhaDataset]) -> dict:
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


def agregar_por(linhas: list[LinhaDataset], chave) -> dict:
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


def janela_informativa(linha: LinhaDataset) -> bool:
    """Diz se a linha carrega evidencia factual sobre a janela de atribuicao.

    Nem todo `result_attribution_window` NULL significa a mesma coisa, e tratar
    os dois casos como um so foi um erro medido: no bloco real de sete dias ele
    tornava 20 das 39 campanhas tipadas artificialmente incompativeis.

    - **NULL neutro** — a linha e FORMA A: a fonte declarou o `indicator` e nao
      entregou `values`. Sem `values` nao existe janela factual a comparar, e o
      NULL e ausencia de evidencia, nao uma janela alternativa. A linha continua
      factual e valida, e seu investimento continua entrando no denominador —
      ela apenas nao acrescenta semantica ao conjunto de janelas do recorte.

    - **NULL informativo** — a linha e FORMA B: ha quantidade e custo, e a fonte
      simplesmente nao aplica janela a esse `indicator`. Isso e uma semantica
      real de "sem janela" e continua incompativel com uma janela explicita.

    Quantidade zero COM janela explicita tambem e informativa: ali a fonte
    declarou a janela, e declaracao explicita nunca e neutralizada por o
    resultado ter sido zero.

    A neutralidade existe apenas nesta analise agregada. O grao factual
    persistido na Silver e no Gold nao muda: nenhuma janela e imputada, nenhum
    valor e herdado de outro dia.

    Args:
        linha: Linha factual tipada (`result_type` nao nulo).

    Returns:
        ``True`` quando a linha deve participar da decisao de compatibilidade
        de janela.
    """
    quantidade = linha.get("result_count")
    return (
        (quantidade is not None and quantidade > 0)
        or linha.get("cost_per_result") is not None
        or linha.get("result_attribution_window") is not None
    )


def resultado_campanha(
    linhas: list[LinhaDataset], *, exigir_rotulo: bool = True
) -> dict:
    """Agrega Resultado Meta no grao campanha x periodo filtrado.

    O custo factual vindo da API e guardado para auditoria, mas nao participa
    desta conta: somar ou tirar media de razoes seria incorreto. Quando TODAS
    as linhas do recorte declaram o mesmo `result_type` +
    `result_attribution_window`, o custo agregado e
    `SUM(spend) / SUM(result_count)`.

    Ausencia total e ausencia declarada sao coisas diferentes
    -------------------------------------------------------
    Uma linha com `result_type` NULL e AUSENCIA TOTAL: a Meta nao devolveu
    `results` nem `cost_per_result`, entao nao declarou tipo algum. Nao e a
    FORMA A do parser, em que a fonte declara o `indicator` e entrega
    `result_count = 0` — ali o tipo existe e a linha participa normalmente da
    soma de investimento.

    Por que o recorte misto e fail closed
    -------------------------------------
    Somar o investimento de uma linha sem tipo ao denominador de um Resultado
    observado em OUTRO dia assume que aquele gasto pertence a mesma semantica.
    Nada no dado sustenta isso: `objective` e `optimization_goal` sao contexto,
    nao contrato, e a auditoria do bloco real (56 campanhas: 17 so com ausencia
    total, 39 so com Resultado observado, intersecao ZERO) nao produziu uma
    unica campanha em que a inferencia pudesse ser verificada. Sem evidencia, o
    recorte misto devolve "Dados incompletos" — nao "Multiplos", porque o
    problema nao e haver mais de um tipo, e sim faltar contrato em parte do
    periodo.

    Compatibilidade de janela
    -------------------------
    So as linhas informativas decidem — ver :func:`janela_informativa`. Uma
    linha de FORMA A (quantidade zero, sem custo e sem janela) e NEUTRA: entra
    no investimento, nao entra no conjunto de janelas. Um recorte inteiramente
    neutro continua agregavel, com quantidade zero e custo indisponivel.

    Mais de um tipo, mais de uma janela informativa, indicador desconhecido,
    Google ou ausencia total devolvem valores indisponiveis.

    Rotulo ausente nao e defeito semantico
    --------------------------------------
    Um `result_type` sem entrada em `ROTULOS_RESULTADO` nao pode virar KPI de
    painel: exibir "conversa iniciada" como se fosse Lead seria interpretacao
    de negocio inventada na apresentacao. Comparar o custo de duas campanhas
    do MESMO `result_type` tecnico, por outro lado, continua valido — a
    comparacao nao depende de existir um nome amigavel. Por isso
    `exigir_rotulo=False` deixa o agregado seguir com o tipo tecnico, marcado
    como `RESULTADO_NAO_MAPEADO`, sem afrouxar nenhuma das checagens
    semanticas anteriores. O padrao continua sendo o comportamento do painel.

    Args:
        linhas: Linhas factuais de uma unica campanha no recorte.
        exigir_rotulo: Quando ``True`` (padrao), tipo sem rotulo amigavel
            interrompe a agregacao com `RESULTADO_DESCONHECIDO`. Quando
            ``False``, a agregacao prossegue com o tipo tecnico.

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

    # Recorte misto: ha tipo declarado em parte do periodo e ausencia total no
    # resto. Barrado antes de qualquer conta — inclusive antes da checagem de
    # multiplos tipos, porque a falta de contrato e o defeito mais grave e o
    # rotulo precisa dizer isso, nao "Multiplos".
    if len(com_resultado) != len(linhas):
        return {
            **base,
            "tipo_resultado": RESULTADO_INCOMPLETO,
            "status_resultado": RESULTADO_PARCIAL,
        }

    tipos = {linha.get("result_type") for linha in com_resultado}
    if len(tipos) != 1:
        return {
            **base,
            "tipo_resultado": RESULTADO_MULTIPLOS,
            "status_resultado": RESULTADO_INCOMPATIVEL,
        }

    result_type = next(iter(tipos))
    rotulo = ROTULOS_RESULTADO.get(result_type)
    if rotulo is None and exigir_rotulo:
        return {
            **base,
            "result_type": result_type,
            "tipo_resultado": RESULTADO_NAO_MAPEADO,
            "status_resultado": RESULTADO_DESCONHECIDO,
        }

    # Defensivo. O parser da Silver nunca emite tipo com quantidade NULL, e o
    # contrato do CSV recusa a linha antes daqui. Se chegasse, a quantidade
    # ausente NAO vira zero: o recorte fica incompleto.
    quantidades = [linha.get("result_count") for linha in com_resultado]
    if any(valor is None for valor in quantidades):
        return {
            **base,
            "tipo_resultado": RESULTADO_INCOMPLETO,
            "status_resultado": RESULTADO_PARCIAL,
        }

    # So as linhas INFORMATIVAS decidem a compatibilidade de janela. Ver
    # `janela_informativa`: a linha de FORMA A nao tem `values`, logo nao tem
    # janela factual a comparar, e seu NULL nao pode contar como uma segunda
    # semantica.
    janelas = {
        linha.get("result_attribution_window")
        for linha in com_resultado
        if janela_informativa(linha)
    }
    if len(janelas) > 1:
        return {
            **base,
            "tipo_resultado": RESULTADO_MULTIPLOS,
            "status_resultado": RESULTADO_INCOMPATIVEL,
        }

    # Sem nenhuma linha informativa (o recorte inteiro e FORMA A) o agregado
    # continua valido: o tipo e conhecido, a quantidade e zero e a janela
    # permanece NULL. Nao ha janela a imputar porque nao houve resultado.
    janela = next(iter(janelas)) if janelas else None

    result_count = sum(quantidades, Decimal(0))
    spend = sum((linha["spend"] for linha in linhas), Decimal(0))
    return {
        "result_type": result_type,
        "result_count": result_count,
        "result_attribution_window": janela,
        "cost_per_result": dividir(spend, result_count),
        "tipo_resultado": rotulo if rotulo is not None else RESULTADO_NAO_MAPEADO,
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


def totais_por_plataforma(linhas: list[LinhaDataset]) -> dict[str, dict]:
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


def painel(linhas: list[LinhaDataset]) -> dict:
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


def serie_diaria(
    linhas: list[LinhaDataset], metrica: str, por_plataforma: bool = True
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
    linhas: list[LinhaDataset], nivel: str, metrica: str,
    topo: int | None = None,
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
