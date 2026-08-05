{#
    Soma os `value` de um array JSON do Meta (`actions` ou `action_values`)
    cujo `action_type` esteja na lista informada.

    A API do Meta nao devolve conversoes como coluna: devolve um array de
    objetos {action_type, value}, e cada objetivo de campanha usa um
    action_type diferente. Esta macro encapsula esse desempacotamento.

    Args:
        payload_col: coluna JSONB com o payload bruto.
        array_key:   'actions' ou 'action_values'.
        action_types: lista de action_types a somar.

    Observacao: se a chave nao existir no payload, `jsonb_array_elements`
    recebe NULL e devolve zero linhas — o COALESCE resolve para 0.
#}
{% macro sum_action_value(payload_col, array_key, action_types) -%}
    COALESCE((
        SELECT SUM((elem->>'value')::numeric)
        FROM jsonb_array_elements({{ payload_col }}->'{{ array_key }}') AS elem
        WHERE elem->>'action_type' IN (
            {%- for action_type in action_types -%}
            '{{ action_type }}'{% if not loop.last %}, {% endif %}
            {%- endfor -%}
        )
    ), 0)
{%- endmacro %}
