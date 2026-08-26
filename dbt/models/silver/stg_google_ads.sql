/*
    Silver — Google Ads.

    Mesma deduplicacao por ultima observacao de entidade/dia da stg_meta_ads.
    A query GAQL ja devolve metricas em colunas, entao aqui o trabalho e
    sobretudo renomear para o vocabulario comum e explicitar as metricas que a
    plataforma nao fornece neste nivel de consulta.

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

with ultimo_snapshot as (

    {{ ultimo_snapshot(
        'google_ads',
        ['account_id', 'campaign_id', 'ad_group_id', 'ad_id']
    ) }}

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

    -- Metricas disponiveis.
    -- A ORDEM importa e e a mesma de stg_meta_ads — ver o comentario la e o
    -- teste assert_staging_mesmo_contrato.
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

    -- Nao fornecidas pela GAQL neste nivel. Zero aqui e AUSENCIA DE SUPORTE,
    -- nao desempenho medido — a convencao nao-nula do contrato unificado e
    -- mantida, e quem apresenta o numero e responsavel por dizer isso.
    -- `purchase_value` em especial NAO recebe `conversions_value`: o valor de
    -- conversao do Google agrega todas as conversion actions da conta, nao so
    -- compras. Sao conceitos diferentes e nao se substituem.
    0::bigint                                           as reach,
    0::int                                              as profile_views,
    0::int                                              as purchases,
    0::numeric                                          as purchase_value,

    -- A familia Resultado/Custo por Resultado e semantica oficial do Meta.
    -- NULL significa ausencia de suporte, nao resultado zero e nao conversao
    -- Google reinterpretada.
    null::text                                          as result_type,
    null::numeric                                       as result_count,
    null::text                                          as result_attribution_window,
    null::numeric                                       as cost_per_result,
    null::text                                          as objective,
    null::text                                          as optimization_goal,

    -- Simetria interna com a guarda do staging Meta. Google nao tem estrutura
    -- Meta para validar, logo o contrato esta valido por ausencia de suporte.
    true                                                as resultado_valido,

    extracted_at

from ultimo_snapshot
