{{ config(severity = 'warn') }}

/*
    Alerta quando um anuncio que tinha gasto no snapshot anterior de um dia
    desaparece do snapshot mais recente. Como a silver adota o mais recente,
    o gasto ja carregado seria apagado do DW sem deixar rastro na gold.

    Foi assim que se descobriu o filtro `campaign.status = 'ENABLED'` na GAQL:
    ele comparava o status de HOJE com a entrega do dia consultado, entao uma
    campanha pausada depois sumia da reextracao e levava o gasto junto
    (R$ 210,57 em 04/08/2026, ja corrigido no extrator).

    O grao importa: contar linhas por lote NAO pegaria o caso, porque naquele
    dia cinco anuncios novos entraram e o total subiu de 250 para 254 mesmo
    com a perda. So a comparacao anuncio a anuncio revela a subtracao.

    Severidade `warn`, nao `error`: sumir pode ser legitimo (anuncio excluido
    da conta). O teste nao decide se esta errado — obriga a olhar antes de
    aceitar o lote.
*/

with snapshots as (

    select
        source,
        reference_date,
        payload->>'ad_id'                                     as anuncio_id,
        coalesce(
            (payload->>'spend')::numeric,
            (payload->>'cost')::numeric,
            0
        )                                                     as gasto,
        dense_rank() over (
            partition by source, reference_date
            order by extracted_at desc
        )                                                     as recencia

    from {{ source('bronze', 'raw_ads') }}

),

atual as (
    select source, reference_date, anuncio_id
    from snapshots
    where recencia = 1
),

anterior as (
    select source, reference_date, anuncio_id, gasto
    from snapshots
    where recencia = 2
      and gasto > 0
)

select
    anterior.source,
    anterior.reference_date,
    anterior.anuncio_id,
    anterior.gasto as gasto_perdido

from anterior

left join atual
    on  atual.source = anterior.source
    and atual.reference_date = anterior.reference_date
    and atual.anuncio_id = anterior.anuncio_id

where atual.anuncio_id is null
