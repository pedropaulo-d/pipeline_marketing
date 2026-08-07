{#
    Chave substituta da dimensao Tempo, derivada da propria data.

    A formula precisa ser identica nos dois lados do join: `dim_tempo` a usa
    para gerar `tempo_sk` e `fato_metricas` a usa para apontar para ela.
    Escrita duas vezes, mudar uma so quebra o join sem nenhum erro de sintaxe —
    o `left join` simplesmente para de casar e as metricas somem do resultado.

    Args:
        coluna: expressao de data a converter (ex: 'data', 'u.data').
#}
{% macro chave_tempo(coluna) -%}
    md5({{ coluna }}::text)
{%- endmacro %}
