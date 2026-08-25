"""Componentes visuais reutilizaveis do dashboard.

Concentra o CSS e os blocos de interface que se repetem entre as paginas —
cartao de KPI, cabecalho de pagina, cabecalho de secao, selo de origem e
tabela — para que `app.py` fique com a composicao das telas e nao com
marcacao.

Identidade visual
-----------------
Conteudo claro, barra lateral escura, uma unica cor de destaque. As cores
estruturais (fundo, campo, texto, borda) vivem no tema declarado em
`.streamlit/config.toml`, porque os controles do Streamlit sao componentes
React que derivam suas cores do tema e ignoram CSS de pagina. O que sobra para
este modulo e a camada de layout: densidade, tipografia, cartoes e a barra
lateral.

A variacao percentual e apresentada em cinza nos dois sentidos: alta de
investimento e alta de CPA nao tem a mesma leitura, e o dashboard nao decide
isso pelo usuario.
"""

import html

import streamlit as st

from dashboard import metricas as m

# As mesmas cores do tema, repetidas aqui porque o CSS precisa delas e o
# Streamlit nao expoe os tokens do tema como variaveis CSS estaveis. Mudar uma
# cor exige mudar nos dois lugares — o preco de os controles nativos e o
# layout proprio conviverem.
ESTILO: str = """
<style>
    :root {
        --fundo: #F6F7F9;
        --cartao: #FFFFFF;
        --borda: #E4E7EC;
        --tinta: #172033;
        --tinta-media: #3D4757;
        --tinta-suave: #667085;
        --destaque: #E84A5F;
        --chip: #F2F4F7;

        --sb-fundo: #151A23;
        --sb-campo: #232B39;
        --sb-texto: #E7EAF0;
        --sb-suave: #98A2B3;
        --sb-rotulo: #8B96AB;
        --sb-ativo: #212A38;

        --espaco-1: 4px;
        --espaco-2: 8px;
        --espaco-3: 12px;
        --espaco-4: 16px;
        --espaco-6: 24px;
        --espaco-8: 32px;
        --raio: 10px;

        --fonte: Inter, system-ui, -apple-system, BlinkMacSystemFont,
                 "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    }

    /* O conteudo e claro independentemente do tema do navegador. Sem isto,
       `prefers-color-scheme: dark` puxava partes da interface para escuro e a
       pagina ficava com duas identidades ao mesmo tempo. */
    html, body, .stApp, [data-testid="stAppViewContainer"] {
        color-scheme: light;
        background: var(--fundo);
        color: var(--tinta);
        font-family: var(--fonte);
    }
    @media (prefers-color-scheme: dark) {
        html, body, .stApp, [data-testid="stAppViewContainer"] {
            color-scheme: light;
            background: var(--fundo);
            color: var(--tinta);
        }
    }

    /* Ruido do chrome do Streamlit. O cabecalho continua existindo — e nele
       que mora o controle de recolher a barra lateral —, apenas transparente. */
    [data-testid="stDecoration"] { display: none; }
    [data-testid="stHeader"] { background: transparent; }
    [data-testid="stToolbarActions"] { display: none; }
    footer { display: none; }

    /* Container central: limitado em telas grandes e sem margem fantasma
       quando a sidebar e recolhida. */
    .block-container {
        width: 100%;
        max-width: 1376px;
        margin-inline: auto;
        padding: 24px 32px 48px;
    }

    /* Densidade. O padrao do Streamlit reserva espaco vertical generoso entre
       elementos; em 1366x768 isso custa uma secao inteira de conteudo. */
    [data-testid="stVerticalBlock"] { gap: 8px; }
    [data-testid="stHorizontalBlock"] { gap: 12px; }
    [data-testid="stElementContainer"] { margin-bottom: 0; }

    h1, h2, h3, h4 {
        color: var(--tinta);
        font-family: var(--fonte);
        letter-spacing: -0.015em;
    }

    /* ── Cabecalho da pagina ─────────────────────────────────────────── */
    .pg-titulo {
        font-size: 1.8rem;
        font-weight: 700;
        color: var(--tinta);
        margin: 0;
        line-height: 1.2;
    }
    .pg-desc {
        font-size: 0.95rem;
        color: var(--tinta-suave);
        margin: 4px 0 0;
        max-width: 70ch;
        line-height: 1.45;
    }
    .pg-meta {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        align-items: center;
        gap: 16px 24px;
        margin-top: 12px;
        padding-bottom: 16px;
        border-bottom: 1px solid var(--borda);
    }
    .pg-info {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
    }
    .pg-periodo {
        font-size: 0.93rem;
        font-weight: 650;
        color: var(--tinta);
        line-height: 1.35;
    }
    .pg-registros {
        font-size: 0.82rem;
        color: var(--tinta-suave);
        line-height: 1.35;
    }

    .selo {
        display: inline-block;
        font-size: 0.66rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        padding: 5px 9px;
        border-radius: 6px;
        white-space: nowrap;
    }
    .selo-real { background: #EEF2FF; color: #313E7A; border: 1px solid #D3DBF5; }
    .selo-demo { background: #FDF1E3; color: #7C4A03; border: 1px solid #F2DCBC; }

    /* ── Cabecalho de secao ──────────────────────────────────────────── */
    .secao {
        display: block;
        margin: 24px 0 12px;
    }
    .secao-titulo {
        font-size: 1.1rem;
        font-weight: 645;
        color: var(--tinta);
        margin: 0;
    }
    .secao-apoio {
        font-size: 0.83rem;
        color: var(--tinta-suave);
        margin: 4px 0 0;
        line-height: 1.45;
        max-width: 76ch;
    }

    /* ── Cartao de KPI ───────────────────────────────────────────────── */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
        width: 100%;
    }
    .kpi-grid.compacta {
        grid-template-columns: repeat(5, minmax(0, 1fr));
    }
    .kpi-grid.compacta.qtd-3 {
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    .kpi {
        background: var(--cartao);
        border: 1px solid var(--borda);
        border-radius: var(--raio);
        padding: 16px;
        min-height: 124px;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
    }
    .kpi-rotulo {
        font-size: 0.72rem;
        font-weight: 650;
        letter-spacing: 0.07em;
        text-transform: uppercase;
        color: var(--tinta-suave);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .kpi-valor {
        font-size: 1.9rem;
        font-weight: 700;
        color: var(--tinta);
        line-height: 1.18;
        margin-top: 6px;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .kpi-delta {
        margin-top: 6px;
        font-size: 0.78rem;
        color: var(--tinta-suave);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .kpi-delta b { color: var(--tinta-media); font-weight: 620; }
    .kpi-tag {
        align-self: flex-start;
        margin-top: 0.28rem;
        font-size: 0.7rem;
        color: var(--tinta-suave);
        background: var(--chip);
        border-radius: 4px;
        padding: 0.1rem 0.4rem;
        white-space: nowrap;
        max-width: 100%;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .kpi.compacto { padding: 12px 14px; min-height: 92px; }
    .kpi.compacto .kpi-rotulo { font-size: 0.68rem; }
    .kpi.compacto .kpi-valor { font-size: 1.35rem; margin-top: 4px; }
    .kpi.compacto .kpi-delta { font-size: 0.73rem; margin-top: 4px; }

    /* ── Nota / ressalva ─────────────────────────────────────────────── */
    .nota {
        background: var(--cartao);
        border: 1px solid var(--borda);
        border-left: 3px solid #CBD5E1;
        border-radius: 8px;
        padding: 0.65rem 0.85rem;
        font-size: 0.82rem;
        color: var(--tinta-suave);
        line-height: 1.5;
    }

    /* ── Graficos e tabelas ganham o mesmo acabamento dos cartoes ────── */
    .stPlotlyChart {
        background: var(--cartao);
        border: 1px solid var(--borda);
        border-radius: var(--raio);
        padding: 12px 12px 8px;
        overflow: hidden;
    }
    [data-testid="stDataFrame"] { border-radius: var(--raio); }
    .grafico-titulo {
        color: var(--tinta);
        font-size: 0.84rem;
        font-weight: 650;
        margin: 0 0 6px;
    }

    /* ── Controles na area de conteudo ───────────────────────────────── */
    .block-container [data-testid="stWidgetLabel"] p {
        font-size: 0.8rem;
        font-weight: 600;
        color: var(--tinta-suave);
    }
    .block-container [data-testid="stSelectbox"] [data-baseweb="select"] > div {
        min-height: 44px;
    }
    .st-key-controles_serie [data-testid="stHorizontalBlock"],
    .st-key-controles_ranking_campanha [data-testid="stHorizontalBlock"],
    .st-key-controles_ranking_anuncio [data-testid="stHorizontalBlock"],
    .st-key-controles_anuncio [data-testid="stHorizontalBlock"] {
        align-items: end;
    }
    .st-key-controles_serie { max-width: 760px; }
    .st-key-controles_ranking_campanha,
    .st-key-controles_ranking_anuncio { max-width: 560px; }
    .st-key-controles_anuncio { max-width: 760px; }

    /* ── Barra lateral ───────────────────────────────────────────────── */
    section[data-testid="stSidebar"] {
        background: var(--sb-fundo);
        width: 288px !important;
        min-width: 288px !important;
    }
    section[data-testid="stSidebar"][aria-expanded="false"] {
        width: 0 !important;
        min-width: 0 !important;
    }
    section[data-testid="stSidebar"] > div { background: var(--sb-fundo); }
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        padding: 0 !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
        padding: 0 20px 24px;
    }
    section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 4px;
    }
    /* O cabecalho do Streamlit reserva altura dentro da barra lateral para o
       controle de recolher; sem isto sobrava um vao de quase 90 px antes da
       marca. */
    section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
        height: 40px;
        padding: 4px 20px 0 !important;
    }

    .sb-titulo {
        color: #FFFFFF;
        font-size: 1rem;
        font-weight: 680;
        line-height: 1.25;
        margin: 0;
    }
    .sb-produto {
        color: var(--sb-texto);
        font-size: 0.82rem;
        font-weight: 600;
        margin: 3px 0 0;
    }
    .sb-sub {
        color: var(--sb-suave);
        font-size: 0.75rem;
        margin: 2px 0 0;
    }
    .sb-marca {
        padding-bottom: 12px;
        border-bottom: 1px solid #2A3342;
        margin-bottom: 0;
    }
    .sb-rotulo {
        color: var(--sb-rotulo);
        font-size: 0.67rem;
        font-weight: 700;
        letter-spacing: 0.11em;
        text-transform: uppercase;
        margin: 16px 0 6px;
    }
    .sb-rodape {
        color: var(--sb-rotulo);
        font-size: 0.71rem;
        line-height: 1.5;
        margin-top: 16px;
        padding-top: 12px;
        border-top: 1px solid #2A3342;
        overflow-wrap: anywhere;
    }
    .sb-rodape b { color: var(--sb-suave); font-weight: 600; }

    /* Navegacao: o radio continua sendo um radio — acessivel e navegavel
       pelo teclado —, mas sem a bolinha, que nao acrescenta significado
       quando os itens ja sao uma lista de paginas. */
    section[data-testid="stSidebar"] [data-testid="stRadioGroup"] {
        gap: 0.12rem;
    }
    section[data-testid="stSidebar"] [data-testid="stRadioOption"] {
        width: 100%;
        margin: 0;
        padding: 8px 10px;
        border-radius: 7px;
        box-shadow: inset 2px 0 0 transparent;
        transition: background 0.12s ease;
        cursor: pointer;
    }
    section[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover {
        background: #1D2431;
    }
    /* Esconde so o circulo do radio: a linha que contem o rotulo tem o
       marcador como primeiro filho e o texto como segundo. O `input` continua
       no DOM, entao teclado e leitor de tela seguem funcionando. */
    section[data-testid="stSidebar"] [data-testid="stRadioOption"]
        div:has(> [data-testid="stMarkdownContainer"]) > div:first-child {
        display: none !important;
    }
    section[data-testid="stSidebar"] [data-testid="stRadioOption"] p {
        color: var(--sb-suave);
        font-size: 0.875rem;
        font-weight: 500;
    }
    section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {
        background: var(--sb-ativo);
        box-shadow: inset 2px 0 0 var(--destaque);
    }
    section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p {
        color: #FFFFFF;
        font-weight: 620;
    }

    /* Campos: preenchimento um degrau acima do fundo da barra, borda
       discreta, texto claro. O tema ja entrega a maior parte disto; o que
       sobra aqui e o acabamento. */
    section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
        color: var(--sb-suave);
        font-size: 0.78rem;
        font-weight: 600;
    }
    section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] {
        margin-bottom: 4px;
    }
    section[data-testid="stSidebar"] [data-baseweb="select"] > div,
    section[data-testid="stSidebar"] [data-baseweb="input"],
    section[data-testid="stSidebar"] [data-baseweb="base-input"] {
        background-color: var(--sb-campo) !important;
        border-color: #38425380 !important;
    }
    section[data-testid="stSidebar"] [data-baseweb="select"] > div,
    section[data-testid="stSidebar"] [data-testid="stDateInputField"],
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] {
        min-height: 44px;
    }
    section[data-testid="stSidebar"] [data-baseweb="select"] svg { fill: var(--sb-suave); }

    /* Streamlit 1.62 nao usa mais `data-baseweb="tag"` nos chips. Estes
       seletores partem do testid estavel do multiselect e do atributo
       semantico `data-tag`, sem depender de classes geradas por Emotion. */
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"] {
        align-content: center;
        max-height: 128px;
        overflow-x: hidden;
        overflow-y: auto;
        padding: 4px;
    }
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"]
        > span[role="group"] {
        display: flex;
        flex: 0 1 calc(100% - 40px);
        flex-wrap: wrap;
        align-items: center;
        gap: 4px;
        min-width: 0;
        max-width: calc(100% - 40px);
    }
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"]
        [data-tag] {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        max-width: 100%;
        min-height: 28px;
        padding: 3px 6px 3px 8px;
        overflow: hidden;
        color: #FFD8DE !important;
        background: rgba(232, 74, 95, 0.16) !important;
        border: 1px solid rgba(232, 74, 95, 0.42);
        border-radius: 6px;
    }
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"]
        [data-tag] > span[title] {
        min-width: 0;
        max-width: 150px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"]
        [data-tag] button {
        flex: 0 0 20px;
        width: 20px;
        height: 20px;
        padding: 5px;
        color: #FFD8DE;
    }
    /* O input de busca mantinha 114 px mesmo depois da selecao e forcava um
       unico chip para outra linha. Ele continua focavel e digitavel, mas pode
       ocupar apenas o espaco restante da linha. */
    section[data-testid="stSidebar"] [data-testid="stMultiSelectTagsContainer"]
        input[role="combobox"] {
        flex: 1 1 32px !important;
        width: 32px !important;
        min-width: 32px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stMultiSelect"]
        button[aria-label="Clear all"] {
        flex: 0 0 28px;
        width: 28px;
        height: 40px;
        padding: 6px;
    }
    section[data-testid="stSidebar"] [data-testid="stMultiSelect"]
        button[aria-label="Open"] {
        flex: 0 0 32px;
        width: 32px;
        height: 40px;
    }
    section[data-testid="stSidebar"] [data-testid="stMultiSelect"]
        [data-rac][role="group"]:focus-within {
        border-color: var(--destaque) !important;
        box-shadow: 0 0 0 2px rgba(232, 74, 95, 0.2);
    }
    section[data-testid="stSidebar"] .stButton > button {
        width: 100%;
        background: transparent;
        color: var(--sb-suave);
        border: 1px solid #38425380;
        font-size: 0.8rem;
        font-weight: 560;
        min-height: 42px;
        padding: 8px 12px;
    }
    section[data-testid="stSidebar"] .stButton > button:hover {
        color: #FFFFFF;
        border-color: var(--destaque);
        background: #1D2431;
    }

    /* ── Breakpoints explicitos ──────────────────────────────────────── */
    @media (max-width: 1439px) {
        .block-container { padding-inline: 24px; }
    }
    @media (max-width: 1299px) {
        .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .kpi-grid.compacta { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .kpi-valor { font-size: 1.72rem; }
    }
    @media (max-width: 1099px) {
        .block-container { padding-inline: 20px; }
        .kpi-grid { grid-template-columns: minmax(0, 1fr); }
        .kpi-grid.compacta { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .pg-titulo { font-size: 1.58rem; }

        .st-key-controles_serie [data-testid="stHorizontalBlock"],
        .st-key-controles_ranking_campanha [data-testid="stHorizontalBlock"],
        .st-key-controles_ranking_anuncio [data-testid="stHorizontalBlock"],
        .st-key-controles_anuncio [data-testid="stHorizontalBlock"],
        .st-key-graficos_plataforma [data-testid="stHorizontalBlock"] {
            flex-direction: column;
            align-items: stretch;
            gap: 12px;
        }
        .st-key-controles_serie [data-testid="stColumn"],
        .st-key-controles_ranking_campanha [data-testid="stColumn"],
        .st-key-controles_ranking_anuncio [data-testid="stColumn"],
        .st-key-controles_anuncio [data-testid="stColumn"],
        .st-key-graficos_plataforma [data-testid="stColumn"] {
            width: 100% !important;
            flex: 1 1 100% !important;
        }
    }
    @media (max-width: 991px) {
        .pg-meta { grid-template-columns: minmax(0, 1fr); }
        .selo { justify-self: start; }
    }
    @media (max-width: 640px) {
        .block-container { padding: 20px 16px 40px; }
        .kpi-grid.compacta { grid-template-columns: minmax(0, 1fr); }
    }
</style>
"""


def injetar_estilo() -> None:
    """Injeta o CSS da aplicacao. Chamar uma vez, no inicio da pagina."""
    st.markdown(ESTILO, unsafe_allow_html=True)


def _escapar(texto) -> str:
    """Escapa texto antes de interpola-lo em HTML.

    Args:
        texto: Valor a escapar.

    Returns:
        Texto seguro para interpolacao.
    """
    return html.escape(str(texto))


def marca_lateral(titulo: str, produto: str, subtitulo: str) -> None:
    """Desenha a marca no topo da barra lateral.

    Args:
        titulo: Nome do painel.
        produto: Linha que identifica o produto.
        subtitulo: Linha de apoio.
    """
    st.markdown(
        f'<div class="sb-marca"><p class="sb-titulo">{_escapar(titulo)}</p>'
        f'<p class="sb-produto">{_escapar(produto)}</p>'
        f'<p class="sb-sub">{_escapar(subtitulo)}</p></div>',
        unsafe_allow_html=True,
    )


def rotulo_lateral(texto: str) -> None:
    """Desenha um rotulo de grupo na barra lateral.

    Args:
        texto: Texto do rotulo, exibido em caixa alta discreta.
    """
    st.markdown(
        f'<p class="sb-rotulo">{_escapar(texto)}</p>', unsafe_allow_html=True
    )


def rodape_lateral(origem: str, modo: str) -> None:
    """Desenha o rodape da barra lateral com a origem dos dados.

    Args:
        origem: Caminho relativo do dataset.
        modo: Rotulo do modo de operacao.
    """
    st.markdown(
        f'<div class="sb-rodape"><b>{_escapar(modo)}</b><br>'
        f"{_escapar(origem)}</div>",
        unsafe_allow_html=True,
    )


def cabecalho(
    titulo: str,
    descricao: str,
    periodo: str,
    registros: str,
    selo: str,
    modo: str,
) -> None:
    """Desenha o cabecalho da pagina.

    Args:
        titulo: Nome da pagina.
        descricao: Uma frase sobre o que a pagina responde.
        periodo: Periodo selecionado, ja formatado.
        registros: Linha secundaria com a contagem de registros.
        selo: Texto do selo de origem.
        modo: `pseudonimizado` ou `demonstracao`, define a cor do selo.
    """
    classe = "selo-demo" if modo == "demonstracao" else "selo-real"
    st.markdown(
        f"""
        <p class="pg-titulo">{_escapar(titulo)}</p>
        <p class="pg-desc">{_escapar(descricao)}</p>
        <div class="pg-meta">
            <div class="pg-info">
                <span class="pg-periodo">{_escapar(periodo)}</span>
                <span class="pg-registros">{_escapar(registros)}</span>
            </div>
            <span class="selo {classe}">{_escapar(selo)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def secao(titulo: str, apoio: str = "") -> None:
    """Desenha o cabecalho de uma secao.

    Args:
        titulo: Titulo da secao.
        apoio: Linha explicativa opcional, exibida abaixo do titulo.
    """
    linha_apoio = (
        f'<p class="secao-apoio">{_escapar(apoio)}</p>' if apoio else ""
    )
    st.markdown(
        f'<div class="secao"><p class="secao-titulo">{_escapar(titulo)}</p>'
        f"{linha_apoio}</div>",
        unsafe_allow_html=True,
    )


def cartao_kpi(
    rotulo: str,
    valor: str,
    delta: str | None = None,
    com_comparacao: bool = False,
    tag: str = "",
    tooltip: str = "",
    compacto: bool = False,
) -> None:
    """Desenha um cartao de indicador.

    Args:
        rotulo: Nome do indicador, em caixa alta discreta.
        valor: Valor ja formatado. E o elemento dominante do cartao.
        delta: Variacao ja formatada, ou ``None`` quando nao calculavel.
        com_comparacao: Se este cartao participa da comparacao com o periodo
            anterior. Quando `True` e `delta` e ``None``, o cartao diz "sem
            base de comparacao"; quando `False`, nao ha linha de comparacao —
            um cartao descritivo (quantas contas, quantas linhas) nao tem
            periodo anterior com que se comparar.
        tag: Marcador curto de cobertura (ex: ``Parcial · Meta Ads``).
        tooltip: Explicacao exibida ao passar o mouse — formula do indicador
            ou motivo da cobertura parcial. Fica fora do fluxo visual de
            proposito: paragrafo dentro do cartao desequilibra a linha.
        compacto: Tipografia menor, para a linha de eficiencia.
    """
    st.markdown(
        _html_cartao_kpi(
            rotulo, valor, delta, com_comparacao, tag, tooltip, compacto
        ),
        unsafe_allow_html=True,
    )


def _html_cartao_kpi(
    rotulo: str,
    valor: str,
    delta: str | None,
    com_comparacao: bool,
    tag: str,
    tooltip: str,
    compacto: bool,
) -> str:
    """Monta o HTML seguro de um cartao de KPI.

    O helper permite reunir varios cartoes num unico grid CSS responsivo sem
    trocar os controles funcionais do Streamlit por HTML.

    Args:
        rotulo: Nome do indicador.
        valor: Valor formatado.
        delta: Variacao formatada.
        com_comparacao: Se deve exibir a linha de comparacao.
        tag: Marcador curto de cobertura.
        tooltip: Texto nativo exibido no hover.
        compacto: Se usa a variacao compacta do cartao.

    Returns:
        Marcacao HTML do cartao.
    """
    classe = "kpi compacto" if compacto else "kpi"
    titulo = f' title="{_escapar(tooltip)}"' if tooltip else ""

    if not com_comparacao:
        bloco_delta = ""
    elif delta is None:
        bloco_delta = '<div class="kpi-delta">sem base de comparacao</div>'
    else:
        bloco_delta = (
            f'<div class="kpi-delta"><b>{_escapar(delta)}</b> '
            "vs. periodo anterior</div>"
        )
    bloco_tag = f'<span class="kpi-tag">{_escapar(tag)}</span>' if tag else ""

    return (
        f'<article class="{classe}"{titulo}>'
        f'<div class="kpi-rotulo">{_escapar(rotulo)}</div>'
        f'<div class="kpi-valor">{_escapar(valor)}</div>'
        f"{bloco_delta}{bloco_tag}</article>"
    )


def nota(texto: str) -> None:
    """Desenha uma ressalva metodologica.

    Args:
        texto: Conteudo da nota.
    """
    st.markdown(
        f'<div class="nota">{_escapar(texto)}</div>', unsafe_allow_html=True
    )


def linha_kpis(cartoes: list[dict], compacto: bool = False) -> None:
    """Desenha uma linha de cartoes de KPI.

    Args:
        cartoes: Um dicionario por cartao, com `rotulo`, `valor`, `delta`,
            `tag` e `tooltip`. A presenca da chave `delta` — mesmo com valor
            ``None`` — e o que marca o cartao como participante da comparacao
            com o periodo anterior.
        compacto: Define a densidade e a grade de indicadores secundarios.
    """
    if not cartoes:
        return
    classe = "kpi-grid compacta" if compacto else "kpi-grid"
    classe += f" qtd-{len(cartoes)}"
    html_cartoes = "".join(
        _html_cartao_kpi(
            dados_cartao["rotulo"],
            dados_cartao["valor"],
            dados_cartao.get("delta"),
            "delta" in dados_cartao,
            dados_cartao.get("tag", ""),
            dados_cartao.get("tooltip", ""),
            compacto,
        )
        for dados_cartao in cartoes
    )
    st.markdown(
        f'<div class="{classe}">{html_cartoes}</div>',
        unsafe_allow_html=True,
    )


def titulo_grafico(texto: str) -> None:
    """Desenha um titulo curto fora da area interna do Plotly.

    Args:
        texto: Titulo da visualizacao.
    """
    st.markdown(
        f'<p class="grafico-titulo">{_escapar(texto)}</p>',
        unsafe_allow_html=True,
    )


def tabela(linhas: list[dict], altura: int | None = None) -> None:
    """Renderiza uma tabela ja formatada.

    Args:
        linhas: Lista de dicionarios com valores em texto.
        altura: Altura em pixels; deixa o Streamlit decidir quando omitida.
    """
    if not linhas:
        st.info("Nenhum registro no recorte atual.")
        return
    # `height` so e passado quando ha valor: versoes recentes do Streamlit
    # recusam `None` explicito nesse parametro.
    extras = {"height": altura} if altura else {}
    st.dataframe(linhas, width="stretch", hide_index=True, **extras)


def aviso_sem_dados(periodo: str) -> None:
    """Mensagem padrao para recorte vazio.

    Args:
        periodo: Descricao do periodo selecionado.
    """
    st.warning(
        f"Nenhum registro em {periodo} com os filtros atuais. "
        "Amplie o periodo ou limpe os filtros."
    )


def erro_de_contrato(mensagem: str) -> None:
    """Apresenta uma falha de contrato sem stack trace.

    Args:
        mensagem: Texto da excecao `dados.ContratoInvalido`.
    """
    st.error("O dataset apresentado nao satisfaz o contrato de exposicao.")
    st.markdown(
        f'<div class="nota">{_escapar(mensagem)}</div>', unsafe_allow_html=True
    )
    st.markdown(
        "O dashboard consome **apenas** a superficie de exposicao "
        "pseudonimizada ou o dataset sintetico de demonstracao. Ele nao "
        "consulta o Data Warehouse nem as APIs de anuncios."
    )


def rotulo_metrica(metrica: str) -> str:
    """Rotulo de exibicao de uma metrica base.

    Args:
        metrica: Chave da metrica.

    Returns:
        Rotulo do catalogo.
    """
    return m.CATALOGO[metrica].rotulo
