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

Para executar uma vez, sem agendar, pela UI: *Trigger DAG*. Pelo terminal:

```bash
docker exec tcc_airflow_scheduler airflow dags trigger pipeline_marketing_diario
```

## Janela movel de 7 dias

Cada execucao reextrai os **ultimos 7 dias**, nao apenas o dia anterior.

As metricas do Meta mudam retroativamente por ate 28 dias (janela de
atribuicao): o valor do dia D consultado em D+1 nao e o mesmo consultado em
D+7. Extrair so o dia anterior congelaria numeros que ainda vao mudar.

Isso e seguro porque duas decisoes anteriores ja sustentavam o reprocessamento:
a bronze e append-only (reextrair cria lote novo, nao sobrescreve) e a silver
adota o snapshot mais recente de cada dia. Efeito colateral util: a deriva
retroativa fica **registrada e mensuravel** na bronze.

Ajustavel em `DIAS_DE_JANELA`, no topo da DAG.

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
```

## Estado da verificacao

Verificado ate aqui: a imagem constroi, os quatro servicos sobem, a DAG e lida
sem erro de import, a janela renderiza `--start-date 2026-07-31 --end-date
2026-08-06` para `ds=2026-08-06`, e as tasks `carrega_bronze` e
`transforma_dbt` executam dentro do Airflow — a segunda com os **72 testes dbt
passando** (o `PASS=83` do `dbt build` conta nós: 11 modelos + 72 testes), o
que prova o caminho inteiro (bind mount, import do projeto,
`DW_DB_URL` e conexao com o DW).

**Ainda nao executadas: `extrai_meta` e `extrai_google`.** Elas chamam as APIs
de producao e sobrescrevem `temp_meta_raw.json` / `temp_google_raw.json`, que
sao o que sustenta o `--skip-extract`. Alem disso, a janela de 7 dias traz dias
que ainda nao estao no armazem — o que muda os agregados legitimamente e exige
recongelar o golden de proposito.
