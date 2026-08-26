{#
    Le UMA representacao de um evento no array `actions`/`action_values` do
    Meta, escolhida por ordem de prioridade — nunca a soma de varias.

    Por que nao somar
    -----------------
    O Meta descreve o MESMO evento em varios `action_type` ao mesmo tempo.
    Medido na bronze deste projeto em 26/08/2026: `purchase` e `omni_purchase`
    coexistem em 100% dos payloads que tem compra (132 de 132 em `actions`,
    128 de 128 em `action_values`) e com valor IGUAL em 100% deles. Nenhum
    payload traz apenas uma das duas. Somar as duas, como fazia
    `sum_action_value(..., ['purchase', 'omni_purchase'])`, contava cada compra
    duas vezes.

    A regra e determinista: vence a primeira representacao presente na ordem
    declarada, e as demais so entram como fallback quando a anterior falta.
    `COALESCE` sobre subqueries com `LIMIT 1` implementa exatamente isso.

    Quando a chave nao existe no payload, `jsonb_array_elements` recebe NULL e
    devolve zero linhas; o `COALESCE` final resolve para 0.

    Args:
        payload_col:  coluna JSONB com o payload bruto.
        array_key:    'actions' ou 'action_values'.
        action_types: representacoes em ORDEM DE PRIORIDADE. A primeira e a
                      canonica; as seguintes sao fallback.
#}
{% macro acao_canonica(payload_col, array_key, action_types) -%}
    COALESCE(
        {%- for action_type in action_types %}
        (
            SELECT (elem->>'value')::numeric
            FROM jsonb_array_elements({{ payload_col }}->'{{ array_key }}') AS elem
            WHERE elem->>'action_type' = '{{ action_type }}'
            LIMIT 1
        ),
        {%- endfor %}
        0
    )
{%- endmacro %}
