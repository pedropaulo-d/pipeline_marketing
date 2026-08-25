"""Aplicacao Streamlit do painel analitico.

Papel na arquitetura
--------------------
Ultima camada do pipeline, e a unica que um avaliador ve em movimento:

    Meta Ads + Google Ads -> ELT -> bronze -> silver -> gold
        -> gold.vw_metricas_completas
        -> scripts/exportar_dataset_exposicao.py
        -> data/exposicao/metricas.csv  (superficie pseudonimizada)
        -> este dashboard

Ela e **consumidora** da superficie segura, nunca responsavel por produzi-la.
Nao ha conexao com banco, nao ha chamada de API e nao ha logica de
pseudonimizacao aqui: o modulo `dashboard.dados` so sabe ler CSV, e recusa
qualquer arquivo que carregue coluna de identidade real.

Execucao
--------
    streamlit run dashboard/app.py
    docker compose up -d dashboard   # http://localhost:8501
"""

import sys
from datetime import date
from pathlib import Path

# `streamlit run` coloca o diretorio do SCRIPT no inicio do sys.path, nao a
# raiz do projeto — e a imagem do dashboard nao instala o pacote do ETL de
# proposito (ela nao tem driver de banco nem SDK de plataforma). Sem isto,
# `from dashboard import ...` falharia ao rodar fora do container.
_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

import streamlit as st  # noqa: E402

from dashboard import componentes as ui  # noqa: E402
from dashboard import dados, filtros, graficos  # noqa: E402
from dashboard import metricas as m  # noqa: E402

TITULO: str = "Painel Analítico de Mídia Paga"
MARCA: str = "Painel Analítico"
PRODUTO: str = "Mídia Paga"
SUBTITULO: str = "Google Ads + Meta Ads"

PAGINAS: tuple[str, ...] = (
    "Visao Geral", "Campanhas", "Anuncios", "Sobre os dados",
)

ROTULOS_PAGINAS: dict[str, str] = {
    "Visao Geral": "Visão Geral",
    "Campanhas": "Campanhas",
    "Anuncios": "Anúncios",
    "Sobre os dados": "Sobre os dados",
}

DESCRICAO: dict[str, str] = {
    "Visao Geral": (
        "Acompanhe o desempenho consolidado das campanhas de mídia paga."
    ),
    "Campanhas": (
        "Compare as campanhas pseudonimizadas do período selecionado."
    ),
    "Anuncios": (
        "Identifique os anúncios que sustentam o resultado do período."
    ),
    "Sobre os dados": (
        "O que existe no dataset carregado e por onde ele chega ate aqui."
    ),
}

# Seis indicadores principais, em duas linhas de tres. Ficam de fora as
# metricas cujo total consolidado nao teria leitura honesta: `video_views`
# (definicao diferente por plataforma), `reach` (nao aditiva no tempo) e
# `profile_views` (sem suporte na GAQL e zerada no artefato).
KPIS_PRINCIPAIS: tuple[tuple[str, ...], ...] = (
    ("spend", "impressions", "link_clicks"),
    ("conversions", "conversion_value", "purchases"),
)

KPIS_DERIVADOS: tuple[str, ...] = ("ctr", "cpc", "cpm", "cpa", "roas")

# Metricas oferecidas na comparacao entre plataformas: somente as que somam
# com significado entre origens diferentes.
COMPARACAO_PLATAFORMA: tuple[str, ...] = (
    "spend", "impressions", "link_clicks", "conversions",
)

CHAVES_FILTRO: tuple[str, ...] = (
    "filtro_periodo", "filtro_plataformas", "filtro_contas",
    "filtro_campanhas", "filtro_adsets",
)

MESES: tuple[str, ...] = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)

TEXTO_FRONTEIRA: str = (
    "Este dashboard consome exclusivamente a superficie de exposicao do "
    "pipeline. Identificadores reais de clientes, contas, campanhas e "
    "anuncios nao sao disponibilizados nesta camada."
)


# ── Carregamento ──────────────────────────────────────────────────────────


@st.cache_data(show_spinner=False)
def carregar_dataset(caminho: str, modo: str, assinatura: float):
    """Le e valida o dataset, com cache.

    O `assinatura` (mtime do arquivo) entra na chave do cache de proposito:
    regenerar a superficie de exposicao invalida o cache sem exigir reinicio.

    Args:
        caminho: Caminho absoluto do CSV.
        modo: Modo da fonte.
        assinatura: Timestamp de modificacao do arquivo.

    Returns:
        O `dados.Dataset` validado.

    Raises:
        dados.ContratoInvalido: Em qualquer violacao do contrato.
    """
    del assinatura  # participa da chave do cache, nao do corpo
    return dados.carregar(dados.Fonte(Path(caminho), modo))


def obter_dataset():
    """Resolve a fonte e carrega o dataset.

    Returns:
        O `dados.Dataset` validado.

    Raises:
        dados.ContratoInvalido: Se nao houver fonte utilizavel ou o contrato
            falhar.
    """
    fonte = dados.escolher_fonte()
    return carregar_dataset(
        str(fonte.caminho), fonte.modo, fonte.caminho.stat().st_mtime
    )


# ── Formatacao de periodo ─────────────────────────────────────────────────


def _dia_mes(dia: date) -> str:
    """Formata uma data como ``12 ago``.

    Args:
        dia: Data a formatar.

    Returns:
        Dia e mes abreviado, sem depender de locale do sistema.
    """
    return f"{dia.day:02d} {MESES[dia.month - 1]}"


def formatar_periodo(inicio: date, fim: date) -> str:
    """Formata um intervalo de datas para o cabecalho.

    Args:
        inicio: Primeiro dia.
        fim: Ultimo dia.

    Returns:
        Texto como ``12 ago — 18 ago 2026``.
    """
    if inicio == fim:
        return f"{_dia_mes(inicio)} {inicio.year}"
    if inicio.year == fim.year:
        return f"{_dia_mes(inicio)} — {_dia_mes(fim)} {fim.year}"
    return f"{_dia_mes(inicio)} {inicio.year} — {_dia_mes(fim)} {fim.year}"


# ── Filtros ───────────────────────────────────────────────────────────────


def _multiselect(rotulo: str, opcoes: list[str], chave: str) -> tuple[str, ...]:
    """Multiselect que descarta selecao que deixou de ser valida.

    Quando o usuario troca a conta, campanhas de outra conta continuam no
    estado do widget; mante-las produziria recorte vazio sem explicacao.

    Args:
        rotulo: Rotulo do widget.
        opcoes: Opcoes validas no momento.
        chave: Chave no `session_state`.

    Returns:
        Valores escolhidos.
    """
    st.session_state[chave] = [
        valor for valor in st.session_state.get(chave, []) if valor in opcoes
    ]
    return tuple(
        st.multiselect(
            rotulo, opcoes, key=chave, placeholder="Todos",
        )
    )


def barra_lateral(dataset) -> tuple[str, filtros.Selecao]:
    """Desenha marca, navegacao e filtros globais.

    Args:
        dataset: Dataset carregado.

    Returns:
        Tupla ``(pagina, selecao)``.
    """
    linhas = dataset.linhas
    inicio_dataset, fim_dataset = filtros.intervalo_disponivel(linhas)

    with st.sidebar:
        ui.marca_lateral(MARCA, PRODUTO, SUBTITULO)

        ui.rotulo_lateral("Navegação")
        pagina = st.radio(
            "Navegação",
            PAGINAS,
            format_func=ROTULOS_PAGINAS.__getitem__,
            label_visibility="collapsed",
        )

        ui.rotulo_lateral("Filtros")

        if inicio_dataset is None:
            st.info("Dataset sem linhas.")
            return pagina, filtros.selecao_inicial(linhas)

        # O default e instalado no `session_state` ANTES do widget existir.
        # Passar `value=` junto de `key=` faz o Streamlit avisar que o default
        # e o estado disputam a mesma chave.
        if "filtro_periodo" not in st.session_state:
            padrao = filtros.periodo_padrao(linhas)
            st.session_state["filtro_periodo"] = padrao

        escolha = st.date_input(
            "Período",
            min_value=inicio_dataset,
            max_value=fim_dataset,
            format="DD/MM/YYYY",
            key="filtro_periodo",
        )
        # O widget devolve uma tupla de um elemento enquanto o usuario ainda
        # nao escolheu a segunda data.
        if isinstance(escolha, (tuple, list)):
            data_inicio = escolha[0]
            data_fim = escolha[1] if len(escolha) > 1 else escolha[0]
        else:
            data_inicio = data_fim = escolha

        selecao = filtros.Selecao(data_inicio, data_fim)

        disponiveis = filtros.opcoes(linhas, selecao)
        plataformas = _multiselect(
            "Plataforma", disponiveis["plataformas"], "filtro_plataformas"
        )
        selecao = filtros.Selecao(data_inicio, data_fim, plataformas)

        disponiveis = filtros.opcoes(linhas, selecao)
        contas = _multiselect(
            "Conta", disponiveis["contas"], "filtro_contas"
        )
        selecao = filtros.Selecao(data_inicio, data_fim, plataformas, contas)

        disponiveis = filtros.opcoes(linhas, selecao)
        campanhas = _multiselect(
            "Campanha", disponiveis["campanhas"], "filtro_campanhas"
        )
        selecao = filtros.Selecao(
            data_inicio, data_fim, plataformas, contas, campanhas
        )

        disponiveis = filtros.opcoes(linhas, selecao)
        adsets = _multiselect(
            "Ad set", disponiveis["adsets"], "filtro_adsets"
        )
        selecao = filtros.Selecao(
            data_inicio, data_fim, plataformas, contas, campanhas, adsets
        )

        if st.button("Limpar filtros", width="stretch"):
            for chave in CHAVES_FILTRO:
                st.session_state.pop(chave, None)
            st.rerun()

        ui.rodape_lateral(
            dataset.fonte.caminho_relativo, dataset.rotulo_modo
        )

    return pagina, filtros.sanear(linhas, selecao)


# ── Blocos reutilizados entre paginas ────────────────────────────────────


def tag_cobertura(metrica: str, plataformas: list[str]) -> tuple[str, str]:
    """Monta o marcador de cobertura de uma metrica.

    Args:
        metrica: Chave da metrica base.
        plataformas: Plataformas presentes no recorte.

    Returns:
        Tupla ``(tag, tooltip)``. Ambas vazias quando todas as origens
        suportam a metrica.
    """
    sem_suporte = [p for p in plataformas if not m.suportada(metrica, p)]
    if not sem_suporte:
        return "", ""
    com_suporte = [p for p in plataformas if m.suportada(metrica, p)]
    tag = "Parcial · " + ", ".join(com_suporte) if com_suporte else "Indisponivel"
    tooltip = (
        f"{', '.join(sem_suporte)} nao disponibiliza esta metrica neste "
        "nivel. O total reflete apenas as demais origens."
    )
    return tag, tooltip


def bloco_kpis(atual: list[dict], anterior: list[dict] | None,
               plataformas: list[str]) -> None:
    """Desenha os cartoes de KPI principais.

    Args:
        atual: Linhas do periodo selecionado.
        anterior: Linhas do periodo de comparacao, ou ``None`` quando nao ha.
        plataformas: Plataformas presentes no recorte.
    """
    totais = m.agregar(atual)
    totais_anteriores = m.agregar(anterior) if anterior else None

    cartoes = []
    for grupo in KPIS_PRINCIPAIS:
        for metrica in grupo:
            base = totais_anteriores[metrica] if totais_anteriores else None
            variacao = m.variacao(totais[metrica], base)
            tag, tooltip = tag_cobertura(metrica, plataformas)
            cartoes.append({
                "rotulo": m.CATALOGO[metrica].rotulo,
                "valor": m.formatar_metrica(metrica, totais[metrica]),
                "delta": (
                    m.formatar_variacao(variacao)
                    if variacao is not None else None
                ),
                "tag": tag,
                "tooltip": tooltip or m.CATALOGO[metrica].observacao,
            })
    ui.linha_kpis(cartoes)


def bloco_eficiencia(atual: list[dict],
                     anterior: list[dict] | None) -> None:
    """Desenha os cartoes de indicadores derivados.

    Args:
        atual: Linhas do periodo selecionado.
        anterior: Linhas do periodo de comparacao, ou ``None``.
    """
    totais = m.agregar(atual)
    derivadas = m.calcular_derivadas(totais)
    derivadas_anteriores = (
        m.calcular_derivadas(m.agregar(anterior)) if anterior else {}
    )

    cartoes = []
    for chave in KPIS_DERIVADOS:
        definicao = m.DERIVADAS[chave]
        variacao = m.variacao(
            derivadas[chave], derivadas_anteriores.get(chave)
        )
        cartoes.append({
            "rotulo": definicao.rotulo,
            "valor": m.formatar_derivada(chave, derivadas[chave]),
            "delta": (
                m.formatar_variacao(variacao) if variacao is not None else None
            ),
            # A formula fica no tooltip: dentro do cartao ela roubava o peso
            # visual do numero e desalinhava a linha.
            "tooltip": f"{definicao.rotulo} = {definicao.descricao}",
        })
    ui.linha_kpis(cartoes, compacto=True)


def seletor_metrica(rotulo: str, opcoes: tuple[str, ...], chave: str) -> str:
    """Selectbox de metrica com rotulos do catalogo.

    Args:
        rotulo: Rotulo do widget.
        opcoes: Chaves de metrica oferecidas.
        chave: Chave no `session_state`.

    Returns:
        A chave da metrica escolhida.
    """
    return st.selectbox(
        rotulo,
        opcoes,
        format_func=lambda chave_metrica: m.CATALOGO[chave_metrica].rotulo,
        key=chave,
    )


def tabela_ranking(itens: list[dict], nivel: str) -> list[dict]:
    """Formata o ranking para exibicao em tabela.

    Args:
        itens: Saida de `metricas.ranking`.
        nivel: Nivel exibido, usado no rotulo da primeira coluna.

    Returns:
        Lista de dicionarios com todos os valores em texto.
    """
    rotulo_id = {
        "conta": "Conta", "campanha": "Campanha",
        "adset": "Ad set", "anuncio": "Anuncio",
    }[nivel]

    linhas = []
    for item in itens:
        linha = {rotulo_id: item["id"], "Plataforma": item["plataforma"]}
        for pai, rotulo in (("conta", "Conta"), ("campanha", "Campanha"),
                            ("adset", "Ad set")):
            if pai in item and pai != nivel:
                linha[f"{rotulo} (pai)"] = item[pai]
        linha.update({
            "Investimento": m.formatar_metrica("spend", item["spend"]),
            "Impressoes": m.formatar_metrica(
                "impressions", item["impressions"]),
            "Cliques": m.formatar_metrica(
                "link_clicks", item["link_clicks"]),
            "Conversoes": m.formatar_metrica(
                "conversions", item["conversions"]),
            "CTR": m.formatar_derivada("ctr", item["ctr"]),
            "CPC": m.formatar_derivada("cpc", item["cpc"]),
            "CPA": m.formatar_derivada("cpa", item["cpa"]),
            "ROAS": m.formatar_derivada("roas", item["roas"]),
            "Versoes SCD2": str(item["versoes"]),
            "Dias com dado": str(item["linhas"]),
        })
        linhas.append(linha)
    return linhas


def pagina_ranking(linhas: list[dict], nivel: str, titulo: str,
                   apoio: str) -> None:
    """Desenha uma pagina de ranking (campanhas ou anuncios).

    Args:
        linhas: Linhas filtradas.
        nivel: `campanha` ou `anuncio`.
        titulo: Titulo da secao de ranking.
        apoio: Linha explicativa da secao.
    """
    ui.secao(titulo, apoio)

    with st.container(key=f"controles_ranking_{nivel}"):
        coluna_metrica, coluna_topo = st.columns(
            [2, 1], vertical_alignment="bottom"
        )
        with coluna_metrica:
            metrica = seletor_metrica(
                "Ordenar por", m.METRICAS, f"metrica_{nivel}"
            )
        with coluna_topo:
            topo = st.selectbox("Exibir", (10, 15), key=f"topo_{nivel}")

    completo = m.ranking(linhas, nivel, metrica)
    if not completo:
        ui.tabela([])
        return

    st.plotly_chart(
        graficos.barras_ranking(completo[:topo], metrica),
        width="stretch",
        config={"displayModeBar": False},
    )

    observacao = m.CATALOGO[metrica].observacao
    if observacao:
        ui.nota(f"{m.CATALOGO[metrica].rotulo}: {observacao}")

    plural = {"campanha": "campanhas", "anuncio": "anuncios"}.get(
        nivel, f"{nivel}s"
    )
    ui.secao(
        "Detalhamento",
        f"{len(completo)} {plural} no recorte atual — a tabela mostra o "
        "conjunto completo, nao apenas o Top N.",
    )
    ui.tabela(tabela_ranking(completo, nivel), altura=360)


# ── Paginas ───────────────────────────────────────────────────────────────


def pagina_visao_geral(dataset, selecao: filtros.Selecao,
                       linhas: list[dict]) -> None:
    """Desenha a pagina de visao geral.

    Args:
        dataset: Dataset carregado.
        selecao: Filtros vigentes.
        linhas: Linhas ja filtradas.
    """
    plataformas = sorted({linha["plataforma"] for linha in linhas})

    inicio_anterior, fim_anterior = m.periodo_anterior(
        selecao.data_inicio, selecao.data_fim
    )
    anteriores = filtros.aplicar_em_periodo(
        dataset.linhas, selecao, inicio_anterior, fim_anterior
    )

    ui.secao(
        "Indicadores do período",
        f"vs. {formatar_periodo(inicio_anterior, fim_anterior)}"
        if anteriores else "Sem base de comparação no período anterior.",
    )
    bloco_kpis(linhas, anteriores or None, plataformas)

    ui.secao("Eficiência", "Indicadores derivados do período selecionado.")
    bloco_eficiencia(linhas, anteriores or None)

    ui.secao(
        "Evolução diária",
        "Acompanhe o comportamento da métrica selecionada ao longo do período.",
    )
    with st.container(key="controles_serie"):
        coluna_metrica, coluna_modo = st.columns(
            [1.35, 1], vertical_alignment="bottom"
        )
        with coluna_metrica:
            metrica = seletor_metrica(
                "Métrica", m.METRICAS, "metrica_serie"
            )
        with coluna_modo:
            separar = st.toggle(
                "Comparar plataformas",
                value=len(plataformas) > 1,
                key="serie_por_plataforma",
            )

    series = m.serie_diaria(linhas, metrica, por_plataforma=separar)
    st.plotly_chart(
        graficos.serie_temporal(series, metrica),
        width="stretch",
        config={"displayModeBar": False},
    )
    observacao = m.CATALOGO[metrica].observacao
    if observacao:
        ui.nota(f"{m.CATALOGO[metrica].rotulo}: {observacao}")

    ui.secao(
        "Meta Ads x Google Ads",
        "Compare métricas coletadas nas duas origens com a mesma definição.",
    )
    valores = m.agregar_por(linhas, lambda linha: linha["plataforma"])

    with st.container(key="graficos_plataforma"):
        colunas = st.columns(2, gap="small")
        for indice, metrica_comparada in enumerate(COMPARACAO_PLATAFORMA):
            with colunas[indice % 2]:
                ui.titulo_grafico(m.CATALOGO[metrica_comparada].rotulo)
                st.plotly_chart(
                    graficos.barras_plataforma(
                        {p: t[metrica_comparada] for p, t in valores.items()},
                        metrica_comparada,
                    ),
                    width="stretch",
                    config={"displayModeBar": False},
                )

    ui.secao(
        "Participacao e cobertura",
        "Como o investimento se divide e o que cada origem nao fornece.",
    )
    if len(plataformas) > 1:
        st.plotly_chart(
            graficos.barras_participacao(
                {p: t["spend"] for p, t in valores.items()}, "spend"
            ),
            width="stretch",
            config={"displayModeBar": False},
        )

    cobertura = [
        f"{m.CATALOGO[metrica_base].rotulo} — {plataforma}"
        for metrica_base in m.METRICAS
        for plataforma in plataformas
        if not m.suportada(metrica_base, plataforma)
    ]
    if cobertura:
        ui.nota(
            "Nao disponibilizado nesta origem: " + " · ".join(cobertura)
            + ". Zero nessas celulas significa ausencia de suporte, nao "
            "desempenho nulo."
        )

    ui.secao("Indicadores por plataforma", "")
    comparativo = []
    for plataforma in sorted(valores):
        totais = valores[plataforma]
        derivadas = m.calcular_derivadas(totais)
        comparativo.append({
            "Plataforma": plataforma,
            "Investimento": m.formatar_metrica("spend", totais["spend"]),
            "Impressoes": m.formatar_metrica(
                "impressions", totais["impressions"]),
            "Cliques": m.formatar_metrica(
                "link_clicks", totais["link_clicks"]),
            "Conversoes": m.formatar_metrica(
                "conversions", totais["conversions"]),
            "CTR": m.formatar_derivada("ctr", derivadas["ctr"]),
            "CPC": m.formatar_derivada("cpc", derivadas["cpc"]),
            "CPM": m.formatar_derivada("cpm", derivadas["cpm"]),
            "CPA": m.formatar_derivada("cpa", derivadas["cpa"]),
            "ROAS": m.formatar_derivada("roas", derivadas["roas"]),
        })
    ui.tabela(comparativo)


def pagina_anuncios(linhas: list[dict]) -> None:
    """Desenha a pagina de anuncios.

    Args:
        linhas: Linhas ja filtradas.
    """
    pagina_ranking(
        linhas, "anuncio", "Ranking de anúncios",
        "Anúncios pseudonimizados, no grão de anúncio x dia.",
    )

    identificadores = sorted({linha["anuncio_id"] for linha in linhas})
    ui.secao(
        "Evolução de um anúncio",
        "Série diária de um anúncio do recorte atual.",
    )
    with st.container(key="controles_anuncio"):
        coluna_anuncio, coluna_metrica = st.columns(
            [1, 1], vertical_alignment="bottom"
        )
        with coluna_anuncio:
            anuncio = st.selectbox(
                "Anúncio", identificadores, key="anuncio_detalhe"
            )
        with coluna_metrica:
            metrica = seletor_metrica(
                "Métrica", m.METRICAS, "metrica_anuncio_detalhe"
            )

    do_anuncio = [
        linha for linha in linhas if linha["anuncio_id"] == anuncio
    ]
    series = m.serie_diaria(do_anuncio, metrica, por_plataforma=True)
    st.plotly_chart(
        graficos.serie_temporal(series, metrica, altura=300),
        width="stretch",
        config={"displayModeBar": False},
    )


def pagina_sobre(dataset, linhas: list[dict]) -> None:
    """Desenha a pagina "Sobre os dados".

    Args:
        dataset: Dataset carregado.
        linhas: Linhas ja filtradas (usadas apenas para o recorte atual).
    """
    resumo = dados.resumo(dataset)
    manifesto = dataset.manifesto

    periodo = (
        formatar_periodo(resumo["data_min"], resumo["data_max"])
        if resumo["data_min"] else m.INDISPONIVEL
    )

    ui.secao("Dataset carregado", dataset.fonte.caminho_relativo)
    ui.linha_kpis([
        {"rotulo": "Periodo", "valor": periodo,
         "tooltip": f"{resumo['dias']} dias com dado"},
        {"rotulo": "Plataformas",
         "valor": str(len(resumo["plataformas"])),
         "tag": ", ".join(resumo["plataformas"])},
        {"rotulo": "Linhas", "valor": m.formatar(resumo["linhas"], m.INTEIRO),
         "tag": "grao: anuncio x dia"},
    ], compacto=True)
    ui.linha_kpis([
        {"rotulo": "Contas", "valor": m.formatar(resumo["contas"], m.INTEIRO)},
        {"rotulo": "Campanhas",
         "valor": m.formatar(resumo["campanhas"], m.INTEIRO)},
        {"rotulo": "Ad sets",
         "valor": m.formatar(resumo["adsets"], m.INTEIRO)},
        {"rotulo": "Anuncios",
         "valor": m.formatar(resumo["anuncios"], m.INTEIRO)},
        {"rotulo": "No recorte atual",
         "valor": m.formatar(len(linhas), m.INTEIRO),
         "tag": "apos os filtros"},
    ], compacto=True)

    ui.secao("Segurança e privacidade", "")
    st.markdown(
        f"{TEXTO_FRONTEIRA}\n\n"
        "- Os identificadores exibidos (`Cliente-`, `Campanha-`, `AdSet-`, "
        "`Anuncio-`) sao pseudonimos gerados **fora** desta camada.\n"
        "- Metricas e datas sao reais e intactas: a pseudonimizacao troca "
        "identidade, nunca numero.\n"
        "- O painel nao acessa o Data Warehouse nem as APIs de anuncios; a "
        "unica entrada e um arquivo que satisfaz o contrato de exposicao.\n"
        "- Coluna terminada em `_nk`, `_sk`, `_external_id` ou `_nome` faz o "
        "arquivo inteiro ser recusado."
    )

    ui.secao(
        "Métricas por origem",
        '"nao coletado" = a origem nao disponibiliza a metrica neste nivel. '
        "Zero nessas celulas nao e desempenho nulo.",
    )
    ui.tabela([
        {
            "Metrica": definicao.rotulo,
            "Coluna": definicao.chave,
            # Rotulo curto: a coluna e estreita e o texto longo era cortado
            # pela tabela. O significado esta no apoio da secao.
            "Meta Ads": "sim" if m.suportada(definicao.chave, "Meta Ads")
            else "nao coletado",
            "Google Ads": "sim" if m.suportada(definicao.chave, "Google Ads")
            else "nao coletado",
            "Somavel entre plataformas": (
                "sim" if definicao.comparavel_entre_plataformas else "nao"
            ),
        }
        for definicao in m.CATALOGO.values()
    ])

    with st.expander("Indicadores derivados e manifesto do artefato"):
        ui.tabela([
            {"Indicador": definicao.rotulo, "Formula": definicao.descricao}
            for definicao in m.DERIVADAS.values()
        ])
        if manifesto:
            itens = {
                "Versao do contrato": manifesto.get("versao_contrato"),
                "Gerado em": manifesto.get("gerado_em"),
                "Linhas declaradas": manifesto.get("linhas"),
                "Intervalo declarado": (
                    f"{manifesto.get('data_min')} a {manifesto.get('data_max')}"
                ),
                "sha256 do CSV": manifesto.get("sha256"),
                "Origem declarada": manifesto.get(
                    "origem", manifesto.get("gerador")
                ),
            }
            if manifesto.get("fingerprint_chave"):
                # Impressao digital da chave de pseudonimizacao: nao permite
                # recuperar o segredo e responde se dois artefatos usam a
                # mesma chave — portanto se os pseudonimos sao comparaveis.
                itens["Fingerprint da chave"] = manifesto["fingerprint_chave"]
            if manifesto.get("natureza"):
                itens["Natureza"] = manifesto["natureza"]
            ui.tabela([
                {"Campo": chave, "Valor": str(valor)}
                for chave, valor in itens.items() if valor is not None
            ])

        if dataset.colunas_ignoradas:
            ui.nota(
                "Colunas fora do contrato foram ignoradas de proposito: "
                + ", ".join(dataset.colunas_ignoradas)
                + "."
            )


# ── Composicao ────────────────────────────────────────────────────────────


def linha_registros(dataset, quantidade: int) -> str:
    """Monta a linha secundaria do cabecalho.

    Args:
        dataset: Dataset carregado.
        quantidade: Registros no recorte atual.

    Returns:
        Texto curto com a contagem e, quando o manifesto informar, a data de
        geracao do artefato.
    """
    texto = f"{m.formatar(quantidade, m.INTEIRO)} registros"
    gerado = (dataset.manifesto or {}).get("gerado_em")
    if gerado:
        try:
            data_geracao = date.fromisoformat(str(gerado)[:10])
            texto += f" · dataset de {_dia_mes(data_geracao)} {data_geracao.year}"
        except ValueError:
            # Manifesto antigo ou de terceiro: manter uma representacao curta
            # sem impedir que um dataset valido seja visualizado.
            texto += f" · dataset de {str(gerado)[:10]}"
    return texto


def main() -> None:
    """Ponto de entrada da aplicacao Streamlit."""
    st.set_page_config(
        page_title=TITULO,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    ui.injetar_estilo()

    try:
        dataset = obter_dataset()
    except dados.ContratoInvalido as erro:
        ui.erro_de_contrato(str(erro))
        return

    pagina, selecao = barra_lateral(dataset)
    linhas = filtros.aplicar(dataset.linhas, selecao)

    ui.cabecalho(
        ROTULOS_PAGINAS[pagina],
        DESCRICAO[pagina],
        formatar_periodo(selecao.data_inicio, selecao.data_fim),
        linha_registros(dataset, len(linhas)),
        dataset.rotulo_modo,
        dataset.modo,
    )

    if pagina == "Sobre os dados":
        pagina_sobre(dataset, linhas)
        return

    if not linhas:
        ui.aviso_sem_dados(
            formatar_periodo(selecao.data_inicio, selecao.data_fim)
        )
        return

    if pagina == "Visao Geral":
        pagina_visao_geral(dataset, selecao, linhas)
    elif pagina == "Campanhas":
        pagina_ranking(
            linhas, "campanha", "Ranking de campanhas",
            "Campanhas pseudonimizadas, ordenadas pela métrica escolhida.",
        )
    elif pagina == "Anuncios":
        pagina_anuncios(linhas)


main()
