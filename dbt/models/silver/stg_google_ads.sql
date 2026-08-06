/*
    Silver — Google Ads.

    Mesma deduplicacao por recencia da stg_meta_ads. A query GAQL ja devolve
    metricas em colunas, entao aqui o trabalho e sobretudo renomear para o
    vocabulario comum e explicitar as metricas que a plataforma nao fornece
    neste nivel de consulta.

    `reach`, `profile_views` e `purchases` ficam em zero: nao e ausencia de
    dado, e ausencia de suporte da API neste grao. A distincao esta
    documentada e e verificavel na silver.

    `video_views` passou a ser extraido, de metrics.video_trueview_views.
    Lotes da bronze anteriores a essa mudanca nao trazem a chave no payload e
    caem no coalesce -> 0; reextrair o periodo cria um snapshot novo, que
    vence a deduplicacao por recencia e preenche o valor real.

    ATENCAO — a coluna e comum, a definicao nao. O Google conta visualizacao
    TrueView (30 segundos, video completo ou interacao); o Meta conta a partir
    de 3 segundos. O valor e valido dentro de cada plataforma e comparavel ao
    longo do tempo, mas somar ou dividir uma pela outra nao tem significado.
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
    where source = 'google_ads'

),

ultimo_snapshot as (

    select *
    from bruto
    where recencia = 1

)

select
    'Google Ads'                                        as plataforma,
    reference_date                                      as data,

    -- Hierarquia (ad_group do Google equivale ao adset do Meta)
    payload->>'account_id'                              as conta_external_id,
    payload->>'account_name'                            as conta_nome,
    payload->>'campaign_id'                             as campanha_external_id,
    payload->>'campaign_name'                           as campanha_nome,
    payload->>'ad_group_id'                             as adset_external_id,
    payload->>'ad_group_name'                           as adset_nome,
    payload->>'ad_id'                                   as anuncio_external_id,
    payload->>'ad_name'                                 as anuncio_nome,

    -- Metricas disponiveis
    coalesce((payload->>'cost')::numeric, 0)               as spend,
    coalesce((payload->>'impressions')::bigint, 0)         as impressions,
    coalesce((payload->>'clicks')::int, 0)                 as link_clicks,

    -- Numeric, nao inteiro: o Google reporta conversoes fracionadas por
    -- efeito da modelagem de atribuicao (uma conversao pode ser creditada
    -- parcialmente a varios anuncios). Arredondar aqui descartaria
    -- informacao real da fonte.
    coalesce((payload->>'conversions')::numeric, 0)        as conversions,
    coalesce((payload->>'conversions_value')::numeric, 0)  as conversion_value,
    coalesce((payload->>'video_trueview_views')::bigint, 0) as video_views,

    -- Nao fornecidas pela GAQL neste nivel
    0::bigint                                           as reach,
    0::int                                              as profile_views,
    0::int                                              as purchases,

    extracted_at

from ultimo_snapshot
