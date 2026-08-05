/*
    O grao da tabela fato e (anuncio, dia). Nenhuma combinacao pode se
    repetir — este teste e o equivalente declarativo do
    UNIQUE(anuncio_id, tempo_id) que existia no ETL.

    O teste passa quando a query nao retorna nenhuma linha.
*/

select
    anuncio_sk,
    tempo_sk,
    count(*) as ocorrencias

from {{ ref('fato_metricas') }}

group by anuncio_sk, tempo_sk
having count(*) > 1
