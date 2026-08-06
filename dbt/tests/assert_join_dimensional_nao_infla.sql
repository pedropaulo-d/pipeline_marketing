/*
    A travessia completa da hierarquia, resolvendo a versao vigente pela data
    do fato, tem de devolver exatamente uma linha por linha do fato.

    Com dimensoes SCD2, juntar pela chave natural sem a clausula de validade
    transforma o join em 1:N e infla os agregados sem produzir erro algum —
    o resultado continua sendo uma tabela plausivel, so que maior. Medido em
    06/08/2026: 3 entidades renomeadas inflavam o investimento total em 7,8%.

    Este teste fixa o contrato de consulta do armazem. Se ele falhar, ou uma
    dimensao ganhou versoes sobrepostas, ou o encadeamento de chaves quebrou.
*/

with travessia as (

    select f.anuncio_sk, f.tempo_sk

    from {{ ref('fato_metricas') }} as f

    inner join {{ ref('dim_tempo') }} as t
        on t.tempo_sk = f.tempo_sk

    inner join {{ ref('dim_anuncio') }} as a
        on a.anuncio_sk = f.anuncio_sk

    inner join {{ ref('dim_adset') }} as s
        on  s.adset_nk = a.adset_nk
        and t.data between s.valido_de and s.valido_ate

    inner join {{ ref('dim_campanha') }} as c
        on  c.campanha_nk = s.campanha_nk
        and t.data between c.valido_de and c.valido_ate

    inner join {{ ref('dim_conta') }} as ct
        on  ct.conta_nk = c.conta_nk
        and t.data between ct.valido_de and ct.valido_ate

    inner join {{ ref('dim_plataforma') }} as p
        on p.plataforma_sk = ct.plataforma_sk

),

contagens as (

    select
        (select count(*) from travessia)                       as via_hierarquia,
        (select count(*) from {{ ref('fato_metricas') }})      as no_fato

)

select *
from contagens
where via_hierarquia <> no_fato
