{#
    Parser fail-closed da familia canonica `results` + `cost_per_result`.

    A Graph API v26.0 devolve os dois campos como arrays independentes. O par
    correto compartilha `indicator` e a especificacao de
    `attribution_windows`; posicao no array nao faz parte do contrato. A
    janela e canonizada como conjunto ordenado, entao a ordem interna da lista
    nao muda a chave (`7d_click|1d_view` e `1d_view|7d_click` sao o mesmo
    conjunto). Entradas `values[]` diferentes continuam candidatos distintos
    e tornam a observacao ambigua.

    `resultado_meta_valido` aceita somente:
      - ausencia simultanea dos dois campos; ou
      - exatamente um result, um cost e um pareamento inequivoco.

    O modelo Silver expoe essa validacao internamente e um data test bloqueia
    o build quando ela e falsa. Assim mudanca estrutural da Meta nao vira NULL
    silencioso nem escolha do primeiro elemento.
#}

{% macro array_meta_ou_vazio(expressao) -%}
    case
        when {{ expressao }} is null
          or {{ expressao }} = 'null'::jsonb
        then '[]'::jsonb
        else {{ expressao }}
    end
{%- endmacro %}


{% macro janela_atribuicao_meta(alias_valor) -%}
    (
        select string_agg(janela.valor, '|' order by janela.valor)
        from (
            select elemento #>> '{}' as valor
            from jsonb_array_elements(
                {{ array_meta_ou_vazio(alias_valor ~ "->'attribution_windows'") }}
            ) as elemento
        ) as janela
    )
{%- endmacro %}


{% macro resultado_meta_valido(payload_col, results_key, cost_key) -%}
    (
        with resultados as (

            select
                item->>'indicator' as indicator,
                {{ janela_atribuicao_meta('valor') }} as attribution_window,
                valor->>'value' as value

            from jsonb_array_elements(
                {{ array_meta_ou_vazio(payload_col ~ "->'" ~ results_key ~ "'") }}
            ) as item

            cross join lateral jsonb_array_elements(
                {{ array_meta_ou_vazio("item->'values'") }}
            ) as valor

        ),

        custos as (

            select
                item->>'indicator' as indicator,
                {{ janela_atribuicao_meta('valor') }} as attribution_window,
                valor->>'value' as value

            from jsonb_array_elements(
                {{ array_meta_ou_vazio(payload_col ~ "->'" ~ cost_key ~ "'") }}
            ) as item

            cross join lateral jsonb_array_elements(
                {{ array_meta_ou_vazio("item->'values'") }}
            ) as valor

        ),

        pares as (

            select 1
            from resultados as r
            inner join custos as c
                on  c.indicator = r.indicator
                and c.attribution_window = r.attribution_window

        ),

        contagens as (

            select
                jsonb_array_length(
                    {{ array_meta_ou_vazio(
                        payload_col ~ "->'" ~ results_key ~ "'"
                    ) }}
                ) as itens_resultados,
                jsonb_array_length(
                    {{ array_meta_ou_vazio(
                        payload_col ~ "->'" ~ cost_key ~ "'"
                    ) }}
                ) as itens_custos,
                (select count(*) from resultados) as resultados,
                (select count(*) from custos) as custos,
                (select count(*) from pares) as pares,
                (select count(*) from resultados
                 where indicator is null
                    or attribution_window is null
                    or value is null) as resultados_incompletos,
                (select count(*) from custos
                 where indicator is null
                    or attribution_window is null
                    or value is null) as custos_incompletos

        )

        select
            case
                when itens_resultados = 0
                 and itens_custos = 0
                 and resultados = 0
                 and custos = 0
                then true
                when itens_resultados = 1
                 and itens_custos = 1
                 and resultados = 1
                 and custos = 1
                 and pares = 1
                 and resultados_incompletos = 0
                 and custos_incompletos = 0
                then true
                else false
            end
        from contagens
    )
{%- endmacro %}


{% macro resultado_meta_par(payload_col, results_key, cost_key) -%}
    (
        with resultados as (

            select
                item->>'indicator' as indicator,
                {{ janela_atribuicao_meta('valor') }} as attribution_window,
                (valor->>'value')::numeric as result_count

            from jsonb_array_elements(
                {{ array_meta_ou_vazio(payload_col ~ "->'" ~ results_key ~ "'") }}
            ) as item

            cross join lateral jsonb_array_elements(
                {{ array_meta_ou_vazio("item->'values'") }}
            ) as valor

        ),

        custos as (

            select
                item->>'indicator' as indicator,
                {{ janela_atribuicao_meta('valor') }} as attribution_window,
                (valor->>'value')::numeric as cost_per_result

            from jsonb_array_elements(
                {{ array_meta_ou_vazio(payload_col ~ "->'" ~ cost_key ~ "'") }}
            ) as item

            cross join lateral jsonb_array_elements(
                {{ array_meta_ou_vazio("item->'values'") }}
            ) as valor

        )

        select jsonb_build_object(
            'result_type', r.indicator,
            'result_count', r.result_count,
            'result_attribution_window', r.attribution_window,
            'cost_per_result', c.cost_per_result
        )
        from resultados as r
        inner join custos as c
            on  c.indicator = r.indicator
            and c.attribution_window = r.attribution_window
    )
{%- endmacro %}
