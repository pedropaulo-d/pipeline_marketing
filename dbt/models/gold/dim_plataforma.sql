/*
    Gold — dimensao Plataforma. Topo da hierarquia do Snowflake Schema.
*/

select distinct
    plataforma_sk,
    plataforma as nome

from {{ ref('stg_ads_unified') }}
