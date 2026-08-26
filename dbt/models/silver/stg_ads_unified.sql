/*
    Silver — visao unificada.

    Ponto de convergencia das duas plataformas: a partir daqui o restante do
    pipeline nao precisa saber se a origem foi Meta ou Google. E tambem onde
    nascem as surrogate keys da camada gold.

    As chaves sao encadeadas (a chave da conta entra na da campanha, e assim
    por diante). Isso reproduz a hierarquia do Snowflake Schema e garante que
    IDs externos iguais em plataformas diferentes nao colidam.
*/

{#
    As colunas sao listadas explicitamente porque `union all` casa colunas por
    POSICAO, nao por nome. Um `select *` aqui silenciosamente embaralharia
    metricas caso a ordem das colunas divergisse entre os dois modelos — o
    tipo de erro que passa nos testes de schema e so aparece nos numeros.
#}
{% set colunas = [
    'plataforma', 'data',
    'conta_external_id', 'conta_nome',
    'campanha_external_id', 'campanha_nome',
    'adset_external_id', 'adset_nome',
    'anuncio_external_id', 'anuncio_nome',
    'spend', 'impressions', 'link_clicks',
    'conversions', 'conversion_value',
    'video_views', 'reach', 'profile_views', 'purchases', 'purchase_value',
    'extracted_at'
] %}

with unificado as (

    select {{ colunas | join(', ') }} from {{ ref('stg_meta_ads') }}
    union all
    select {{ colunas | join(', ') }} from {{ ref('stg_google_ads') }}

)

select
    plataforma,
    data,

    -- Chaves NATURAIS encadeadas: identificam a entidade de forma estavel,
    -- independente de renomeacoes. As chaves substitutas (`_sk`), que variam
    -- por versao, nascem nas dimensoes SCD2 da camada gold.
    md5(plataforma)                                     as plataforma_sk,
    md5(plataforma || '|' || conta_external_id)         as conta_nk,
    md5(plataforma || '|' || conta_external_id
                   || '|' || campanha_external_id)      as campanha_nk,
    md5(plataforma || '|' || conta_external_id
                   || '|' || campanha_external_id
                   || '|' || adset_external_id)         as adset_nk,
    md5(plataforma || '|' || conta_external_id
                   || '|' || campanha_external_id
                   || '|' || adset_external_id
                   || '|' || anuncio_external_id)       as anuncio_nk,

    -- Chaves de negocio
    conta_external_id,
    conta_nome,
    campanha_external_id,
    campanha_nome,
    adset_external_id,
    adset_nome,
    anuncio_external_id,
    anuncio_nome,

    -- Metricas
    spend,
    impressions,
    link_clicks,
    conversions,
    conversion_value,
    video_views,
    reach,
    profile_views,
    purchases,
    purchase_value,

    extracted_at

from unificado
