/*
    Metricas de midia nao podem ser negativas. Valor negativo indica erro de
    parsing (ex: casa decimal ou micros do Google interpretados errado) e nao
    comportamento legitimo da plataforma.
*/

select *

from {{ ref('fato_metricas') }}

where spend            < 0
   or impressions      < 0
   or link_clicks      < 0
   or conversions      < 0
   or conversion_value < 0
   or video_views      < 0
   or reach            < 0
   or profile_views    < 0
   or purchases        < 0
