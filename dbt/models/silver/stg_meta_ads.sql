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

    extracted_at

from ultimo_snapshot
