/*
    Invariantes do valor de compra do Meta.

    O contrato anterior somava `purchase` com `omni_purchase` — duas
    representacoes do MESMO evento, presentes juntas em 100% dos payloads reais
    — e contava cada compra duas vezes. E o valor monetario nunca chegava ao
    armazem, porque `conversion_value` procurava valor em `lead`, que o Meta
    nao emite em `action_values`.

    Este teste fixa as tres condicoes que a correcao precisa manter:

    1. `purchase_value` nunca e negativo;
    2. o Google nunca alimenta `purchase_value` — la o valor mora em
       `conversion_value`, que mede outra coisa (todas as conversion actions
       da conta, nao apenas compras);
    3. nao existe valor de compra sem compra. Valor sem quantidade indicaria
       que as duas pontas da regra canonica sairam de sincronia — e e
       exatamente esse desalinhamento que torna o ticket medio implicito
       mentiroso.

    Passa quando nao retorna linhas.
*/

select
    plataforma,
    data,
    purchases,
    purchase_value,
    'purchase_value negativo' as motivo

from {{ ref('vw_metricas_completas') }}
where purchase_value < 0

union all

select
    plataforma,
    data,
    purchases,
    purchase_value,
    'Google nao pode ter valor de compra' as motivo

from {{ ref('vw_metricas_completas') }}
where plataforma = 'Google Ads'
  and purchase_value <> 0

union all

select
    plataforma,
    data,
    purchases,
    purchase_value,
    'valor de compra sem compra' as motivo

from {{ ref('vw_metricas_completas') }}
where purchase_value > 0
  and purchases = 0
