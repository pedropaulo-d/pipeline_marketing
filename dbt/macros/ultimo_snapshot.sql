{#
    Deduplicacao da camada bronze: devolve a observacao mais recente de cada
    entidade no grao logico de uma fonte e dia.

    A bronze e append-only — reprocessar um periodo cria um lote novo em vez de
    sobrescrever o anterior. Um lote posterior pode ser parcial: substituir o
    dia inteiro faria uma entidade ausente desaparecer sem prova de que suas
    metricas viraram zero. A particao por chave preserva a ultima observacao
    conhecida da entidade ausente e, quando ela reaparece, adota a metrica
    revisada pelo `extracted_at` mais recente.

    Este bloco era identico, palavra por palavra, em stg_meta_ads e
    stg_google_ads, mudando apenas o valor de `where source =`. Duas copias da
    mesma regra e a categoria exata do bug do `union all`: elas divergem sem
    que nada acuse.

    Args:
        fonte: identificador da fonte em bronze.raw_ads ('meta_ads',
               'google_ads'). Vem do registro de plataformas, em plataformas.py.
        chaves_entidade: campos do payload que formam a chave natural
               hierarquica da entidade no grao final. Nome e metrica nunca
               participam da deduplicacao.

    Retorna um SELECT completo, para ser usado como corpo de uma CTE:

        with ultimo_snapshot as (
            {{ ultimo_snapshot(
                'meta_ads',
                ['account_id', 'campaign_id', 'adset_id', 'ad_id']
            ) }}
        )
#}
{% macro ultimo_snapshot(fonte, chaves_entidade) -%}
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
                partition by
                    reference_date
                    {%- for chave in chaves_entidade %},
                    payload->>'{{ chave }}'
                    {%- endfor %}
                order by extracted_at desc
            ) as recencia

        from {{ source('bronze', 'raw_ads') }}
        where source = '{{ fonte }}'

    ) as bruto

    where recencia = 1
{%- endmacro %}
