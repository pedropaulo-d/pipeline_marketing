{#
    Extrai do codigo de um modelo de staging as chaves do payload que ele le.

    Por que derivar em vez de declarar
    ----------------------------------
    O objetivo da Fase 9 e detectar quando um campo passa a ser extraido e o
    modelo silver nao e atualizado. Declarar a lista de chaves consumidas num
    `vars:` resolveria — e criaria uma TERCEIRA lista para manter em sincronia,
    que e exatamente o problema que este plano de refatoracao existe para
    remover. Uma lista declarada que sai de sincronia com o SQL faz o teste
    mentir, que e pior que nao ter teste.

    Aqui a lista e lida do proprio modelo, via `raw_code` do grafo do dbt.
    Nao ha o que manter: mudar o SQL muda a lista.

    Padroes reconhecidos
    --------------------
    - `payload->>'chave'` e `payload->'chave'` — acesso direto.
    - `sum_action_value('payload', 'chave', [...])` — a macro do Meta, que le
      um array do payload (`actions`, `action_values`) em vez de um escalar.
    - `acao_canonica('payload', 'chave', [...])` — mesma ideia, mas escolhendo
      UMA representacao por prioridade em vez de somar.

    Se um padrao novo de acesso ao payload for introduzido no futuro, ele
    precisa ser acrescentado aqui, senao a chave sera reportada como nao
    consumida. O teste falha alto nesse caso — nao em silencio.

    Args:
        nome_modelo: nome do modelo (ex: 'stg_meta_ads').

    Returns:
        Lista de chaves, sem duplicatas.
#}
{% macro chaves_consumidas(nome_modelo) %}

    {%- set chaves = [] -%}

    {%- if execute -%}

        {%- set ns = namespace(codigo=none) -%}
        {%- for no in graph.nodes.values() -%}
            {%- if no.resource_type == 'model' and no.name == nome_modelo -%}
                {%- set ns.codigo = no.raw_code -%}
            {%- endif -%}
        {%- endfor -%}

        {%- if ns.codigo is none -%}
            {{ exceptions.raise_compiler_error(
                "chaves_consumidas: modelo nao encontrado no grafo: " ~ nome_modelo
            ) }}
        {%- endif -%}

        {%- set padroes = [
            "payload\\s*->>?\\s*'([a-zA-Z0-9_]+)'",
            "sum_action_value\\(\\s*'payload'\\s*,\\s*'([a-zA-Z0-9_]+)'",
            "acao_canonica\\(\\s*'payload'\\s*,\\s*'([a-zA-Z0-9_]+)'"
        ] -%}

        {%- for padrao in padroes -%}
            {%- for achado in modules.re.findall(padrao, ns.codigo) -%}
                {%- if achado not in chaves -%}
                    {%- do chaves.append(achado) -%}
                {%- endif -%}
            {%- endfor -%}
        {%- endfor -%}

    {%- endif -%}

    {{ return(chaves) }}

{% endmacro %}
