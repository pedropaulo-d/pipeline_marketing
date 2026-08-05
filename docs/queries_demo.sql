-- =====================================================================
-- Queries de demonstracao do Data Warehouse
-- =====================================================================
-- Uso:
--   docker exec -it tcc_dw psql -U etl -d marketing_dw -f /app/docs/queries_demo.sql
-- ou, interativamente:
--   docker exec -it tcc_dw psql -U etl -d marketing_dw
--
-- Objetivo: mostrar que o modelo dimensional responde perguntas de
-- negocio reais, e nao apenas que "os dados entraram no banco".
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. Volumetria por tabela — visao geral da carga
-- ---------------------------------------------------------------------
SELECT 'dim_plataforma' AS tabela, count(*) AS registros FROM dim_plataforma
UNION ALL SELECT 'dim_conta',      count(*) FROM dim_conta
UNION ALL SELECT 'dim_campanha',   count(*) FROM dim_campanha
UNION ALL SELECT 'dim_adset',      count(*) FROM dim_adset
UNION ALL SELECT 'dim_anuncio',    count(*) FROM dim_anuncio
UNION ALL SELECT 'dim_tempo',      count(*) FROM dim_tempo
UNION ALL SELECT 'fato_metricas',  count(*) FROM fato_metricas
ORDER BY 1;


-- ---------------------------------------------------------------------
-- 2. Comparativo entre plataformas — a pergunta que motiva o projeto
--    (unificar Meta e Google numa mesma base comparavel)
-- ---------------------------------------------------------------------
SELECT p.nome                                              AS plataforma,
       round(sum(f.spend), 2)                              AS investimento,
       sum(f.impressions)                                  AS impressoes,
       sum(f.link_clicks)                                  AS cliques,
       sum(f.conversions)                                  AS conversoes,
       round(100.0 * sum(f.link_clicks)
             / NULLIF(sum(f.impressions), 0), 2)           AS ctr_pct,
       round(sum(f.spend)
             / NULLIF(sum(f.link_clicks), 0), 2)           AS cpc,
       round(sum(f.spend)
             / NULLIF(sum(f.conversions), 0), 2)           AS cpa
FROM fato_metricas f
JOIN dim_anuncio    a  ON a.id  = f.anuncio_id
JOIN dim_adset      s  ON s.id  = a.adset_id
JOIN dim_campanha   c  ON c.id  = s.campanha_id
JOIN dim_conta      co ON co.id = c.conta_id
JOIN dim_plataforma p  ON p.id  = co.plataforma_id
GROUP BY p.nome
ORDER BY investimento DESC;


-- ---------------------------------------------------------------------
-- 3. Top 10 campanhas por investimento — percorre a hierarquia completa
--    do Snowflake Schema (5 niveis de dimensao)
-- ---------------------------------------------------------------------
SELECT p.nome                                              AS plataforma,
       co.nome                                             AS conta,
       c.nome                                              AS campanha,
       round(sum(f.spend), 2)                              AS investimento,
       sum(f.impressions)                                  AS impressoes,
       sum(f.link_clicks)                                  AS cliques,
       round(100.0 * sum(f.link_clicks)
             / NULLIF(sum(f.impressions), 0), 2)           AS ctr_pct
FROM fato_metricas f
JOIN dim_anuncio    a  ON a.id  = f.anuncio_id
JOIN dim_adset      s  ON s.id  = a.adset_id
JOIN dim_campanha   c  ON c.id  = s.campanha_id
JOIN dim_conta      co ON co.id = c.conta_id
JOIN dim_plataforma p  ON p.id  = co.plataforma_id
GROUP BY p.nome, co.nome, c.nome
ORDER BY investimento DESC
LIMIT 10;


-- ---------------------------------------------------------------------
-- 4. Serie temporal — investimento por dia
--    (com um unico dia carregado, evidencia a necessidade do backfill)
-- ---------------------------------------------------------------------
SELECT t.data,
       t.dia_semana,
       round(sum(f.spend), 2) AS investimento,
       sum(f.impressions)     AS impressoes,
       count(*)               AS anuncios_ativos
FROM fato_metricas f
JOIN dim_tempo t ON t.id = f.tempo_id
GROUP BY t.data, t.dia_semana
ORDER BY t.data;


-- ---------------------------------------------------------------------
-- 5. PROVA DE IDEMPOTENCIA
--    O grao da fato e (anuncio, dia). Se o UPSERT estiver correto,
--    nenhuma combinacao aparece mais de uma vez, mesmo apos N execucoes
--    do pipeline sobre o mesmo periodo. Resultado esperado: 0 linhas.
-- ---------------------------------------------------------------------
SELECT anuncio_id, tempo_id, count(*) AS ocorrencias
FROM fato_metricas
GROUP BY anuncio_id, tempo_id
HAVING count(*) > 1;


-- ---------------------------------------------------------------------
-- 6. Cobertura de metricas por plataforma
--    Evidencia uma limitacao honesta do modelo atual: a query GAQL do
--    Google nao retorna reach / video_views / purchases neste nivel,
--    entao essas colunas ficam zeradas para essa plataforma.
-- ---------------------------------------------------------------------
SELECT p.nome                                        AS plataforma,
       count(*)                                      AS linhas,
       count(*) FILTER (WHERE f.reach > 0)           AS com_reach,
       count(*) FILTER (WHERE f.video_views > 0)     AS com_video_views,
       count(*) FILTER (WHERE f.conversions > 0)     AS com_conversoes,
       count(*) FILTER (WHERE f.purchases > 0)       AS com_compras
FROM fato_metricas f
JOIN dim_anuncio    a  ON a.id  = f.anuncio_id
JOIN dim_adset      s  ON s.id  = a.adset_id
JOIN dim_campanha   c  ON c.id  = s.campanha_id
JOIN dim_conta      co ON co.id = c.conta_id
JOIN dim_plataforma p  ON p.id  = co.plataforma_id
GROUP BY p.nome;
