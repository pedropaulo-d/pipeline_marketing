/*
    A familia Meta `results` + `cost_per_result` so pode atravessar a Silver
    quando forma zero pares (ausencia legitima) ou exatamente um par por
    indicator + conjunto canonico de attribution windows.

    O parser marca a observacao invalida sem escolher primeiro, maior,
    objective ou optimization_goal. Este teste transforma a marca em bloqueio
    do `dbt build`. A saida e apenas uma contagem agregada: mesmo numa falha,
    nenhum identificador de cliente aparece no log.
*/

select count(*) as observacoes_ambiguas
from {{ ref('stg_meta_ads') }}
where not resultado_valido
having count(*) > 0
