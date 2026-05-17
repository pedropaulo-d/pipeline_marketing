-- =============================================
-- Snowflake Schema: Pipeline de Dados de Marketing
-- =============================================
-- Dimensoes normalizadas em cadeia (FK entre dimensoes):
-- Plataforma -> Conta -> Campanha -> AdSet -> Anuncio -> Fato
-- dim_tempo conecta direto ao fato.

-- Dimensão: Plataforma
CREATE TABLE dim_plataforma (
    id          SERIAL PRIMARY KEY,
    nome        VARCHAR(50) NOT NULL UNIQUE
);

-- Dimensão: Conta
CREATE TABLE dim_conta (
    id              SERIAL PRIMARY KEY,
    external_id     VARCHAR(100) NOT NULL,
    nome            VARCHAR(255) NOT NULL,
    plataforma_id   INT NOT NULL REFERENCES dim_plataforma(id) ON DELETE RESTRICT,
    UNIQUE (external_id, plataforma_id)
);

-- Dimensão: Campanha
CREATE TABLE dim_campanha (
    id              SERIAL PRIMARY KEY,
    external_id     VARCHAR(100) NOT NULL,
    nome            VARCHAR(255) NOT NULL,
    conta_id        INT NOT NULL REFERENCES dim_conta(id) ON DELETE RESTRICT,
    UNIQUE (external_id, conta_id)
);

-- Dimensão: Conjunto de Anúncios (AdSet)
CREATE TABLE dim_adset (
    id              SERIAL PRIMARY KEY,
    external_id     VARCHAR(100) NOT NULL,
    nome            VARCHAR(255) NOT NULL,
    campanha_id     INT NOT NULL REFERENCES dim_campanha(id) ON DELETE RESTRICT,
    UNIQUE (external_id, campanha_id)
);

-- Dimensão: Anúncio (Ad)
CREATE TABLE dim_anuncio (
    id              SERIAL PRIMARY KEY,
    external_id     VARCHAR(100) NOT NULL,
    nome            VARCHAR(255) NOT NULL,
    adset_id        INT NOT NULL REFERENCES dim_adset(id) ON DELETE RESTRICT,
    UNIQUE (external_id, adset_id)
);

-- Dimensão: Tempo
CREATE TABLE dim_tempo (
    id          SERIAL PRIMARY KEY,
    data        DATE NOT NULL UNIQUE,
    dia         SMALLINT NOT NULL,
    mes         SMALLINT NOT NULL,
    ano         SMALLINT NOT NULL,
    trimestre   SMALLINT NOT NULL,
    dia_semana  SMALLINT NOT NULL
);

-- Tabela Fato: Métricas de Performance Diária
CREATE TABLE fato_metricas (
    id                  SERIAL PRIMARY KEY,
    anuncio_id          INT NOT NULL REFERENCES dim_anuncio(id) ON DELETE RESTRICT,
    tempo_id            INT NOT NULL REFERENCES dim_tempo(id) ON DELETE RESTRICT,
    spend               NUMERIC(12, 4) NOT NULL DEFAULT 0,
    impressions         BIGINT NOT NULL DEFAULT 0,
    link_clicks         INT NOT NULL DEFAULT 0,
    conversions         INT NOT NULL DEFAULT 0,
    conversion_value    NUMERIC(14, 4) NOT NULL DEFAULT 0,
    video_views         BIGINT NOT NULL DEFAULT 0,
    reach               BIGINT NOT NULL DEFAULT 0,
    profile_views       INT NOT NULL DEFAULT 0,
    purchases           INT NOT NULL DEFAULT 0,
    UNIQUE (anuncio_id, tempo_id)
);
