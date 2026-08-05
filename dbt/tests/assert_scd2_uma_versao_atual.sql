/*
    Cada entidade versionada deve ter exatamente uma versao marcada como
    atual (`is_atual = true`). Zero indicaria historico truncado; mais de uma
    indicaria falha no fechamento das versoes anteriores.

    Passa quando nao retorna linhas.
*/

{% set dimensoes = [
    ('dim_conta',    'conta_nk'),
    ('dim_campanha', 'campanha_nk'),
    ('dim_adset',    'adset_nk'),
    ('dim_anuncio',  'anuncio_nk')
] %}

{% for modelo, nk in dimensoes %}
select
    '{{ modelo }}' as dimensao,
    {{ nk }}       as chave_natural,
    count(*)       as versoes_atuais

from {{ ref(modelo) }}
where is_atual
group by {{ nk }}
having count(*) <> 1

{% if not loop.last %}union all{% endif %}
{% endfor %}
