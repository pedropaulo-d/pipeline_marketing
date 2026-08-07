/*
    Cada entidade versionada deve ter exatamente uma versao marcada como
    atual (`is_atual = true`). Zero indicaria historico truncado; mais de uma
    indicaria falha no fechamento das versoes anteriores.

    Passa quando nao retorna linhas.

    A lista vem da var `dimensoes_scd2` no dbt_project.yml — dimensao nova
    entra la e os dois testes de SCD2 passam a cobri-la juntos.
*/

{% set dimensoes = var('dimensoes_scd2') %}

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
