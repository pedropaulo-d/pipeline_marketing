/*
    Silver — Meta Ads.

    Desempacota o payload bruto em colunas tipadas. Duas responsabilidades:

    1. Deduplicacao: a bronze e append-only, entao a mesma entidade/dia pode
       ter sido extraida varias vezes. Vence sua observacao mais recente
       (`extracted_at`). Entidade ausente de lote posterior preserva a ultima
       observacao conhecida; ausencia sem tombstone nao significa metrica zero.
    2. Normalizacao das metricas de `actions` / `action_values`, que a API
       devolve como arrays de {action_type, value} em vez de colunas.

    ATENCAO ao par `conversions` / `conversion_value`. Aqui `conversions` conta
    `lead`, e `conversion_value` soma o valor de `lead` — que o Meta NUNCA
    emite em `action_values`, porque lead nao carrega valor monetario. Medido
    na bronze: zero ocorrencias de `lead` em `action_values`. Logo
    `conversion_value` do Meta e estruturalmente zero, e o valor monetario real
    das compras mora em `purchase_value`. O contrato de `conversion_value` foi
    preservado de proposito para nao mudar duas coisas ao mesmo tempo; quem
    quer valor Meta usa `purchase_value`.
*/

with ultimo_snapshot as (

    {{ ultimo_snapshot(
        'meta_ads',
        ['account_id', 'campaign_id', 'adset_id', 'ad_id']
    ) }}

),

resultado_parseado as (

    -- Uma unica passagem do parser devolve validade E par no mesmo jsonb.
    -- Antes eram dois macros percorrendo os mesmos arrays, que precisavam
    -- concordar por disciplina; agora nao ha o que divergir.
    select
        *,
        {{ resultado_meta_analise(
            'payload', 'results', 'cost_per_result'
        ) }} as resultado
    from ultimo_snapshot

)

select
    'Meta Ads'                                          as plataforma,
    reference_date                                      as data,

    -- Hierarquia
    payload->>'account_id'                              as conta_external_id,
    payload->>'account_name'                            as conta_nome,
    payload->>'campaign_id'                             as campanha_external_id,
    payload->>'campaign_name'                           as campanha_nome,
    payload->>'adset_id'                                as adset_external_id,
    payload->>'adset_name'                              as adset_nome,
    payload->>'ad_id'                                   as anuncio_external_id,
    payload->>'ad_name'                                 as anuncio_nome,

    -- Metricas.
    -- A ORDEM importa e e a mesma de stg_google_ads, afirmada pelo teste
    -- assert_staging_mesmo_contrato: `union all` casa colunas por posicao,
    -- entao manter os dois modelos alinhados impede que uma troca de metricas
    -- passe despercebida se alguem simplificar stg_ads_unified para `select *`.
    coalesce((payload->>'spend')::numeric, 0)              as spend,
    coalesce((payload->>'impressions')::bigint, 0)         as impressions,
    coalesce((payload->>'inline_link_clicks')::int, 0)     as link_clicks,

    -- Derivadas dos arrays de acoes.
    -- Numeric por simetria com o Google, que reporta valores fracionados.
    {{ sum_action_value('payload', 'actions', ['lead']) }}::numeric
        as conversions,
    {{ sum_action_value('payload', 'action_values', ['lead']) }}::numeric
        as conversion_value,
    {{ sum_action_value('payload', 'actions', ['video_view']) }}::bigint
        as video_views,

    coalesce((payload->>'reach')::bigint, 0)               as reach,

    {{ sum_action_value('payload', 'actions', ['onsite_conversion.ig_profile_view']) }}::int
        as profile_views,
    -- Compra: UMA representacao canonica, nunca a soma de varias.
    -- O Meta descreve a mesma compra em oito `action_type` simultaneos
    -- (`purchase`, `omni_purchase`, `onsite_web_purchase`,
    -- `offsite_conversion.fb_pixel_purchase`, ...), todos com o mesmo valor.
    -- Somar dois deles dobrava a contagem — ver `acao_canonica`.
    -- `omni_purchase` e a primeira escolha por ser a agregacao omnichannel do
    -- Meta (web, app, offline e loja); `purchase` fica como fallback para o
    -- caso de a agregada faltar.
    {{ acao_canonica('payload', 'actions', ['omni_purchase', 'purchase']) }}::int
        as purchases,

    -- Valor monetario da compra, na MESMA ordem canonica da quantidade: a
    -- regra tem de ser coerente entre contagem e valor, senao o ticket medio
    -- implicito deixa de fazer sentido. Nao confundir com `conversion_value`,
    -- que segue o contrato antigo e mede outra coisa.
    {{ acao_canonica('payload', 'action_values', ['omni_purchase', 'purchase']) }}::numeric
        as purchase_value,

    -- Resultado oficial escolhido pela propria Meta. `resultado` carrega o
    -- par quando a estrutura e inequivoca, em qualquer das formas reais que a
    -- API devolve (ver o cabecalho de `macros/resultado_meta.sql`). Ausencia
    -- legitima permanece NULL; ambiguidade deixa `resultado_valido = false` e
    -- bloqueia o build pelo data test, sem escolher primeiro/maior/objetivo.
    --
    -- `cost_per_result` NULL com `result_count` = 0 e um estado esperado, nao
    -- lacuna: custo por resultado nao existe quando o denominador e zero.
    -- `result_attribution_window` NULL significa janela nao aplicavel ou nao
    -- fornecida pela fonte — nao significa contradicao, que e fail closed.
    --
    -- AUSENCIA TOTAL x FORMA A. Sao dois estados diferentes e o DW os mantem
    -- distintos:
    --
    --   ausencia total — a fonte nao devolveu `results` nem `cost_per_result`.
    --     Nenhum tipo foi declarado, entao os quatro campos ficam NULL.
    --     `result_count` NULL nao vira zero: zero e uma afirmacao sobre a
    --     quantidade, e aqui nao ha sequer tipo sobre o que afirmar.
    --
    --   FORMA A — a fonte declarou o `indicator` dos dois lados e nao entregou
    --     `values`. O tipo existe e a quantidade e zero de fato.
    --
    -- Os unit tests `resultado_meta_ausencia_legitima_permanece_null` e
    -- `resultado_meta_forma_a_declara_tipo_sem_quantidade` fixam o contraste.
    -- Achatar um no outro reintroduz inferencia: seria afirmar tipo onde a
    -- fonte nao declarou, ou negar quantidade onde ela declarou.
    --
    -- `objective` e `optimization_goal` viajam como CONTEXTO. Nunca entram na
    -- decisao de `result_type`: `OUTCOME_LEADS` + `LEAD_GENERATION` nao
    -- implica Resultado = Lead neste contrato.
    resultado->>'result_type'                            as result_type,
    (resultado->>'result_count')::numeric                as result_count,
    resultado->>'result_attribution_window'              as result_attribution_window,
    (resultado->>'cost_per_result')::numeric             as cost_per_result,
    payload->>'objective'                                as objective,
    payload->>'optimization_goal'                        as optimization_goal,

    -- Guarda interna da Silver; nao segue para o contrato unificado/Gold.
    (resultado->>'valido')::boolean                      as resultado_valido,

    extracted_at

from resultado_parseado
