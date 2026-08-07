{#
    Deduplicacao da camada bronze: devolve apenas o snapshot mais recente de
    cada dia de uma fonte.

    A bronze e append-only — reprocessar um periodo cria um lote novo em vez de
    sobrescrever o anterior. Sem isso, o mesmo dia apareceria varias vezes na
    silver e as metricas seriam somadas em duplicidade. Vencer o `extracted_at`
    mais recente tambem e o que incorpora as revisoes retroativas da janela de
    atribuicao do Meta, que pode alterar um dia ja carregado por ate 28 dias.

    Este bloco era identico, palavra por palavra, em stg_meta_ads e
    stg_google_ads, mudando apenas o valor de `where source =`. Duas copias da
    mesma regra e a categoria exata do bug do `union all`: elas divergem sem
    que nada acuse.

    Args:
        fonte: identificador da fonte em bronze.raw_ads ('meta_ads',
               'google_ads'). Vem do registro de plataformas, em plataformas.py.

    Retorna um SELECT completo, para ser usado como corpo de uma CTE:

        with ultimo_snapshot as (
            {{ ultimo_snapshot('meta_ads') }}
        )
#}
{% macro ultimo_snapshot(fonte) -%}
    select
        reference_date,
        extracted_at,
        payload

    from (

        select
            reference_date,
            extracted_at,
            payload,
            dense_rank() over (
                partition by reference_date
                order by extracted_at desc
            ) as recencia

        from {{ source('bronze', 'raw_ads') }}
        where source = '{{ fonte }}'

    ) as bruto

    where recencia = 1
{%- endmacro %}
