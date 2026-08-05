/*
    Silver — Meta Ads.

    Desempacota o payload bruto em colunas tipadas. Duas responsabilidades:

    1. Deduplicacao: a bronze e append-only, entao o mesmo dia pode ter sido
       extraido varias vezes. Vence o snapshot mais recente (`extracted_at`),
       o que naturalmente incorpora as revisoes retroativas da janela de
       atribuicao do Meta.
    2. Normalizacao das metricas de `actions` / `action_values`, que a API
       devolve como arrays de {action_type, value} em vez de colunas.
*/

with bruto as (

    select
        reference_date,
        extracted_at,
        payload,
        dense_rank() over (
            partition by reference_date
            order by extracted_at desc
        ) as recencia

    from {{ source('bronze', 'raw_ads') }}
    where source = 'meta_ads'

),

ultimo_snapshot as (

    select *
    from bruto
    where recencia = 1

)

select
    'Meta Ads'                                          as plataforma,
    reference_date                                      as data,

    -- Hierarquia
    payload->>'account_id'                              as conta_external_id,
    payload->>'account_name'                            as conta_nome,
    payload->>'campaign_id'                             as campanha_external_id,
    payload->>'campaign_name'                           as campanha_nome,
    payload->>'adset_id'                                as adset_external_id,
    payload->>'adset_name'                              as adset_nome,
    payload->>'ad_id'                                   as anuncio_external_id,
    payload->>'ad_name'                                 as anuncio_nome,

    -- Metricas diretas
    coalesce((payload->>'spend')::numeric, 0)              as spend,
    coalesce((payload->>'impressions')::bigint, 0)         as impressions,
    coalesce((payload->>'inline_link_clicks')::int, 0)     as link_clicks,
    coalesce((payload->>'reach')::bigint, 0)               as reach,

    -- Metricas derivadas dos arrays de acoes
    -- Numeric por simetria com o Google, que reporta valores fracionados.
    {{ sum_action_value('payload', 'actions', ['lead']) }}::numeric
        as conversions,
    {{ sum_action_value('payload', 'action_values', ['lead']) }}::numeric
        as conversion_value,
    {{ sum_action_value('payload', 'actions', ['video_view']) }}::bigint
        as video_views,
    {{ sum_action_value('payload', 'actions', ['onsite_conversion.ig_profile_view']) }}::int
        as profile_views,
    {{ sum_action_value('payload', 'actions', ['purchase', 'omni_purchase']) }}::int
        as purchases,

    extracted_at

from ultimo_snapshot
