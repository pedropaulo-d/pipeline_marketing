/*
    Falha quando um anuncio que ja teve gasto positivo na Bronze desaparece da
    Silver. A Silver mantem a observacao mais recente por entidade/dia: um
    registro posterior atualiza metricas, mas a ausencia sem tombstone nao
    apaga a ultima observacao valida.

    Foi uma perda desse tipo que revelou dois filtros por estado atual: o de
    campanha na GAQL, corrigido anteriormente, e o de conta na descoberta
    Meta. Contar linhas por lote nao basta, porque entradas novas podem ocultar
    a subtracao de entidades antigas.

    A comparacao cobre TODO o historico, nao apenas o snapshot imediatamente
    anterior. Isso pega omissoes consecutivas e continua aceitando zero
    explicito: se a entidade vier num lote novo com gasto zero, ela existe na
    Silver e sua observacao mais recente vence.
*/

with historico_positivo as (

    select
        source,
        reference_date,
        payload->>'account_id' as conta_id,
        payload->>'campaign_id' as campanha_id,
        coalesce(payload->>'adset_id', payload->>'ad_group_id') as adset_id,
        payload->>'ad_id' as anuncio_id

    from {{ source('bronze', 'raw_ads') }}
    where coalesce(
        (payload->>'spend')::numeric,
        (payload->>'cost')::numeric,
        0
    ) > 0
    group by 1, 2, 3, 4, 5, 6

),

silver as (

    select
        'meta_ads' as source,
        data as reference_date,
        conta_external_id as conta_id,
        campanha_external_id as campanha_id,
        adset_external_id as adset_id,
        anuncio_external_id as anuncio_id
    from {{ ref('stg_meta_ads') }}

    union all

    select
        'google_ads' as source,
        data as reference_date,
        conta_external_id as conta_id,
        campanha_external_id as campanha_id,
        adset_external_id as adset_id,
        anuncio_external_id as anuncio_id
    from {{ ref('stg_google_ads') }}

)

select
    historico_positivo.*

from historico_positivo

left join silver
    using (source, reference_date, conta_id, campanha_id, adset_id, anuncio_id)

where silver.anuncio_id is null
