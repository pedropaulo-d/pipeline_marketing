-- =====================================================================
-- Queries de demonstracao do Data Warehouse — camadas bronze/silver/gold
-- =====================================================================
-- Uso:
--   docker exec -i tcc_dw psql -U etl -d marketing_dw < docs/queries_demo.sql
-- ou, interativamente:
--   docker exec -it tcc_dw psql -U etl -d marketing_dw
--
-- Objetivo: mostrar que o modelo dimensional responde perguntas de
-- negocio reais, e nao apenas que "os dados entraram no banco".
-- =====================================================================
--
-- ATENCAO AO PERCORRER A HIERARQUIA
--
-- As dimensoes sao SCD Tipo 2: uma entidade renomeada tem mais de uma
-- linha, cada uma valida num intervalo. A chave natural (`_nk`) e estavel
-- entre versoes — por isso liga a hierarquia, e por isso NAO basta para o
-- join. Sem a clausula de validade o join vira 1:N e infla os agregados
-- sem produzir erro nenhum. Medido em 06/08/2026: 3 entidades renomeadas
-- inflaram o investimento total em 7,8%.
--
-- A forma correta aparece em todas as queries abaixo:
--
--     JOIN gold.dim_campanha c
--       ON  c.campanha_nk = s.campanha_nk
--       AND t.data BETWEEN c.valido_de AND c.valido_ate
--
-- Verificacao de um segundo: a soma das linhas por plataforma tem de
-- fechar com o total de gold.fato_metricas. O teste dbt
-- `assert_join_dimensional_nao_infla` automatiza essa conferencia.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. Volumetria por camada — mostra o pipeline inteiro de uma vez
--    A bronze e maior que a gold de proposito: ela acumula um snapshot
--    por extracao, a gold guarda o estado consolidado.
-- ---------------------------------------------------------------------
SELECT 'bronze.raw_ads'      AS objeto, count(*) AS registros FROM bronze.raw_ads
UNION ALL SELECT 'bronze.ingestion_log', count(*) FROM bronze.ingestion_log
UNION ALL SELECT 'silver.stg_ads_unified', count(*) FROM silver.stg_ads_unified
UNION ALL SELECT 'gold.dim_plataforma', count(*) FROM gold.dim_plataforma
UNION ALL SELECT 'gold.dim_conta',      count(*) FROM gold.dim_conta
UNION ALL SELECT 'gold.dim_campanha',   count(*) FROM gold.dim_campanha
UNION ALL SELECT 'gold.dim_adset',      count(*) FROM gold.dim_adset
UNION ALL SELECT 'gold.dim_anuncio',    count(*) FROM gold.dim_anuncio
UNION ALL SELECT 'gold.dim_tempo',      count(*) FROM gold.dim_tempo
UNION ALL SELECT 'gold.fato_metricas',  count(*) FROM gold.fato_metricas
ORDER BY 1;


-- ---------------------------------------------------------------------
-- 2. Comparativo entre plataformas — a pergunta que motiva o projeto
--    (unificar Meta e Google numa mesma base comparavel)
-- ---------------------------------------------------------------------
SELECT p.nome                                              AS plataforma,
       count(*)                                            AS linhas,
       round(sum(f.spend), 2)                              AS investimento,
       sum(f.impressions)                                  AS impressoes,
       sum(f.link_clicks)                                  AS cliques,
       round(sum(f.conversions), 2)                        AS conversoes,
       round(100.0 * sum(f.link_clicks)
             / NULLIF(sum(f.impressions), 0), 2)           AS ctr_pct,
       round(sum(f.spend)
             / NULLIF(sum(f.link_clicks), 0), 2)           AS cpc,
       round(sum(f.spend)
             / NULLIF(sum(f.conversions), 0), 2)           AS cpa
FROM gold.fato_metricas f
JOIN gold.dim_tempo      t  ON t.tempo_sk = f.tempo_sk
JOIN gold.dim_anuncio    a  ON a.anuncio_sk = f.anuncio_sk
JOIN gold.dim_adset      s  ON s.adset_nk = a.adset_nk
                           AND t.data BETWEEN s.valido_de AND s.valido_ate
JOIN gold.dim_campanha   c  ON c.campanha_nk = s.campanha_nk
                           AND t.data BETWEEN c.valido_de AND c.valido_ate
JOIN gold.dim_conta      co ON co.conta_nk = c.conta_nk
                           AND t.data BETWEEN co.valido_de AND co.valido_ate
JOIN gold.dim_plataforma p  ON p.plataforma_sk = co.plataforma_sk
GROUP BY p.nome
ORDER BY investimento DESC;

-- Ressalva metodologica para a defesa: o CPA nao e comparavel de igual
-- para igual entre plataformas — cada uma credita conversoes com seu
-- proprio modelo de atribuicao.


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
FROM gold.fato_metricas f
JOIN gold.dim_tempo      t  ON t.tempo_sk = f.tempo_sk
JOIN gold.dim_anuncio    a  ON a.anuncio_sk = f.anuncio_sk
JOIN gold.dim_adset      s  ON s.adset_nk = a.adset_nk
                           AND t.data BETWEEN s.valido_de AND s.valido_ate
JOIN gold.dim_campanha   c  ON c.campanha_nk = s.campanha_nk
                           AND t.data BETWEEN c.valido_de AND c.valido_ate
JOIN gold.dim_conta      co ON co.conta_nk = c.conta_nk
                           AND t.data BETWEEN co.valido_de AND co.valido_ate
JOIN gold.dim_plataforma p  ON p.plataforma_sk = co.plataforma_sk
GROUP BY p.nome, co.nome, c.nome
ORDER BY investimento DESC
LIMIT 10;


-- ---------------------------------------------------------------------
-- 4. Serie temporal — investimento por dia
-- ---------------------------------------------------------------------
SELECT t.data,
       t.dia_semana,
       round(sum(f.spend), 2) AS investimento,
       sum(f.impressions)     AS impressoes,
       count(*)               AS anuncios_com_entrega
FROM gold.fato_metricas f
JOIN gold.dim_tempo t ON t.tempo_sk = f.tempo_sk
GROUP BY t.data, t.dia_semana
ORDER BY t.data;


-- ---------------------------------------------------------------------
-- 5. PROVA DE IDEMPOTENCIA
--    O grao da fato e (anuncio, dia). Reprocessar o mesmo periodo N vezes
--    nao duplica nenhuma combinacao: a bronze acumula os snapshots e a
--    silver mantem so o mais recente. Resultado esperado: 0 linhas.
--
--    Idempotencia aqui significa "nao duplica", nao "devolve o numero
--    identico": a fonte revisa o passado (cliques invalidados, conversoes
--    creditadas retroativamente), entao os valores podem mudar.
-- ---------------------------------------------------------------------
SELECT anuncio_sk, tempo_sk, count(*) AS ocorrencias
FROM gold.fato_metricas
GROUP BY anuncio_sk, tempo_sk
HAVING count(*) > 1;


-- ---------------------------------------------------------------------
-- 6. Cobertura de metricas por plataforma
--    Evidencia uma limitacao honesta do modelo: a query GAQL do Google
--    nao retorna reach / profile_views / purchases neste nivel, entao
--    essas colunas ficam zeradas para essa plataforma. E ausencia de
--    suporte na consulta, nao ausencia de dado.
--
--    video_views passou a ser extraido em 06/08, mas conta visualizacao
--    TrueView (30s, video completo ou interacao) contra os 3s do Meta —
--    a coluna e comum, a definicao nao. Nao somar entre plataformas.
-- ---------------------------------------------------------------------
SELECT p.nome                                        AS plataforma,
       count(*)                                      AS linhas,
       count(*) FILTER (WHERE f.reach > 0)           AS com_reach,
       count(*) FILTER (WHERE f.video_views > 0)     AS com_video_views,
       count(*) FILTER (WHERE f.conversions > 0)     AS com_conversoes,
       count(*) FILTER (WHERE f.purchases > 0)       AS com_compras
FROM gold.fato_metricas f
JOIN gold.dim_tempo      t  ON t.tempo_sk = f.tempo_sk
JOIN gold.dim_anuncio    a  ON a.anuncio_sk = f.anuncio_sk
JOIN gold.dim_adset      s  ON s.adset_nk = a.adset_nk
                           AND t.data BETWEEN s.valido_de AND s.valido_ate
JOIN gold.dim_campanha   c  ON c.campanha_nk = s.campanha_nk
                           AND t.data BETWEEN c.valido_de AND c.valido_ate
JOIN gold.dim_conta      co ON co.conta_nk = c.conta_nk
                           AND t.data BETWEEN co.valido_de AND co.valido_ate
JOIN gold.dim_plataforma p  ON p.plataforma_sk = co.plataforma_sk
GROUP BY p.nome
ORDER BY p.nome;


-- ---------------------------------------------------------------------
-- 7. SCD TIPO 2 EM ACAO — o relatorio de abril nao e reescrito pela
--    renomeacao de agosto. Cada data exibe o nome vigente a epoca.
--
--    Esta e a query que demonstra por que o versionamento existe. Com
--    SCD Tipo 1 (sobrescrever), as duas linhas exibiriam o nome atual.
-- ---------------------------------------------------------------------
SELECT c.external_id,
       c.versao,
       c.valido_de,
       c.valido_ate,
       c.nome,
       count(*)                AS linhas_do_fato,
       round(sum(f.spend), 2)  AS investimento
FROM gold.dim_campanha c
JOIN gold.dim_adset      s  ON s.campanha_nk = c.campanha_nk
JOIN gold.dim_anuncio    a  ON a.adset_nk = s.adset_nk
JOIN gold.fato_metricas  f  ON f.anuncio_sk = a.anuncio_sk
JOIN gold.dim_tempo      t  ON t.tempo_sk = f.tempo_sk
                           AND t.data BETWEEN c.valido_de AND c.valido_ate
                           AND t.data BETWEEN s.valido_de AND s.valido_ate
WHERE c.campanha_nk IN (
        SELECT campanha_nk FROM gold.dim_campanha
        GROUP BY campanha_nk HAVING count(*) > 1
      )
GROUP BY c.external_id, c.versao, c.valido_de, c.valido_ate, c.nome
ORDER BY c.external_id, c.versao;


-- ---------------------------------------------------------------------
-- 8. DERIVA RETROATIVA — o que so a bronze append-only permite medir
--    Cada extracao de um mesmo dia fica registrada. Comparar dois
--    snapshots do mesmo dia revela quanto a fonte revisou o passado:
--    janela de atribuicao do Meta (ate 28 dias), cliques invalidados
--    pelo Google. Num pipeline que sobrescreve o bruto, essa diferenca
--    seria invisivel.
-- ---------------------------------------------------------------------
WITH snapshots AS (
    SELECT source,
           reference_date,
           extracted_at,
           COALESCE((payload->>'spend')::numeric,
                    (payload->>'cost')::numeric, 0) AS gasto,
           dense_rank() OVER (PARTITION BY source, reference_date
                              ORDER BY extracted_at DESC) AS recencia
    FROM bronze.raw_ads
)
SELECT source,
       reference_date,
       round(sum(gasto) FILTER (WHERE recencia = 2), 2) AS gasto_snapshot_anterior,
       round(sum(gasto) FILTER (WHERE recencia = 1), 2) AS gasto_snapshot_atual,
       round(sum(gasto) FILTER (WHERE recencia = 1)
           - sum(gasto) FILTER (WHERE recencia = 2), 2) AS deriva
FROM snapshots
WHERE recencia <= 2
GROUP BY source, reference_date
HAVING count(*) FILTER (WHERE recencia = 2) > 0
ORDER BY source, reference_date;
