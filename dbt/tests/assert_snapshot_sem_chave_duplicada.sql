/*
    Um unico lote nao pode trazer duas linhas para a mesma entidade/dia.

    A deduplicacao usa dense_rank de proposito: empate de extracted_at nao e
    resolvido arbitrariamente. Se a fonte ou o loader duplicar a chave dentro
    do batch, as duas linhas sobrevivem e este teste (alem do teste de grao)
    falha fechado.
*/

with chaves as (

    select
        source,
        reference_date,
        batch_id,
        payload->>'account_id' as conta_id,
        payload->>'campaign_id' as campanha_id,
        coalesce(payload->>'adset_id', payload->>'ad_group_id') as adset_id,
        payload->>'ad_id' as anuncio_id
    from {{ source('bronze', 'raw_ads') }}

)

select
    source,
    reference_date,
    batch_id,
    conta_id,
    campanha_id,
    adset_id,
    anuncio_id,
    count(*) as ocorrencias
from chaves
group by 1, 2, 3, 4, 5, 6, 7
having count(*) > 1
