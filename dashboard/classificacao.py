"""Motores de classificacao relativa de campanhas e anuncios.

O que este modulo faz
---------------------
Recebe as linhas factuais de um periodo, agrega por campanha ou por anuncio e
devolve um status explicavel: `EXCELENTE`, `BOA`, `ATENCAO`, `RUIM`,
`DADOS_INSUFICIENTES` ou `NAO_COMPARAVEL`. Nao desenha nada. Nao le arquivo,
nao abre conexao, nao importa Streamlit e nao conhece o estado global do
painel: recebe listas de `LinhaDataset` e devolve dataclasses.

O que a classificacao afirma — e o que ela nao afirma
-----------------------------------------------------
Ela e **relativa**. Nao existe limiar absoluto de mercado aqui: nenhum
"CPL abaixo de R$ 20 e bom". O status diz apenas a posicao da campanha dentro
de um grupo de campanhas semanticamente comparaveis, medida por quartis da
distribuicao observada naquele periodo. Trocar a carteira de clientes muda os
quartis, e isso e a propriedade desejada — a referencia e o portfolio real,
nao um numero herdado de blog de marketing.

No nivel de anuncio, a referencia e deliberadamente mais local: primeiro os
outros anuncios do mesmo ad set/grupo e, se forem insuficientes, os da mesma
campanha. O benchmark nunca atravessa campanha. Essa hierarquia, o gate de
tres dias/tres resultados e a ausencia de tendencia vieram do estudo empirico
especifico de anuncios; nao sao uma copia presumida do contrato de campanhas.

Por que nao existe score
------------------------
Um `score = CPL * 0,5 + CTR * 0,2 + ...` exigiria pesos, e nenhum peso
testado no estudo empirico tinha origem no dado. A regra e por etapas, e cada
etapa produz um motivo legivel. Um numero unico esconderia justamente a parte
que interessa ao operador: por que a campanha caiu naquele status.

De onde vem cada parametro
--------------------------
Todos os cortes vieram do estudo exploratorio sobre a superficie real
(janela continua de 30 dias, 173 campanhas ativas em 57 contas), nao de
convencao:

- **3 pares no mesmo cliente / 5 pares no portfolio.** Exigir 5/8 nao mudou a
  cobertura nem o numero de contas atendidas — so trocava referencia boa por
  referencia generica. O limite util e 3.
- **Denominador minimo 3.** Com `>= 10` a cobertura cai de 64% para 50% e sete
  contas perdem qualquer classificacao; com `>= 1` passam a receber status
  campanhas de uma unica conversao, que e ruido.
- **Multiplicador 2x no gasto sem resultado.** Entre 1x e 3x o resultado muda
  em uma campanha; 2x foi escolhido por ser o mais defensavel de enunciar.
- **Zona estavel de 15% na tendencia.** Com denominador alto (Result do Meta,
  mediana de 227 resultados) a variacao semanal mediana e 9,5%; com
  denominador baixo (Google, mediana de 7,7 conversoes) ela e 50%. Dai o gate
  de 10 no denominador dos dois periodos: sem ele, tendencia seria ruido
  formatado como sinal.

O eixo separa mais que o cliente
--------------------------------
Medido: dentro do mesmo `result_type`, campanhas de clientes diferentes
variam pouco (razao entre o maximo e a mediana de 2,2x a 5,2x). Misturando
tipos DENTRO do mesmo cliente, a dispersao explode (medianas por conta
separadas por 106x, IQR/mediana de 27). Por isso o benchmark de nivel 2 do
Meta atravessa clientes mantendo o `result_type` — e por isso nada aqui
compara campanhas de eixos diferentes, nem para "aumentar N".

Google e conservador de proposito
---------------------------------
Nem a superficie nem o Data Warehouse tem eixo semantico para o Google:
`objective` e `optimization_goal` sao nulos em 100% das linhas Google. Sem
eixo, atravessar clientes seria comparar uma campanha de marca com uma de
performance so porque as duas chamam `conversions` de conversao. Google fica
restrito ao nivel 1 (mesma conta) e, sem pares, devolve
`DADOS_INSUFICIENTES`.

Metricas que nao decidem status
-------------------------------
`reach` nao aparece neste modulo: e nao aditiva, e somar linhas conta a mesma
pessoa varias vezes. CTR e CPC tambem nao decidem: o quartil de CTR discorda
do quartil de custo em 73% das campanhas Google e 77% das campanhas Meta com
Lead. ROAS nao decide: o `conversion_value` do Google tem mediana de ROAS de
0,015 — o campo nao representa receita — e o Meta tem uma unica campanha com
`purchase_value` positivo no periodo inteiro.
"""

from dataclasses import dataclass
from decimal import Decimal

from dashboard import metricas as m
from dashboard.contratos import LinhaDataset

# ── Status ───────────────────────────────────────────────────
# Constantes em vez de string solta: o rotulo visual sera decidido na camada
# de UI, e o motor nao deve ser a origem de texto de tela.
EXCELENTE: str = "excelente"
BOA: str = "boa"
ATENCAO: str = "atencao"
RUIM: str = "ruim"
DADOS_INSUFICIENTES: str = "dados_insuficientes"
NAO_COMPARAVEL: str = "nao_comparavel"

STATUS: tuple[str, ...] = (
    EXCELENTE,
    BOA,
    ATENCAO,
    RUIM,
    DADOS_INSUFICIENTES,
    NAO_COMPARAVEL,
)

# Status que representam posicao medida. Os outros dois dizem que a medicao
# nao aconteceu — e a diferenca entre eles importa: `DADOS_INSUFICIENTES` e
# falta de evidencia (pode virar status com mais dias ou mais volume);
# `NAO_COMPARAVEL` e limite semantico do dado (nao melhora com o tempo).
STATUS_DE_DESEMPENHO: tuple[str, ...] = (EXCELENTE, BOA, ATENCAO, RUIM)

# ── Motivos ──────────────────────────────────────────────────
# Cada codigo corresponde a UM ramo da regra. Eles existem para que a camada
# de apresentacao possa contar, agrupar e escolher texto sem interpretar a
# frase de `motivo` — string parsing na UI transformaria a redacao de uma
# mensagem em contrato de dados.
MOTIVO_RESULT_INCOMPLETO: str = "result_incompleto"
MOTIVO_MULTIPLOS_RESULT_TYPES: str = "multiplos_result_types"
MOTIVO_JANELA_INCOMPATIVEL: str = "janela_incompativel"
MOTIVO_SEM_KPI_META: str = "sem_kpi_meta"
MOTIVO_SPEND_ZERO: str = "spend_zero"
MOTIVO_POUCOS_DIAS: str = "poucos_dias"
MOTIVO_DENOMINADOR_BAIXO: str = "denominador_baixo"
MOTIVO_SEM_PEERS: str = "sem_peers"
MOTIVO_ZERO_RESULT_SEM_REFERENCIA: str = "zero_result_sem_referencia"
MOTIVO_ZERO_RESULT_GASTO_BAIXO: str = "zero_result_gasto_baixo"
MOTIVO_ZERO_RESULT_GASTO_RELEVANTE: str = "zero_result_gasto_relevante"
MOTIVO_ZERO_RESULT_GASTO_ALTO: str = "zero_result_gasto_alto"
MOTIVO_QUARTIL: str = "quartil"

MOTIVOS: tuple[str, ...] = (
    MOTIVO_RESULT_INCOMPLETO,
    MOTIVO_MULTIPLOS_RESULT_TYPES,
    MOTIVO_JANELA_INCOMPATIVEL,
    MOTIVO_SEM_KPI_META,
    MOTIVO_SPEND_ZERO,
    MOTIVO_POUCOS_DIAS,
    MOTIVO_DENOMINADOR_BAIXO,
    MOTIVO_SEM_PEERS,
    MOTIVO_ZERO_RESULT_SEM_REFERENCIA,
    MOTIVO_ZERO_RESULT_GASTO_BAIXO,
    MOTIVO_ZERO_RESULT_GASTO_RELEVANTE,
    MOTIVO_ZERO_RESULT_GASTO_ALTO,
    MOTIVO_QUARTIL,
)

# ── Origem do benchmark ──────────────────────────────────────
MESMO_CLIENTE: str = "mesmo_cliente"
MESMO_TIPO_PORTFOLIO: str = "mesmo_tipo_portfolio"
MESMO_GRUPO: str = "mesmo_grupo"
MESMA_CAMPANHA: str = "mesma_campanha"
INDISPONIVEL: str = "indisponivel"

# ── KPI primario ─────────────────────────────────────────────
# Todos sao custo por unidade de resultado, e em todos MENOR E MELHOR. A
# uniformidade nao e coincidencia: e o que permite uma unica regra de quartil.
CPR: str = "cpr"
CPL: str = "cpl"
CPA: str = "cpa"

# ── Tendencia ────────────────────────────────────────────────
MELHORANDO: str = "melhorando"
ESTAVEL: str = "estavel"
PIORANDO: str = "piorando"

# ── Eixos de comparabilidade ─────────────────────────────────
# O eixo e a chave que define quem pode ser comparado com quem. Campanhas de
# eixos diferentes nunca entram no mesmo benchmark.
EIXO_META_RESULT: str = "meta_result"
EIXO_META_LEAD: str = "meta_lead"
EIXO_GOOGLE: str = "google_conversion"

# ── Parametros empiricos ─────────────────────────────────────
MIN_PARES_CLIENTE: int = 3
MIN_PARES_PORTFOLIO: int = 5
MIN_PARES_ANUNCIO: int = 3
MIN_DIAS_ATIVOS: int = 3
MIN_DENOMINADOR: Decimal = Decimal(3)
GASTO_SEM_RESULTADO_ATENCAO: Decimal = Decimal("0.5")
GASTO_SEM_RESULTADO_RUIM: Decimal = Decimal(2)
MIN_DENOMINADOR_TENDENCIA: Decimal = Decimal(10)
ZONA_ESTAVEL: Decimal = Decimal("0.15")
DIAS_PERIODO_CURTO: int = 7


@dataclass(frozen=True)
class ClassificacaoCampanha:
    """Resultado da classificacao de uma campanha em um periodo.

    Carrega apenas identificadores publicos da superficie de exposicao. Nome
    real, `external_id`, chave interna, `objective` e `optimization_goal` nao
    entram aqui — nem como campo, nem embutidos no motivo.

    Attributes:
        plataforma: `Meta Ads` ou `Google Ads`.
        conta_id: Pseudonimo da conta.
        campanha_id: Pseudonimo da campanha.
        status: Um dos valores de `STATUS`.
        motivo_codigo: Um dos valores de `MOTIVOS`. E o campo que a UI deve
            ler para contar, agrupar ou decidir mensagem; `motivo` e texto e
            pode ser reescrito sem aviso.
        motivo: Texto determinista explicando o status. Sem nome de entidade.
        eixo_comparacao: Chave semantica do grupo de comparacao, ou ``None``
            quando a campanha nao chegou a ter eixo definido.
        kpi_tipo: `CPR`, `CPL`, `CPA` ou ``None``.
        kpi_valor: Custo por unidade de resultado, ou ``None`` quando o
            denominador nao permite calcular.
        benchmark_origem: `MESMO_CLIENTE`, `MESMO_TIPO_PORTFOLIO` ou
            `INDISPONIVEL`.
        benchmark_n: Quantidade de pares efetivamente usados. Zero quando nao
            houve benchmark.
        benchmark_p25: Primeiro quartil dos pares, ou ``None``.
        benchmark_mediana: Mediana dos pares, ou ``None``.
        benchmark_p75: Terceiro quartil dos pares, ou ``None``.
        diferenca_mediana_pct: `(kpi - mediana) / mediana`. Negativo significa
            custo menor que a referencia, ou seja, melhor. O sinal nao e
            invertido para "parecer positivo": a inversao, se desejada, e
            decisao de apresentacao.
        dias_ativos: Dias distintos com observacao no periodo.
        denominador: Resultados, Leads ou conversoes somados no periodo.
        spend: Investimento no periodo.
        tendencia: `MELHORANDO`, `ESTAVEL`, `PIORANDO` ou ``None``. Nunca
            altera `status`.
        periodo_curto: ``True`` quando o periodo analisado tem menos de
            `DIAS_PERIODO_CURTO` dias distintos. Metadado para a UI avisar;
            o motor classifica normalmente.
    """

    plataforma: str
    conta_id: str
    campanha_id: str
    status: str
    motivo_codigo: str
    motivo: str
    eixo_comparacao: tuple | None
    kpi_tipo: str | None
    kpi_valor: Decimal | None
    benchmark_origem: str
    benchmark_n: int
    benchmark_p25: Decimal | None
    benchmark_mediana: Decimal | None
    benchmark_p75: Decimal | None
    diferenca_mediana_pct: Decimal | None
    dias_ativos: int
    denominador: Decimal | None
    spend: Decimal
    tendencia: str | None
    periodo_curto: bool


@dataclass(frozen=True)
class ClassificacaoAnuncio:
    """Resultado da classificacao relativa de um anuncio no periodo.

    Diferentemente da campanha, o anuncio nao carrega tendencia: o estudo
    empirico mostrou cobertura insuficiente e variacao excessiva nesse grao.
    Os filtros de conta, campanha e ad set limitam apenas quais instancias
    desta estrutura saem da funcao; o benchmark e sempre montado antes, sobre
    todo o universo recebido.
    """

    plataforma: str
    conta_id: str
    campanha_id: str
    adset_id: str
    anuncio_id: str
    status: str
    motivo_codigo: str
    motivo: str
    eixo_comparacao: tuple | None
    kpi_tipo: str | None
    kpi_valor: Decimal | None
    result_type: str | None
    benchmark_origem: str
    benchmark_n: int
    benchmark_p25: Decimal | None
    benchmark_mediana: Decimal | None
    benchmark_p75: Decimal | None
    diferenca_mediana_pct: Decimal | None
    dias_ativos: int
    denominador: Decimal | None
    spend: Decimal


@dataclass(frozen=True)
class _SemanticaKpi:
    """Eixo e KPI factual de uma unidade, antes da hierarquia do benchmark."""

    spend: Decimal
    dias_ativos: int
    eixo: tuple | None
    kpi_tipo: str | None
    kpi_valor: Decimal | None
    denominador: Decimal | None
    bloqueio: tuple[str, str, str] | None


@dataclass(frozen=True)
class _Agregado:
    """Estado intermediario de uma campanha, antes de virar status.

    Existe para que a avaliacao semantica (que decide o eixo e o KPI) fique
    separada da decisao de status (que depende dos pares). O universo inteiro
    e avaliado uma vez, e so entao cada campanha alvo e classificada — sem
    isso, o benchmark teria de reavaliar a semantica de cada par.
    """

    plataforma: str
    conta_id: str
    campanha_id: str
    spend: Decimal
    dias_ativos: int
    eixo: tuple | None
    kpi_tipo: str | None
    kpi_valor: Decimal | None
    denominador: Decimal | None
    bloqueio: tuple[str, str, str] | None


@dataclass(frozen=True)
class _AgregadoAnuncio:
    """Estado intermediario de um anuncio, antes da classificacao relativa."""

    plataforma: str
    conta_id: str
    campanha_id: str
    adset_id: str
    anuncio_id: str
    spend: Decimal
    dias_ativos: int
    eixo: tuple | None
    kpi_tipo: str | None
    kpi_valor: Decimal | None
    denominador: Decimal | None
    bloqueio: tuple[str, str, str] | None


def percentil(valores: list[Decimal], posicao: int) -> Decimal | None:
    """Percentil por interpolacao linear entre as duas observacoes vizinhas.

    O metodo e o mesmo do `numpy` com `method="linear"`, escrito aqui em
    `Decimal` porque a imagem do painel nao tem `numpy` nem `pandas` — a
    camada de dados do dashboard e stdlib pura de proposito. A lista de
    entrada e ordenada internamente, entao o resultado nao depende da ordem
    em que as campanhas chegaram.

    Args:
        valores: Valores do grupo de comparacao.
        posicao: Percentil desejado, de 0 a 100.

    Returns:
        O percentil, ou ``None`` quando a lista esta vazia.
    """
    if not valores:
        return None
    ordenados = sorted(valores)
    if len(ordenados) == 1:
        return ordenados[0]
    indice = (Decimal(len(ordenados) - 1) * Decimal(posicao)) / Decimal(100)
    inferior = int(indice)
    superior = min(inferior + 1, len(ordenados) - 1)
    fracao = indice - inferior
    return ordenados[inferior] + (ordenados[superior] - ordenados[inferior]) * fracao


def _dias_ativos(linhas: list[LinhaDataset]) -> int:
    """Conta dias distintos com observacao."""
    return len({linha["data"] for linha in linhas})


def _agrupar_por_campanha(
    linhas: list[LinhaDataset],
) -> dict[tuple[str, str, str], list[LinhaDataset]]:
    """Agrupa linhas na unidade classificada: plataforma x conta x campanha.

    A conta entra na chave porque o pseudonimo de campanha e derivado da
    cadeia hierarquica; incluir a conta mantem a chave legivel e evita que uma
    eventual colisao entre carteiras vire uma campanha unica.
    """
    grupos: dict[tuple[str, str, str], list[LinhaDataset]] = {}
    for linha in linhas:
        chave = (linha["plataforma"], linha["conta_id"], linha["campanha_id"])
        grupos.setdefault(chave, []).append(linha)
    return grupos


def _avaliar_semantica(
    plataforma: str, linhas: list[LinhaDataset]
) -> _SemanticaKpi:
    """Decide eixo, KPI e denominador sem conhecer o nivel hierarquico.

    Toda a semantica de Resultado vem de `metricas.resultado_campanha`, que ja
    e a implementacao canonica do painel: recorte misto, mais de um tipo e
    janela incompativel sao decididos la, uma vez so. Este modulo nao
    reimplementa nenhuma dessas regras — ele apenas traduz o veredito em eixo
    e KPI. Campanha e anuncio chamam esta mesma primitiva, mas preservam
    agregacoes, peers, filtros e mensagens hierarquicas proprias.

    Args:
        plataforma: Plataforma unica das linhas agregadas.
        linhas: Linhas factuais de uma unica unidade no periodo.

    Returns:
        Semantica com eixo e KPI, ou com `bloqueio` preenchido.
    """
    spend = sum((linha["spend"] for linha in linhas), Decimal(0))
    dias = _dias_ativos(linhas)

    def base(**extra) -> _SemanticaKpi:
        campos = dict(
            spend=spend,
            dias_ativos=dias,
            eixo=None,
            kpi_tipo=None,
            kpi_valor=None,
            denominador=None,
            bloqueio=None,
        )
        campos.update(extra)
        return _SemanticaKpi(**campos)

    if plataforma == m.GOOGLE:
        conversoes = sum((linha["conversions"] for linha in linhas), Decimal(0))
        return base(
            eixo=(EIXO_GOOGLE,),
            kpi_tipo=CPA,
            kpi_valor=m.dividir(spend, conversoes),
            denominador=conversoes,
        )

    # Meta. O rotulo amigavel nao e exigido: comparar o custo de duas
    # campanhas do mesmo `result_type` tecnico e valido mesmo enquanto o nome
    # de exibicao daquele indicador nao foi decidido.
    resultado = m.resultado_campanha(linhas, exigir_rotulo=False)
    estado = resultado["status_resultado"]

    if estado == m.RESULTADO_PARCIAL:
        return base(
            bloqueio=(
                NAO_COMPARAVEL,
                MOTIVO_RESULT_INCOMPLETO,
                "Dados de Result incompletos no período.",
            )
        )

    if estado == m.RESULTADO_INCOMPATIVEL:
        # O veredito canonico usa o mesmo rotulo para os dois defeitos. A
        # contagem de tipos abaixo NAO redecide nada — ela so escolhe qual das
        # duas frases descreve o que ja foi barrado.
        tipos = {
            linha["result_type"]
            for linha in linhas
            if linha.get("result_type") is not None
        }
        if len(tipos) > 1:
            codigo = MOTIVO_MULTIPLOS_RESULT_TYPES
            motivo = "Múltiplos tipos de Resultado no período."
        else:
            codigo = MOTIVO_JANELA_INCOMPATIVEL
            motivo = "Janelas de atribuição incompatíveis."
        return base(bloqueio=(NAO_COMPARAVEL, codigo, motivo))

    if estado == m.RESULTADO_DISPONIVEL:
        quantidade = resultado["result_count"]
        return base(
            eixo=(
                EIXO_META_RESULT,
                resultado["result_type"],
                resultado["result_attribution_window"],
            ),
            kpi_tipo=CPR,
            kpi_valor=m.dividir(spend, quantidade),
            denominador=quantidade,
        )

    # Sem Resultado utilizavel. O unico KPI primario que a superficie ainda
    # oferece para o Meta e o custo por Lead — e `conversions` do Meta E Lead,
    # nao "conversoes" no sentido generico do Google.
    leads = sum((linha["conversions"] for linha in linhas), Decimal(0))
    if leads > 0:
        return base(
            eixo=(EIXO_META_LEAD,),
            kpi_tipo=CPL,
            kpi_valor=m.dividir(spend, leads),
            denominador=leads,
        )

    # Sem Result e sem Lead nao existe KPI primario definivel pela superficie.
    # Isso NAO e desempenho ruim: e ausencia de contrato observavel. Cair para
    # CTR ou CPC aqui inventaria um criterio que o estudo empirico rejeitou.
    return base(
        bloqueio=(
            NAO_COMPARAVEL,
            MOTIVO_SEM_KPI_META,
            "Sem Result e sem Leads observados no período; não há KPI "
            "primário definível pela superfície v3.",
        )
    )


def _avaliar(chave: tuple[str, str, str], linhas: list[LinhaDataset]) -> _Agregado:
    """Acopla a semantica compartilhada a identidade de uma campanha."""
    plataforma, conta_id, campanha_id = chave
    semantica = _avaliar_semantica(plataforma, linhas)
    return _Agregado(
        plataforma=plataforma,
        conta_id=conta_id,
        campanha_id=campanha_id,
        spend=semantica.spend,
        dias_ativos=semantica.dias_ativos,
        eixo=semantica.eixo,
        kpi_tipo=semantica.kpi_tipo,
        kpi_valor=semantica.kpi_valor,
        denominador=semantica.denominador,
        bloqueio=semantica.bloqueio,
    )


def _tem_evidencia_para_benchmark(
    candidato: _Agregado | _AgregadoAnuncio, *, exigir_spend_positivo: bool
) -> bool:
    """Aplica o gate factual comum, com a politica de spend do nivel."""
    return (
        (not exigir_spend_positivo or candidato.spend > 0)
        and candidato.kpi_valor is not None
        and candidato.denominador is not None
        and candidato.denominador >= MIN_DENOMINADOR
        and candidato.dias_ativos >= MIN_DIAS_ATIVOS
    )


def _e_par_valido(candidato: _Agregado) -> bool:
    """Diz se uma campanha pode servir de referencia para outra.

    Par valido e campanha com o mesmo rigor de evidencia exigido de quem esta
    sendo classificado: KPI calculavel, denominador e dias suficientes. Sem
    isso, a referencia poderia ser construida sobre campanhas de uma unica
    conversao — exatamente o ruido que o gate de suficiencia existe para
    manter fora do status.
    """
    return _tem_evidencia_para_benchmark(
        candidato,
        exigir_spend_positivo=False,
    )


def _pares(
    universo: list[_Agregado], alvo: _Agregado
) -> tuple[list[Decimal], str, int]:
    """Monta o grupo de comparacao da campanha alvo.

    A cascata tem no maximo dois niveis, e a campanha alvo nunca participa do
    proprio benchmark (leave-one-out). Incluir a propria campanha mudaria o
    rotulo de 7% dos casos medidos, e em grupo de 2 a 4 campanhas ela pesaria
    entre 25% e 50% da referencia que a julga.

    Nivel 1 — mesma conta, mesmo eixo, pelo menos `MIN_PARES_CLIENTE` pares.
    Nivel 2 — mesmo eixo em outras contas, pelo menos `MIN_PARES_PORTFOLIO`
    pares. **Nao existe nivel 2 para o Google**: sem eixo semantico, o grupo
    seria "toda campanha Google da carteira", que nao e um grupo comparavel.

    Args:
        universo: Todas as campanhas avaliadas do periodo.
        alvo: Campanha sendo classificada.

    Returns:
        Tupla `(valores, origem, n)`. `valores` vazio e origem `INDISPONIVEL`
        quando nenhum nivel alcancou o minimo.
    """
    if alvo.eixo is None:
        return [], INDISPONIVEL, 0

    candidatos = [
        candidato
        for candidato in universo
        if candidato.eixo == alvo.eixo
        and (candidato.conta_id, candidato.campanha_id)
        != (alvo.conta_id, alvo.campanha_id)
        and _e_par_valido(candidato)
    ]

    mesmo_cliente = [c for c in candidatos if c.conta_id == alvo.conta_id]
    if len(mesmo_cliente) >= MIN_PARES_CLIENTE:
        return (
            [c.kpi_valor for c in mesmo_cliente],
            MESMO_CLIENTE,
            len(mesmo_cliente),
        )

    if alvo.plataforma == m.GOOGLE:
        return [], INDISPONIVEL, 0

    if len(candidatos) >= MIN_PARES_PORTFOLIO:
        return [c.kpi_valor for c in candidatos], MESMO_TIPO_PORTFOLIO, len(candidatos)

    return [], INDISPONIVEL, 0


def _quartil(valor: Decimal, p25: Decimal, p50: Decimal, p75: Decimal) -> str:
    """Traduz posicao em status, para KPI em que menor e melhor.

    As bordas pertencem ao lado melhor: um custo exatamente igual ao primeiro
    quartil e `EXCELENTE`, e um custo igual a mediana e `BOA`. So acima do
    terceiro quartil o status vira `RUIM`.
    """
    if valor <= p25:
        return EXCELENTE
    if valor <= p50:
        return BOA
    if valor <= p75:
        return ATENCAO
    return RUIM


def _texto_pares(origem: str, n: int) -> str:
    """Descreve o grupo de comparacao sem citar entidade alguma."""
    if origem == MESMO_CLIENTE:
        return f"{n} campanhas comparáveis do mesmo cliente"
    return f"{n} campanhas comparáveis do mesmo tipo no portfólio"


def _tendencia(atual: _Agregado, anterior: _Agregado | None) -> str | None:
    """Compara o KPI com o do periodo anterior de mesma duracao.

    Exige denominador alto **nos dois** periodos: com denominador baixo a
    variacao semanal medida foi de 50%, e rotular isso como "piorando" seria
    apresentar ruido como sinal. Tendencia nunca altera o status.

    Args:
        atual: Agregado do periodo selecionado.
        anterior: Agregado da mesma campanha no periodo imediatamente
            anterior, ou ``None``.

    Returns:
        `MELHORANDO`, `ESTAVEL`, `PIORANDO` ou ``None``.
    """
    if anterior is None:
        return None
    if atual.eixo is None or atual.eixo != anterior.eixo:
        return None
    if atual.kpi_valor is None or anterior.kpi_valor is None:
        return None
    if anterior.kpi_valor <= 0:
        return None
    if atual.denominador is None or anterior.denominador is None:
        return None
    if (
        atual.denominador < MIN_DENOMINADOR_TENDENCIA
        or anterior.denominador < MIN_DENOMINADOR_TENDENCIA
    ):
        return None

    variacao = (atual.kpi_valor - anterior.kpi_valor) / anterior.kpi_valor
    if variacao <= -ZONA_ESTAVEL:
        return MELHORANDO
    if variacao >= ZONA_ESTAVEL:
        return PIORANDO
    return ESTAVEL


def _classificar_uma(
    alvo: _Agregado,
    universo: list[_Agregado],
    anterior: _Agregado | None,
    periodo_curto: bool,
) -> ClassificacaoCampanha:
    """Aplica a regra por etapas a uma campanha."""
    valores, origem, n = _pares(universo, alvo)
    p25 = percentil(valores, 25)
    p50 = percentil(valores, 50)
    p75 = percentil(valores, 75)
    tendencia = _tendencia(alvo, anterior)

    def resultado(
        status: str, codigo: str, motivo: str, com_benchmark: bool
    ) -> ClassificacaoCampanha:
        diferenca = None
        if com_benchmark and p50 is not None and p50 > 0 and alvo.kpi_valor is not None:
            diferenca = (alvo.kpi_valor - p50) / p50
        return ClassificacaoCampanha(
            plataforma=alvo.plataforma,
            conta_id=alvo.conta_id,
            campanha_id=alvo.campanha_id,
            status=status,
            motivo_codigo=codigo,
            motivo=motivo,
            eixo_comparacao=alvo.eixo,
            kpi_tipo=alvo.kpi_tipo,
            kpi_valor=alvo.kpi_valor,
            benchmark_origem=origem if com_benchmark else INDISPONIVEL,
            benchmark_n=n if com_benchmark else 0,
            benchmark_p25=p25 if com_benchmark else None,
            benchmark_mediana=p50 if com_benchmark else None,
            benchmark_p75=p75 if com_benchmark else None,
            diferenca_mediana_pct=diferenca,
            dias_ativos=alvo.dias_ativos,
            denominador=alvo.denominador,
            spend=alvo.spend,
            tendencia=tendencia,
            periodo_curto=periodo_curto,
        )

    # 1. Limite semantico. Nao melhora com mais dias, entao vem antes de
    #    qualquer gate de volume.
    if alvo.bloqueio is not None:
        status, codigo, motivo = alvo.bloqueio
        return resultado(status, codigo, motivo, com_benchmark=False)

    # 2. Sem investimento nao existe custo a comparar.
    if alvo.spend <= 0:
        return resultado(
            DADOS_INSUFICIENTES,
            MOTIVO_SPEND_ZERO,
            "Sem investimento no período.",
            com_benchmark=False,
        )

    # 3. Gasto sem resultado. Vem ANTES dos gates de volume de proposito: uma
    #    campanha que gastou varias vezes o custo de referencia sem produzir
    #    nada e informacao, nao ausencia de informacao. O que muda o veredito
    #    aqui e o quanto ela gastou em relacao a referencia, nao ha quantos
    #    dias ela existe.
    if alvo.denominador is not None and alvo.denominador <= 0:
        if origem == INDISPONIVEL or p50 is None or p50 <= 0:
            return resultado(
                DADOS_INSUFICIENTES,
                MOTIVO_ZERO_RESULT_SEM_REFERENCIA,
                "Nenhum resultado observado e sem referência de custo para "
                "avaliar o investimento.",
                com_benchmark=False,
            )
        multiplo = alvo.spend / p50
        if multiplo < GASTO_SEM_RESULTADO_ATENCAO:
            return resultado(
                DADOS_INSUFICIENTES,
                MOTIVO_ZERO_RESULT_GASTO_BAIXO,
                "Investimento ainda baixo frente ao custo de referência e "
                "nenhum resultado observado.",
                com_benchmark=True,
            )
        if multiplo < GASTO_SEM_RESULTADO_RUIM:
            return resultado(
                ATENCAO,
                MOTIVO_ZERO_RESULT_GASTO_RELEVANTE,
                "Investimento relevante sem resultado.",
                com_benchmark=True,
            )
        return resultado(
            RUIM,
            MOTIVO_ZERO_RESULT_GASTO_ALTO,
            f"Investiu {multiplo:.1f}× o custo mediano de referência sem "
            "gerar resultado.",
            com_benchmark=True,
        )

    # 4. Evidencia da propria campanha.
    if alvo.dias_ativos < MIN_DIAS_ATIVOS:
        return resultado(
            DADOS_INSUFICIENTES,
            MOTIVO_POUCOS_DIAS,
            f"Apenas {alvo.dias_ativos} dia(s) com observação no período.",
            com_benchmark=False,
        )
    if alvo.denominador is None or alvo.denominador < MIN_DENOMINADOR:
        quantidade = m.formatar_quantidade_resultado(alvo.denominador)
        return resultado(
            DADOS_INSUFICIENTES,
            MOTIVO_DENOMINADOR_BAIXO,
            f"Apenas {quantidade} resultado(s) no período.",
            com_benchmark=False,
        )

    # 5. Referencia.
    if origem == INDISPONIVEL:
        return resultado(
            DADOS_INSUFICIENTES,
            MOTIVO_SEM_PEERS,
            "Não há campanhas comparáveis suficientes para construir a "
            "referência.",
            com_benchmark=False,
        )

    # 6. Posicao relativa.
    status = _quartil(alvo.kpi_valor, p25, p50, p75)
    faixa = {
        EXCELENTE: "no primeiro quartil",
        BOA: "entre o primeiro quartil e a mediana",
        ATENCAO: "entre a mediana e o terceiro quartil",
        RUIM: "acima do terceiro quartil",
    }[status]
    motivo = f"{alvo.kpi_tipo.upper()} {faixa} entre {_texto_pares(origem, n)}."
    if alvo.kpi_tipo == CPL:
        # O leitor precisa saber que este nao e o KPI preferencial do Meta: o
        # custo por Lead entrou porque a campanha nao tem Resultado utilizavel
        # no periodo, nao porque Lead seja o objetivo declarado dela.
        motivo += " KPI usado: CPL (Result indisponível para a campanha no período)."
    return resultado(status, MOTIVO_QUARTIL, motivo, com_benchmark=True)


def classificar_campanhas(
    linhas_periodo: list[LinhaDataset],
    *,
    conta_id: str | None = None,
    plataforma: str | None = None,
    linhas_periodo_anterior: list[LinhaDataset] | None = None,
) -> list[ClassificacaoCampanha]:
    """Classifica campanhas do periodo, com benchmark montado no proprio periodo.

    A separacao entre alvo e referencia e o ponto central da assinatura:
    `linhas_periodo` e o **universo** do periodo (a carteira inteira, ja
    filtrada por data), enquanto `conta_id` e `plataforma` recortam apenas
    quem sera classificado. Passar so as linhas do cliente selecionado
    funciona, mas destroi o nivel 2 do benchmark do Meta — o portfolio deixa
    de existir.

    Nesta versao a performance corrente e os pares vem do MESMO periodo. O
    periodo anterior entra somente na tendencia, nunca no benchmark.

    Args:
        linhas_periodo: Universo de linhas do periodo selecionado.
        conta_id: Restringe a saida a uma conta. ``None`` classifica todas.
        plataforma: Restringe a saida a uma plataforma. ``None`` classifica
            as duas.
        linhas_periodo_anterior: Linhas do periodo imediatamente anterior, de
            mesma duracao, para a tendencia. ``None`` desliga a tendencia.

    Returns:
        Lista de `ClassificacaoCampanha` ordenada por plataforma, conta e
        campanha — ordem estavel, independente da ordem de entrada.
    """
    universo = [
        _avaliar(chave, linhas)
        for chave, linhas in _agrupar_por_campanha(linhas_periodo).items()
    ]
    anteriores: dict[tuple[str, str, str], _Agregado] = {}
    if linhas_periodo_anterior:
        anteriores = {
            chave: _avaliar(chave, linhas)
            for chave, linhas in _agrupar_por_campanha(linhas_periodo_anterior).items()
        }

    periodo_curto = 0 < len({linha["data"] for linha in linhas_periodo}) < DIAS_PERIODO_CURTO

    alvos = [
        agregado
        for agregado in universo
        if (conta_id is None or agregado.conta_id == conta_id)
        and (plataforma is None or agregado.plataforma == plataforma)
    ]
    classificacoes = [
        _classificar_uma(
            alvo,
            universo,
            anteriores.get((alvo.plataforma, alvo.conta_id, alvo.campanha_id)),
            periodo_curto,
        )
        for alvo in alvos
    ]
    return sorted(
        classificacoes,
        key=lambda c: (c.plataforma, c.conta_id, c.campanha_id),
    )


def _agrupar_por_anuncio(
    linhas: list[LinhaDataset],
) -> dict[tuple[str, str, str, str, str], list[LinhaDataset]]:
    """Agrupa linhas na unidade anuncio, preservando toda a hierarquia."""
    grupos: dict[
        tuple[str, str, str, str, str], list[LinhaDataset]
    ] = {}
    for linha in linhas:
        chave = (
            linha["plataforma"],
            linha["conta_id"],
            linha["campanha_id"],
            linha["adset_id"],
            linha["anuncio_id"],
        )
        grupos.setdefault(chave, []).append(linha)
    return grupos


def _avaliar_anuncio(
    chave: tuple[str, str, str, str, str],
    linhas: list[LinhaDataset],
) -> _AgregadoAnuncio:
    """Acopla a semantica compartilhada a identidade de um anuncio."""
    plataforma, conta_id, campanha_id, adset_id, anuncio_id = chave
    semantica = _avaliar_semantica(plataforma, linhas)
    return _AgregadoAnuncio(
        plataforma=plataforma,
        conta_id=conta_id,
        campanha_id=campanha_id,
        adset_id=adset_id,
        anuncio_id=anuncio_id,
        spend=semantica.spend,
        dias_ativos=semantica.dias_ativos,
        eixo=semantica.eixo,
        kpi_tipo=semantica.kpi_tipo,
        kpi_valor=semantica.kpi_valor,
        denominador=semantica.denominador,
        bloqueio=semantica.bloqueio,
    )


def _identidade_anuncio(
    anuncio: _AgregadoAnuncio,
) -> tuple[str, str, str, str, str]:
    """Devolve a chave publica completa usada no leave-one-out."""
    return (
        anuncio.plataforma,
        anuncio.conta_id,
        anuncio.campanha_id,
        anuncio.adset_id,
        anuncio.anuncio_id,
    )


def _e_par_valido_anuncio(candidato: _AgregadoAnuncio) -> bool:
    """Exige do peer de anuncio KPI, spend, dias e denominador suficientes."""
    return _tem_evidencia_para_benchmark(
        candidato,
        exigir_spend_positivo=True,
    )


def _pares_anuncio(
    universo: list[_AgregadoAnuncio],
    alvo: _AgregadoAnuncio,
) -> tuple[list[Decimal], str, int]:
    """Monta o benchmark local do anuncio, sempre com leave-one-out.

    N1 usa o mesmo ad set/grupo e eixo. Se nao houver tres outros anuncios
    elegiveis, N2 amplia apenas ate a campanha. Nao existe nivel entre
    campanhas, contas ou portfolio.
    """
    if alvo.eixo is None:
        return [], INDISPONIVEL, 0

    identidade_alvo = _identidade_anuncio(alvo)
    candidatos = [
        candidato
        for candidato in universo
        if candidato.eixo == alvo.eixo
        and _identidade_anuncio(candidato) != identidade_alvo
        and candidato.plataforma == alvo.plataforma
        and candidato.conta_id == alvo.conta_id
        and candidato.campanha_id == alvo.campanha_id
        and _e_par_valido_anuncio(candidato)
    ]

    mesmo_grupo = [
        candidato
        for candidato in candidatos
        if candidato.adset_id == alvo.adset_id
    ]
    if len(mesmo_grupo) >= MIN_PARES_ANUNCIO:
        return (
            [candidato.kpi_valor for candidato in mesmo_grupo],
            MESMO_GRUPO,
            len(mesmo_grupo),
        )

    if len(candidatos) >= MIN_PARES_ANUNCIO:
        return (
            [candidato.kpi_valor for candidato in candidatos],
            MESMA_CAMPANHA,
            len(candidatos),
        )

    return [], INDISPONIVEL, 0


def _result_type_do_eixo(eixo: tuple | None) -> str | None:
    """Extrai o indicator tecnico quando o eixo for Meta Result."""
    if eixo and eixo[0] == EIXO_META_RESULT:
        return eixo[1]
    return None


def _texto_pares_anuncio(origem: str, n: int) -> str:
    """Descreve a referencia de anuncio sem incluir identificadores."""
    if origem == MESMO_GRUPO:
        return f"{n} anúncios comparáveis do mesmo grupo"
    return f"{n} anúncios comparáveis da mesma campanha"


def _classificar_um_anuncio(
    alvo: _AgregadoAnuncio,
    universo: list[_AgregadoAnuncio],
) -> ClassificacaoAnuncio:
    """Aplica a regra empirica aprovada a um anuncio."""
    valores, origem, n = _pares_anuncio(universo, alvo)
    p25 = percentil(valores, 25)
    p50 = percentil(valores, 50)
    p75 = percentil(valores, 75)

    def resultado(
        status: str,
        codigo: str,
        motivo: str,
        *,
        com_benchmark: bool,
    ) -> ClassificacaoAnuncio:
        diferenca = None
        if (
            com_benchmark
            and p50 is not None
            and p50 > 0
            and alvo.kpi_valor is not None
        ):
            diferenca = (alvo.kpi_valor - p50) / p50
        return ClassificacaoAnuncio(
            plataforma=alvo.plataforma,
            conta_id=alvo.conta_id,
            campanha_id=alvo.campanha_id,
            adset_id=alvo.adset_id,
            anuncio_id=alvo.anuncio_id,
            status=status,
            motivo_codigo=codigo,
            motivo=motivo,
            eixo_comparacao=alvo.eixo,
            kpi_tipo=alvo.kpi_tipo,
            kpi_valor=alvo.kpi_valor,
            result_type=_result_type_do_eixo(alvo.eixo),
            benchmark_origem=origem if com_benchmark else INDISPONIVEL,
            benchmark_n=n if com_benchmark else 0,
            benchmark_p25=p25 if com_benchmark else None,
            benchmark_mediana=p50 if com_benchmark else None,
            benchmark_p75=p75 if com_benchmark else None,
            diferenca_mediana_pct=diferenca,
            dias_ativos=alvo.dias_ativos,
            denominador=alvo.denominador,
            spend=alvo.spend,
        )

    # Limites semanticos precedem qualquer inferencia estatistica.
    if alvo.bloqueio is not None:
        status, codigo, motivo = alvo.bloqueio
        return resultado(status, codigo, motivo, com_benchmark=False)

    if alvo.spend <= 0:
        return resultado(
            DADOS_INSUFICIENTES,
            MOTIVO_SPEND_ZERO,
            "Sem investimento no período.",
            com_benchmark=False,
        )

    # Denominador zero e informacao quando o gasto pode ser comparado a uma
    # referencia valida. Por isso este ramo vem antes do gate minimo de tres.
    if alvo.denominador is not None and alvo.denominador <= 0:
        if origem == INDISPONIVEL or p50 is None or p50 <= 0:
            return resultado(
                DADOS_INSUFICIENTES,
                MOTIVO_ZERO_RESULT_SEM_REFERENCIA,
                "Nenhum resultado observado e sem referência de custo para "
                "avaliar o investimento.",
                com_benchmark=False,
            )
        multiplo = alvo.spend / p50
        if multiplo < GASTO_SEM_RESULTADO_ATENCAO:
            return resultado(
                DADOS_INSUFICIENTES,
                MOTIVO_ZERO_RESULT_GASTO_BAIXO,
                "Investimento ainda baixo frente ao custo de referência e "
                "nenhum resultado observado.",
                com_benchmark=True,
            )
        if multiplo < GASTO_SEM_RESULTADO_RUIM:
            return resultado(
                ATENCAO,
                MOTIVO_ZERO_RESULT_GASTO_RELEVANTE,
                "Investimento relevante sem resultado.",
                com_benchmark=True,
            )
        return resultado(
            RUIM,
            MOTIVO_ZERO_RESULT_GASTO_ALTO,
            f"Investiu {multiplo:.1f}× o custo mediano de referência sem "
            "gerar resultado.",
            com_benchmark=True,
        )

    if alvo.dias_ativos < MIN_DIAS_ATIVOS:
        return resultado(
            DADOS_INSUFICIENTES,
            MOTIVO_POUCOS_DIAS,
            f"Apenas {alvo.dias_ativos} dia(s) com observação no período.",
            com_benchmark=False,
        )
    if alvo.denominador is None or alvo.denominador < MIN_DENOMINADOR:
        quantidade = m.formatar_quantidade_resultado(alvo.denominador)
        return resultado(
            DADOS_INSUFICIENTES,
            MOTIVO_DENOMINADOR_BAIXO,
            f"Apenas {quantidade} resultado(s) no período.",
            com_benchmark=False,
        )

    if origem == INDISPONIVEL:
        return resultado(
            DADOS_INSUFICIENTES,
            MOTIVO_SEM_PEERS,
            "Não há anúncios comparáveis suficientes para construir a "
            "referência.",
            com_benchmark=False,
        )

    status = _quartil(alvo.kpi_valor, p25, p50, p75)
    faixa = {
        EXCELENTE: "no primeiro quartil",
        BOA: "entre o primeiro quartil e a mediana",
        ATENCAO: "entre a mediana e o terceiro quartil",
        RUIM: "acima do terceiro quartil",
    }[status]
    motivo = (
        f"{alvo.kpi_tipo.upper()} {faixa} entre "
        f"{_texto_pares_anuncio(origem, n)}."
    )
    if alvo.kpi_tipo == CPL:
        motivo += (
            " KPI usado: CPL (Result indisponível para o anúncio no período)."
        )
    return resultado(status, MOTIVO_QUARTIL, motivo, com_benchmark=True)


def classificar_anuncios(
    linhas_periodo: list[LinhaDataset],
    *,
    conta_id: str | None = None,
    plataforma: str | None = None,
    campanha_id: str | None = None,
    adset_id: str | None = None,
) -> list[ClassificacaoAnuncio]:
    """Classifica anuncios sem deixar filtros de saida destruir os peers.

    `linhas_periodo` e o universo factual. Os argumentos opcionais recortam
    apenas os alvos devolvidos; N1 e N2 continuam sendo montados sobre todo o
    universo recebido. Como N2 para na campanha, outras contas nunca servem
    de referencia mesmo quando estiverem presentes na lista.

    Args:
        linhas_periodo: Universo do periodo, idealmente a conta inteira.
        conta_id: Restringe os anuncios devolvidos a uma conta.
        plataforma: Restringe os anuncios devolvidos a uma plataforma.
        campanha_id: Restringe a saida sem remover peers da campanha.
        adset_id: Restringe a saida sem remover peers do grupo ou campanha.

    Returns:
        Classificacoes ordenadas pela hierarquia publica completa.
    """
    universo = [
        _avaliar_anuncio(chave, linhas)
        for chave, linhas in _agrupar_por_anuncio(linhas_periodo).items()
    ]
    alvos = [
        agregado
        for agregado in universo
        if (conta_id is None or agregado.conta_id == conta_id)
        and (plataforma is None or agregado.plataforma == plataforma)
        and (campanha_id is None or agregado.campanha_id == campanha_id)
        and (adset_id is None or agregado.adset_id == adset_id)
    ]
    return sorted(
        (_classificar_um_anuncio(alvo, universo) for alvo in alvos),
        key=lambda item: (
            item.plataforma,
            item.conta_id,
            item.campanha_id,
            item.adset_id,
            item.anuncio_id,
        ),
    )


def resumir_classificacoes(
    classificacoes: list[ClassificacaoCampanha | ClassificacaoAnuncio],
) -> dict:
    """Conta status, motivos, origens e tendencias de um conjunto ja classificado.

    Funcao pura de contagem: nao reclassifica nada e nao conhece a UI. Ela
    existe para que a camada de apresentacao nao precise reimplementar
    agregacao — nem, pior, deduzir causa lendo o texto de `motivo`.

    Todas as chaves de `STATUS` e de `MOTIVOS` aparecem no resultado, mesmo
    zeradas: um painel que itera o resumo mostra as mesmas categorias sempre,
    em vez de fazer a categoria sumir quando ninguem caiu nela.

    Args:
        classificacoes: Saida de :func:`classificar_campanhas` ou
            :func:`classificar_anuncios`.

    Returns:
        Dicionario com `total`, `por_status`, `por_motivo`, `por_origem`,
        `por_tendencia` e `com_desempenho` (quantas receberam posicao medida).
    """
    por_status = {status: 0 for status in STATUS}
    por_motivo = {motivo: 0 for motivo in MOTIVOS}
    anuncios = any(isinstance(item, ClassificacaoAnuncio) for item in classificacoes)
    origens = (
        (MESMO_GRUPO, MESMA_CAMPANHA, INDISPONIVEL)
        if anuncios
        else (MESMO_CLIENTE, MESMO_TIPO_PORTFOLIO, INDISPONIVEL)
    )
    por_origem = {origem: 0 for origem in origens}
    por_tendencia = {tendencia: 0 for tendencia in (MELHORANDO, ESTAVEL, PIORANDO)}
    por_tendencia[None] = 0

    for item in classificacoes:
        por_status[item.status] += 1
        por_motivo[item.motivo_codigo] += 1
        por_origem[item.benchmark_origem] += 1
        por_tendencia[getattr(item, "tendencia", None)] += 1

    return {
        "total": len(classificacoes),
        "com_desempenho": sum(por_status[s] for s in STATUS_DE_DESEMPENHO),
        "por_status": por_status,
        "por_motivo": por_motivo,
        "por_origem": por_origem,
        "por_tendencia": por_tendencia,
    }
