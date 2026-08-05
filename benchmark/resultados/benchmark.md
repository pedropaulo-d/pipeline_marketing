# Resultados do benchmark

Tempos em milissegundos (mediana). Menor e melhor.

## Escala 10k — 9,900 linhas

| Consulta | Perfil | PostgreSQL | DuckDB | Vencedor | Fator |
|---|---|---:|---:|---|---:|
| Q1 — Agregacao total por plataforma | varredura completa | 1.7 ms | 0.9 ms | DuckDB | 1.9x |
| Q2 — Serie temporal mensal com metricas derivadas | varredura completa + calculo | 4.2 ms | 1.8 ms | DuckDB | 2.4x |
| Q3 — Top 20 campanhas por investimento | agregacao de alta cardinalidade + ordenacao | 2.6 ms | 3.9 ms | PostgreSQL | 1.5x |
| Q4 — Janela dos ultimos 7 dias por plataforma | filtro seletivo por periodo | 0.5 ms | 0.7 ms | PostgreSQL | 1.5x |
| Q5 — Historico de um anuncio especifico | busca pontual por chave | 0.2 ms | 0.9 ms | PostgreSQL | 4.6x |

## Escala 100k — 99,540 linhas

| Consulta | Perfil | PostgreSQL | DuckDB | Vencedor | Fator |
|---|---|---:|---:|---|---:|
| Q1 — Agregacao total por plataforma | varredura completa | 11.2 ms | 2.4 ms | DuckDB | 4.6x |
| Q2 — Serie temporal mensal com metricas derivadas | varredura completa + calculo | 24.1 ms | 3.3 ms | DuckDB | 7.4x |
| Q3 — Top 20 campanhas por investimento | agregacao de alta cardinalidade + ordenacao | 34.7 ms | 7.7 ms | DuckDB | 4.5x |
| Q4 — Janela dos ultimos 7 dias por plataforma | filtro seletivo por periodo | 1.0 ms | 0.9 ms | DuckDB | 1.1x |
| Q5 — Historico de um anuncio especifico | busca pontual por chave | 0.3 ms | 1.3 ms | PostgreSQL | 4.3x |

## Escala 1M — 999,000 linhas

| Consulta | Perfil | PostgreSQL | DuckDB | Vencedor | Fator |
|---|---|---:|---:|---|---:|
| Q1 — Agregacao total por plataforma | varredura completa | 56.4 ms | 4.2 ms | DuckDB | 13.5x |
| Q2 — Serie temporal mensal com metricas derivadas | varredura completa + calculo | 160.9 ms | 5.8 ms | DuckDB | 27.5x |
| Q3 — Top 20 campanhas por investimento | agregacao de alta cardinalidade + ordenacao | 384.3 ms | 13.8 ms | DuckDB | 27.9x |
| Q4 — Janela dos ultimos 7 dias por plataforma | filtro seletivo por periodo | 3.3 ms | 1.1 ms | DuckDB | 3.1x |
| Q5 — Historico de um anuncio especifico | busca pontual por chave | 0.8 ms | 3.0 ms | PostgreSQL | 3.6x |

## Escala 10M — 9,998,244 linhas

| Consulta | Perfil | PostgreSQL | DuckDB | Vencedor | Fator |
|---|---|---:|---:|---|---:|
| Q1 — Agregacao total por plataforma | varredura completa | 502.3 ms | 21.7 ms | DuckDB | 23.1x |
| Q2 — Serie temporal mensal com metricas derivadas | varredura completa + calculo | 1256.2 ms | 25.4 ms | DuckDB | 49.4x |
| Q3 — Top 20 campanhas por investimento | agregacao de alta cardinalidade + ordenacao | 5337.6 ms | 82.3 ms | DuckDB | 64.8x |
| Q4 — Janela dos ultimos 7 dias por plataforma | filtro seletivo por periodo | 10.0 ms | 1.3 ms | DuckDB | 7.6x |
| Q5 — Historico de um anuncio especifico | busca pontual por chave | 1.9 ms | 9.6 ms | PostgreSQL | 5.0x |

