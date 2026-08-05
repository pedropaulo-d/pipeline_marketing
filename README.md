# Pipeline de Dados — Marketing Digital

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-4169E1?logo=postgresql&logoColor=white)
![Meta Ads](https://img.shields.io/badge/Meta_Ads-API-0081FB?logo=meta&logoColor=white)
![Google Ads](https://img.shields.io/badge/Google_Ads-API-4285F4?logo=googleads&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

Motor ETL containerizado que extrai metricas diarias de campanhas do **Meta Ads** e **Google Ads**, transforma em um schema unificado e carrega em um banco **PostgreSQL** via UPSERT idempotente. Projetado como trabalho de conclusao de curso (TCC) em Engenharia de Dados.

---

## Arquitetura

Pipeline **ELT em camadas** (bronze → silver → gold). O caminho ETL original
continua disponivel via `--mode etl` para fins de comparacao.

```mermaid
flowchart TD
    META["Meta Ads API"]
    GADS["Google Ads API"]
    EXT["extractors/ · Python"]

    subgraph BRONZE["BRONZE · imutavel"]
        RAW[("bronze.raw_ads<br/>JSONB append-only")]
        LOG[("bronze.ingestion_log")]
    end

    subgraph SILVER["SILVER · dbt views"]
        SU["stg_meta_ads · stg_google_ads<br/>stg_ads_unified"]
    end

    subgraph GOLD["GOLD · dbt tables"]
        DIM["6 dimensoes<br/>Snowflake Schema"]
        FATO["fato_metricas"]
    end

    META --> EXT
    GADS --> EXT
    EXT --> RAW
    EXT --> LOG
    RAW --> SU
    SU --> DIM
    SU --> FATO
    DIM --> FATO
```

O `main.py` orquestra extracao → carga bronze → `dbt build` (transformacao +
testes). Se qualquer etapa falhar, o pipeline interrompe com exit code 1.

Detalhes de projeto, validacao e limitacoes em
[`docs/arquitetura-elt.md`](docs/arquitetura-elt.md).

---

## Features

| Feature | Descricao |
|---|---|
| **Arquitetura em camadas** | Bronze (JSONB bruto, append-only) → Silver (limpeza e unificacao) → Gold (modelo dimensional) |
| **Idempotencia** | Reprocessar o mesmo periodo nao altera o resultado da gold; a bronze acumula snapshots e a silver mantem o mais recente |
| **Testes de dados** | 65 testes dbt: unicidade, nao-nulidade, dominios e integridade referencial entre fato e dimensoes |
| **Rastreabilidade** | Dado bruto preservado permite reprocessar todas as camadas sem chamar a API novamente |
| **Observabilidade** | `bronze.ingestion_log` registra lote, fonte, periodo e volume de cada carga |
| **Backfill historico** | Argumento `--start-date` / `--end-date` permite carga retroativa de qualquer periodo |
| **Snowflake Schema** | 5 dimensoes normalizadas em cadeia (Plataforma -> Conta -> Campanha -> AdSet -> Anuncio) + dim_tempo + 1 tabela fato com 9 metricas |
| **Multi-plataforma** | Meta Ads (Insights API com paginacao) e Google Ads (GAQL) unificados em schema comum |
| **Metricas avancadas** | spend, impressions, link_clicks, conversions, conversion_value, video_views, reach, profile_views, purchases |
| **DevSecOps** | Container non-root, mascaramento de logs (`mask()`), validacao fail-fast de env vars, zero SQL injection |

---

## Modelo de Dados

```sql
-- Dimensoes (hierarquia com FK em cascata)
dim_plataforma   → UNIQUE(nome)
dim_conta        → UNIQUE(external_id, plataforma_id)
dim_campanha     → UNIQUE(external_id, conta_id)
dim_adset        → UNIQUE(external_id, campanha_id)
dim_anuncio      → UNIQUE(external_id, adset_id)
dim_tempo        → UNIQUE(data)

-- Tabela Fato
fato_metricas    → UNIQUE(anuncio_id, tempo_id)
  Metricas: spend | impressions | link_clicks | conversions
            conversion_value | video_views | reach
            profile_views | purchases
```

---

## Pre-requisitos

- [Docker](https://docs.docker.com/get-docker/) e [Docker Compose](https://docs.docker.com/compose/install/)
- Credenciais de API do **Meta Ads** (App ID, App Secret, Access Token, Business ID)
- Credenciais de API do **Google Ads** (Developer Token, Client ID/Secret, Refresh Token, Login Customer ID)

O Data Warehouse sobe junto com o projeto (PostgreSQL 16 em container), entao
nao e necessario nenhum banco externo. Para carregar num Postgres gerenciado
(ex: [Supabase](https://supabase.com/)), basta apontar `DW_DB_URL` para ele.

---

## Como Rodar

### 1. Clonar o repositorio

```bash
git clone https://github.com/<seu-usuario>/tcc_pipeline_dados.git
cd tcc_pipeline_dados
```

### 2. Configurar variaveis de ambiente

```bash
cp .env_template .env
# Preencha as credenciais das APIs no .env
```

### 3. Subir o Data Warehouse

```bash
docker compose up -d db
```

O schema (`init_db.sql`) e aplicado automaticamente na primeira subida.
O banco fica exposto em `localhost:5433` (usuario `etl`, senha `etl`,
database `marketing_dw`).

### 4. Executar o pipeline

```bash
# Pipeline completo em modo ELT (default) — extrai o dia anterior (D-1)
docker compose run --rm etl_app python main.py

# Backfill — carga historica de um periodo especifico
docker compose run --rm etl_app python main.py --start-date 2026-03-01 --end-date 2026-03-31

# Apenas uma plataforma (util quando as credenciais da outra estao indisponiveis)
docker compose run --rm etl_app python main.py --platforms meta

# Reprocessar os dados brutos ja extraidos, sem consumir a API
docker compose run --rm etl_app python main.py --skip-extract

# Caminho ETL original (transformacao em pandas, carga no schema public)
docker compose run --rm etl_app python main.py --mode etl
```

### 4.1. Transformacoes e testes isolados

```bash
# Materializa silver e gold e roda os 65 testes de dados
docker compose run --rm -e DBT_PROFILES_DIR=/app/dbt -w /app/dbt etl_app dbt build

# Apenas os testes
docker compose run --rm -e DBT_PROFILES_DIR=/app/dbt -w /app/dbt etl_app dbt test

# Documentacao navegavel com grafo de lineage
docker compose run --rm -e DBT_PROFILES_DIR=/app/dbt -w /app/dbt etl_app dbt docs generate
```

### 5. Consultar o Data Warehouse

```bash
# Queries analiticas de demonstracao (inclui a prova de idempotencia)
docker exec -i tcc_dw psql -U etl -d marketing_dw < docs/queries_demo.sql

# Sessao interativa
docker exec -it tcc_dw psql -U etl -d marketing_dw
```

### 6. Execucao de modulos individuais (opcional)

```bash
# Apenas extracao
docker compose run --rm etl_app python extractors/meta_ads.py --start-date 2026-03-30 --end-date 2026-03-31

# Apenas transformacao
docker compose run --rm etl_app python transformers/data_transformer.py

# Apenas carga
docker compose run --rm etl_app python loaders/supabase_loader.py
```

---

## Estrutura do Projeto

```
tcc_pipeline_dados/
|-- config.py                  # Env vars, mascaramento de logs, conexao do dbt
|-- main.py                    # Orquestrador (--mode elt|etl)
|-- init_db.sql                # DDL do Snowflake Schema do caminho ETL
|-- Dockerfile                 # Python 3.11-slim, usuario non-root (UID 1000)
|-- docker-compose.yml         # Servicos db (PostgreSQL 16) e etl_app
|-- requirements.txt           # Dependencias Python (inclui dbt-postgres)
|
|-- extractors/
|   |-- meta_ads.py            # Extrator Meta Ads (Insights API + paginacao)
|   |-- google_ads.py          # Extrator Google Ads (GAQL)
|
|-- loaders/
|   |-- bronze_loader.py       # ELT: carga do JSON bruto na bronze
|   |-- supabase_loader.py     # ETL: UPSERT em 6 dimensoes + 1 fato
|
|-- transformers/
|   |-- data_transformer.py    # ETL: transformacao em pandas
|
|-- sql/bronze/
|   |-- init_bronze.sql        # DDL da camada bronze + log de ingestao
|
|-- dbt/
|   |-- dbt_project.yml
|   |-- profiles.yml
|   |-- macros/                # generate_schema_name, sum_action_value
|   |-- models/
|   |   |-- silver/            # stg_meta_ads, stg_google_ads, stg_ads_unified
|   |   |-- gold/              # 6 dimensoes + fato_metricas
|   |-- tests/                 # testes singulares (grao, metricas negativas)
|
|-- scripts/
|   |-- generate_google_refresh_token.py
|   |-- oauth_manual.py        # Fluxo OAuth manual em dois passos
|
|-- docs/
    |-- arquitetura-elt.md     # Projeto das camadas e validacao de paridade
    |-- der.md                 # Diagrama entidade-relacionamento
    |-- queries_demo.sql       # Queries analiticas de demonstracao
    |-- reuniao-orientador.md  # Material de orientacao academica
```

---

## Seguranca

Este projeto passou por uma auditoria de seguranca (DevSecOps) cobrindo:

- **Credenciais nos logs**: todos os IDs sensiveis mascarados via `config.mask()`; tracebacks sanitizados para nao expor tokens
- **SQL Injection**: 100% das queries usam bind parameters via SQLAlchemy; zero concatenacao de strings em SQL
- **Validacao de ambiente**: `config.validate_env()` verifica 11 variaveis obrigatorias no startup com fail-fast
- **Container hardening**: Dockerfile executa como usuario non-root (`etl`, UID 1000); `.dockerignore` impede que `.env` e `.git` entrem na imagem
- **Repositorio**: `.gitignore` exclui `.env` e arquivos temporarios

---

## Stack Tecnica

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.11 |
| Container | Docker / Docker Compose |
| Extracao | facebook-business SDK, google-ads SDK |
| Transformacao | pandas |
| Carga | SQLAlchemy + psycopg2-binary |
| Banco | PostgreSQL (Supabase) |
| Seguranca | python-dotenv, config.py (mask + validate_env) |

---

## Licenca

Este projeto e distribuido sob a licenca MIT. Consulte o arquivo `LICENSE` para mais detalhes.
