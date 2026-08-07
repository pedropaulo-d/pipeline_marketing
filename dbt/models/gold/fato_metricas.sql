/*
    Gold — tabela fato.

    Grao: um anuncio por dia.

    Com as dimensoes em SCD Tipo 2, a fato nao pode mais apontar para a
    entidade — precisa apontar para a VERSAO vigente na data da metrica. O
    join abaixo faz essa resolucao (surrogate key pipeline, na terminologia
    de Kimball): casa pela chave natural e filtra pelo intervalo de validade.

    Como os intervalos das versoes sao contiguos e cobrem de `valido_de` ate
    '9999-12-31', toda linha encontra exatamente uma versao — condicao
    verificada pelo teste `assert_grao_unico_fato`.
*/

select
    a.anuncio_sk,
    {{ chave_tempo('u.data') }} as tempo_sk,

    u.spend,
    u.impressions,
    u.link_clicks,
    u.conversions,
    u.conversion_value,
    u.video_views,
    u.reach,
    u.profile_views,
    u.purchases

from {{ ref('stg_ads_unified') }} u

join {{ ref('dim_anuncio') }} a
    on  a.anuncio_nk = u.anuncio_nk
    and u.data between a.valido_de and a.valido_ate
