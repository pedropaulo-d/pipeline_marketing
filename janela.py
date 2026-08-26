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

Janela informada a mao
----------------------
Um disparo manual pela UI pode substituir o calculo por um intervalo explicito,
via os params ``data_inicial`` e ``data_final``. E substituicao, nao ajuste: as
duas datas valem como estao, o intervalo pode ter qualquer tamanho e o dia
corrente deixa de ser excluido automaticamente — quem digitou a data respondeu
pela escolha.

O padrao nao muda. Sem os dois params preenchidos a execucao usa ``[D-7,
D-1]``, seja ela agendada ou manual. A decisao entre os dois modos vive aqui, e
nao no template da DAG, pelo mesmo motivo que o calculo ja vivia: e regra de
negocio testavel fora do Airflow.

Uso:
    from janela import janela_extracao, resolver_janela

    inicio, fim = janela_extracao(dag_run.run_after)
    inicio, fim, manual = resolver_janela(dag_run, params)
"""

import re
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

# Nomes dos params expostos na tela "Trigger DAG". Ficam aqui porque a
# validacao e a leitura deles moram neste modulo; a DAG so os declara.
PARAM_INICIO: str = "data_inicial"
PARAM_FIM: str = "data_final"

# `date.fromisoformat` aceita outras grafias ISO 8601 no Python 3.11
# (`20260812`, `2026-W33-3`). O contrato publicado e YYYY-MM-DD, entao a
# grafia e conferida antes da conversao.
_ISO_ANO_MES_DIA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


# ── Janela informada a mao ───────────────────────────────────
# Nenhuma destas funcoes conhece o Airflow: recebem texto e devolvem texto ou
# erro. E o que permite testar as sete regras de validacao sem orquestrador.


def _texto_informado(valor) -> str | None:
    """Normaliza o valor bruto de um param.

    Campo em branco e AUSENCIA, nao entrada invalida: a tela de disparo do
    Airflow envia string vazia quando o usuario nao digita nada, e recusar
    isso impediria o proprio caso "deixe vazio para usar a janela automatica".

    Args:
        valor: Valor cru do param — ``None``, texto ou qualquer outro tipo.

    Returns:
        O texto sem espacos nas pontas, ou ``None`` quando nao ha conteudo.
    """
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _data_informada(texto: str, campo: str) -> date:
    """Converte o texto de um param em data de calendario, sem tolerancia.

    Args:
        texto: Valor ja normalizado.
        campo: Nome do param, usado na mensagem de erro.

    Returns:
        A data correspondente.

    Raises:
        ValueError: Se a grafia nao for YYYY-MM-DD ou se a data nao existir no
            calendario. Entrada invalida falha; nunca e corrigida em silencio.
    """
    if not _ISO_ANO_MES_DIA.match(texto):
        raise ValueError(
            f"`{campo}` precisa estar no formato YYYY-MM-DD "
            f"(recebido: {texto!r})."
        )
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise ValueError(
            f"`{campo}` nao e uma data valida no calendario "
            f"(recebido: {texto!r})."
        ) from None


def janela_informada(inicio=None, fim=None) -> tuple[str, str] | None:
    """Valida o par de datas informado a mao.

    Args:
        inicio: Valor cru do param ``data_inicial``.
        fim: Valor cru do param ``data_final``.

    Returns:
        Par ``(start_date, end_date)`` em ``YYYY-MM-DD`` quando as duas datas
        foram informadas e sao coerentes, ou ``None`` quando nenhuma foi — o
        sinal de que a janela automatica vale.

    Raises:
        ValueError: Se apenas uma das duas foi informada, se alguma nao for
            uma data YYYY-MM-DD valida, ou se o fim for anterior ao inicio.
            Inicio igual ao fim e valido: significa um unico dia.
    """
    texto_inicio = _texto_informado(inicio)
    texto_fim = _texto_informado(fim)

    if texto_inicio is None and texto_fim is None:
        return None

    if texto_inicio is None or texto_fim is None:
        informado, ausente = (
            (PARAM_FIM, PARAM_INICIO)
            if texto_inicio is None
            else (PARAM_INICIO, PARAM_FIM)
        )
        raise ValueError(
            f"`{informado}` foi informado sem `{ausente}`. A janela manual "
            f"exige as duas datas. Deixe as duas vazias para usar a janela "
            f"automatica de {DIAS_DE_JANELA} dias."
        )

    primeiro = _data_informada(texto_inicio, PARAM_INICIO)
    ultimo = _data_informada(texto_fim, PARAM_FIM)

    if ultimo < primeiro:
        raise ValueError(
            f"`{PARAM_FIM}` ({ultimo.isoformat()}) e anterior a "
            f"`{PARAM_INICIO}` ({primeiro.isoformat()}). O intervalo precisa "
            f"terminar em ou depois do dia em que comeca."
        )

    return primeiro.isoformat(), ultimo.isoformat()


def resolver_janela(
    dag_run,
    params=None,
    dias: int = DIAS_DE_JANELA,
    timezone: str = TIMEZONE,
) -> tuple[str, str, bool]:
    """Decide qual janela a execucao usa.

    Ponto unico da decisao entre os dois modos. As tres tasks do contrato
    (as duas extracoes e a carga) passam por aqui, entao Meta, Google e
    manifesto recebem o mesmo intervalo por construcao — nao por coincidencia
    de template.

    Args:
        dag_run: DagRun do contexto da task.
        params: Params da execucao. ``None`` ou vazio significa janela
            automatica.
        dias: Quantidade de dias completos da janela automatica.
        timezone: Fuso em que o dia e definido.

    Returns:
        Tripla ``(start_date, end_date, manual)``, com as datas em
        ``YYYY-MM-DD`` e ``manual`` dizendo se vieram dos params.

    Raises:
        ValueError: Se os params forem incoerentes (ver
            :func:`janela_informada`) ou se o DagRun nao tiver ``run_after``.
    """
    params = params or {}
    manual = janela_informada(
        params.get(PARAM_INICIO), params.get(PARAM_FIM)
    )
    if manual is not None:
        return manual[0], manual[1], True

    inicio, fim = janela_extracao(_referencia(dag_run), dias, timezone)
    return inicio, fim, False


# ── Macros da DAG ────────────────────────────────────────────
# Registradas em `user_defined_macros` e chamadas como
# `{{ janela_inicio(dag_run, params) }}`. Recebem o DagRun e os params em vez
# de lerem o contexto por conta propria: as funcoes continuam puras e
# testaveis com um objeto qualquer que exponha `run_after` e um dicionario.
#
# `params` e opcional na assinatura para que chamada antiga
# (`janela_inicio(dag_run)`) continue valendo e signifique o que sempre
# significou: janela automatica.


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


def janela_inicio(dag_run, params=None, dias: int = DIAS_DE_JANELA) -> str:
    """Primeiro dia da janela, para uso em template da DAG.

    Args:
        dag_run: DagRun do contexto da task.
        params: Params da execucao; vazio significa janela automatica.
        dias: Quantidade de dias completos da janela automatica.

    Returns:
        Data inicial no formato ``YYYY-MM-DD``.
    """
    return resolver_janela(dag_run, params, dias)[0]


def janela_fim(dag_run, params=None, dias: int = DIAS_DE_JANELA) -> str:
    """Ultimo dia da janela, para uso em template da DAG.

    Args:
        dag_run: DagRun do contexto da task.
        params: Params da execucao; vazio significa janela automatica.
        dias: Quantidade de dias completos da janela automatica.

    Returns:
        Data final no formato ``YYYY-MM-DD``. Na janela automatica e sempre o
        dia anterior ao da execucao; na manual, o dia informado.
    """
    return resolver_janela(dag_run, params, dias)[1]


def janela_descricao(dag_run, params=None, dias: int = DIAS_DE_JANELA) -> str:
    """Linha de log que declara a janela e a origem dela.

    Renderizada no comando de cada task para aparecer no inicio do log, sem
    exigir uma task nova so para registrar. Nao carrega credencial nem
    conteudo de param alem das duas datas ja validadas.

    Args:
        dag_run: DagRun do contexto da task.
        params: Params da execucao; vazio significa janela automatica.
        dias: Quantidade de dias completos da janela automatica.

    Returns:
        Texto como ``Janela de extração manual: 2026-08-12 a 2026-08-18``.
    """
    inicio, fim, manual = resolver_janela(dag_run, params, dias)
    origem = "manual" if manual else "automática"
    return f"Janela de extração {origem}: {inicio} a {fim}"
