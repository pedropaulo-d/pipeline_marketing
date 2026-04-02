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

```
   Meta Ads API        Google Ads API
        |                    |
        v                    v
  +-----------+      +-----------+
  | meta_ads  |      | google_ads|       EXTRACAO
  +-----------+      +-----------+
        |                    |
        v                    v
   temp_meta_raw.json   temp_google_raw.json
        |                    |
        +--------+-----------+
                 |
                 v
      +--------------------+
      | data_transformer   |             TRANSFORMACAO
      +--------------------+
                 |
          +------+------+
          |             |
          v             v
    temp_fato.csv  temp_dim_ads.csv
          |             |
          +------+------+
                 |
                 v
      +--------------------+
      | supabase_loader    |             CARGA (UPSERT)
      +--------------------+
                 |
                 v
      +--------------------+
      |  PostgreSQL        |
      |  (Star Schema)     |
      |  6 dims + 1 fato   |
      +--------------------+
```

O `main.py` orquestra as tres etapas sequencialmente. Se qualquer etapa falhar, o pipeline interrompe com rollback automatico e exit code 1.

---

## Features

| Feature | Descricao |
|---|---|
| **Idempotencia** | UPSERT via `INSERT ... ON CONFLICT DO UPDATE` — reprocessar o mesmo dia nao duplica dados |
| **Backfill historico** | Argumento `--start-date` / `--end-date` permite carga retroativa de qualquer periodo |
| **Star Schema** | 6 tabelas de dimensao com FK em cascata + 1 tabela fato com 9 metricas |
| **Multi-plataforma** | Meta Ads (Insights API com paginacao) e Google Ads (GAQL) unificados em schema comum |
| **Metricas avancadas** | spend, impressions, link_clicks, conversions, conversion_value, video_views, reach, profile_views, purchases |
| **Transacao atomica** | Carga de dimensoes + fato em transacao unica com rollback em caso de erro |
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
- Banco **PostgreSQL** acessivel (ex: [Supabase](https://supabase.com/))

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
# Preencha todas as variaveis no .env com suas credenciais
```

### 3. Criar as tabelas no banco (primeira vez)

```bash
docker compose run --rm etl_app python -c "
from dotenv import load_dotenv; load_dotenv()
import os; from sqlalchemy import create_engine, text
engine = create_engine(os.getenv('SUPABASE_DB_URL'))
with engine.begin() as c: c.execute(text(open('init_db.sql').read()))
"
```

### 4. Executar o pipeline

```bash
# Pipeline completo — extrai o dia anterior (D-1)
docker compose run --rm etl_app python main.py

# Backfill — carga historica de um periodo especifico
docker compose run --rm etl_app python main.py --start-date 2026-03-01 --end-date 2026-03-31
```

### 5. Execucao de modulos individuais (opcional)

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
|-- config.py                  # Validacao de env vars + mascaramento de logs
|-- main.py                    # Orquestrador ETL (argparse, interrupcao em cascata)
|-- init_db.sql                # DDL do Star Schema (7 tabelas)
|-- Dockerfile                 # Python 3.11-slim, usuario non-root (UID 1000)
|-- docker-compose.yml         # Servico etl_app com env_file
|-- .dockerignore              # Exclui .env, .git, temp_* da imagem
|-- .env_template              # Template de variaveis de ambiente
|-- requirements.txt           # Dependencias Python
|
|-- extractors/
|   |-- meta_ads.py            # Extrator Meta Ads (Insights API + paginacao)
|   |-- google_ads.py          # Extrator Google Ads (GAQL)
|
|-- transformers/
|   |-- data_transformer.py    # Normalizacao, desempacotamento de actions, unificacao
|
|-- loaders/
    |-- supabase_loader.py     # UPSERT em 6 dimensoes + 1 fato (transacao atomica)
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
