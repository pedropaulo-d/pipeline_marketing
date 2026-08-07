/*
    Em SCD Tipo 2 os intervalos de validade de uma mesma entidade nao podem
    se sobrepor — se sobrepusessem, o join do fato encontraria mais de uma
    versao para a mesma data e duplicaria metricas.

    Verifica todas as dimensoes versionadas. Passa quando nao retorna linhas.

    A lista vem da var `dimensoes_scd2` no dbt_project.yml — dimensao nova
    entra la e os dois testes de SCD2 passam a cobri-la juntos.
*/

{% set dimensoes = var('dimensoes_scd2') %}

{% for modelo, nk in dimensoes %}
select
    '{{ modelo }}' as dimensao,
    a.{{ nk }}     as chave_natural,
    a.valido_de    as inicio_a,
    b.valido_de    as inicio_b

from {{ ref(modelo) }} a
join {{ ref(modelo) }} b
    on  a.{{ nk }} = b.{{ nk }}
    and a.valido_de < b.valido_de
    and a.valido_ate >= b.valido_de

{% if not loop.last %}union all{% endif %}
{% endfor %}
