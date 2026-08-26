"""Visualizacoes Plotly integradas ao tema dark do dashboard.

Este modulo e a unica fronteira em que ``Decimal`` vira ``float``. Os textos
visiveis continuam vindo dos formatadores exatos de :mod:`dashboard.metricas`.
Todos os graficos passam por :func:`aplicar_tema`, que centraliza superficie,
tipografia, eixos, hover e densidade.
"""

from decimal import Decimal

import plotly.graph_objects as go

from dashboard import metricas as m


COR_PLATAFORMA: dict[str, str] = {
    "Meta Ads": "#4F7CFF",
    "Google Ads": "#F59E0B",
}
COR_PADRAO: str = "#64748B"
COR_TEXTO: str = "#F1F5F9"
COR_SECUNDARIA: str = "#94A3B8"
COR_MUTED: str = "#7C899D"
COR_GRADE: str = "rgba(148, 163, 184, 0.12)"
COR_BORDA: str = "#27303D"
COR_HOVER: str = "#161D27"
TRANSPARENTE: str = "rgba(0,0,0,0)"
FONTE: str = (
    "Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
)
MESES: tuple[str, ...] = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)
CONFIG_PLOTLY: dict = {
    "displayModeBar": False,
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": False,
    "locale": "pt-BR",
}


def cor(plataforma: str) -> str:
    """Devolve a cor de uma plataforma ou um neutro para fonte desconhecida."""
    return COR_PLATAFORMA.get(plataforma, COR_PADRAO)


def _float(valor) -> float:
    """Converte um agregado para float apenas na fronteira do Plotly."""
    return float(valor if valor is not None else Decimal(0))


def aplicar_tema(figura: go.Figure, altura: int) -> go.Figure:
    """Aplica o sistema visual comum a qualquer figura do dashboard.

    Args:
        figura: Figura Plotly a integrar ao produto.
        altura: Altura final em pixels.

    Returns:
        A propria figura com tema, hover e eixos normalizados.
    """
    figura.update_layout(
        template=None,
        height=altura,
        margin=dict(l=12, r=18, t=24, b=10),
        font=dict(family=FONTE, size=12, color=COR_TEXTO),
        separators=",.",
        paper_bgcolor=TRANSPARENTE,
        plot_bgcolor=TRANSPARENTE,
        hoverlabel=dict(
            bgcolor=COR_HOVER,
            bordercolor=COR_BORDA,
            font=dict(family=FONTE, size=12, color=COR_TEXTO),
            namelength=-1,
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="left", x=0, title_text="",
            font=dict(size=11, color=COR_SECUNDARIA),
        ),
        hoverdistance=40,
        spikedistance=-1,
    )
    figura.update_xaxes(
        showgrid=False,
        zeroline=False,
        showline=True,
        linecolor=COR_BORDA,
        tickfont=dict(size=11, color=COR_MUTED),
        title_font=dict(size=11, color=COR_MUTED),
        fixedrange=True,
        automargin=True,
    )
    figura.update_yaxes(
        showgrid=True,
        gridcolor=COR_GRADE,
        gridwidth=1,
        zeroline=False,
        showline=False,
        tickfont=dict(size=11, color=COR_MUTED),
        title_font=dict(size=11, color=COR_MUTED),
        fixedrange=True,
        automargin=True,
    )
    return figura


def _formato_eixo(metrica: str) -> dict:
    """Define tickformat e unidade sem alterar os valores da figura."""
    formato = m.CATALOGO[metrica].formato
    if formato == m.MOEDA:
        return {"tickprefix": "R$ ", "tickformat": ",.0f"}
    if formato == m.INTEIRO:
        return {"tickformat": ",.0f"}
    return {"tickformat": ",.2f"}


def _poucos_dias(series: dict) -> bool:
    """Informa se ha no maximo quinze datas na serie."""
    dias = {ponto[0] for pontos in series.values() for ponto in pontos}
    return len(dias) <= 15


def _data_pt(data, com_ano: bool = True) -> str:
    """Formata uma data em portugues sem depender do locale do Plotly."""
    base = f"{data.day:02d} {MESES[data.month - 1]}"
    return f"{base} {data.year}" if com_ano else base


def serie_temporal(series: dict, metrica: str, altura: int = 350) -> go.Figure:
    """Desenha uma serie diaria com linha premium e hover unificado."""
    figura = go.Figure()
    dias = sorted({ponto[0] for pontos in series.values() for ponto in pontos})
    categorias = [_data_pt(dia) for dia in dias]
    for nome, pontos in series.items():
        figura.add_trace(go.Scatter(
            x=[_data_pt(ponto[0]) for ponto in pontos],
            y=[_float(ponto[1]) for ponto in pontos],
            name=nome,
            mode="lines+markers" if len(pontos) <= 15 else "lines",
            line=dict(color=cor(nome), width=2.6, shape="linear"),
            marker=dict(size=5, color=cor(nome), line=dict(width=0)),
            customdata=[m.formatar_metrica(metrica, ponto[1]) for ponto in pontos],
            hovertemplate=(
                "<b>%{fullData.name}</b><br>%{customdata}<extra></extra>"
            ),
            connectgaps=False,
        ))
    aplicar_tema(figura, altura)
    figura.update_layout(hovermode="x unified")
    passo = 1 if _poucos_dias(series) else max(1, len(dias) // 8)
    figura.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=categorias,
        tickmode="array",
        tickvals=categorias[::passo],
        ticktext=[_data_pt(dia, com_ano=False) for dia in dias[::passo]],
    )
    figura.update_yaxes(rangemode="tozero", title_text="", **_formato_eixo(metrica))
    return figura


def barras_plataforma(valores: dict, metrica: str,
                      altura: int = 190) -> go.Figure:
    """Compara Meta e Google em barras horizontais com valores reais."""
    plataformas = sorted(valores, key=lambda nome: _float(valores[nome]))
    suportadas = [m.suportada(metrica, plataforma) for plataforma in plataformas]
    numeros = [
        _float(valores[plataforma]) if suportada else 0.0
        for plataforma, suportada in zip(plataformas, suportadas)
    ]
    rotulos = [
        m.formatar_metrica(metrica, valores[plataforma])
        if suportada else m.AVISO_NAO_DISPONIVEL
        for plataforma, suportada in zip(plataformas, suportadas)
    ]
    figura = go.Figure(go.Bar(
        x=numeros,
        y=plataformas,
        orientation="h",
        marker=dict(
            color=[cor(p) if ok else COR_MUTED
                   for p, ok in zip(plataformas, suportadas)],
            line=dict(width=0),
        ),
        width=0.48,
        text=rotulos,
        textposition="outside",
        textfont=dict(size=11, color=COR_TEXTO),
        cliponaxis=False,
        customdata=rotulos,
        hovertemplate="<b>%{y}</b><br>%{customdata}<extra></extra>",
    ))
    aplicar_tema(figura, altura)
    maior = max(numeros, default=0)
    figura.update_layout(
        showlegend=False,
        margin=dict(l=10, r=100, t=8, b=8),
        bargap=0.42,
    )
    figura.update_xaxes(
        visible=False,
        range=[0, maior * 1.34] if maior else None,
    )
    figura.update_yaxes(
        showgrid=False,
        tickfont=dict(size=11, color=COR_SECUNDARIA),
    )
    return figura


def barras_ranking(itens: list[dict], metrica: str,
                   altura: int | None = None) -> go.Figure:
    """Desenha um ranking horizontal com origem legivel junto da entidade."""
    ordenados = list(reversed(itens))
    valores = [_float(item[metrica]) for item in ordenados]
    rotulos = [m.formatar_metrica(metrica, item[metrica]) for item in ordenados]
    ticktext = [
        f"{item['id']}<br><span style='color:{COR_MUTED};font-size:10px'>"
        f"{item['plataforma']}</span>" for item in ordenados
    ]
    figura = go.Figure(go.Bar(
        x=valores,
        y=list(range(len(ordenados))),
        orientation="h",
        marker=dict(
            color=[cor(item["plataforma"]) for item in ordenados],
            line=dict(width=0),
        ),
        width=0.56,
        text=rotulos,
        textposition="outside",
        textfont=dict(size=11, color=COR_TEXTO),
        cliponaxis=False,
        customdata=[
            [item["id"], item["plataforma"], rotulo]
            for item, rotulo in zip(ordenados, rotulos)
        ],
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>%{customdata[1]}<br>"
            "%{customdata[2]}<extra></extra>"
        ),
    ))
    aplicar_tema(figura, altura or max(250, 34 * len(itens) + 52))
    maior = max(valores, default=0)
    figura.update_layout(
        showlegend=False,
        margin=dict(l=12, r=110, t=8, b=8),
        bargap=0.34,
    )
    figura.update_xaxes(
        visible=False,
        range=[0, maior * 1.28] if maior else None,
    )
    figura.update_yaxes(
        showgrid=False,
        tickmode="array",
        tickvals=list(range(len(ordenados))),
        ticktext=ticktext,
        tickfont=dict(size=11, color=COR_TEXTO),
    )
    return figura


def barras_participacao(valores: dict, metrica: str,
                        altura: int = 126) -> go.Figure:
    """Desenha uma barra de participacao 100% horizontal e compacta."""
    total = sum(_float(valor) for valor in valores.values())
    figura = go.Figure()
    for plataforma in sorted(valores):
        valor = _float(valores[plataforma])
        percentual = (valor / total * 100) if total else 0.0
        percentual_formatado = m.formatar(
            Decimal(str(percentual)), m.PERCENTUAL
        )
        figura.add_trace(go.Bar(
            x=[percentual],
            y=["participacao"],
            orientation="h",
            name=f"{plataforma} · {percentual_formatado}",
            marker=dict(color=cor(plataforma), line=dict(width=0)),
            text=percentual_formatado if percentual >= 13 else "",
            textposition="inside",
            insidetextanchor="middle",
            textfont=dict(size=11, color="#FFFFFF"),
            customdata=[[m.formatar_metrica(metrica, valores[plataforma]),
                         percentual_formatado]],
            hovertemplate=(
                f"<b>{plataforma}</b><br>%{{customdata[0]}}"
                "<br>%{customdata[1]} do total<extra></extra>"
            ),
        ))
    aplicar_tema(figura, altura)
    figura.update_layout(
        barmode="stack",
        barnorm="percent",
        margin=dict(l=4, r=4, t=28, b=4),
        bargap=0.5,
    )
    figura.update_xaxes(visible=False, range=[0, 100])
    figura.update_yaxes(visible=False, showgrid=False)
    return figura
