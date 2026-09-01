"""Camada de apresentacao da classificacao de campanhas.

Fronteira
---------
Este modulo traduz `ClassificacaoCampanha` em texto de tela. Ele **nao** decide
status, nao calcula quartil, nao monta grupo de comparacao e nao recalcula
tendencia: tudo isso e `dashboard.classificacao`, que e a autoridade. Aqui so
existe rotulo, ordenacao e formatacao — funcoes puras, sem Streamlit, para que
o comportamento visivel possa ser testado sem renderizar nada.

Ordem por acao, nao por qualidade
---------------------------------
A tabela abre por `RUIM` e `ATENCAO`. O usuario nao entra no painel para se
parabenizar: ele entra para descobrir onde precisa mexer. `EXCELENTE` e `BOA`
vem em seguida, e os dois estados sem medicao ficam por ultimo — presentes,
porque esconde-los transformaria "nao sabemos" em "nao existe".

Cor nunca e a unica informacao
------------------------------
Todo status tem texto. O icone e apoio: acompanha o rotulo, nunca o substitui.
E `NAO_COMPARAVEL` nao recebe vermelho — nao e desempenho ruim, e ausencia de
base de comparacao semantica.
"""

from decimal import Decimal

from dashboard import classificacao as cl
from dashboard import metricas as m

ROTULO_STATUS: dict[str, str] = {
    cl.EXCELENTE: "Excelente",
    cl.BOA: "Boa",
    cl.ATENCAO: "Atenção",
    cl.RUIM: "Ruim",
    cl.DADOS_INSUFICIENTES: "Dados insuficientes",
    cl.NAO_COMPARAVEL: "Não comparável",
}

# Vermelho so em `RUIM`. Os dois ultimos sao neutros de proposito — e claros:
# o painel roda em tema escuro, onde um icone preto some contra o fundo e
# transforma "sem base de comparacao" em "linha apagada".
ICONE_STATUS: dict[str, str] = {
    cl.EXCELENTE: "⭐",
    cl.BOA: "🟢",
    cl.ATENCAO: "🟡",
    cl.RUIM: "🔴",
    cl.DADOS_INSUFICIENTES: "⚪",
    cl.NAO_COMPARAVEL: "⬜",
}

# Problema primeiro. Dentro do mesmo status, o desempate e o identificador
# publico, que e estavel entre execucoes.
ORDEM_STATUS: tuple[str, ...] = (
    cl.RUIM,
    cl.ATENCAO,
    cl.EXCELENTE,
    cl.BOA,
    cl.DADOS_INSUFICIENTES,
    cl.NAO_COMPARAVEL,
)

ROTULO_KPI: dict[str, str] = {
    cl.CPR: "Custo por resultado",
    cl.CPL: "Custo por lead",
    cl.CPA: "Custo por conversão",
}

SIGLA_KPI: dict[str, str] = {cl.CPR: "CPR", cl.CPL: "CPL", cl.CPA: "CPA"}

ROTULO_ORIGEM: dict[str, str] = {
    cl.MESMO_CLIENTE: "Mesmo cliente",
    cl.MESMO_TIPO_PORTFOLIO: "Mesmo tipo no portfólio",
    cl.INDISPONIVEL: m.INDISPONIVEL,
}

ROTULO_TENDENCIA: dict[str | None, str] = {
    cl.MELHORANDO: "Melhorando",
    cl.ESTAVEL: "Estável",
    cl.PIORANDO: "Piorando",
    None: m.INDISPONIVEL,
}

AVISO_RESULT_INCOMPLETO: str = (
    "Parte das campanhas Meta não pôde ser classificada por Custo por "
    "Resultado porque o período selecionado inclui linhas com e sem cobertura "
    "de Resultado. Isso não representa desempenho ruim: significa que não há "
    "contrato de Resultado completo para todo o período selecionado."
)

AVISO_GOOGLE_SEM_PARES: str = (
    "Campanhas do Google sem pares suficientes permanecem sem classificação: "
    "o modelo não usa benchmark entre clientes para o Google."
)

AVISO_PERIODO_CURTO: str = (
    "Períodos curtos podem resultar em mais campanhas classificadas como "
    "Dados insuficientes."
)

NOTA_ESCOPO: str = (
    "A classificação considera todas as campanhas da conta no período — "
    "filtros de campanha, ad set e anúncio não alteram o grupo de comparação."
)

AJUDA: str = (
    "A classificação é relativa, não absoluta.\n\n"
    "- compara cada campanha com campanhas de KPI semanticamente equivalente;\n"
    "- usa os quartis do grupo de comparação do período;\n"
    "- a campanha avaliada é excluída do próprio grupo de referência. Por "
    "isso, campanhas do mesmo grupo podem apresentar medianas ligeiramente "
    "diferentes;\n"
    "- **Dados insuficientes** e **Não comparável** não significam desempenho "
    "ruim: significam que não há evidência ou base de comparação."
)

AJUDA_DIFERENCA: str = (
    "Valores negativos indicam custo abaixo da mediana de referência."
)


def rotulo_tipo_resultado(tipo: str | None) -> str:
    """Traduz um `result_type` tecnico para o nome de tela.

    Indicador novo na fonte nao pode derrubar a renderizacao nem virar `--`:
    ele aparece identificado, com o valor tecnico a vista, e a classificacao
    continua valendo — o motor compara pelo tipo, nao pelo nome bonito.

    Args:
        tipo: Indicador tecnico, ou ``None``.

    Returns:
        Rotulo amigavel, o texto de fallback, ou vazio quando nao ha tipo.
    """
    if not tipo:
        return ""
    rotulo = m.ROTULOS_RESULTADO.get(tipo)
    if rotulo:
        return rotulo
    return f"Resultado não rotulado ({tipo})"


def tipo_de_resultado(item: cl.ClassificacaoCampanha) -> str:
    """Extrai o tipo de Resultado do eixo, quando o KPI for CPR.

    Args:
        item: Classificacao de uma campanha.

    Returns:
        Rotulo do tipo, ou vazio quando o eixo nao carrega tipo.
    """
    eixo = item.eixo_comparacao
    if not eixo or eixo[0] != cl.EIXO_META_RESULT:
        return ""
    return rotulo_tipo_resultado(eixo[1])


def formatar_status(status: str) -> str:
    """Monta o texto do status com o icone de apoio."""
    return f"{ICONE_STATUS[status]} {ROTULO_STATUS[status]}"


def formatar_diferenca(valor: Decimal | None) -> str:
    """Formata a diferenca contra a mediana preservando o sinal do motor.

    Custo menor que a referencia produz numero negativo, e ele continua
    negativo na tela. Inverter o sinal para "parecer positivo" trocaria a
    leitura de um valor medido por uma opiniao sobre ele.

    Args:
        valor: Fracao devolvida pelo motor, ou ``None``.

    Returns:
        Texto como ``-18%``, ``+32%`` ou `--`.
    """
    if valor is None:
        return m.INDISPONIVEL
    percentual = valor * 100
    sinal = "+" if percentual > 0 else ""
    return f"{sinal}{m.formatar(percentual, m.PERCENTUAL, casas=0)}"


def formatar_referencia(item: cl.ClassificacaoCampanha) -> str:
    """Descreve a referencia usada: mediana, origem e tamanho do grupo.

    Args:
        item: Classificacao de uma campanha.

    Returns:
        Texto como ``R$ 18,40 · Mesmo cliente · N=4``, ou `--` quando nao
        houve benchmark. Nenhuma mediana e fabricada.
    """
    if item.benchmark_origem == cl.INDISPONIVEL or item.benchmark_mediana is None:
        return m.INDISPONIVEL
    return (
        f"{m.formatar(item.benchmark_mediana, m.MOEDA)} · "
        f"{ROTULO_ORIGEM[item.benchmark_origem]} · N={item.benchmark_n}"
    )


def ordenar(
    classificacoes: list[cl.ClassificacaoCampanha],
) -> list[cl.ClassificacaoCampanha]:
    """Ordena por urgencia de acao e, dentro do status, por identificador."""
    posicao = {status: indice for indice, status in enumerate(ORDEM_STATUS)}
    return sorted(
        classificacoes,
        key=lambda item: (posicao[item.status], item.plataforma, item.campanha_id),
    )


def colunas_da_tabela(
    classificacoes: list[cl.ClassificacaoCampanha],
) -> tuple[str, ...]:
    """Decide quais colunas a tabela precisa mostrar para este recorte.

    Coluna que repete informacao ou que nao carrega informacao nenhuma custa
    largura, e largura gasta empurra o motivo para fora da tela — que e
    justamente a coluna que sustenta a explicabilidade. Por isso:

    - **Benchmark nao existe como coluna.** A origem ja aparece dentro de
      `Referência`, junto da mediana e do N. O dado continua no modelo
      (`benchmark_origem`), so nao e desenhado duas vezes.
    - **Plataforma so aparece quando ha mais de uma.** Numa conta que so tem
      Meta, a coluna repete o mesmo texto em todas as linhas.
    - **Tendência so aparece quando alguma campanha tem tendencia.** O gate de
      volume continua o mesmo: a coluna some porque estaria inteira em `--`,
      nao porque o criterio afrouxou.
    - **Tipo de resultado so aparece quando alguma campanha tem tipo.** Numa
      conta so do Google a coluna ficaria inteira em `--`, porque a fonte nao
      declara Resultado ali. Basta uma campanha com tipo para a coluna voltar:
      ela e o que explica contra qual referencia aquela linha foi medida, e as
      demais linhas mostram `--` normalmente.

    Args:
        classificacoes: Classificacoes exibidas.

    Returns:
        Nomes das colunas, na ordem de leitura.
    """
    colunas = ["Campanha"]
    if len({item.plataforma for item in classificacoes}) > 1:
        colunas.append("Plataforma")
    colunas += ["Status", "KPI"]
    if any(tipo_de_resultado(item) for item in classificacoes):
        colunas.append("Tipo de resultado")
    colunas += ["Valor", "Referência", "Diferença vs. mediana"]
    if any(item.tendencia is not None for item in classificacoes):
        colunas.append("Tendência")
    colunas.append("Motivo")
    return tuple(colunas)


def linhas_tabela(
    classificacoes: list[cl.ClassificacaoCampanha],
) -> list[dict]:
    """Monta as linhas da tabela de classificacao, ja em texto.

    Args:
        classificacoes: Classificacoes da conta selecionada.

    Returns:
        Lista de dicionarios prontos para a tabela, na ordem de acao e com as
        colunas que este recorte realmente precisa.
    """
    colunas = colunas_da_tabela(classificacoes)
    linhas = []
    for item in ordenar(classificacoes):
        completa = {
            "Campanha": item.campanha_id,
            "Plataforma": item.plataforma,
            "Status": formatar_status(item.status),
            "KPI": ROTULO_KPI.get(item.kpi_tipo, m.INDISPONIVEL),
            "Tipo de resultado": tipo_de_resultado(item) or m.INDISPONIVEL,
            "Valor": m.formatar(item.kpi_valor, m.MOEDA),
            "Referência": formatar_referencia(item),
            "Diferença vs. mediana": formatar_diferenca(
                item.diferenca_mediana_pct
            ),
            "Tendência": ROTULO_TENDENCIA[item.tendencia],
            "Motivo": item.motivo,
        }
        linhas.append({coluna: completa[coluna] for coluna in colunas})
    return linhas


def cartoes_resumo(resumo: dict) -> tuple[list[dict], list[dict]]:
    """Divide a contagem por status em foco operacional e contexto.

    Nao existe nota, media nem indice de saude: a unica sintese oferecida e
    quantas campanhas caíram em cada estado. Um numero unico esconderia a
    diferenca entre uma carteira com problemas e uma carteira sem evidencia.

    Args:
        resumo: Saida de `classificacao.resumir_classificacoes`.

    Returns:
        Dois grupos de cartoes: os quatro estados de desempenho e os dois
        estados sem medicao.
    """
    def cartao(status: str) -> dict:
        return {
            "rotulo": f"{ICONE_STATUS[status]} {ROTULO_STATUS[status]}",
            "valor": m.formatar(resumo["por_status"][status], m.INTEIRO),
        }

    desempenho = [cartao(status) for status in cl.STATUS_DE_DESEMPENHO]
    contexto = [
        cartao(cl.DADOS_INSUFICIENTES),
        cartao(cl.NAO_COMPARAVEL),
    ]
    return desempenho, contexto


def tem_result_incompleto(
    classificacoes: list[cl.ClassificacaoCampanha],
) -> bool:
    """Diz se alguma campanha caiu na cobertura parcial de Resultado.

    A deteccao usa `motivo_codigo`, nunca o texto de `motivo`: interpretar a
    frase transformaria a redacao de uma mensagem em contrato de dados.
    """
    return any(
        item.motivo_codigo == cl.MOTIVO_RESULT_INCOMPLETO
        for item in classificacoes
    )


def tem_google_sem_pares(
    classificacoes: list[cl.ClassificacaoCampanha],
) -> bool:
    """Diz se ha campanha Google sem grupo de comparacao na propria conta."""
    return any(
        item.plataforma == m.GOOGLE and item.motivo_codigo == cl.MOTIVO_SEM_PEERS
        for item in classificacoes
    )
