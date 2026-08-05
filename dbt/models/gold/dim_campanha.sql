/*
    Gold — dimensao Campanha, versionada em SCD Tipo 2.

    E a dimensao onde o versionamento mais importa: nomes de campanha carregam
    convencoes operacionais (objetivo, publico, data da criacao) e sao
    renomeados com frequencia pelos gestores de trafego.
*/

{{ dimensao_scd2('campanha', 'conta_nk') }}
