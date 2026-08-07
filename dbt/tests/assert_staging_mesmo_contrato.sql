/*
    Os dois modelos de staging tem de expor exatamente as mesmas colunas, com
    os mesmos nomes e na mesma posicao.

    `union all` casa colunas por POSICAO, nao por nome. Hoje stg_ads_unified se
    protege listando as colunas explicitamente, mas essa protecao e uma
    convencao: basta alguem simplificar para `select *` — que parece uma
    limpeza inofensiva — para que uma divergencia de ordem entre os dois
    modelos troque metricas de lugar em silencio. Ja aconteceu neste
    repositorio e passou nos 65 testes da epoca, porque erro de conteudo nao
    e erro de schema.

    Este teste transforma a convencao em contrato verificado. Ele falha em
    tres situacoes:
      - uma coluna existe num modelo e nao no outro;
      - o mesmo nome aparece em posicoes diferentes;
      - alguem renomeou uma coluna de um lado so.

    Quando um dos modelos ganhar uma metrica nova, o outro precisa ganhar a
    mesma coluna (nem que seja zerada, como ja acontece com reach,
    profile_views e purchases no Google) e na mesma posicao.
*/

with meta as (

    select column_name, ordinal_position
    from information_schema.columns
    where table_schema = '{{ ref("stg_meta_ads").schema }}'
      and table_name   = '{{ ref("stg_meta_ads").identifier }}'

),

google as (

    select column_name, ordinal_position
    from information_schema.columns
    where table_schema = '{{ ref("stg_google_ads").schema }}'
      and table_name   = '{{ ref("stg_google_ads").identifier }}'

),

divergencias as (

    select
        coalesce(m.column_name, g.column_name) as coluna,
        m.ordinal_position                     as posicao_meta,
        g.ordinal_position                     as posicao_google

    from meta as m
    full outer join google as g
        on m.column_name = g.column_name

)

select *
from divergencias
where posicao_meta is distinct from posicao_google
