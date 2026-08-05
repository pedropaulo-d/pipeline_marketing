/*
    Gold — dimensao Tempo.

    Gerada a partir das datas efetivamente presentes no fato, com os
    atributos pre-calculados que evitam recomputo em cada agregacao
    analitica (mes, trimestre, dia da semana).
*/

with datas as (

    select distinct data
    from {{ ref('stg_ads_unified') }}

)

select
    md5(data::text)                     as tempo_sk,
    data,
    extract(day     from data)::smallint as dia,
    extract(month   from data)::smallint as mes,
    extract(year    from data)::smallint as ano,
    extract(quarter from data)::smallint as trimestre,
    extract(isodow  from data)::smallint as dia_semana,
    to_char(data, 'YYYY-MM')             as ano_mes

from datas
