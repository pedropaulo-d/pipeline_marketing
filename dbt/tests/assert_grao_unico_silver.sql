/*
    A silver unificada deve ter no maximo uma linha por anuncio por dia.
    Uma falha aqui indica deduplicacao incorreta na bronze — tipicamente
    dois snapshots do mesmo dia com o mesmo `extracted_at`.
*/

select
    anuncio_nk,
    data,
    count(*) as ocorrencias

from {{ ref('stg_ads_unified') }}

group by anuncio_nk, data
having count(*) > 1
