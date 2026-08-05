{#
    Gera uma dimensao com versionamento SCD Tipo 2 a partir da silver.

    Cada mudanca no nome da entidade fecha a versao anterior e abre uma nova,
    com intervalo de validade contiguo. A tabela fato passa a apontar para a
    versao vigente na data da metrica, preservando o historico.

    De onde vem o historico
    -----------------------
    Da propria bronze. Como ela e append-only, guardamos o nome observado em
    cada extracao. Isso importa porque a API **nao** permite reconstruir esse
    historico: consultada hoje, ela devolve o nome ATUAL mesmo para datas
    passadas. Ou seja, o versionamento reflete o que foi observado no momento
    da extracao — nao o estado real da plataforma naquele dia. E uma
    aproximacao honesta, e a unica possivel sem CDC na origem.

    Chaves
    ------
    - `<ent>_nk`: chave natural, estavel (hash da cadeia hierarquica).
    - `<ent>_sk`: chave substituta, unica por VERSAO.
    - pai: referenciado pela chave NATURAL, para que uma nova versao do pai
      nao force novas versoes em toda a descendencia.

    Args:
        entidade: prefixo das colunas na silver (ex: 'campanha').
        pai: coluna que referencia o nivel superior (ex: 'conta_nk').
#}
{% macro dimensao_scd2(entidade, pai) %}

with observado_por_dia as (

    -- Um nome por entidade por dia. O `min()` desempata o caso raro de dois
    -- nomes para a mesma entidade no mesmo dia (contas distintas do mesmo
    -- anunciante), tornando o resultado deterministico.
    select
        {{ entidade }}_nk                    as nk,
        {{ pai }}                            as pai_nk,
        {{ entidade }}_external_id           as external_id,
        data,
        min({{ entidade }}_nome)             as nome

    from {{ ref('stg_ads_unified') }}
    group by 1, 2, 3, 4

),

marcado as (

    -- Sinaliza o dia em que o nome mudou em relacao a observacao anterior.
    select
        *,
        case
            when nome is distinct from lag(nome) over (
                partition by nk order by data
            ) then 1
            else 0
        end as mudou

    from observado_por_dia

),

versionado as (

    -- Soma cumulativa das mudancas = numero da versao.
    select
        *,
        sum(mudou) over (
            partition by nk
            order by data
            rows unbounded preceding
        ) as versao

    from marcado

),

agrupado as (

    select
        nk,
        versao,
        min(pai_nk)      as pai_nk,
        min(external_id) as external_id,
        min(nome)        as nome,
        min(data)        as valido_de

    from versionado
    group by nk, versao

)

select
    md5(nk || '|v' || versao::text) as {{ entidade }}_sk,
    nk                              as {{ entidade }}_nk,
    pai_nk                          as {{ pai }},
    external_id,
    nome,
    versao,
    valido_de,

    -- A versao vale ate a vespera do inicio da proxima. A ultima fica aberta
    -- com data-sentinela, o que torna os intervalos contiguos e garante que
    -- toda linha do fato encontre exatamente uma versao.
    coalesce(
        (lead(valido_de) over (partition by nk order by versao) - interval '1 day')::date,
        '9999-12-31'::date
    ) as valido_ate,

    lead(valido_de) over (partition by nk order by versao) is null as is_atual

from agrupado

{% endmacro %}
