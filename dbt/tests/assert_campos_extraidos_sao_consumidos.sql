/*
    Todo campo que chega na bronze precisa ser lido pela silver ou estar
    declarado como ignorado de proposito.

    O buraco que este teste fecha
    -----------------------------
    Nada ligava a lista de campos pedidos ao extrator (INSIGHT_FIELDS no Meta,
    a lista do GAQL_ADS_TEMPLATE no Google) aos modelos silver que leem essas
    chaves do payload. Acrescentar um campo no extrator e esquecer do modelo
    nao produzia erro nenhum: o dado entrava na bronze, ficava la, e a silver
    seguia sem ele. Foi literalmente o caso do `video_views` do Google,
    resolvido em 06/08 na direcao inversa.

    Como funciona
    -------------
    Compara as chaves presentes no LOTE MAIS RECENTE de cada fonte com as
    chaves que o modelo de staging correspondente le. A lista de chaves
    consumidas nao e declarada em lugar nenhum: a macro `chaves_consumidas`
    extrai do proprio SQL do modelo. Mudar o modelo muda a lista.

    Passa quando nao retorna linhas. Cada linha retornada e um campo que esta
    entrando no armazem e sendo descartado em silencio.

    Por que so o lote mais recente
    ------------------------------
    A bronze e append-only e guarda o historico de formatos: lotes antigos nao
    tem chaves que passaram a ser extraidas depois. Olhar o historico inteiro
    reportaria o passado como se fosse problema.

    Por que a direcao inversa NAO e verificada
    ------------------------------------------
    Seria tentador exigir tambem que toda chave lida pela silver exista no
    lote. Nao da: campos opcionais da API podem faltar legitimamente num lote
    inteiro — `action_values` do Meta so aparece em 10 de 527 registros, e
    nada impede um dia em que nao apareca em nenhum. O `coalesce` dos modelos
    ja trata essa ausencia, e o teste acusaria falso positivo.
*/

{% set fontes = var('fontes_staging') %}

with ultimo_lote as (

    select distinct on (source) source, batch_id
    from {{ source('bronze', 'raw_ads') }}
    order by source, extracted_at desc

),

chaves_do_lote as (

    select distinct
        r.source as fonte,
        k.chave

    from {{ source('bronze', 'raw_ads') }} as r

    inner join ultimo_lote as u
        on  u.source = r.source
        and u.batch_id = r.batch_id

    cross join lateral jsonb_object_keys(r.payload) as k(chave)

)

{% for f in fontes %}
{%- set conhecidas = chaves_consumidas(f.modelo) + f.ignoradas -%}

select
    fonte,
    chave,
    'extraida mas nao consumida por {{ f.modelo }}' as problema

from chaves_do_lote
where fonte = '{{ f.fonte }}'
  and chave not in (
      {%- for chave in conhecidas -%}
      '{{ chave }}'{% if not loop.last %}, {% endif %}
      {%- endfor -%}
  )

{% if not loop.last %}union all{% endif %}
{% endfor %}
