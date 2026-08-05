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
    start_date      DATE        NOT NULL,
    end_date        DATE        NOT NULL,
    row_count       INT         NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE bronze.ingestion_log IS
    'Registro de cada carga na bronze — base de observabilidade do pipeline.';
