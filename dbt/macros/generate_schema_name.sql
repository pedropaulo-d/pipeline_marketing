{#
    Por padrao o dbt concatena o schema do profile com o schema customizado
    ("public_silver"). Aqui sobrescrevemos para usar o nome exato configurado
    no dbt_project.yml, produzindo os schemas `silver` e `gold` limpos.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
