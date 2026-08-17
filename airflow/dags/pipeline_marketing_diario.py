"""DAG diaria do pipeline de marketing — Meta + Google Ads -> bronze -> gold.

Automatiza a sequencia que o ``main.py`` executa a mao, com uma task por etapa:

    extrai_meta    ─┐
                    ├─> carrega_bronze ─> transforma_dbt
    extrai_google  ─┘

As duas extracoes sao independentes (APIs diferentes, credenciais diferentes) e
rodam em paralelo no LocalExecutor. ``carrega_bronze`` e o ponto de fan-in: so
dispara quando as duas terminam, porque le os dois arquivos brutos de uma vez.

Por que uma task por etapa, e nao um `main.py` so
------------------------------------------------
Falha isolada e retry seletivo. Uma falha no dbt reexecutaria a extracao das
151 contas (~2 min de API) se tudo fosse uma task unica. Alem disso o grafo na
UI passa a descrever a arquitetura sem precisar de slide.

A JANELA: os SETE DIAS COMPLETOS ANTERIORES
-------------------------------------------
Uma execucao do dia D extrai de **D-7 ate D-1**. O dia corrente nunca entra —
as plataformas ainda estao consolidando as metricas dele.

Reextrair sete dias, e nao so o dia anterior, nao e margem de seguranca: as
metricas do Meta mudam RETROATIVAMENTE por ate 28 dias, por efeito da janela de
atribuicao. O valor do dia D consultado em D+1 nao e o mesmo consultado em D+7.

Isso e seguro e barato por causa de duas decisoes que ja existiam:

- a bronze e append-only, entao reextrair cria um lote novo em vez de
  sobrescrever — e a deriva fica registrada, mensuravel;
- a silver deduplica por `dense_rank()` sobre (source, reference_date) ordenado
  por `extracted_at desc`, entao o snapshot mais recente vence sozinho.

O calculo vive em ``janela.py``, fora da DAG, e chega aqui como macro. Ele
NAO usa `ds`, por dois motivos medidos em 17/08/2026: no Airflow 3 uma string
de cron produz `CronTriggerTimetable`, em que `logical_date` e o instante do
disparo (a janela virava `[D-6, D]`, incluindo o dia parcial); e um DagRun
manual nasce com `logical_date = NULL`, o que fazia `{{ ds }}` sumir do
contexto e a task quebrar no render. A referencia passou a ser
`dag_run.run_after`, campo obrigatorio do DagRun nas duas situacoes.

Agendamento
-----------
06:00 em America/Sao_Paulo. As plataformas consolidam o dia anterior de
madrugada; rodar cedo demais pega dado parcial.

A DAG nasce PAUSADA (`AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION`). Ela consome
API de producao com dado real de clientes: despausar e uma decisao consciente,
nao um efeito colateral de subir o compose.
"""

from __future__ import annotations

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

from janela import DIAS_DE_JANELA, TIMEZONE, janela_fim, janela_inicio

# Raiz do projeto dentro dos containers do Airflow, conforme o bind mount
# `.:/opt/project` no docker-compose.yml.
PROJETO = "/opt/project"

# As datas e o `run_id` sao resolvidos em tempo de render. `run_id` existe em
# execucao agendada e manual; `dag_run` idem — nenhum dos dois depende de
# `logical_date`, que e nula em run manual.
DATA_INICIAL = "{{ janela_inicio(dag_run) }}"
DATA_FINAL = "{{ janela_fim(dag_run) }}"
RUN_ID = "{{ run_id }}"

# Aplicado a todas as tasks. Retry cobre falha transitoria de API e de rede;
# 3 tentativas com 5 minutos de intervalo nao mascaram bug persistente.
argumentos_padrao = {
    "retries": 2,
    "retry_delay": pendulum.duration(minutes=5),
}

with DAG(
    dag_id="pipeline_marketing_diario",
    description=(
        "Extracao Meta + Google Ads (7 dias completos anteriores) -> bronze "
        "append-only -> dbt build (silver, gold e testes)."
    ),
    schedule="0 6 * * *",
    start_date=pendulum.datetime(2026, 8, 1, tz=TIMEZONE),
    # Sem catchup: despausar a DAG nao dispara uma execucao por dia desde
    # start_date. O historico ja esta na bronze, e reprocessa-lo pela API
    # traria o nome ATUAL das entidades para datas passadas, achatando o SCD2.
    catchup=False,
    default_args=argumentos_padrao,
    tags=["tcc", "marketing", "elt"],
    # Duas execucoes simultaneas escreveriam no mesmo temp_*_raw.json.
    max_active_runs=1,
    # A janela e uma regra de negocio testada em `tests/test_janela.py`, nao
    # aritmetica de template. Expo-la como macro mantem o calculo unico e
    # verificavel fora do Airflow.
    user_defined_macros={
        "janela_inicio": janela_inicio,
        "janela_fim": janela_fim,
    },
) as dag:

    extrai_meta = BashOperator(
        task_id="extrai_meta",
        bash_command=(
            f"cd {PROJETO} && python -m extractors.meta_ads "
            f"--start-date {DATA_INICIAL} --end-date {DATA_FINAL} "
            f"--run-id '{RUN_ID}'"
        ),
        doc_md=(
            "Insights API. Descobre as contas ativas via Business ID e grava "
            "`temp_meta_raw.json` mais o manifesto `temp_meta_raw.manifesto."
            "json`, que carrega fonte, `run_id`, janela e sha256. Costuma "
            "levar ~2 min para 87 contas."
        ),
    )

    extrai_google = BashOperator(
        task_id="extrai_google",
        bash_command=(
            f"cd {PROJETO} && python -m extractors.google_ads "
            f"--start-date {DATA_INICIAL} --end-date {DATA_FINAL} "
            f"--run-id '{RUN_ID}'"
        ),
        doc_md=(
            "GAQL. Descobre as subcontas via `customer_client` no MCC e grava "
            "`temp_google_raw.json` mais o manifesto. O acesso precisa ser no "
            "MCC, nao nas contas individuais."
        ),
    )

    carrega_bronze = BashOperator(
        task_id="carrega_bronze",
        # `--run-id` e a janela transformam a carga em verificacao: cada
        # arquivo precisa provar, pelo manifesto, que veio DESTE run. Sem isso
        # um JSON sobrado de execucao anterior era reingerido como lote novo.
        bash_command=(
            f"cd {PROJETO} && python -m loaders.bronze_loader "
            f"--sources meta_ads,google_ads "
            f"--run-id '{RUN_ID}' "
            f"--start-date {DATA_INICIAL} --end-date {DATA_FINAL}"
        ),
        doc_md=(
            "JSON bruto -> `bronze.raw_ads` (JSONB) + `ingestion_log`, sem "
            "transformar nada. Recusa artefato que nao seja deste run: "
            "manifesto ausente, `run_id` de outra execucao, janela diferente "
            "ou sha256 divergente falham a task."
        ),
    )

    transforma_dbt = BashOperator(
        task_id="transforma_dbt",
        # Reusa `main.run_dbt` em vez de chamar `dbt build` direto de proposito:
        # ela deriva DBT_HOST/PORT/USER/PASSWORD/DBNAME de DW_DB_URL via
        # `config.dbt_env()`. Escrever a conexao de novo aqui criaria uma
        # segunda fonte de verdade para o banco — a familia de bug que este
        # repositorio ja pagou tres vezes.
        bash_command=(
            f'cd {PROJETO} && python -c "from main import run_dbt; run_dbt()"'
        ),
        doc_md=(
            "`dbt build`: materializa silver e gold e roda os 72 testes — o "
            "`PASS=83` conta nos, isto e, 11 modelos mais os 72 testes. "
            "Falha de teste falha a task — dado ruim nao avanca em silencio. "
            "Nao chama API: pode ser reexecutada sozinha."
        ),
    )

    [extrai_meta, extrai_google] >> carrega_bronze >> transforma_dbt

# Mantido como documentacao viva do parametro: a janela e de `DIAS_DE_JANELA`
# dias e termina sempre em D-1.
dag.doc_md = __doc__ + f"\nJanela atual: {DIAS_DE_JANELA} dias, fuso {TIMEZONE}.\n"
