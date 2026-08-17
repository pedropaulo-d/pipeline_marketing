# Orquestracao com Airflow

Automatiza o que o `main.py` faz a mao, com uma task por etapa.

```
extrai_meta    ─┐
                ├─> carrega_bronze ─> transforma_dbt
extrai_google  ─┘
```

## Subir

```bash
docker compose up -d airflow-apiserver airflow-scheduler airflow-dag-processor
```

UI em **http://localhost:8082** (usuario e senha `admin` por padrao).

A porta 8082 nao e arbitraria: a 8080 e do Airflow do projeto
`b3-data-pipeline`, que roda em paralelo nesta maquina, e a 8081 e do callback
OAuth do Google (`scripts/oauth_manual.py`).

Derrubar sem apagar o estado:

```bash
docker compose stop airflow-apiserver airflow-scheduler airflow-dag-processor
```

## A DAG nasce pausada

De proposito. As tasks de extracao chamam as APIs de producao com **dado real
de clientes de uma agencia**. Despausar precisa ser decisao consciente, nao
efeito colateral de subir o compose.

### Executar uma carga real: `unpause` sozinho

O procedimento de producao e **despausar e nao disparar nada**. Com
`catchup=False`, o scheduler cria UM run para o horario vencido, executa pelo
LocalExecutor e para ali.

```bash
# 1. pre-condicoes: DAG pausada, nenhum run queued/running
docker exec tcc_airflow_scheduler airflow dags list
docker exec tcc_airflow_db psql -U airflow -d airflow -c \
  "select run_id, state from dag_run where state in ('queued','running');"

# 2. despausar — e SO isso
docker exec tcc_airflow_scheduler airflow dags unpause pipeline_marketing_diario

# 3. acompanhar ate o estado terminal (nao pausar antes)
docker exec tcc_airflow_scheduler airflow dags list-runs -d pipeline_marketing_diario

# 4. so depois do DagRun terminar
docker exec tcc_airflow_scheduler airflow dags pause pipeline_marketing_diario
```

Medido em 17/08/2026 com uma sonda identica em schedule, fuso, `catchup`,
`max_active_runs` e `retries`: o `unpause` sozinho criou **exatamente um**
DagRun, `run_type=scheduled`, zero runs manuais, `executor=LocalExecutor
(parallelism=32)`, downstream normal, `DagRun state=success`, e nenhum segundo
run agendado apareceu depois.

### O que NAO usar nesta operacao

| Comando | Por que nao |
|---|---|
| `airflow dags trigger` com a DAG **pausada** | O DagRun nasce e fica em `queued` indefinidamente (4 min no teste, TaskInstances sem estado). E o que o `--help` do comando descreve. Vale tambem para *Trigger DAG* na UI |
| `unpause` **+** `trigger` | **Proibido neste procedimento.** Medido: o `unpause` executa tudo que estiver pendente — o manual enfileirado E o agendado vencido, dois DagRuns em 5 segundos. Em producao, duas extracoes completas das APIs |
| `airflow dags test --use-executor` | **Ferramenta de teste/debug**, nao procedimento de carga real: roda com a DAG pausada e cria um unico DagRun, mas as tasks nascem com `max_tries=0` (sem os 2 retries do `default_args`) e o run depende do processo do terminal continuar vivo. Util para exercitar a DAG sem esperar o horario |

Em qualquer caminho, **a janela nao depende de `--logical-date`**: no Airflow 3
um DagRun manual nasce com `logical_date = NULL` e o calculo usa
`dag_run.run_after` (ver abaixo).

## Janela: os sete dias completos anteriores

Uma execucao do dia **D** extrai de **D-7 ate D-1**, no fuso
`America/Sao_Paulo`. O dia corrente nunca entra: as plataformas ainda estao
consolidando as metricas dele.

Reextrair sete dias, e nao so o dia anterior, nao e margem de seguranca. As
metricas do Meta mudam retroativamente por ate 28 dias (janela de atribuicao):
o valor do dia D consultado em D+1 nao e o mesmo consultado em D+7. Extrair so
o dia anterior congelaria numeros que ainda vao mudar.

Isso e seguro porque duas decisoes anteriores ja sustentavam o reprocessamento:
a bronze e append-only (reextrair cria lote novo, nao sobrescreve) e a silver
adota o snapshot mais recente de cada dia. Efeito colateral util: a deriva
retroativa fica **registrada e mensuravel** na bronze.

O calculo vive em `janela.py` — fora da DAG, com teste proprio
(`tests/test_janela.py`) — e chega as tasks como macro
(`{{ janela_inicio(dag_run) }}`). Ajustavel em `DIAS_DE_JANELA`.

### Por que nao usa `ds`

Duas razoes medidas na auditoria de 17/08/2026, e as duas produziam janela
errada em silencio:

1. **`ds` mudou de significado no Airflow 3.** Uma string de cron agora produz
   `CronTriggerTimetable`, em que `logical_date` e o INSTANTE DO DISPARO, nao o
   inicio de um intervalo (`data_interval_start == data_interval_end`). A
   expressao antiga `{{ macros.ds_add(ds, -6) }} .. {{ ds }}` virava `[D-6, D]`
   e incluia o dia corrente, ainda parcial.
2. **`ds` nao existe em run manual.** Sem `logical_date`, as chaves derivadas
   dela somem do contexto e o template estourava com
   `TypeError: strptime() argument 1 must be str, not StrictUndefined`.

A referencia passou a ser `dag_run.run_after`, campo **obrigatorio** do DagRun
no Airflow 3 (`run_after: UtcDateTime`, sem `| None`): existe nos dois modos e,
no agendado, e o proprio horario de disparo.

## Contrato dos artefatos entre extracao e carga

Cada extracao grava, ao lado do JSON bruto, um **manifesto**
(`temp_meta_raw.manifesto.json`, `temp_google_raw.manifesto.json`) com fonte,
`run_id`, janela, instante, contagem de registros e `sha256` do bruto.

`carrega_bronze` roda com `--run-id` e a janela do run, e so aceita um artefato
que prove pertencer a ele. Sao rejeitados, com falha da task:

| Situacao | Antes | Agora |
|---|---|---|
| JSON sobrado de outro DagRun | ingerido como lote novo | `run_id` nao confere, falha |
| Meta novo + Google velho | metade da execucao entrava | falha antes de qualquer insert |
| Arquivo sem manifesto (legado) | ingerido | falha |
| Arquivo alterado apos a extracao | ingerido | `sha256` nao confere, falha |
| Janela diferente da pedida | invisivel | falha |
| Extracao legitima com 0 registros | `warning` igual ao de arquivo ausente | aceita e registrada como vazia |

A verificacao acontece **antes** de abrir conexao com o banco: uma execucao
invalida nao escreve nada. Sem `--run-id` (uso local, `main.py --skip-extract`)
a checagem e dispensada de proposito — ali os arquivos em disco sao a entrada
pretendida.

## Decisoes de implementacao

**Uma task por etapa, nao um `main.py` so.** Falha isolada e retry seletivo —
uma falha no dbt reexecutaria a extracao das 151 contas (~2 min de API) se
tudo fosse uma task unica. E o grafo na UI passa a descrever a arquitetura.

**BashOperator sobre bind mount, nao DockerOperator.** O projeto inteiro e
montado em `/opt/project` e as tasks rodam os mesmos comandos do terminal. A
alternativa (Airflow lancando o container `etl_app` por task) evitaria misturar
dependencias, mas exigiria expor o socket do Docker ao scheduler.

**A imagem usa a variante `-python3.11`.** A `apache/airflow:3.3.0` sem sufixo
traz Python 3.13, e o pipeline e verificado em 3.11. Orquestrar codigo num
runtime diferente do que foi testado troca uma garantia por uma suposicao.

**A task do dbt chama `main.run_dbt`, e nao `dbt build` direto.** `run_dbt`
deriva `DBT_HOST`/`PORT`/`USER`/`PASSWORD`/`DBNAME` de `DW_DB_URL` via
`config.dbt_env()`. Escrever a conexao de novo na DAG criaria uma segunda fonte
de verdade para o banco — a familia de bug que este repositorio ja pagou tres
vezes.

**Metadados em banco proprio** (`airflow_db`), separado do Data Warehouse.
Estado de orquestracao e dado analitico tem ciclos de vida diferentes; dropar
um nao pode levar o outro.

**Sem `catchup`.** Despausar a DAG nao dispara uma execucao por dia desde a
`start_date`. O historico ja esta na bronze, e reprocessa-lo pela API traria o
nome ATUAL das entidades para datas passadas, achatando as versoes do SCD
Tipo 2 — o mesmo motivo pelo qual 2026-04-07 nao e reextraido.

**Sem task de verificacao de paridade.** O golden
(`scripts/verificar_paridade.py`) congela os agregados para detectar mudanca
acidental durante *refatoracao*. Extracao nova muda numero por definicao — uma
task de paridade na DAG falharia toda execucao bem-sucedida.

## Componentes

O Airflow 3 separou o que o 2 juntava:

| Servico | Papel |
|---|---|
| `airflow-apiserver` | UI e Task Execution API (era `webserver`) |
| `airflow-scheduler` | Agenda e executa (LocalExecutor) |
| `airflow-dag-processor` | Parseia os arquivos de DAG — processo proprio no 3.x |
| `airflow-init` | Roda uma vez: migra o schema e cria o admin |
| `airflow_db` | Postgres de metadados |

## Diagnostico

```bash
# A DAG foi lida?
docker exec tcc_airflow_scheduler airflow dags list
docker exec tcc_airflow_scheduler airflow dags list-import-errors

# O que uma task vai executar, com as datas ja substituidas
docker exec tcc_airflow_scheduler airflow tasks render \
  pipeline_marketing_diario extrai_meta 2026-08-06

# Executar UMA task, sem criar DagRun (as duas abaixo nao chamam API)
docker exec tcc_airflow_scheduler airflow tasks test \
  pipeline_marketing_diario carrega_bronze 2026-08-06
docker exec tcc_airflow_scheduler airflow tasks test \
  pipeline_marketing_diario transforma_dbt 2026-08-06

# Testes do projeto (janela, manifesto, contrato da carga, grafo da DAG).
# Os testes do grafo so rodam onde o Airflow esta instalado; no `etl_app` sao
# pulados.
docker exec tcc_airflow_scheduler bash -c \
  "cd /opt/project && python -m unittest discover -s tests -t ."
```

## Estado da verificacao

Verificado ate aqui: a imagem constroi, os quatro servicos sobem, a DAG e lida
sem erro de import, as tasks `carrega_bronze` e `transforma_dbt` executam
dentro do Airflow — a segunda com os **72 testes dbt passando** (o `PASS=83` do
`dbt build` conta nós: 11 modelos + 72 testes), o que prova o caminho inteiro
(bind mount, import do projeto, `DW_DB_URL` e conexao com o DW).

Em 17/08/2026, **sondas temporarias** (DAGs de duas tasks `echo`/testes, sem
API, removidas em seguida junto com seus metadados) exercitaram pela primeira
vez o caminho completo de execucao: DagRun manual real criado com
`logical_date = NULL`, scheduler enfileirando, LocalExecutor executando,
TaskInstances em `success`, logs persistidos em
`airflow/logs/dag_id=.../run_id=.../task_id=.../attempt=1.log`. A macro de
janela renderizou em execucao real: `inicio=2026-08-10 fim=2026-08-16`. Um run
intermediario **falhou de proposito** e a falha propagou corretamente para o
DagRun — o caminho de erro tambem esta verificado.

A segunda sonda mediu o comportamento com a DAG **pausada**: `dags trigger`
deixa o run em `queued` indefinidamente; `unpause` executa o que estiver
pendente (foram dois DagRuns de uma vez, porque havia um manual enfileirado); e
`dags test --use-executor` roda um unico DagRun sem despausar, mas sem retries.

A terceira sonda validou o procedimento de producao — `unpause` **sozinho**,
sem `trigger`, com `retries=2` e uma task que falha de proposito na primeira
tentativa:

```
DagRun:  scheduled__2026-08-17T09:00:00+00:00 | run_type=scheduled | success   (1 run, 0 manuais)
tasks:   primeira          success  try=1 max_tries=2
         segunda_com_retry up_for_retry try=1  ->  success try=2
scheduler: executor=LocalExecutor(parallelism=32), executor_state=success
janela renderizada no run agendado: 2026-08-10..2026-08-16
```

O historico de tentativas (`task_instance_history`) guarda a tentativa 1 como
`failed` — o retry do Scheduler esta verificado ponta a ponta, sem API.

**Ainda nao executadas: `extrai_meta` e `extrai_google`.** Elas chamam as APIs
de producao e sobrescrevem `temp_meta_raw.json` / `temp_google_raw.json`, que
sao o que sustenta o `--skip-extract`. Alem disso, a janela traz dias que ainda
nao estao no armazem — o que muda os agregados legitimamente e exige recongelar
o golden de proposito.
