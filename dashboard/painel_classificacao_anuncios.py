"""Camada de apresentacao da classificacao de anuncios.

O motor em :mod:`dashboard.classificacao` decide KPI, comparabilidade,
suficiencia, peers, quartis e status. Este modulo apenas recorta os alvos que
a tela mostra e traduz a dataclass aprovada em texto. As primitivas visuais
comuns continuam em :mod:`dashboard.painel_classificacao`, para que campanha
e anuncio usem os mesmos rotulos, icones e formatos sem duplicacao.
"""

from dashboard import classificacao as cl
from dashboard import metricas as m
from dashboard import painel_classificacao as pc

ROTULO_ORIGEM: dict[str, str] = {
    cl.MESMO_GRUPO: "Grupo",
    cl.MESMA_CAMPANHA: "Campanha",
    cl.INDISPONIVEL: m.INDISPONIVEL,
}

# Proporcoes exclusivas da tabela de anuncios. O motivo recebe a maior area;
# identificadores e valores continuam legiveis sem competir com a explicacao.
LARGURA_COLUNA: dict[str, str] = {
    "Anúncio": "medium",
    "Campanha": "medium",
    "Grupo": "medium",
    "Plataforma": "small",
    "Status": "small",
    "KPI": "small",
    "Resultado": "medium",
    "Valor": "small",
    "Referência": "medium",
    "Δ mediana": "small",
    "Motivo": "large",
}

AVISO_RESULT_INCOMPLETO: str = (
    "Parte dos anúncios Meta não pôde ser classificada por Custo por "
    "Resultado porque o período selecionado inclui linhas com e sem cobertura "
    "de Resultado. Isso não representa desempenho ruim."
)

NOTA_SEM_PEERS: str = (
    "Anúncios sem pares suficientes permanecem sem classificação. O modelo "
    "não compara anúncios entre campanhas diferentes."
)

NOTA_ESCOPO: str = (
    "Filtros de campanha e ad set restringem os anúncios exibidos, mas não "
    "removem os pares necessários do grupo ou da campanha."
)

AJUDA: str = (
    "A classificação é relativa e compara anúncios semanticamente "
    "equivalentes.\n\n"
    "- primeiro tenta anúncios do mesmo grupo;\n"
    "- sem três pares elegíveis, tenta anúncios da mesma campanha;\n"
    "- nunca compara anúncios entre campanhas diferentes;\n"
    "- usa quartis e exige investimento, pelo menos três dias e três "
    "resultados ou conversões;\n"
    "- o anúncio avaliado é excluído do próprio grupo de referência. Por "
    "isso, anúncios do mesmo grupo podem apresentar medianas ligeiramente "
    "diferentes;\n"
    "- **Dados insuficientes** e **Não comparável** não significam desempenho "
    "ruim;\n"
    "- não usa tendência no nível de anúncio.\n\n"
    "Anúncios exigem pelo menos três pares comparáveis no mesmo grupo ou "
    "campanha, além de evidência mínima de desempenho. Por isso, a cobertura "
    "pode ser menor que na classificação de campanhas."
)


def filtrar_alvos(
    classificacoes: list[cl.ClassificacaoAnuncio],
    *,
    campanhas: tuple[str, ...] = (),
    adsets: tuple[str, ...] = (),
    anuncios: tuple[str, ...] = (),
) -> list[cl.ClassificacaoAnuncio]:
    """Restringe apenas a saida, depois que os benchmarks foram calculados.

    Args:
        classificacoes: Saida do motor sobre a conta inteira.
        campanhas: Campanhas que devem permanecer visiveis.
        adsets: Grupos que devem permanecer visiveis.
        anuncios: Anuncios que devem permanecer visiveis.

    Returns:
        Subconjunto dos alvos, preservando cada benchmark ja calculado.
    """
    return [
        item
        for item in classificacoes
        if (not campanhas or item.campanha_id in campanhas)
        and (not adsets or item.adset_id in adsets)
        and (not anuncios or item.anuncio_id in anuncios)
    ]


def tipo_de_resultado(item: cl.ClassificacaoAnuncio) -> str:
    """Traduz o indicador factual usando o mapa canonico das campanhas."""
    return pc.rotulo_tipo_resultado(item.result_type)


def formatar_referencia(item: cl.ClassificacaoAnuncio) -> str:
    """Descreve mediana, origem local e quantidade de outros anuncios."""
    if item.benchmark_origem == cl.INDISPONIVEL or item.benchmark_mediana is None:
        return m.INDISPONIVEL
    return (
        f"{m.formatar(item.benchmark_mediana, m.MOEDA)} · "
        f"{ROTULO_ORIGEM[item.benchmark_origem]} · N={item.benchmark_n}"
    )


def ordenar(
    classificacoes: list[cl.ClassificacaoAnuncio],
) -> list[cl.ClassificacaoAnuncio]:
    """Ordena por prioridade operacional e depois pela hierarquia publica."""
    posicao = {status: indice for indice, status in enumerate(pc.ORDEM_STATUS)}
    return sorted(
        classificacoes,
        key=lambda item: (
            posicao[item.status],
            item.campanha_id,
            item.adset_id,
            item.anuncio_id,
        ),
    )


def colunas_da_tabela(
    classificacoes: list[cl.ClassificacaoAnuncio],
) -> tuple[str, ...]:
    """Seleciona contexto util sem criar colunas inteiras de repeticao."""
    colunas = ["Anúncio"]
    if len({item.campanha_id for item in classificacoes}) > 1:
        colunas.append("Campanha")
    if len({item.adset_id for item in classificacoes}) > 1:
        colunas.append("Grupo")
    if len({item.plataforma for item in classificacoes}) > 1:
        colunas.append("Plataforma")
    colunas += ["Status", "KPI"]
    if any(tipo_de_resultado(item) for item in classificacoes):
        colunas.append("Resultado")
    colunas += [
        "Valor",
        "Referência",
        "Δ mediana",
        "Motivo",
    ]
    return tuple(colunas)


def linhas_tabela(
    classificacoes: list[cl.ClassificacaoAnuncio],
) -> list[dict]:
    """Monta linhas formatadas sem recalcular qualquer regra do motor."""
    colunas = colunas_da_tabela(classificacoes)
    linhas = []
    for item in ordenar(classificacoes):
        completa = {
            "Anúncio": item.anuncio_id,
            "Campanha": item.campanha_id,
            "Grupo": item.adset_id,
            "Plataforma": item.plataforma,
            "Status": pc.formatar_status(item.status),
            "KPI": pc.ROTULO_KPI.get(item.kpi_tipo, m.INDISPONIVEL),
            "Resultado": tipo_de_resultado(item) or m.INDISPONIVEL,
            "Valor": m.formatar(item.kpi_valor, m.MOEDA),
            "Referência": formatar_referencia(item),
            "Δ mediana": pc.formatar_diferenca(
                item.diferenca_mediana_pct
            ),
            "Motivo": item.motivo,
        }
        linhas.append({coluna: completa[coluna] for coluna in colunas})
    return linhas


def tem_motivo(
    classificacoes: list[cl.ClassificacaoAnuncio], motivo_codigo: str
) -> bool:
    """Detecta um estado explicativo pelo codigo estruturado do motor."""
    return any(item.motivo_codigo == motivo_codigo for item in classificacoes)
