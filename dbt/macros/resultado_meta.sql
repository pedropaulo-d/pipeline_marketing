{#
    Parser fail-closed da familia canonica `results` + `cost_per_result`.

    A Graph API v26.0 devolve os dois campos como arrays independentes. O par
    correto compartilha `indicator` e a especificacao de
    `attribution_windows`; posicao no array nao faz parte do contrato. A
    janela e canonizada como conjunto ordenado, entao a ordem interna da lista
    nao muda a chave (`7d_click|1d_view` e `1d_view|7d_click` sao o mesmo
    conjunto).

    Formas reais observadas
    -----------------------
    O primeiro request real com a familia completa (bloco 2026-08-01..07,
    901 registros) mostrou que a resposta tem mais formas do que a hipotese
    inicial supunha. As tres seguintes sao legitimas e nao podem ser tratadas
    como ambiguidade:

    - FORMA A — o item traz somente `indicator`, sem `values`, dos DOIS lados.
      A fonte declarou o tipo de Resultado e nao entregou quantidade nem
      custo. Isso e ZERO resultado no grao factual, nao resultado
      desconhecido: `result_count = 0`, `cost_per_result` e janela em NULL.

    - FORMA B — `values` existe dos dois lados mas sem `attribution_windows`.
      Acontece com indicators que nao tem janela de atribuicao aplicavel
      (`profile_visit_view`, `reach`, `estimated_ad_recallers`). O par e
      inequivoco e vale; a janela persiste em NULL.

    - FORMA C — `results` traz um unico valor igual a zero e o custo traz o
      mesmo `indicator` sem `values`. Custo por resultado nao existe quando o
      denominador e zero. `result_count = 0`, `cost_per_result` em NULL —
      nunca zero, nunca divisao por zero, nunca custo inventado.

    Os tres estados da janela
    -------------------------
    A. explicita — o conjunto ordenado dos `attribution_windows`.
    B. nao aplicavel / nao fornecida — persiste NULL. Legitimo para
       determinados Result Types; NAO e o mesmo que contradicao.
    C. contraditoria — janela de um lado e outra (ou nenhuma) do outro.
       Fail closed.

    Para distinguir B de C o pareamento usa um sentinel tecnico
    (`sentinela_sem_janela`) no lugar do NULL. Isso e necessario porque
    `NULL = NULL` e desconhecido em SQL: sem o sentinel, dois lados
    igualmente sem janela nunca se encontrariam no join, e a FORMA B viraria
    ambiguidade. O sentinel existe SOMENTE dentro deste macro; a projecao
    final o converte de volta em NULL com `nullif`. Ele nunca alcanca a
    Silver, o Gold, a superficie de exposicao ou o dashboard.

    O que continua fail closed
    --------------------------
    - mais de um item em qualquer dos lados;
    - `indicator` diferente entre os lados, ou ausente;
    - mais de um `values` de um lado (multiplas janelas ou multiplos pares);
    - janela explicita de um lado e ausente do outro;
    - `result_count > 0` com custo sem valor — a FORMA C so vale porque a
      quantidade e zero;
    - custo com valor e resultado sem `values`.

    `resultado_meta_analise` e a UNICA implementacao da regra. Antes havia
    `resultado_meta_valido` e `resultado_meta_par`, duas copias da mesma
    logica que precisavam concordar por disciplina — a categoria exata de bug
    que este repositorio ja pagou no `union all`. Agora a validacao e o par
    saem da mesma passagem, num unico jsonb.

    O modelo Silver expoe `resultado_valido` internamente e um data test
    bloqueia o build quando ela e falsa. Assim mudanca estrutural da Meta nao
    vira NULL silencioso nem escolha do primeiro elemento.
#}

{% macro sentinela_sem_janela() -%}
    '__NO_ATTRIBUTION_WINDOW__'
{%- endmacro %}


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


{#
    Desempacota um dos dois arrays da familia em linhas
    (indicator, janela normalizada, valor numerico).

    A janela ausente vira o sentinel aqui, uma unica vez, para que o
    pareamento seja uma comparacao de igualdade normal.
#}
{% macro _linhas_familia_meta(payload_col, chave) -%}
    select
        item->>'indicator' as indicator,
        coalesce(
            {{ janela_atribuicao_meta('valor') }},
            {{ sentinela_sem_janela() }}
        ) as janela,
        (valor->>'value')::numeric as valor_numerico

    from jsonb_array_elements(
        {{ array_meta_ou_vazio(payload_col ~ "->'" ~ chave ~ "'") }}
    ) as item

    cross join lateral jsonb_array_elements(
        {{ array_meta_ou_vazio("item->'values'") }}
    ) as valor
{%- endmacro %}


{#
    Indicators declarados num dos arrays, INDEPENDENTE de haver `values`.

    E o que permite reconhecer a FORMA A: ali o indicator existe e o array de
    valores nao, entao ele nao aparece em `_linhas_familia_meta`.
#}
{% macro _indicadores_familia_meta(payload_col, chave) -%}
    select distinct item->>'indicator' as indicator
    from jsonb_array_elements(
        {{ array_meta_ou_vazio(payload_col ~ "->'" ~ chave ~ "'") }}
    ) as item
{%- endmacro %}


{% macro resultado_meta_analise(payload_col, results_key, cost_key) -%}
    (
        with resultados as (

            {{ _linhas_familia_meta(payload_col, results_key) }}

        ),

        custos as (

            {{ _linhas_familia_meta(payload_col, cost_key) }}

        ),

        indicadores_resultados as (

            {{ _indicadores_familia_meta(payload_col, results_key) }}

        ),

        indicadores_custos as (

            {{ _indicadores_familia_meta(payload_col, cost_key) }}

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

                (select count(*) from resultados) as linhas_resultados,
                (select count(*) from custos) as linhas_custos,

                (select count(*) from indicadores_resultados)
                    as indicadores_resultados,
                (select count(*) from indicadores_custos)
                    as indicadores_custos,

                -- Lidos apenas quando a contagem correspondente e 1, entao
                -- `min` devolve o unico valor. Nunca uma escolha entre
                -- candidatos: a escolha e barrada antes, pela contagem.
                (select min(indicator) from indicadores_resultados)
                    as indicator_resultado,
                (select min(indicator) from indicadores_custos)
                    as indicator_custo,
                (select min(janela) from resultados) as janela_resultado,
                (select min(janela) from custos) as janela_custo,
                (select min(valor_numerico) from resultados)
                    as valor_resultado,
                (select min(valor_numerico) from custos) as valor_custo,

                (select count(*) from indicadores_resultados
                 where indicator is null) as indicadores_resultados_nulos,
                (select count(*) from indicadores_custos
                 where indicator is null) as indicadores_custos_nulos,
                (select count(*) from resultados
                 where indicator is null
                    or janela is null
                    or valor_numerico is null) as resultados_incompletos,
                (select count(*) from custos
                 where indicator is null
                    or janela is null
                    or valor_numerico is null) as custos_incompletos

        )

        select
            case

                -- Ausencia simultanea: a observacao legitimamente nao tem
                -- Resultado. Nenhuma chave de par e emitida.
                when itens_resultados = 0
                 and itens_custos = 0
                 and linhas_resultados = 0
                 and linhas_custos = 0
                then jsonb_build_object('valido', true)

                -- Daqui em diante exige exatamente um item de cada lado,
                -- um unico indicator, nao nulo e igual nos dois.
                when itens_resultados = 1
                 and itens_custos = 1
                 and indicadores_resultados = 1
                 and indicadores_custos = 1
                 and indicadores_resultados_nulos = 0
                 and indicadores_custos_nulos = 0
                 and indicator_custo = indicator_resultado
                then case

                    -- FORMA A: tipo declarado, quantidade nao entregue.
                    when linhas_resultados = 0
                     and linhas_custos = 0
                    then jsonb_build_object(
                        'valido', true,
                        'result_type', indicator_resultado,
                        'result_count', 0,
                        'result_attribution_window', null,
                        'cost_per_result', null
                    )

                    -- Par completo. Cobre a janela explicita e a FORMA B,
                    -- em que os dois lados carregam o sentinel.
                    when linhas_resultados = 1
                     and linhas_custos = 1
                     and resultados_incompletos = 0
                     and custos_incompletos = 0
                     and janela_custo = janela_resultado
                    then jsonb_build_object(
                        'valido', true,
                        'result_type', indicator_resultado,
                        'result_count', valor_resultado,
                        'result_attribution_window',
                            nullif(janela_resultado, {{ sentinela_sem_janela() }}),
                        'cost_per_result', valor_custo
                    )

                    -- FORMA C: quantidade zero e custo sem valor. So vale
                    -- porque o denominador e zero; com quantidade positiva
                    -- isto cai no fail closed abaixo.
                    when linhas_resultados = 1
                     and linhas_custos = 0
                     and resultados_incompletos = 0
                     and valor_resultado = 0
                    then jsonb_build_object(
                        'valido', true,
                        'result_type', indicator_resultado,
                        'result_count', 0,
                        'result_attribution_window',
                            nullif(janela_resultado, {{ sentinela_sem_janela() }}),
                        'cost_per_result', null
                    )

                    else jsonb_build_object('valido', false)
                end

                else jsonb_build_object('valido', false)
            end
        from contagens
    )
{%- endmacro %}
