"""Componentes visuais reutilizaveis do dashboard.

O tema nativo cuida das cores dos widgets React do Streamlit. Este modulo
completa a identidade dark com layout, densidade e componentes de apresentacao.
A ajuda dos indicadores usa ``st.metric(help=...)``: o icone e o tooltip sao
nativos, alcancaveis por teclado e nao dependem de interacao CSS artesanal.
"""

import html

import streamlit as st

from dashboard import metricas as m


ESTILO: str = """
<style>
    :root {
        --fundo: #080B10;
        --sidebar: #0D1117;
        --cartao: #11161E;
        --elevado: #161D27;
        --borda: #27303D;
        --borda-suave: #242C37;
        --texto: #F1F5F9;
        --texto-secundario: #94A3B8;
        --texto-muted: #7C899D;
        --accent: #8B5CF6;
        --accent-claro: #A78BFA;
        --raio: 11px;
        --fonte: Inter, system-ui, -apple-system, BlinkMacSystemFont,
                 "Segoe UI", sans-serif;
    }

    html, body, .stApp, [data-testid="stAppViewContainer"] {
        color-scheme: dark;
        background: var(--fundo);
        color: var(--texto);
        font-family: var(--fonte);
    }
    @media (prefers-color-scheme: light) {
        html, body, .stApp, [data-testid="stAppViewContainer"] {
            color-scheme: dark;
            background: var(--fundo);
            color: var(--texto);
        }
    }
    [data-testid="stDecoration"] { display: none; }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stToolbarActions"] { display: none; }
    footer { display: none; }

    .block-container {
        width: 100%;
        max-width: 1440px;
        margin-inline: auto;
        padding: 20px 32px 48px;
    }
    [data-testid="stVerticalBlock"] { gap: 8px; }
    [data-testid="stHorizontalBlock"] { gap: 12px; }
    [data-testid="stElementContainer"] { margin-bottom: 0; }
    h1, h2, h3, h4, p, span, label, button, input { font-family: var(--fonte); }
    h1, h2, h3, h4 { color: var(--texto); }
    a { color: var(--accent-claro); }

    /* Cabecalho de pagina */
    .pg-titulo {
        margin: 0;
        color: var(--texto);
        font-size: 1.82rem;
        font-weight: 680;
        letter-spacing: -0.025em;
        line-height: 1.18;
    }
    .pg-desc {
        max-width: 72ch;
        margin: 5px 0 0;
        color: var(--texto-secundario);
        font-size: 0.93rem;
        line-height: 1.45;
    }
    .pg-meta {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        align-items: end;
        gap: 16px 24px;
        margin-top: 12px;
        padding-bottom: 4px;
    }
    .pg-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .pg-periodo {
        color: var(--texto);
        font-size: 0.84rem;
        font-weight: 580;
        line-height: 1.35;
    }
    .pg-registros {
        color: var(--texto-muted);
        font-size: 0.76rem;
        line-height: 1.35;
    }
    .selo {
        display: inline-flex;
        align-items: center;
        min-height: 26px;
        padding: 4px 9px;
        border: 1px solid rgba(139, 92, 246, 0.35);
        border-radius: 7px;
        background: rgba(139, 92, 246, 0.09);
        color: #C4B5FD;
        font-size: 0.64rem;
        font-weight: 650;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        white-space: nowrap;
    }
    .selo-demo {
        border-color: rgba(245, 158, 11, 0.34);
        background: rgba(245, 158, 11, 0.09);
        color: #FBBF24;
    }

    /* Titulos e microcopy */
    .secao { margin: 18px 0 9px; }
    .secao-titulo {
        margin: 0;
        color: var(--texto);
        font-size: 1rem;
        font-weight: 620;
        letter-spacing: -0.012em;
    }
    .secao-apoio, .grafico-apoio {
        max-width: 78ch;
        margin: 3px 0 0;
        color: var(--texto-muted);
        font-size: 0.78rem;
        line-height: 1.45;
    }
    .grafico-titulo {
        margin: 0;
        color: var(--texto);
        font-size: 0.9rem;
        font-weight: 620;
        letter-spacing: -0.01em;
    }

    /* KPI nativo: o help de st.metric fornece o icone acessivel. */
    [data-testid="stMetric"] {
        box-sizing: border-box;
        min-height: 116px;
        padding: 15px 16px 13px;
        border: 1px solid var(--borda) !important;
        border-radius: var(--raio) !important;
        background: var(--cartao);
        transition: background-color 180ms ease, border-color 180ms ease;
    }
    [data-testid="stMetric"]:hover {
        background: var(--elevado);
        border-color: #354154 !important;
    }
    [data-testid="stMetricLabel"] {
        color: var(--texto-muted);
        font-size: 0.7rem;
        font-weight: 620;
        letter-spacing: 0.075em;
        text-transform: uppercase;
    }
    [data-testid="stMetricValue"] {
        margin-top: 3px;
        color: var(--texto);
        font-size: clamp(1.65rem, 2.1vw, 2rem);
        font-weight: 670;
        letter-spacing: -0.035em;
        line-height: 1.15;
        font-variant-numeric: tabular-nums;
    }
    [data-testid="stMetricDelta"] {
        overflow: visible !important;
        padding: 0 !important;
        background: transparent !important;
        color: var(--texto-secundario) !important;
        font-size: 0.74rem;
        line-height: 1.25;
    }
    [data-testid="stMetricDelta"] p {
        overflow: visible !important;
        white-space: normal !important;
        text-overflow: clip !important;
    }
    [data-testid="stMetric"] button:focus-visible {
        outline: 2px solid var(--accent);
        outline-offset: 2px;
    }
    .st-key-grade_eficiencia [data-testid="stMetric"],
    .st-key-grade_resumo [data-testid="stMetric"],
    .st-key-grade_resumo_entidades [data-testid="stMetric"] {
        min-height: 88px;
        padding: 11px 13px 10px;
    }
    .st-key-grade_eficiencia [data-testid="stMetricValue"],
    .st-key-grade_resumo [data-testid="stMetricValue"],
    .st-key-grade_resumo_entidades [data-testid="stMetricValue"] {
        font-size: 1.45rem;
    }
    /* Cards e Plotly compartilham superficie. */
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--borda) !important;
        border-radius: var(--raio) !important;
        background: var(--cartao);
        transition: background-color 180ms ease, border-color 180ms ease;
    }
    [data-testid="stVerticalBlockBorderWrapper"]:hover {
        border-color: #354154 !important;
    }
    .st-key-cartao_evolucao [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-cartao_ranking_campanha [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-cartao_ranking_anuncio [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-cartao_detalhe_anuncio [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-card_participacao [data-testid="stVerticalBlockBorderWrapper"],
    .st-key-card_cobertura [data-testid="stVerticalBlockBorderWrapper"] {
        padding: 15px 16px 12px;
    }
    .stPlotlyChart { border-radius: 8px; overflow: hidden; }
    .modebar { display: none !important; }

    /* Controles da area principal. */
    .block-container [data-testid="stWidgetLabel"] p {
        color: var(--texto-secundario);
        font-size: 0.75rem;
        font-weight: 560;
    }
    .block-container [data-baseweb="select"] > div,
    .block-container [data-baseweb="input"],
    .block-container [data-baseweb="base-input"] {
        border-color: var(--borda) !important;
        background: var(--elevado) !important;
    }
    .block-container [data-baseweb="select"] > div:focus-within,
    .block-container [data-baseweb="input"]:focus-within,
    .block-container [data-baseweb="base-input"]:focus-within {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.18);
    }
    .st-key-controles_serie { max-width: 690px; }
    .st-key-controles_ranking_campanha,
    .st-key-controles_ranking_anuncio { max-width: 520px; }
    .st-key-controles_anuncio { max-width: 720px; }

    /* Notas, empty state e detalhe. */
    .nota, .estado-vazio {
        border: 1px solid var(--borda);
        border-radius: var(--raio);
        background: var(--cartao);
        color: var(--texto-secundario);
    }
    .nota {
        padding: 10px 12px;
        border-left: 2px solid var(--texto-muted);
        font-size: 0.77rem;
        line-height: 1.48;
    }
    .estado-vazio { padding: 28px 24px; text-align: center; }
    .estado-vazio strong {
        display: block;
        color: var(--texto);
        font-size: 0.95rem;
        font-weight: 610;
    }
    .estado-vazio span {
        display: block;
        margin-top: 4px;
        color: var(--texto-muted);
        font-size: 0.8rem;
    }
    .detalhe-titulo {
        margin: 0 0 10px;
        color: var(--texto);
        font-size: 1rem;
        font-weight: 620;
    }
    .detalhe-grid {
        display: grid;
        grid-template-columns: repeat(5, minmax(0, 1fr));
        gap: 10px;
        margin-bottom: 8px;
    }
    .detalhe-item {
        min-width: 0;
        padding: 9px 10px;
        border: 1px solid var(--borda-suave);
        border-radius: 8px;
        background: #0D1219;
    }
    .detalhe-item span {
        display: block;
        color: var(--texto-muted);
        font-size: 0.64rem;
        font-weight: 620;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }
    .detalhe-item strong {
        display: block;
        margin-top: 4px;
        overflow: hidden;
        color: var(--texto);
        font-size: 0.82rem;
        font-weight: 570;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    /* Cobertura: zero nunca representa indisponibilidade. */
    .cobertura { width: 100%; border-collapse: collapse; font-size: 0.76rem; }
    .cobertura th {
        padding: 7px 8px;
        color: var(--texto-muted);
        font-size: 0.64rem;
        font-weight: 620;
        letter-spacing: 0.06em;
        text-align: center;
        text-transform: uppercase;
    }
    .cobertura th:first-child, .cobertura td:first-child { text-align: left; }
    .cobertura td {
        padding: 8px;
        border-top: 1px solid var(--borda-suave);
        color: var(--texto-secundario);
        text-align: center;
    }
    .disponivel { color: #7DD3A8; }
    .indisponivel { color: var(--texto-muted); }

    /* Dataframe, expander e popover em dark coerente. */
    [data-testid="stDataFrame"] {
        overflow: hidden;
        border: 1px solid var(--borda);
        border-radius: var(--raio);
        background: var(--cartao);
    }
    [data-testid="stExpander"] {
        border-color: var(--borda) !important;
        border-radius: var(--raio) !important;
        background: var(--cartao);
    }
    [data-testid="stPopoverBody"] {
        border-color: var(--borda) !important;
        background: var(--elevado) !important;
        color: var(--texto);
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        width: 288px !important;
        min-width: 288px !important;
        border-right: 1px solid #1D2530;
        background: var(--sidebar);
    }
    section[data-testid="stSidebar"][aria-expanded="false"] {
        width: 0 !important;
        min-width: 0 !important;
    }
    section[data-testid="stSidebar"] > div { background: var(--sidebar); }
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding: 0 !important; }
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding: 0 20px 24px; }
    section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 4px; }
    section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
        height: 40px;
        padding: 4px 20px 0 !important;
    }
    .sb-marca { padding-bottom: 12px; border-bottom: 1px solid #202834; }
    .sb-titulo {
        margin: 0;
        color: #FFFFFF;
        font-size: 1rem;
        font-weight: 660;
        line-height: 1.25;
    }
    .sb-produto {
        margin: 3px 0 0;
        color: var(--texto);
        font-size: 0.82rem;
        font-weight: 560;
    }
    .sb-sub { margin: 2px 0 0; color: var(--texto-muted); font-size: 0.73rem; }
    .sb-rotulo {
        margin: 15px 0 6px;
        color: var(--texto-muted);
        font-size: 0.64rem;
        font-weight: 650;
        letter-spacing: 0.11em;
        text-transform: uppercase;
    }
    .sb-rodape {
        margin-top: 15px;
        padding-top: 11px;
        overflow-wrap: anywhere;
        border-top: 1px solid #202834;
        color: var(--texto-muted);
        font-size: 0.68rem;
        line-height: 1.45;
    }
    .sb-rodape b { color: var(--texto-secundario); font-weight: 560; }

    section[data-testid="stSidebar"] [data-testid="stRadioGroup"] { gap: 2px; }
    section[data-testid="stSidebar"] [data-testid="stRadioOption"] {
        width: 100%;
        margin: 0;
        padding: 8px 10px;
        border-radius: 7px;
        box-shadow: inset 2px 0 0 transparent;
        cursor: pointer;
        transition: background-color 160ms ease, box-shadow 160ms ease;
    }
    section[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover { background: var(--elevado); }
    section[data-testid="stSidebar"] [data-testid="stRadioOption"]
        div:has(> [data-testid="stMarkdownContainer"]) > div:first-child {
        display: none !important;
    }
    section[data-testid="stSidebar"] [data-testid="stRadioOption"] p {
        color: var(--texto-secundario);
        font-size: 0.84rem;
        font-weight: 480;
    }
    section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {
        background: #171D27;
        box-shadow: inset 2px 0 0 var(--accent);
    }
    section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p {
        color: #FFFFFF;
        font-weight: 580;
    }
    section[data-testid="stSidebar"] [data-testid="stRadioOption"]:focus-within {
        outline: 2px solid var(--accent);
        outline-offset: 1px;
    }
    section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
        color: var(--texto-secundario);
        font-size: 0.74rem;
        font-weight: 540;
    }
    section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] { margin-bottom: 3px; }
    section[data-testid="stSidebar"] [data-baseweb="select"] > div,
    section[data-testid="stSidebar"] [data-baseweb="input"],
    section[data-testid="stSidebar"] [data-baseweb="base-input"] {
        border-color: var(--borda) !important;
        background: var(--elevado) !important;
    }
    section[data-testid="stSidebar"] [data-baseweb="select"] > div,
    section[data-testid="stSidebar"] [data-testid="stDateInputField"],
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] { min-height: 42px; }
    section[data-testid="stSidebar"] [data-rac][role="group"]:focus-within {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.18);
    }
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] {
        align-content: center;
        max-height: 118px;
        overflow-x: hidden;
        overflow-y: auto;
        padding: 4px;
    }
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] > span[role="group"] {
        display: flex;
        flex: 0 1 calc(100% - 40px);
        flex-wrap: wrap;
        align-items: center;
        gap: 4px;
        min-width: 0;
        max-width: calc(100% - 40px);
    }
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] [data-tag] {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        max-width: 100%;
        min-height: 27px;
        padding: 3px 6px 3px 8px;
        overflow: hidden;
        border: 1px solid rgba(139, 92, 246, 0.36);
        border-radius: 6px;
        background: rgba(139, 92, 246, 0.14) !important;
        color: #DDD6FE !important;
    }
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] [data-tag] > span[title] {
        min-width: 0;
        max-width: 150px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] input[role="combobox"] {
        flex: 1 1 32px !important;
        width: 32px !important;
        min-width: 32px !important;
    }
    section[data-testid="stSidebar"] .stButton > button {
        width: 100%;
        min-height: 40px;
        border: 1px solid var(--borda);
        background: transparent;
        color: var(--texto-secundario);
        font-size: 0.76rem;
        font-weight: 540;
    }
    section[data-testid="stSidebar"] .stButton > button:hover {
        border-color: var(--accent);
        background: var(--elevado);
        color: #FFFFFF;
    }

    /* Breakpoints validados. */
    @media (max-width: 1439px) { .block-container { padding-inline: 24px; } }
    @media (max-width: 1299px) {
        .st-key-grade_eficiencia [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
        .st-key-grade_eficiencia [data-testid="stColumn"] {
            min-width: calc(33.333% - 8px) !important;
            flex: 1 1 calc(33.333% - 8px) !important;
        }
        .detalhe-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 1099px) {
        .block-container { padding-inline: 20px; }
        .pg-titulo { font-size: 1.62rem; }
        .st-key-grade_resultados [data-testid="stHorizontalBlock"],
        .st-key-grade_valor [data-testid="stHorizontalBlock"],
        .st-key-grade_entrega [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
        .st-key-grade_resultados [data-testid="stColumn"],
        .st-key-grade_valor [data-testid="stColumn"],
        .st-key-grade_entrega [data-testid="stColumn"] {
            min-width: calc(50% - 6px) !important;
            flex: 1 1 calc(50% - 6px) !important;
        }
        .st-key-grade_comparacao [data-testid="stHorizontalBlock"],
        .st-key-grade_participacao [data-testid="stHorizontalBlock"],
        .st-key-controles_serie [data-testid="stHorizontalBlock"],
        .st-key-controles_ranking_campanha [data-testid="stHorizontalBlock"],
        .st-key-controles_ranking_anuncio [data-testid="stHorizontalBlock"],
        .st-key-controles_anuncio [data-testid="stHorizontalBlock"] {
            flex-direction: column;
            align-items: stretch;
        }
        .st-key-grade_comparacao [data-testid="stColumn"],
        .st-key-grade_participacao [data-testid="stColumn"],
        .st-key-controles_serie [data-testid="stColumn"],
        .st-key-controles_ranking_campanha [data-testid="stColumn"],
        .st-key-controles_ranking_anuncio [data-testid="stColumn"],
        .st-key-controles_anuncio [data-testid="stColumn"] {
            width: 100% !important;
            flex: 1 1 100% !important;
        }
    }
    @media (max-width: 767px) {
        .block-container { padding: 18px 16px 40px; }
        .pg-meta { grid-template-columns: minmax(0, 1fr); }
        .selo { justify-self: start; }
        .st-key-grade_eficiencia [data-testid="stColumn"] {
            min-width: calc(50% - 6px) !important;
            flex-basis: calc(50% - 6px) !important;
        }
        .detalhe-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 520px) {
        .st-key-grade_resultados [data-testid="stColumn"],
        .st-key-grade_valor [data-testid="stColumn"],
        .st-key-grade_entrega [data-testid="stColumn"],
        .st-key-grade_eficiencia [data-testid="stColumn"] {
            min-width: 100% !important;
            flex-basis: 100% !important;
        }
        .detalhe-grid { grid-template-columns: minmax(0, 1fr); }
    }
    @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after { transition-duration: 0.01ms !important; }
    }
</style>
"""


def injetar_estilo() -> None:
    """Injeta o CSS da aplicacao uma vez no inicio da pagina."""
    st.markdown(ESTILO, unsafe_allow_html=True)


def _escapar(texto) -> str:
    """Escapa texto antes de interpola-lo em HTML."""
    return html.escape(str(texto))


def marca_lateral(titulo: str, produto: str, subtitulo: str) -> None:
    """Desenha a marca no topo da barra lateral."""
    st.markdown(
        f'<div class="sb-marca"><p class="sb-titulo">{_escapar(titulo)}</p>'
        f'<p class="sb-produto">{_escapar(produto)}</p>'
        f'<p class="sb-sub">{_escapar(subtitulo)}</p></div>',
        unsafe_allow_html=True,
    )


def rotulo_lateral(texto: str) -> None:
    """Desenha o rotulo discreto de um grupo da sidebar."""
    st.markdown(f'<p class="sb-rotulo">{_escapar(texto)}</p>', unsafe_allow_html=True)


def rodape_lateral(origem: str, modo: str) -> None:
    """Desenha origem e modo no rodape da sidebar."""
    st.markdown(
        f'<div class="sb-rodape"><b>{_escapar(modo)}</b><br>{_escapar(origem)}</div>',
        unsafe_allow_html=True,
    )


def cabecalho(titulo: str, descricao: str, periodo: str, registros: str,
              selo: str, modo: str) -> None:
    """Desenha o cabecalho SaaS da pagina."""
    classe = "selo-demo" if modo == "demonstracao" else "selo-real"
    st.markdown(
        f'<p class="pg-titulo">{_escapar(titulo)}</p>'
        f'<p class="pg-desc">{_escapar(descricao)}</p>'
        '<div class="pg-meta"><div class="pg-info">'
        f'<span class="pg-periodo">{_escapar(periodo)}</span>'
        f'<span class="pg-registros">{_escapar(registros)}</span></div>'
        f'<span class="selo {classe}">{_escapar(selo)}</span></div>',
        unsafe_allow_html=True,
    )


def secao(titulo: str, apoio: str = "") -> None:
    """Desenha titulo e microcopy de uma secao."""
    linha = f'<p class="secao-apoio">{_escapar(apoio)}</p>' if apoio else ""
    st.markdown(
        f'<div class="secao"><p class="secao-titulo">{_escapar(titulo)}</p>{linha}</div>',
        unsafe_allow_html=True,
    )


def _delta_cartao(delta: str | None, com_comparacao: bool,
                  tag: str = "") -> str | None:
    """Monta a linha neutra de comparacao de um KPI."""
    if not com_comparacao:
        return tag or None
    texto = (
        "Sem base de comparação"
        if delta is None else f"{delta} · vs. período anterior"
    )
    return f"{texto} · {tag}" if tag else texto


def cartao_kpi(rotulo: str, valor: str, delta: str | None = None,
               com_comparacao: bool = False, tag: str = "",
               tooltip: str = "", compacto: bool = False) -> None:
    """Desenha um KPI com ajuda nativa, delta neutro e valor formatado."""
    del compacto
    st.metric(
        label=rotulo, value=valor,
        delta=_delta_cartao(delta, com_comparacao, tag),
        delta_color="off", delta_arrow="off", help=tooltip or None,
        border=True,
    )


def linha_kpis(cartoes: list[dict], compacto: bool = False,
               chave: str = "grade_resultados") -> None:
    """Desenha KPIs em 3 colunas ou a grade compacta de eficiencia."""
    if not cartoes:
        return
    quantidade = len(cartoes) if compacto else min(3, len(cartoes))
    with st.container(key=chave):
        for inicio in range(0, len(cartoes), quantidade):
            grupo = cartoes[inicio:inicio + quantidade]
            colunas = st.columns(quantidade, gap="small")
            for indice, dados_cartao in enumerate(grupo):
                with colunas[indice]:
                    cartao_kpi(
                        dados_cartao["rotulo"], dados_cartao["valor"],
                        dados_cartao.get("delta"), "delta" in dados_cartao,
                        dados_cartao.get("tag", ""),
                        dados_cartao.get("tooltip", ""), compacto,
                    )


def titulo_grafico(texto: str, apoio: str = "") -> None:
    """Desenha titulo e apoio fora da area interna do Plotly."""
    complemento = f'<p class="grafico-apoio">{_escapar(apoio)}</p>' if apoio else ""
    st.markdown(
        f'<p class="grafico-titulo">{_escapar(texto)}</p>{complemento}',
        unsafe_allow_html=True,
    )


def nota(texto: str) -> None:
    """Desenha uma ressalva metodologica discreta."""
    st.markdown(f'<div class="nota">{_escapar(texto)}</div>', unsafe_allow_html=True)


def tabela(linhas: list[dict], altura: int | None = None) -> None:
    """Renderiza uma tabela formatada, com scroll restrito ao componente."""
    if not linhas:
        estado_vazio("Nenhum registro encontrado", "Ajuste os filtros ou o período.")
        return
    extras = {"height": altura} if altura else {}
    st.dataframe(linhas, width="stretch", hide_index=True, **extras)


def estado_vazio(titulo: str, texto: str) -> None:
    """Renderiza um empty state no lugar de uma visualizacao vazia."""
    st.markdown(
        f'<div class="estado-vazio"><strong>{_escapar(titulo)}</strong>'
        f'<span>{_escapar(texto)}</span></div>', unsafe_allow_html=True,
    )


def aviso_sem_dados(periodo: str) -> None:
    """Mostra o empty state padrao para um recorte sem linhas."""
    estado_vazio(
        "Nenhum dado encontrado",
        f"Ajuste os filtros ou selecione outro período. Recorte atual: {periodo}.",
    )


def quadro_cobertura(metricas: list[tuple[str, bool, bool]]) -> None:
    """Desenha uma matriz discreta de disponibilidade por plataforma."""
    linhas = []
    for rotulo, meta, google in metricas:
        linhas.append(
            "<tr>" + f"<td>{_escapar(rotulo)}</td>" +
            f'<td><span class="{("disponivel" if meta else "indisponivel")}">'
            f'{("✓ Disponível" if meta else "— Não disponível")}</span></td>' +
            f'<td><span class="{("disponivel" if google else "indisponivel")}">'
            f'{("✓ Disponível" if google else "— Não disponível")}</span></td></tr>'
        )
    st.markdown(
        '<table class="cobertura" aria-label="Cobertura das métricas por origem">'
        '<thead><tr><th>Métrica</th><th>Meta</th><th>Google</th></tr></thead>'
        f'<tbody>{"".join(linhas)}</tbody></table>', unsafe_allow_html=True,
    )


def detalhe_anuncio(titulo: str, itens: list[tuple[str, str]]) -> None:
    """Desenha os atributos e totais essenciais do anuncio selecionado."""
    blocos = "".join(
        '<div class="detalhe-item">'
        f'<span>{_escapar(rotulo)}</span><strong title="{_escapar(valor)}">'
        f'{_escapar(valor)}</strong></div>' for rotulo, valor in itens
    )
    st.markdown(
        f'<p class="detalhe-titulo">{_escapar(titulo)}</p>'
        f'<div class="detalhe-grid">{blocos}</div>', unsafe_allow_html=True,
    )


def erro_de_contrato(mensagem: str) -> None:
    """Apresenta uma falha de contrato sem stack trace."""
    st.error("O dataset apresentado não satisfaz o contrato de exposição.")
    nota(mensagem)
    st.markdown(
        "O dashboard consome **apenas** a superfície de exposição "
        "pseudonimizada ou o dataset sintético de demonstração."
    )


def rotulo_metrica(metrica: str) -> str:
    """Devolve o rotulo de exibicao de uma metrica base."""
    return m.CATALOGO[metrica].rotulo
