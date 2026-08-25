"""Graficos Plotly do dashboard.

Este modulo e a unica fronteira em que `Decimal` vira `float`. A conversao
acontece aqui porque Plotly serializa para JSON e nao entende `Decimal`; toda
agregacao a montante permanece exata, e os rotulos exibidos no tooltip sao os
textos ja formatados por `metricas.formatar`, nao o `float` reconvertido.

Escolhas visuais
----------------
- Uma metrica por grafico. Metricas com escalas incompativeis no mesmo eixo
  produzem uma serie achatada contra o eixo e outra ilegivel.
- Cor por plataforma, sempre a mesma em toda a aplicacao, para o leitor nao
  reaprender a legenda a cada secao.
- `plotly_white`, grade discreta e fonte grande o suficiente para projetor.
- Sem titulo dentro do grafico: o titulo e o cabecalho da secao no Streamlit,
  o que evita duplicacao e economiza altura util.
"""

from decimal import Decimal

import plotly.graph_objects as go

from dashboard import metricas as m

# Cores das plataformas: referencia moderada, nao reproducao de identidade
# visual. Azul para o Meta, ambar para o Google, ambos rebaixados em saturacao
# para conviverem com o fundo claro sem vibrar no projetor.
COR_PLATAFORMA: dict[str, str] = {
    "Meta Ads": "#3B6FE0",
    "Google Ads": "#D9902B",
}

COR_PADRAO: str = "#98A2B3"
COR_TEXTO: str = "#172033"
COR_SUAVE: str = "#667085"
COR_GRADE: str = "#EAEDF2"

FONTE: str = (
    "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
)


def cor(plataforma: str) -> str:
    """Devolve a cor associada a uma plataforma.

    Args:
        plataforma: Nome da plataforma.

    Returns:
        Cor em hexadecimal; cinza neutro para plataforma desconhecida — uma
        fonte nova nao deve herdar a cor de outra.
    """
    return COR_PLATAFORMA.get(plataforma, COR_PADRAO)


def _float(valor) -> float:
    """Converte para `float` na fronteira de apresentacao.

    Args:
        valor: Valor agregado, normalmente `Decimal`.

    Returns:
        O mesmo valor como `float`.
    """
    return float(valor if valor is not None else Decimal(0))


def _aplicar_layout(figura: go.Figure, altura: int) -> go.Figure:
    """Aplica o layout comum a todos os graficos.

    Args:
        figura: Figura a ajustar.
        altura: Altura em pixels.

    Returns:
        A propria figura, ajustada.
    """
    figura.update_layout(
        template="plotly_white",
        height=altura,
        margin=dict(l=6, r=10, t=26, b=6),
        font=dict(family=FONTE, size=12.5, color=COR_TEXTO),
        hoverlabel=dict(font_size=13, font_family=FONTE),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            title_text="",
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )
    figura.update_xaxes(
        showgrid=False, linecolor=COR_GRADE, tickfont=dict(color=COR_SUAVE)
    )
    figura.update_yaxes(
        gridcolor=COR_GRADE, zerolinecolor=COR_GRADE,
        tickfont=dict(color=COR_SUAVE),
    )
    return figura


def serie_temporal(series: dict, metrica: str, altura: int = 340) -> go.Figure:
    """Desenha a evolucao diaria de uma metrica.

    Args:
        series: Saida de `metricas.serie_diaria`: ``serie -> [(data, valor)]``.
        metrica: Chave da metrica base, usada para rotulo e formatacao.
        altura: Altura do grafico em pixels.

    Returns:
        Figura com uma linha por serie, tooltip unificado por dia e rotulos
        formatados em pt-BR.
    """
    figura = go.Figure()
    for nome, pontos in series.items():
        datas = [ponto[0] for ponto in pontos]
        valores = [_float(ponto[1]) for ponto in pontos]
        rotulos = [m.formatar_metrica(metrica, ponto[1]) for ponto in pontos]
        figura.add_trace(go.Scatter(
            x=datas,
            y=valores,
            name=nome,
            mode="lines+markers",
            line=dict(color=cor(nome), width=2.5, shape="spline", smoothing=0.4),
            marker=dict(size=5),
            customdata=rotulos,
            hovertemplate="%{customdata}<extra>%{fullData.name}</extra>",
        ))

    _aplicar_layout(figura, altura)
    figura.update_layout(hovermode="x unified")
    figura.update_xaxes(tickformat="%d/%m", dtick="D1" if _poucos_dias(series) else None)
    figura.update_yaxes(title_text=m.CATALOGO[metrica].rotulo, rangemode="tozero")
    return figura


def _poucos_dias(series: dict) -> bool:
    """Diz se a serie e curta o bastante para marcar todos os dias no eixo.

    Args:
        series: Series por nome.

    Returns:
        ``True`` quando ha no maximo 15 dias distintos.
    """
    dias = {ponto[0] for pontos in series.values() for ponto in pontos}
    return len(dias) <= 15


def barras_plataforma(
    valores: dict, metrica: str, altura: int = 210
) -> go.Figure:
    """Compara uma metrica entre plataformas.

    Plataforma que nao coleta a metrica neste grao recebe barra vazia e o
    rotulo "nao disponibilizado nesta origem": exibir o zero sem contexto
    sugeriria desempenho nulo onde nao houve medicao.

    Args:
        valores: ``plataforma -> valor agregado``.
        metrica: Chave da metrica base.
        altura: Altura do grafico em pixels.

    Returns:
        Figura de barras verticais, uma por plataforma.
    """
    plataformas = sorted(valores)
    suportadas = [m.suportada(metrica, p) for p in plataformas]
    alturas = [
        _float(valores[p]) if ok else 0.0
        for p, ok in zip(plataformas, suportadas)
    ]
    rotulos = [
        m.formatar_metrica(metrica, valores[p]) if ok else m.AVISO_NAO_DISPONIVEL
        for p, ok in zip(plataformas, suportadas)
    ]

    figura = go.Figure(go.Bar(
        x=plataformas,
        y=alturas,
        marker_color=[cor(p) if ok else "#CBD5E1"
                      for p, ok in zip(plataformas, suportadas)],
        text=rotulos,
        textposition="outside",
        cliponaxis=False,
        customdata=rotulos,
        hovertemplate="%{x}: %{customdata}<extra></extra>",
        width=0.45,
    ))
    _aplicar_layout(figura, altura)
    figura.update_layout(
        showlegend=False,
        margin=dict(l=6, r=10, t=18, b=6),
    )
    figura.update_yaxes(rangemode="tozero", showticklabels=False)
    return figura


def barras_ranking(
    itens: list[dict], metrica: str, altura: int | None = None
) -> go.Figure:
    """Desenha o ranking de entidades por uma metrica.

    Args:
        itens: Saida de `metricas.ranking`, ja recortada no Top N.
        metrica: Chave da metrica usada na ordenacao.
        altura: Altura em pixels; calculada a partir da quantidade de itens
            quando omitida.

    Returns:
        Figura de barras horizontais, do maior para o menor de cima para
        baixo, colorida por plataforma.
    """
    # Plotly desenha o eixo Y de baixo para cima: inverter aqui poe o maior no
    # topo, que e como se le um ranking.
    ordenados = list(reversed(itens))
    identificadores = [item["id"] for item in ordenados]
    valores = [_float(item[metrica]) for item in ordenados]
    rotulos = [m.formatar_metrica(metrica, item[metrica]) for item in ordenados]
    cores = [cor(item["plataforma"]) for item in ordenados]

    figura = go.Figure(go.Bar(
        x=valores,
        y=identificadores,
        orientation="h",
        marker_color=cores,
        text=rotulos,
        textposition="auto",
        customdata=[[item["plataforma"], rotulo]
                    for item, rotulo in zip(ordenados, rotulos)],
        hovertemplate="%{y}<br>%{customdata[0]}: %{customdata[1]}<extra></extra>",
    ))
    _aplicar_layout(figura, altura or max(230, 30 * len(itens) + 55))
    figura.update_layout(showlegend=False)
    figura.update_xaxes(showticklabels=False, showgrid=False)
    figura.update_yaxes(gridcolor="white", tickfont=dict(size=12))
    return figura


def barras_participacao(
    valores: dict, metrica: str, altura: int = 104
) -> go.Figure:
    """Desenha a participacao de cada plataforma numa metrica consolidavel.

    Args:
        valores: ``plataforma -> valor agregado``.
        metrica: Chave da metrica base.
        altura: Altura em pixels.

    Returns:
        Figura de barra unica empilhada horizontalmente.
    """
    total = sum(_float(v) for v in valores.values())
    figura = go.Figure()
    for plataforma in sorted(valores):
        valor = _float(valores[plataforma])
        fracao = (valor / total * 100) if total else 0.0
        figura.add_trace(go.Bar(
            x=[valor],
            y=[m.CATALOGO[metrica].rotulo],
            orientation="h",
            name=plataforma,
            marker_color=cor(plataforma),
            text=f"{plataforma} · {m.formatar(Decimal(str(fracao)), m.PERCENTUAL)}",
            textposition="inside",
            insidetextanchor="middle",
            hovertemplate=(
                f"{plataforma}: "
                f"{m.formatar_metrica(metrica, valores[plataforma])}"
                "<extra></extra>"
            ),
        ))
    _aplicar_layout(figura, altura)
    figura.update_layout(
        barmode="stack", showlegend=False,
        margin=dict(l=6, r=6, t=6, b=6),
        bargap=0.35,
    )
    figura.update_xaxes(showticklabels=False, showgrid=False)
    figura.update_yaxes(showticklabels=False)
    return figura
