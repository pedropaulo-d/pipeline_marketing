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
        "Performance consolidada das campanhas de mídia paga."
    ),
    "Campanhas": (
        "Compare as campanhas pseudonimizadas do período selecionado."
    ),
    "Anuncios": (
        "Identifique os anúncios que sustentam o resultado do período."
    ),
    "Sobre os dados": (
        "O que existe no dataset carregado e por onde ele chega até aqui."
    ),
}

# Seis indicadores principais, em duas linhas de tres. Ficam de fora as
# metricas cujo total consolidado nao teria leitura honesta: `video_views`
# (definicao diferente por plataforma), `reach` (nao aditiva no tempo) e
# `profile_views` (sem suporte na GAQL e zerada no artefato).
# A composicao dos cartoes por recorte vive em `metricas.py`, junto do
# catalogo e das formulas: assim ela e testavel sem carregar o Streamlit.
PAINEL_RESULTADOS = m.PAINEL_RESULTADOS
PAINEL_VALOR = m.PAINEL_VALOR
ENTREGA = m.ENTREGA
EFICIENCIA = m.EFICIENCIA

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
    "Este dashboard consome exclusivamente a superfície de exposição do "
    "pipeline. Identificadores reais de clientes, contas, campanhas e "
    "anúncios não são disponibilizados nesta camada."
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
        f"{', '.join(sem_suporte)} não disponibiliza esta métrica neste "
        "nível. O total reflete apenas as demais origens."
    )
    return tag, tooltip


_recorte = m.recorte


def _cartao_metrica(metrica: str, totais: dict, anteriores: dict | None,
                    plataformas: list[str]) -> dict:
    """Monta um cartao a partir de uma metrica do catalogo.

    Args:
        metrica: Chave em :data:`metricas.CATALOGO`.
        totais: Agregado do periodo.
        anteriores: Agregado do periodo de comparacao, ou ``None``.
        plataformas: Plataformas presentes no recorte.

    Returns:
        Dicionario no formato que :func:`componentes.linha_kpis` espera.
    """
    definicao = m.CATALOGO[metrica]
    base = anteriores[metrica] if anteriores else None
    variacao = m.variacao(totais[metrica], base)
    tag, cobertura = tag_cobertura(metrica, plataformas)
    # A definicao da metrica vem primeiro; a ressalva de cobertura (ou a
    # observacao do catalogo) fecha o texto. As duas convivem: saber o que o
    # numero conta nao dispensa saber de onde ele nao vem.
    partes = (definicao.ajuda, cobertura or definicao.observacao)
    return {
        "rotulo": definicao.rotulo,
        "valor": m.formatar_metrica(metrica, totais[metrica]),
        "delta": (
            m.formatar_variacao(variacao) if variacao is not None else None
        ),
        "tag": tag,
        "tooltip": " ".join(parte for parte in partes if parte),
    }


def _cartao_painel(chave: str, valores: dict, anteriores: dict | None,
                   isolado: bool = False) -> dict:
    """Monta um cartao a partir de um indicador do painel por plataforma.

    Args:
        chave: Chave em :data:`metricas.PAINEL`.
        valores: Saida de :func:`metricas.painel` para o periodo.
        anteriores: Mesma estrutura para o periodo de comparacao, ou ``None``.
        isolado: ``True`` quando o filtro ja deixou uma unica plataforma. Nesse
            caso vale o rotulo curto, quando houver: o sufixo de plataforma
            informa no recorte misto e vira ruido no exclusivo.

    Returns:
        Dicionario no formato que :func:`componentes.linha_kpis` espera.
    """
    definicao = m.PAINEL[chave]
    base = anteriores.get(chave) if anteriores else None
    variacao = m.variacao(valores[chave], base)
    return {
        "rotulo": (
            definicao.rotulo_curto
            if isolado and definicao.rotulo_curto
            else definicao.rotulo
        ),
        "valor": m.formatar_painel(chave, valores[chave]),
        "delta": (
            m.formatar_variacao(variacao) if variacao is not None else None
        ),
        "tag": "",
        "tooltip": definicao.ajuda,
    }


def _cartoes(chaves: tuple[str, ...], totais: dict, totais_anteriores: dict | None,
             valores: dict, valores_anteriores: dict | None,
             plataformas: list[str]) -> list[dict]:
    """Monta uma lista mista de cartoes.

    Uma chave prefixada por ``@`` vem do catalogo de metricas, uma prefixada
    por ``#`` vem do catalogo de derivadas, e as demais vem do painel por
    plataforma. Os prefixos evitam listas paralelas para descrever uma unica
    linha de cartoes.

    Args:
        chaves: Chaves na ordem de exibicao.
        totais: Agregado do periodo.
        totais_anteriores: Agregado de comparacao, ou ``None``.
        valores: Saida de :func:`metricas.painel`.
        valores_anteriores: Painel do periodo de comparacao, ou ``None``.
        plataformas: Plataformas presentes no recorte.

    Returns:
        Lista de cartoes prontos para :func:`componentes.linha_kpis`.
    """
    isolado = m.recorte(plataformas) != "ambas"
    cartoes = []
    for chave in chaves:
        if chave.startswith("@"):
            cartoes.append(
                _cartao_metrica(chave[1:], totais, totais_anteriores, plataformas)
            )
        elif chave.startswith("#"):
            cartoes.append(
                _cartao_derivada(chave[1:], totais, totais_anteriores)
            )
        else:
            cartoes.append(
                _cartao_painel(chave, valores, valores_anteriores, isolado)
            )
    return cartoes


def bloco_resultados(atual: list[dict], anterior: list[dict] | None,
                     plataformas: list[str]) -> None:
    """Desenha os KPIs de resultado, nomeados por plataforma.

    Args:
        atual: Linhas do periodo selecionado.
        anterior: Linhas do periodo de comparacao, ou ``None``.
        plataformas: Plataformas presentes no recorte.
    """
    valores = m.painel(atual)
    valores_anteriores = m.painel(anterior) if anterior else None
    cartoes = _cartoes(
        PAINEL_RESULTADOS[_recorte(plataformas)],
        m.agregar(atual), None, valores, valores_anteriores, plataformas,
    )
    ui.linha_kpis(cartoes, chave="grade_resultados")


def bloco_valor(atual: list[dict], anterior: list[dict] | None,
                plataformas: list[str]) -> None:
    """Desenha os KPIs de valor atribuido e retorno.

    Args:
        atual: Linhas do periodo selecionado.
        anterior: Linhas do periodo de comparacao, ou ``None``.
        plataformas: Plataformas presentes no recorte.
    """
    valores = m.painel(atual)
    valores_anteriores = m.painel(anterior) if anterior else None
    cartoes = _cartoes(
        PAINEL_VALOR[_recorte(plataformas)],
        m.agregar(atual), None, valores, valores_anteriores, plataformas,
    )
    ui.linha_kpis(cartoes, chave="grade_valor")


def bloco_entrega(atual: list[dict], anterior: list[dict] | None,
                  plataformas: list[str]) -> None:
    """Desenha os KPIs de entrega — volume, nao resultado.

    Args:
        atual: Linhas do periodo selecionado.
        anterior: Linhas do periodo de comparacao, ou ``None``.
        plataformas: Plataformas presentes no recorte.
    """
    totais = m.agregar(atual)
    totais_anteriores = m.agregar(anterior) if anterior else None
    valores = m.painel(atual)
    valores_anteriores = m.painel(anterior) if anterior else None
    cartoes = _cartoes(
        ENTREGA[_recorte(plataformas)],
        totais, totais_anteriores, valores, valores_anteriores, plataformas,
    )
    ui.linha_kpis(cartoes, chave="grade_entrega")


def _cartao_derivada(chave: str, totais: dict,
                     anteriores: dict | None) -> dict:
    """Monta um cartao a partir de um indicador derivado consolidavel.

    Args:
        chave: Chave em :data:`metricas.DERIVADAS`.
        totais: Agregado do periodo.
        anteriores: Agregado do periodo de comparacao, ou ``None``.

    Returns:
        Dicionario no formato que :func:`componentes.linha_kpis` espera.
    """
    definicao = m.DERIVADAS[chave]
    valor = m.calcular_derivada(chave, totais)
    base = m.calcular_derivada(chave, anteriores) if anteriores else None
    variacao = m.variacao(valor, base)
    return {
        "rotulo": definicao.rotulo,
        "valor": m.formatar_derivada(chave, valor),
        "delta": (
            m.formatar_variacao(variacao) if variacao is not None else None
        ),
        "tag": "",
        # A definicao e a formula ficam na ajuda contextual: dentro do cartao
        # elas roubavam o peso visual do numero e desalinhavam a linha.
        "tooltip": (
            definicao.ajuda or f"{definicao.rotulo} = {definicao.descricao}"
        ),
    }


def bloco_eficiencia(atual: list[dict], anterior: list[dict] | None,
                     plataformas: list[str]) -> None:
    """Desenha os indicadores de eficiencia do recorte.

    CTR e CPC saem sempre isolados por plataforma; so o CPM consolida.

    Args:
        atual: Linhas do periodo selecionado.
        anterior: Linhas do periodo de comparacao, ou ``None``.
        plataformas: Plataformas presentes no recorte.
    """
    totais = m.agregar(atual)
    totais_anteriores = m.agregar(anterior) if anterior else None
    valores = m.painel(atual)
    valores_anteriores = m.painel(anterior) if anterior else None
    cartoes = _cartoes(
        EFICIENCIA[m.recorte(plataformas)],
        totais, totais_anteriores, valores, valores_anteriores, plataformas,
    )
    ui.linha_kpis(cartoes, compacto=True, chave="grade_eficiencia")


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
        "adset": "Ad set", "anuncio": "Anúncio",
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
            "Impressões": m.formatar_metrica(
                "impressions", item["impressions"]),
            "Cliques": m.formatar_metrica(
                "link_clicks", item["link_clicks"]),
            "Conversões": m.formatar_metrica(
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

    with st.container(border=True, key=f"cartao_ranking_{nivel}"):
        ui.titulo_grafico(
            "Desempenho no período",
            "A barra usa o valor real da métrica; a origem aparece junto à entidade.",
        )
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
            ui.estado_vazio(
                "Nenhum dado encontrado", "Ajuste os filtros ou o período."
            )
            return

        st.plotly_chart(
            graficos.barras_ranking(completo[:topo], metrica),
            width="stretch",
            config=graficos.CONFIG_PLOTLY,
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
        "conjunto completo, não apenas o Top N.",
    )
    ui.tabela(tabela_ranking(completo, nivel), altura=330)


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

    comparacao = (
        f"vs. {formatar_periodo(inicio_anterior, fim_anterior)}"
        if anteriores else "Sem base de comparação no período anterior."
    )

    ui.secao("Resultados", comparacao)
    bloco_resultados(linhas, anteriores or None, plataformas)

    ui.secao(
        "Valor e retorno",
        "Meta e Google atribuem valor por definições próprias; os totais "
        "somam origens, não conceitos equivalentes.",
    )
    bloco_valor(linhas, anteriores or None, plataformas)

    ui.secao("Eficiência", "Indicadores derivados do período selecionado.")
    bloco_eficiencia(linhas, anteriores or None, plataformas)

    ui.secao("Entrega", "Volume de veiculação no período selecionado.")
    bloco_entrega(linhas, anteriores or None, plataformas)

    ui.secao("Evolução diária", "")
    with st.container(border=True, key="cartao_evolucao"):
        ui.titulo_grafico(
            "Evolução diária",
            "Visualize a evolução da métrica no período selecionado.",
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
        if series:
            st.plotly_chart(
                graficos.serie_temporal(series, metrica),
                width="stretch",
                config=graficos.CONFIG_PLOTLY,
            )
        else:
            ui.estado_vazio(
                "Nenhum dado encontrado", "Ajuste os filtros ou o período."
            )
        observacao = m.CATALOGO[metrica].observacao
        if observacao:
            ui.nota(f"{m.CATALOGO[metrica].rotulo}: {observacao}")

    ui.secao(
        "Meta Ads × Google Ads",
        "Compare métricas coletadas nas duas origens com a mesma definição.",
    )
    valores = m.agregar_por(linhas, lambda linha: linha["plataforma"])

    with st.container(key="grade_comparacao"):
        colunas = st.columns(2, gap="small")
        for indice, metrica_comparada in enumerate(COMPARACAO_PLATAFORMA):
            with colunas[indice % 2]:
                with st.container(
                    border=True, key=f"comparacao_{metrica_comparada}"
                ):
                    ui.titulo_grafico(m.CATALOGO[metrica_comparada].rotulo)
                    st.plotly_chart(
                        graficos.barras_plataforma(
                            {
                                p: t[metrica_comparada]
                                for p, t in valores.items()
                            },
                            metrica_comparada,
                        ),
                        width="stretch",
                        config=graficos.CONFIG_PLOTLY,
                    )

    ui.secao(
        "Participação e cobertura",
        "Como o investimento se divide e quais métricas cada origem fornece.",
    )
    with st.container(key="grade_participacao"):
        coluna_participacao, coluna_cobertura = st.columns(2, gap="small")
        with coluna_participacao:
            with st.container(border=True, key="card_participacao"):
                ui.titulo_grafico(
                    "Participação no investimento",
                    "Distribuição percentual do valor investido no recorte.",
                )
                if len(plataformas) > 1:
                    st.plotly_chart(
                        graficos.barras_participacao(
                            {p: t["spend"] for p, t in valores.items()}, "spend"
                        ),
                        width="stretch",
                        config=graficos.CONFIG_PLOTLY,
                    )
                else:
                    ui.estado_vazio(
                        "Comparação indisponível",
                        "Selecione as duas plataformas para visualizar a participação.",
                    )
        with coluna_cobertura:
            with st.container(border=True, key="card_cobertura"):
                ui.titulo_grafico(
                    "Cobertura das métricas",
                    "Indisponibilidade nunca é apresentada como desempenho zero.",
                )
                ui.quadro_cobertura([
                    (
                        m.CATALOGO[chave].rotulo,
                        m.suportada(chave, "Meta Ads"),
                        m.suportada(chave, "Google Ads"),
                    )
                    for chave in ("reach", "purchases", "conversions")
                ])

    ui.secao("Indicadores por plataforma", "")
    comparativo = []
    for plataforma in sorted(valores):
        totais = valores[plataforma]
        derivadas = m.calcular_derivadas(totais)
        comparativo.append({
            "Plataforma": plataforma,
            "Investimento": m.formatar_metrica("spend", totais["spend"]),
            "Impressões": m.formatar_metrica(
                "impressions", totais["impressions"]),
            "Cliques": m.formatar_metrica(
                "link_clicks", totais["link_clicks"]),
            "Conversões": m.formatar_metrica(
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
        "Detalhe do anúncio",
        "Contexto essencial e evolução temporal sem ampliar a superfície de dados.",
    )
    with st.container(border=True, key="cartao_detalhe_anuncio"):
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
        totais = m.agregar(do_anuncio)
        referencia = do_anuncio[0]
        ui.detalhe_anuncio(anuncio, [
            ("Plataforma", referencia["plataforma"]),
            ("Campanha", referencia["campanha_id"]),
            ("Investimento", m.formatar_metrica("spend", totais["spend"])),
            ("Cliques", m.formatar_metrica("link_clicks", totais["link_clicks"])),
            ("Conversões", m.formatar_metrica("conversions", totais["conversions"])),
        ])
        ui.titulo_grafico(
            "Evolução temporal",
            "Série diária do anúncio no período e nos filtros atuais.",
        )
        series = m.serie_diaria(do_anuncio, metrica, por_plataforma=True)
        st.plotly_chart(
            graficos.serie_temporal(series, metrica, altura=310),
            width="stretch",
            config=graficos.CONFIG_PLOTLY,
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
        {"rotulo": "Período", "valor": periodo,
         "tooltip": f"{resumo['dias']} dias com dado"},
        {"rotulo": "Plataformas",
         "valor": str(len(resumo["plataformas"])),
         "tag": ", ".join(resumo["plataformas"])},
        {"rotulo": "Linhas", "valor": m.formatar(resumo["linhas"], m.INTEIRO),
         "tag": "grão: anúncio × dia"},
    ], compacto=True, chave="grade_resumo")
    ui.linha_kpis([
        {"rotulo": "Contas", "valor": m.formatar(resumo["contas"], m.INTEIRO)},
        {"rotulo": "Campanhas",
         "valor": m.formatar(resumo["campanhas"], m.INTEIRO)},
        {"rotulo": "Ad sets",
         "valor": m.formatar(resumo["adsets"], m.INTEIRO)},
        {"rotulo": "Anúncios",
         "valor": m.formatar(resumo["anuncios"], m.INTEIRO)},
        {"rotulo": "No recorte atual",
         "valor": m.formatar(len(linhas), m.INTEIRO),
         "tag": "após os filtros"},
    ], compacto=True, chave="grade_resumo_entidades")

    ui.secao("Segurança e privacidade", "")
    st.markdown(
        f"{TEXTO_FRONTEIRA}\n\n"
        "- Os identificadores exibidos (`Cliente-`, `Campanha-`, `AdSet-`, "
        "`Anuncio-`) são pseudônimos gerados **fora** desta camada.\n"
        "- Métricas e datas são reais e intactas: a pseudonimização troca "
        "identidade, nunca número.\n"
        "- O painel não acessa o Data Warehouse nem as APIs de anúncios; a "
        "única entrada é um arquivo que satisfaz o contrato de exposição.\n"
        "- Coluna terminada em `_nk`, `_sk`, `_external_id` ou `_nome` faz o "
        "arquivo inteiro ser recusado."
    )

    ui.secao(
        "Métricas por origem",
        '"— Não disponível" = a origem não fornece a métrica neste nível. '
        "Zero nunca é usado como sinônimo de indisponibilidade.",
    )
    ui.tabela([
        {
            "Métrica": definicao.rotulo,
            "Coluna": definicao.chave,
            # Rotulo curto: a coluna e estreita e o texto longo era cortado
            # pela tabela. O significado esta no apoio da secao.
            "Meta Ads": "✓ Disponível"
            if m.suportada(definicao.chave, "Meta Ads")
            else "— Não disponível",
            "Google Ads": "✓ Disponível"
            if m.suportada(definicao.chave, "Google Ads")
            else "— Não disponível",
            "Somável entre plataformas": (
                "✓ Sim" if definicao.comparavel_entre_plataformas else "— Não"
            ),
        }
        for definicao in m.CATALOGO.values()
    ])

    with st.expander("Indicadores derivados e manifesto do artefato"):
        ui.tabela([
            {"Indicador": definicao.rotulo, "Fórmula": definicao.descricao}
            for definicao in m.DERIVADAS.values()
        ])
        if manifesto:
            itens = {
                "Versão do contrato": manifesto.get("versao_contrato"),
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
            texto += (
                f" · atualizado em {_dia_mes(data_geracao)} "
                f"{data_geracao.year}"
            )
        except ValueError:
            # Manifesto antigo ou de terceiro: manter uma representacao curta
            # sem impedir que um dataset valido seja visualizado.
            texto += f" · atualizado em {str(gerado)[:10]}"
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
