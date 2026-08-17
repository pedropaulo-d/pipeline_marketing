"""Janela movel de extracao — fonte unica do periodo que cada execucao consulta.

O contrato e explicito: **uma execucao do dia D extrai os sete dias completos
anteriores, de D-7 ate D-1**. O dia corrente nunca entra, porque as plataformas
ainda estao consolidando as metricas dele.

Por que isso virou um modulo
----------------------------
A DAG calculava a janela com ``{{ macros.ds_add(ds, -6) }} .. {{ ds }}``, o que
carregava dois problemas medidos em 17/08/2026:

1. **`ds` mudou de significado no Airflow 3.** Uma string de cron agora produz
   ``CronTriggerTimetable``, em que ``logical_date`` e o INSTANTE DO DISPARO e
   nao o inicio de um intervalo (``data_interval_start == data_interval_end``).
   Com isso ``ds`` passou a ser o proprio dia da execucao e a janela virou
   ``[D-6, D]`` — sete dias, mas com o ultimo ainda pela metade.
2. **`ds` nao existe em run manual.** No Airflow 3 um DagRun manual nasce com
   ``logical_date = NULL``, e as chaves derivadas dela somem do contexto:
   ``airflow dags trigger`` sem ``--logical-date`` quebrava no render com
   ``TypeError: strptime() argument 1 must be str, not StrictUndefined``.

A referencia passou a ser ``dag_run.run_after``, que o Airflow 3 declara como
campo **obrigatorio** do DagRun (``run_after: UtcDateTime``, sem ``| None``):
existe em execucao agendada e em execucao manual, e para o agendamento vale
exatamente o horario de disparo. Uma unica regra serve aos dois casos.

Uso:
    from janela import janela_extracao

    inicio, fim = janela_extracao(dag_run.run_after)
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# Fuso em que o "dia" e definido. A operacao e brasileira e as plataformas
# fecham o dia no horario local; calcular a janela em UTC deslocaria a fronteira
# do dia em tres horas.
TIMEZONE: str = "America/Sao_Paulo"

# Quantos dias completos cada execucao reextrai. Nao e margem de seguranca: as
# metricas do Meta mudam retroativamente por ate 28 dias (janela de
# atribuicao), entao o valor do dia D consultado em D+1 nao e o mesmo
# consultado em D+7.
DIAS_DE_JANELA: int = 7


def dia_de_referencia(instante: datetime, timezone: str = TIMEZONE) -> date:
    """Converte um instante para o dia civil correspondente no fuso do projeto.

    Args:
        instante: Momento da execucao, obrigatoriamente com fuso.
        timezone: Fuso em que o dia e definido.

    Returns:
        O dia civil (``date``) daquele instante no fuso informado.

    Raises:
        ValueError: Se ``instante`` for ingenuo (sem fuso). Um datetime sem
            fuso tornaria a janela dependente do relogio de quem executa.
    """
    if instante.tzinfo is None or instante.utcoffset() is None:
        raise ValueError(
            "A referencia da janela precisa ter fuso. Um datetime ingenuo "
            "produziria janelas diferentes conforme o fuso do processo."
        )
    return instante.astimezone(ZoneInfo(timezone)).date()


def janela_extracao(
    instante: datetime,
    dias: int = DIAS_DE_JANELA,
    timezone: str = TIMEZONE,
) -> tuple[str, str]:
    """Calcula a janela de extracao de uma execucao.

    Args:
        instante: Momento da execucao (``dag_run.run_after``), com fuso.
        dias: Quantidade de dias completos a extrair.
        timezone: Fuso em que o dia e definido.

    Returns:
        Par ``(start_date, end_date)`` no formato ``YYYY-MM-DD``, com
        ``end_date`` sendo sempre o dia anterior ao da execucao.

    Raises:
        ValueError: Se ``dias`` for menor que 1 ou se ``instante`` nao tiver
            fuso.
    """
    if dias < 1:
        raise ValueError(f"A janela precisa de pelo menos 1 dia (recebido: {dias}).")

    hoje = dia_de_referencia(instante, timezone)
    fim = hoje - timedelta(days=1)
    inicio = fim - timedelta(days=dias - 1)
    return inicio.isoformat(), fim.isoformat()


def datas_da_janela(
    instante: datetime,
    dias: int = DIAS_DE_JANELA,
    timezone: str = TIMEZONE,
) -> list[str]:
    """Enumera as datas cobertas pela janela.

    Existe para log e para teste: afirmar "sao exatamente sete dias, e nenhum
    deles e hoje" fica verificavel sem reimplementar a aritmetica.

    Args:
        instante: Momento da execucao, com fuso.
        dias: Quantidade de dias completos a extrair.
        timezone: Fuso em que o dia e definido.

    Returns:
        Lista de datas ``YYYY-MM-DD``, em ordem crescente.
    """
    inicio, _ = janela_extracao(instante, dias, timezone)
    primeiro = date.fromisoformat(inicio)
    return [(primeiro + timedelta(days=i)).isoformat() for i in range(dias)]


# ── Macros da DAG ────────────────────────────────────────────
# Registradas em `user_defined_macros` e chamadas como
# `{{ janela_inicio(dag_run) }}`. Recebem o DagRun em vez de lerem o contexto
# por conta propria: a funcao continua pura e testavel com um objeto qualquer
# que exponha `run_after`.


def _referencia(dag_run) -> datetime:
    """Extrai o instante de referencia de um DagRun.

    Args:
        dag_run: Objeto do DagRun exposto ao contexto da task.

    Returns:
        O ``run_after`` do DagRun — presente tanto em execucao agendada quanto
        em manual, ao contrario de ``logical_date``.

    Raises:
        ValueError: Se o objeto nao tiver ``run_after`` preenchido.
    """
    instante = getattr(dag_run, "run_after", None)
    if instante is None:
        raise ValueError(
            "DagRun sem `run_after`. Esse campo e obrigatorio no Airflow 3 e e "
            "a referencia da janela — sem ele nao ha como definir o dia."
        )
    return instante


def janela_inicio(dag_run, dias: int = DIAS_DE_JANELA) -> str:
    """Primeiro dia da janela, para uso em template da DAG.

    Args:
        dag_run: DagRun do contexto da task.
        dias: Quantidade de dias completos a extrair.

    Returns:
        Data inicial no formato ``YYYY-MM-DD``.
    """
    return janela_extracao(_referencia(dag_run), dias)[0]


def janela_fim(dag_run, dias: int = DIAS_DE_JANELA) -> str:
    """Ultimo dia da janela, para uso em template da DAG.

    Args:
        dag_run: DagRun do contexto da task.
        dias: Quantidade de dias completos a extrair.

    Returns:
        Data final no formato ``YYYY-MM-DD`` — sempre o dia anterior ao da
        execucao.
    """
    return janela_extracao(_referencia(dag_run), dias)[1]
