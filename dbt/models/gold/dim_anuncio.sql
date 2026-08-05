/*
    Gold — dimensao Anuncio, versionada em SCD Tipo 2.

    Ultimo nivel da hierarquia: e a esta dimensao que a tabela fato se liga,
    resolvendo a versao vigente na data de cada metrica.
*/

{{ dimensao_scd2('anuncio', 'adset_nk') }}
