/*
    Gold — visao de consumo. A travessia da hierarquia, feita uma vez e certa.

    Por que existe
    --------------
    Juntar uma dimensao SCD Tipo 2 pela chave natural sem resolver a versao
    transforma o join em 1:N e infla os agregados SEM PRODUZIR ERRO NENHUM: o
    resultado continua sendo uma tabela plausivel, so que maior. Medido em
    06/08/2026 neste armazem — 3 entidades renomeadas inflaram o investimento
    total em 7,8% (R$ 20.216,73 -> R$ 21.795,17), e o numero errado chegou a
    entrar na tabela de resultados do TCC.

    A defesa contra isso era documentacao: um aviso pedindo que todo consumidor
    lembrasse de escrever `and <data do fato> between d.valido_de and
    d.valido_ate` em cada um dos quatro niveis versionados. A travessia correta
    estava escrita quatro vezes no repositorio.

    Esta view troca o aviso por impossibilidade. Quem consulta faz

        select plataforma, sum(spend) from gold.vw_metricas_completas
        group by plataforma;

    e nao tem como errar, porque nao ha join a escrever.

    Contrato
    --------
    Uma linha por linha de `fato_metricas` — mesmo grao, 1 anuncio x 1 dia,
    com os nomes de toda a hierarquia ja resolvidos na versao vigente naquela
    data. Isso e afirmado pelo teste `assert_join_dimensional_nao_infla`.

    Materializada como view: no volume deste projeto (~110 mil linhas/ano) o
    custo de recomputar e irrelevante e o dado fica sempre fresco.

    Ressalvas que acompanham as metricas
    ------------------------------------
    - `reach`, `profile_views` e `purchases` sao zero no Google: ausencia de
      suporte da GAQL neste grao, nao ausencia de dado.
    - `video_views` tem definicao diferente em cada plataforma (TrueView de
      30s no Google, 3s no Meta). Valido dentro de cada uma, sem significado
      se somado entre elas.
*/

{{ config(materialized='view') }}

select
    -- Tempo
    t.data,
    t.dia,
    t.mes,
    t.ano,
    t.trimestre,
    t.dia_semana,
    t.ano_mes,

    -- Hierarquia, do topo para a folha. A chave natural acompanha o nome
    -- porque agrupar por nome funde entidades homonimas e separa as que foram
    -- renomeadas; agrupar por `_nk` e o criterio estavel.
    --
    -- O numero da versao SCD2 sai nos QUATRO niveis. Ele nao vem de join novo:
    -- as linhas de dimensao ja foram resolvidas pela clausula de validade
    -- abaixo, entao `versao` e uma projecao da versao vigente naquela data.
    -- Quem consome a superficie de exposicao usa isso para demonstrar SCD2 sem
    -- reimplementar a travessia — a reimplementacao e exatamente o que ja
    -- inflou os agregados neste projeto.
    p.nome                  as plataforma,

    ct.conta_nk,
    ct.external_id          as conta_external_id,
    ct.nome                 as conta_nome,
    ct.versao               as conta_versao,

    c.campanha_nk,
    c.external_id           as campanha_external_id,
    c.nome                  as campanha_nome,
    c.versao                as campanha_versao,

    s.adset_nk,
    s.external_id           as adset_external_id,
    s.nome                  as adset_nome,
    s.versao                as adset_versao,

    a.anuncio_nk,
    a.external_id           as anuncio_external_id,
    a.nome                  as anuncio_nome,
    a.versao                as anuncio_versao,

    -- Metricas, no mesmo grao do fato
    f.spend,
    f.impressions,
    f.link_clicks,
    f.conversions,
    f.conversion_value,
    f.video_views,
    f.reach,
    f.profile_views,
    f.purchases

from {{ ref('fato_metricas') }} as f

inner join {{ ref('dim_tempo') }} as t
    on t.tempo_sk = f.tempo_sk

-- O fato ja aponta para a VERSAO do anuncio (anuncio_sk), entao aqui nao ha
-- clausula de validade: a resolucao ja aconteceu na carga do fato.
inner join {{ ref('dim_anuncio') }} as a
    on a.anuncio_sk = f.anuncio_sk

-- Dos niveis acima, cada um e referenciado pela chave NATURAL do pai, para que
-- uma nova versao do pai nao cascateie versoes na descendencia. Por isso a
-- versao precisa ser resolvida aqui, pela data do fato. E esta clausula, uma
-- por nivel, que sumia nas consultas escritas a mao.
inner join {{ ref('dim_adset') }} as s
    on  s.adset_nk = a.adset_nk
    and t.data between s.valido_de and s.valido_ate

inner join {{ ref('dim_campanha') }} as c
    on  c.campanha_nk = s.campanha_nk
    and t.data between c.valido_de and c.valido_ate

inner join {{ ref('dim_conta') }} as ct
    on  ct.conta_nk = c.conta_nk
    and t.data between ct.valido_de and ct.valido_ate

-- Plataforma e SCD Tipo 0: o nome nao muda, nao ha versao a resolver.
inner join {{ ref('dim_plataforma') }} as p
    on p.plataforma_sk = ct.plataforma_sk
