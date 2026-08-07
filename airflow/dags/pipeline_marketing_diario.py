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

A JANELA DE 7 DIAS nao e margem de seguranca
--------------------------------------------
Cada execucao reextrai os ultimos 7 dias, nao apenas o dia anterior. As
metricas do Meta mudam RETROATIVAMENTE por ate 28 dias, por efeito da janela de
atribuicao: o valor do dia D consultado em D+1 nao e o mesmo consultado em D+7.
Extrair so o dia anterior congelaria numeros que ainda vao mudar.

Isso e seguro e barato por causa de duas decisoes que ja existiam:

- a bronze e append-only, entao reextrair cria um lote novo em vez de
  sobrescrever — e a deriva fica registrada, mensuravel;
- a silver deduplica por `dense_rank()` sobre (source, reference_date) ordenado
  por `extracted_at desc`, entao o snapshot mais recente vence sozinho.

7 dias cobrem a maior parte da revisao sem multiplicar por 28 o volume de
chamadas de API. E um parametro, nao um dogma: ver ``DIAS_DE_JANELA``.

Agendamento
-----------
06:00 em America/Sao_Paulo. As plataformas consolidam o dia anterior de
madrugada; rodar cedo demais pega dado parcial — que a janela movel corrigiria
depois, mas sem necessidade de comecar errado.

A DAG nasce PAUSADA (`AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION`). Ela consome
API de producao com dado real de clientes: despausar e uma decisao consciente,
nao um efeito colateral de subir o compose.
"""

from __future__ import annotations

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

# Raiz do projeto dentro dos containers do Airflow, conforme o bind mount
# `.:/opt/project` no docker-compose.yml.
PROJETO = "/opt/project"

# Quantos dias cada execucao reextrai, contando para tras a partir do dia de
# referencia. Ver "A JANELA DE 7 DIAS" no docstring do modulo.
DIAS_DE_JANELA = 7

# `ds` e a data do inicio do intervalo de dados — para um agendamento diario,
# o dia anterior a execucao. A janela vai de `ds - 6` ate `ds`.
DATA_INICIAL = "{{ macros.ds_add(ds, -" + str(DIAS_DE_JANELA - 1) + ") }}"
DATA_FINAL = "{{ ds }}"

# Aplicado a todas as tasks. Retry cobre falha transitoria de API e de rede;
# 3 tentativas com 5 minutos de intervalo nao mascaram bug persistente.
argumentos_padrao = {
    "retries": 2,
    "retry_delay": pendulum.duration(minutes=5),
}

with DAG(
    dag_id="pipeline_marketing_diario",
    description=(
        "Extracao Meta + Google Ads (janela movel de 7 dias) -> bronze "
        "append-only -> dbt build (silver, gold e testes)."
    ),
    schedule="0 6 * * *",
    start_date=pendulum.datetime(2026, 8, 1, tz="America/Sao_Paulo"),
    # Sem catchup: despausar a DAG nao dispara uma execucao por dia desde
    # start_date. O historico ja esta na bronze, e reprocessa-lo pela API
    # traria o nome ATUAL das entidades para datas passadas, achatando o SCD2.
    catchup=False,
    default_args=argumentos_padrao,
    tags=["tcc", "marketing", "elt"],
    # Duas execucoes simultaneas escreveriam no mesmo temp_*_raw.json.
    max_active_runs=1,
) as dag:

    extrai_meta = BashOperator(
        task_id="extrai_meta",
        bash_command=(
            f"cd {PROJETO} && python -m extractors.meta_ads "
            f"--start-date {DATA_INICIAL} --end-date {DATA_FINAL}"
        ),
        doc_md=(
            "Insights API. Descobre as contas ativas via Business ID e grava "
            "`temp_meta_raw.json`. Costuma levar ~2 min para 87 contas."
        ),
    )

    extrai_google = BashOperator(
        task_id="extrai_google",
        bash_command=(
            f"cd {PROJETO} && python -m extractors.google_ads "
            f"--start-date {DATA_INICIAL} --end-date {DATA_FINAL}"
        ),
        doc_md=(
            "GAQL. Descobre as subcontas via `customer_client` no MCC e grava "
            "`temp_google_raw.json`. O acesso precisa ser no MCC, nao nas "
            "contas individuais."
        ),
    )

    carrega_bronze = BashOperator(
        task_id="carrega_bronze",
        bash_command=f"cd {PROJETO} && python -m loaders.bronze_loader",
        doc_md=(
            "JSON bruto -> `bronze.raw_ads` (JSONB) + `ingestion_log`, sem "
            "transformar nada. Depende das DUAS extracoes: carrega todos os "
            "arquivos brutos presentes, e um arquivo sobrado de execucao "
            "anterior seria reingerido como lote novo."
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
            "`dbt build`: materializa silver e gold e roda os 83 testes. "
            "Falha de teste falha a task — dado ruim nao avanca em silencio."
        ),
    )

    [extrai_meta, extrai_google] >> carrega_bronze >> transforma_dbt
