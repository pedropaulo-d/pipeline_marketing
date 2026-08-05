"""Consultas analiticas do benchmark.

O conjunto foi montado deliberadamente para NAO favorecer um dos motores.
Um benchmark composto apenas de agregacoes sobre a tabela inteira mediria o
melhor cenario do armazenamento colunar e o pior do orientado a linhas — e
produziria uma conclusao pre-determinada.

As cinco consultas cobrem perfis distintos de acesso:

| # | Perfil | Tende a favorecer |
|---|--------|-------------------|
| Q1 | Varredura total com agregacao | colunar |
| Q2 | Serie temporal agrupada por mes | colunar |
| Q3 | Ranking com agregacao e ordenacao | colunar |
| Q4 | Filtro seletivo por periodo curto | orientado a linhas (usa indice) |
| Q5 | Busca pontual por chave | orientado a linhas (usa indice) |

Q4 e Q5 sao o contraponto honesto: representam o padrao de consulta de um
painel operacional que abre "os ultimos 7 dias" ou detalha um anuncio
especifico — exatamente o uso real deste projeto.

O SQL e portavel entre PostgreSQL e DuckDB; nenhuma consulta usa sintaxe
especifica de um dos dois.
"""

CONSULTAS: dict[str, dict[str, str]] = {
    "Q1": {
        "nome": "Agregacao total por plataforma",
        "perfil": "varredura completa",
        "sql": """
            SELECT plataforma_id,
                   COUNT(*)              AS linhas,
                   SUM(spend)            AS investimento,
                   SUM(impressions)      AS impressoes,
                   SUM(link_clicks)      AS cliques,
                   SUM(conversions)      AS conversoes
            FROM fato_bench
            GROUP BY plataforma_id
        """,
    },
    "Q2": {
        "nome": "Serie temporal mensal com metricas derivadas",
        "perfil": "varredura completa + calculo",
        "sql": """
            SELECT EXTRACT(YEAR FROM data)  AS ano,
                   EXTRACT(MONTH FROM data) AS mes,
                   SUM(spend)                                        AS investimento,
                   SUM(link_clicks) * 1.0 / NULLIF(SUM(impressions), 0) AS ctr,
                   SUM(spend)       / NULLIF(SUM(link_clicks), 0)       AS cpc,
                   SUM(spend)       / NULLIF(SUM(conversions), 0)       AS cpa
            FROM fato_bench
            GROUP BY 1, 2
            ORDER BY 1, 2
        """,
    },
    "Q3": {
        "nome": "Top 20 campanhas por investimento",
        "perfil": "agregacao de alta cardinalidade + ordenacao",
        "sql": """
            SELECT campanha_id,
                   SUM(spend)       AS investimento,
                   SUM(impressions) AS impressoes,
                   COUNT(DISTINCT anuncio_id) AS anuncios
            FROM fato_bench
            GROUP BY campanha_id
            ORDER BY investimento DESC
            LIMIT 20
        """,
    },
    "Q4": {
        "nome": "Janela dos ultimos 7 dias por plataforma",
        "perfil": "filtro seletivo por periodo",
        # As datas sao substituidas em tempo de execucao pelos ultimos 7 dias
        # efetivamente presentes na escala, para que a consulta permaneca
        # equivalente em todos os volumes. Note que a SELETIVIDADE muda: 7 dias
        # sao 21% de uma base de 33 dias e 0,7% de uma base de mil dias. Isso
        # nao e defeito do teste — reproduz o que acontece na pratica conforme
        # o historico cresce, e e justamente onde o indice passa a compensar.
        "sql": """
            SELECT plataforma_id,
                   SUM(spend)       AS investimento,
                   SUM(link_clicks) AS cliques
            FROM fato_bench
            WHERE data BETWEEN DATE '{data_inicio}' AND DATE '{data_fim}'
            GROUP BY plataforma_id
        """,
    },
    "Q5": {
        "nome": "Historico de um anuncio especifico",
        "perfil": "busca pontual por chave",
        "sql": """
            SELECT data, spend, impressions, link_clicks, conversions
            FROM fato_bench
            WHERE anuncio_id = 42
            ORDER BY data
        """,
    },
}
