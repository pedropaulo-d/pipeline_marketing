-- =====================================================================
-- Camada BRONZE — dado bruto imutavel
-- =====================================================================
-- Recebe o payload das APIs exatamente como veio, sem transformacao.
-- E APPEND-ONLY: reprocessar um mesmo dia nao sobrescreve nada, gera um
-- novo lote. Isso preserva o historico das respostas da API e permite:
--
--   1. reprocessar as camadas superiores sem chamar a API de novo;
--   2. medir a deriva retroativa das metricas — a janela de atribuicao
--      do Meta revisa conversoes por ate 28 dias, entao o mesmo dia
--      extraido em momentos diferentes traz numeros diferentes.
--
-- A deduplicacao ("ultimo snapshot vence") acontece na camada silver.

CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.raw_ads (
    id              BIGSERIAL   PRIMARY KEY,
    source          TEXT        NOT NULL
                                CHECK (source IN ('meta_ads', 'google_ads')),
    reference_date  DATE        NOT NULL,
    extracted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    batch_id        UUID        NOT NULL,
    payload         JSONB       NOT NULL
);

COMMENT ON TABLE  bronze.raw_ads IS
    'Payload bruto das APIs de anuncios. Append-only, imutavel.';
COMMENT ON COLUMN bronze.raw_ads.source IS
    'Plataforma de origem do registro.';
COMMENT ON COLUMN bronze.raw_ads.reference_date IS
    'Dia a que a metrica se refere (nao o dia da extracao).';
COMMENT ON COLUMN bronze.raw_ads.extracted_at IS
    'Momento da extracao. Define qual snapshot vence na silver.';
COMMENT ON COLUMN bronze.raw_ads.batch_id IS
    'Identificador da execucao que gerou o lote.';

-- Filtro mais comum da silver: fonte + dia de referencia.
CREATE INDEX IF NOT EXISTS idx_raw_ads_source_date
    ON bronze.raw_ads (source, reference_date, extracted_at DESC);

-- Consultas exploratorias sobre o JSON bruto.
CREATE INDEX IF NOT EXISTS idx_raw_ads_payload
    ON bronze.raw_ads USING GIN (payload);

-- Auditoria das execucoes: responde "o pipeline rodou? quando? trouxe quanto?"
CREATE TABLE IF NOT EXISTS bronze.ingestion_log (
    batch_id        UUID        PRIMARY KEY,
    source          TEXT        NOT NULL,
    run_id          TEXT,
    start_date      DATE        NOT NULL,
    end_date        DATE        NOT NULL,
    row_count       INT         NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Evolucao para bancos que nasceram antes do `run_id`. O DDL inteiro e
-- reaplicado a cada carga por `ensure_schema`, entao banco novo (que ja nasce
-- com a coluna no CREATE TABLE acima) e banco existente convergem para a mesma
-- forma sem passo manual. Sem isso as duas instalacoes divergiriam: o
-- `CREATE TABLE IF NOT EXISTS` nao altera tabela que ja existe.
ALTER TABLE bronze.ingestion_log
    ADD COLUMN IF NOT EXISTS run_id TEXT;

-- Idempotencia da carga, no banco.
--
-- `batch_id` identifica o lote FISICO: e sorteado a cada carga, entao rodar o
-- mesmo artefato duas vezes produzia dois lotes distintos e duplicava a
-- bronze. `run_id` identifica a execucao LOGICA que produziu o artefato, e e
-- o que nao pode ser confirmado duas vezes.
--
-- A chave e (source, run_id), nao `run_id` sozinho: um mesmo run carrega Meta
-- e Google, cada um com seu lote, e as duas linhas sao legitimas.
--
-- Parcial porque `run_id` e nulo em dois casos legitimos: os lotes anteriores
-- a esta mudanca e a carga local (`main.py --skip-extract`), que nao tem
-- execucao de origem para declarar. Em Postgres NULL nao colide com NULL num
-- indice unico comum, mas o `WHERE` deixa a intencao escrita em vez de
-- depender desse detalhe.
--
-- E a ultima linha de defesa: o loader consulta antes de inserir, mas duas
-- cargas simultaneas podem consultar juntas e nao ver uma a outra. Aqui so
-- uma confirma; a outra falha e leva junto, no rollback, as linhas que ja
-- tinha inserido em raw_ads.
CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_log_source_run_id
    ON bronze.ingestion_log (source, run_id)
    WHERE run_id IS NOT NULL;

COMMENT ON TABLE bronze.ingestion_log IS
    'Registro de cada carga na bronze — base de observabilidade do pipeline.';
COMMENT ON COLUMN bronze.ingestion_log.run_id IS
    'Execucao logica que produziu o artefato. Unica por fonte; nula na carga local e nos lotes anteriores a esta coluna.';
