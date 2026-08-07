/*
    A travessia completa da hierarquia, resolvendo a versao vigente pela data
    do fato, tem de devolver exatamente uma linha por linha do fato.

    Com dimensoes SCD2, juntar pela chave natural sem a clausula de validade
    transforma o join em 1:N e infla os agregados sem produzir erro algum —
    o resultado continua sendo uma tabela plausivel, so que maior. Medido em
    06/08/2026: 3 entidades renomeadas inflavam o investimento total em 7,8%.

    Desde 07/08/2026 a travessia existe uma vez so, em
    `gold.vw_metricas_completas`, e e ela que este teste verifica. Antes, o
    teste reimplementava os joins e verificava uma copia — o que deixava a
    copia usada pelos consumidores sem guarda nenhuma.

    Se este teste falhar, ou uma dimensao ganhou versoes sobrepostas, ou o
    encadeamento de chaves quebrou, ou alguem removeu uma clausula de validade
    da view.
*/

with contagens as (

    select
        (select count(*) from {{ ref('vw_metricas_completas') }}) as via_hierarquia,
        (select count(*) from {{ ref('fato_metricas') }})         as no_fato

)

select *
from contagens
where via_hierarquia <> no_fato
