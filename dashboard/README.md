# Dashboard — camada de visualização

Painel analítico em Streamlit + Plotly. É a última camada do pipeline e a
única que se vê em movimento na Defesa.

```
Meta Ads + Google Ads
        ↓  extractors/
      bronze.raw_ads (JSONB, append-only)
        ↓  dbt
      silver (views)  →  gold (tabelas, Snowflake Schema)
        ↓
      gold.vw_metricas_completas
        ↓  scripts/exportar_dataset_exposicao.py
      data/exposicao/metricas.csv        ← superfície pseudonimizada
        ↓
      ESTE DASHBOARD
```

O dashboard é **consumidor** da superfície segura. Ele não anonimiza nada, não
consulta banco e não chama API.

## O que ele pode e não pode consumir

| Pode | Não pode |
|---|---|
| `data/exposicao/metricas.csv` (superfície pseudonimizada) | `bronze.raw_ads` |
| `dashboard/dados_demo/metricas.csv` (sintético versionado) | modelos `silver` |
| o `manifesto.json` que acompanha qualquer um dos dois | tabelas e views `gold` |
| | `temp_*_raw.json` e qualquer arquivo bruto |
| | APIs do Meta Ads e do Google Ads |
| | credenciais de qualquer natureza |

A fronteira é estrutural, não disciplinar:

- `dashboard/dados.py` só sabe ler CSV — não há driver de banco importado em
  lugar nenhum do pacote, e há teste de código-fonte que reprova a
  introdução de um;
- a imagem `dashboard/Dockerfile` instala **apenas** Streamlit e Plotly: não
  existe `psycopg2`, SDK do Meta, SDK do Google nem dbt dentro dela;
- o serviço `dashboard` do compose **não** recebe `env_file: .env` e **não**
  declara `depends_on: db`;
- o dataset entra por bind mount **somente leitura**;
- qualquer arquivo com coluna terminada em `_nk`, `_sk`, `_external_id` ou
  `_nome` é recusado inteiro, com mensagem, antes de qualquer renderização.

## Como executar

### 1. Modo demonstração (não precisa de dado real)

Funciona num clone limpo, sem `.env`, sem banco e sem credencial:

```bash
docker compose up -d dashboard
# http://localhost:8501  →  selo "DADOS DE DEMONSTRACAO"
```

Sem Docker:

```bash
pip install -r dashboard/requirements.txt
DASHBOARD_MODO=demo streamlit run dashboard/app.py
```

O dataset sintético já está versionado em `dashboard/dados_demo/`. Para
regerá-lo (a saída é determinística — mesma semente, mesmo arquivo):

```bash
python dashboard/gerar_dados_demo.py
```

### 2. Modo pseudonimizado (dado real da agência)

Primeiro gere a superfície de exposição a partir do Gold — isso exige o DW no
ar e `PSEUDONIMIZACAO_CHAVE` no `.env`:

```bash
docker compose up -d db
docker compose run --rm etl_app python scripts/exportar_dataset_exposicao.py
docker compose run --rm etl_app python scripts/auditar_dataset_exposicao.py
```

Com `data/exposicao/metricas.csv` presente, o dashboard o adota sozinho:

```bash
docker compose up -d dashboard
# http://localhost:8501  →  selo "DADOS PSEUDONIMIZADOS"
```

O painel escolhe a fonte nesta ordem: `DASHBOARD_DATASET` (caminho explícito)
→ `DASHBOARD_MODO=demo` → superfície de exposição local → dataset sintético.
Não há fallback para banco: sem nenhum dos dois arquivos, a tela explica o que
falta em vez de abrir conexão.

## Período padrão

Ao carregar um dataset, o painel abre nos **últimos sete dias de calendário do
próprio dataset**:

```
data_final   = max(data)
data_inicial = data_final - 6 dias      (recortado por min(data))
```

A âncora é o arquivo, nunca `date.today()` — o artefato é um recorte histórico,
e ancorar no relógio abriria o painel vazio no dia seguinte à exportação. Assim
a mesma superfície sempre abre na mesma tela, o que é o que screenshots e a
Defesa precisam. Dataset com menos de sete dias abre inteiro; a seleção manual
continua livre.

## Tema

As cores estruturais vivem em `.streamlit/config.toml`, na raiz do
repositório. Os controles do Streamlit (select, multiselect, data e popover)
são componentes React que derivam suas cores do tema e ignoram CSS de página.
O arquivo fixa `base = "dark"` independentemente do
`prefers-color-scheme` do navegador e declara um `[theme.sidebar]` coerente.

O Dockerfile copia esse arquivo para `/app/.streamlit/config.toml`, que é o
diretório de trabalho do container. Localmente ele é lido da raiz do
repositório, de onde se roda `streamlit run dashboard/app.py`.

O CSS de layout — container central, densidade, cartões, tipografia, barra
lateral — fica em `componentes.py`. O acabamento dos gráficos é centralizado
em `graficos.aplicar_tema()`.

## Testes

```bash
# Lógica (stdlib pura — roda no container do ETL, sem Streamlit)
docker compose run --rm etl_app python -m unittest tests.test_dashboard

# Com Streamlit e Plotly instalados, os smoke tests da aplicação também rodam
pip install -r dashboard/requirements.txt
python -m unittest tests.test_dashboard
```

## Estrutura

| Arquivo | Papel |
|---|---|
| `dados.py` | Escolha da fonte, leitura do CSV, contrato fail closed, tipagem em `Decimal`. Stdlib pura |
| `metricas.py` | Catálogo das 9 métricas (suporte por plataforma, somabilidade), agregação, indicadores derivados, divisão segura, período anterior, formatação pt-BR. Stdlib pura |
| `filtros.py` | Seleção, opções hierárquicas, saneamento de seleção residual. Stdlib pura |
| `graficos.py` | Figuras Plotly. Única fronteira em que `Decimal` vira `float` |
| `componentes.py` | CSS de layout e blocos de interface (KPI, cabeçalho, seção, selo, tabela) |
| `app.py` | Composição das quatro páginas |
| `gerar_dados_demo.py` | Gerador do dataset sintético |
| `dados_demo/` | Dataset sintético versionado (CSV + manifesto) |
| `../.streamlit/config.toml` | Tema nativo do Streamlit: modo claro forçado no conteúdo, barra lateral escura |

Os três primeiros módulos não importam Streamlit nem Plotly — é o que permite
testá-los no container do ETL, que de propósito não instala as dependências do
painel.
