# Benchmark — PostgreSQL (row-store) × DuckDB (column-store)

Experimento que sustenta empiricamente a escolha de armazenamento do projeto.

## A pergunta

O trabalho usa PostgreSQL, um banco orientado a linhas, como Data Warehouse.
A literatura e a prática de mercado apontam armazenamento colunar como padrão
para carga analítica. **A escolha se justifica no volume deste projeto?**

Responder por argumentação é frágil. Este benchmark responde por medição, e
identifica em que volume a resposta muda.

## Como rodar

```bash
docker compose up -d db

# Gera os dados sintéticos (semente fixa — reprodutível)
docker compose run --rm etl_app python benchmark/gerar_dados.py

# Executa a comparação
docker compose run --rm etl_app python benchmark/executar.py

# Escalas específicas e mais repetições
docker compose run --rm etl_app python benchmark/executar.py --escalas 1M 10M --repeticoes 7

# DuckDB sem paralelismo, para isolar o efeito do formato de armazenamento
docker compose run --rm etl_app python benchmark/executar.py --threads-duckdb 1
```

Resultados em `benchmark/resultados/` (CSV e Markdown).

## Método

### Dados

Gerados sinteticamente porque os dados reais do projeto (~1,7 mil linhas) são
pequenos demais para diferenciar os motores. O gerador reproduz a **forma** do
modelo dimensional real, em escalas de 10 mil a 10 milhões de linhas.

Cuidados contra viés — uma geração ingênua com valores uniformes favoreceria
artificialmente o motor colunar, cuja compressão se beneficia de baixa
cardinalidade e distribuição previsível:

| Aspecto | Tratamento |
|---|---|
| Investimento | Distribuição lognormal (cauda longa, como em mídia paga) |
| Impressões | Derivadas do investimento por CPM variável, não sorteadas à parte |
| Cliques e conversões | Taxas características por anúncio, estáveis no tempo |
| Hierarquia | Cardinalidades calibradas pelos dados reais do projeto |
| Crescimento | Anúncios crescem com a raiz do total — o fato cresce por dias, não por novas entidades |

A semente é fixa: a mesma escala produz sempre os mesmos dados.

### Consultas

Cinco consultas cobrindo perfis distintos de acesso. **A composição é
deliberada:** um benchmark só com agregações sobre a tabela inteira mediria o
melhor cenário do colunar e o pior do orientado a linhas, produzindo conclusão
pré-determinada.

| # | Consulta | Perfil | Tende a favorecer |
|---|---|---|---|
| Q1 | Agregação total por plataforma | Varredura completa | Colunar |
| Q2 | Série temporal mensal com CTR/CPC/CPA | Varredura + cálculo | Colunar |
| Q3 | Top 20 campanhas por investimento | Agregação de alta cardinalidade | Colunar |
| Q4 | Janela dos últimos 7 dias | Filtro seletivo | Linhas (usa índice) |
| Q5 | Histórico de um anúncio específico | Busca pontual | Linhas (usa índice) |

Q4 e Q5 são o contraponto: representam o padrão de um painel operacional que
abre "os últimos 7 dias" ou detalha um anúncio — o uso real deste projeto.

O SQL é portável; nenhuma consulta usa sintaxe específica de um dos motores.

### Medição

1. Mesmo arquivo Parquet carregado nos dois motores.
2. **Índices equivalentes em ambos** — em `data` e em `anuncio_id`. A comparação
   é entre motores bem configurados, não entre um otimizado e outro
   negligenciado. No PostgreSQL roda-se `VACUUM ANALYZE`: sem estatísticas o
   planejador escolhe planos ruins e o teste mediria o planejador, não o motor.
3. Uma execução de aquecimento, descartada, seguida de N execuções medidas.
4. Reporta-se a **mediana**, mais resistente a outliers de escalonamento de CPU
   que a média.
5. Todo resultado é materializado (`fetchall`) para que nenhum motor se
   beneficie de avaliação preguiçosa.

## Assimetrias conhecidas

Declaradas para que a leitura dos resultados seja honesta:

- **O DuckDB é embarcado.** Roda no mesmo processo, sem protocolo de rede. O
  PostgreSQL paga serialização e transporte por socket mesmo em conexão local.
  Em consultas de poucos milissegundos, parte da diferença é esse custo fixo e
  não o motor de armazenamento. É por isso que Q5 pode parecer favorável ao
  PostgreSQL por margem maior do que a estrutura de dados justificaria — e
  também por que diferenças abaixo de ~2× em consultas rápidas não devem ser
  interpretadas como superioridade de arquitetura.
- **Paralelismo.** Por padrão ambos usam múltiplas threads, mas com políticas
  diferentes. Use `--threads-duckdb 1` para isolar o efeito do formato de
  armazenamento do efeito do paralelismo.
- **Ambiente containerizado**, compartilhando CPU com o host. Os números são
  válidos para comparação relativa entre os motores na mesma execução, não como
  medida absoluta de desempenho.
- **Escala única de hardware.** Os resultados não se extrapolam para máquinas
  com perfil de I/O muito diferente.

## Resultados

Execução única, 5 repetições medidas por consulta, mediana. 05/08/2026.

### Razão entre os motores

Fator de vantagem do vencedor em cada célula:

| Escala | Q1 varredura | Q2 varredura+cálculo | Q3 alta cardinalidade | Q4 janela 7d | Q5 pontual |
|---|---|---|---|---|---|
| 10k | DuckDB 1,8× | DuckDB 2,4× | **PostgreSQL 1,5×** | **PostgreSQL 1,5×** | **PostgreSQL 4,6×** |
| 100k | DuckDB 4,6× | DuckDB 7,4× | DuckDB 4,5× | DuckDB 1,2× | **PostgreSQL 4,3×** |
| 1M | DuckDB 13,5× | DuckDB 27,5× | DuckDB 27,9× | DuckDB 3,1× | **PostgreSQL 3,6×** |
| 10M | DuckDB 23,1× | DuckDB 49,4× | DuckDB 64,8× | DuckDB 7,6× | **PostgreSQL 5,0×** |

### Tempos absolutos (ms)

| Escala | Motor | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---|---:|---:|---:|---:|---:|
| 10k | PostgreSQL | 1,7 | 4,2 | 2,6 | 0,5 | 0,2 |
| 10k | DuckDB | 0,9 | 1,8 | 3,9 | 0,7 | 0,9 |
| 100k | PostgreSQL | 11,2 | 24,1 | 34,7 | 1,0 | 0,3 |
| 100k | DuckDB | 2,4 | 3,3 | 7,7 | 0,9 | 1,3 |
| 1M | PostgreSQL | 56,4 | 160,9 | 384,3 | 3,3 | 0,8 |
| 1M | DuckDB | 4,2 | 5,9 | 13,8 | 1,1 | 3,0 |
| 10M | PostgreSQL | 502,3 | 1.256,2 | **5.337,6** | 10,0 | 1,9 |
| 10M | DuckDB | 21,7 | 25,4 | 82,4 | 1,3 | 9,6 |

### Carga e armazenamento

| Escala | Carga PG | Disco PG | Carga DuckDB | Disco DuckDB |
|---|---:|---:|---:|---:|
| 10k | 0,4 s | 1,2 MB | 0,1 s | 1 MB |
| 100k | 1,0 s | 12 MB | 0,3 s | 7 MB |
| 1M | 9,3 s | 119 MB | 1,8 s | 50 MB |
| 10M | 93,2 s | 1.187 MB | 11,2 s | 472 MB |

## Interpretação

### O ponto de cruzamento não é único

Depende do perfil da consulta:

| Perfil | Onde o colunar assume |
|---|---|
| Varredura com agregação | Entre 10 mil e 100 mil linhas |
| Agregação de alta cardinalidade | Entre 10 mil e 100 mil linhas |
| Filtro seletivo por período | Entre 100 mil e 1 milhão |
| Busca pontual por chave | Não ocorre dentro do intervalo testado |

Falar em "o volume a partir do qual usar colunar" é, portanto, simplificação.
A pergunta correta envolve o padrão de acesso.

### Como cada motor escala

Ampliando o volume mil vezes (10k → 10M), a Q1 fica **295× mais lenta** no
PostgreSQL e apenas **24× mais lenta** no DuckDB. O motor colunar tem custo
fixo relativamente alto — por isso perde em bases pequenas — mas cresce
sublinearmente, porque lê apenas as colunas envolvidas e opera sobre blocos
comprimidos.

A Q3 no PostgreSQL cresce de forma **superlinear**: 2,6 ms → 34,7 ms →
384 ms → 5.338 ms. O agrupamento de alta cardinalidade com `COUNT(DISTINCT)`
excede a memória de trabalho e passa a usar disco.

### O limite prático

Aos 10 milhões de linhas, a Q3 leva **mais de 5 segundos** no PostgreSQL. Esse
é o ponto em que a diferença deixa de ser acadêmica: um painel analítico com
essa latência é inutilizável. Nas escalas anteriores, o pior caso do PostgreSQL
permanece abaixo de 400 ms — imperceptível para o usuário.

### O eixo que o row-store não perde

O PostgreSQL vence a busca pontual em **todas as escalas**, com vantagem
crescente (4,6× → 4,3× → 3,6× → 5,0×). É o comportamento esperado de um índice
B-tree, e corresponde ao padrão de um painel operacional que detalha um anúncio
específico.

### Compressão

O DuckDB ocupa 2,5× menos espaço aos 10 milhões de linhas (472 MB contra
1.187 MB) e carrega 8× mais rápido. Vantagem estrutural do armazenamento
colunar: valores de mesmo tipo e domínio ficam adjacentes, o que comprime bem.

### Variância da medição

Duas execuções independentes da Q3 aos 10M produziram 4.173 ms e 5.338 ms —
diferença de 28%. O ambiente é containerizado e compartilha CPU com o host.
**Comparações de razão dentro de uma mesma execução são confiáveis; valores
absolutos entre execuções distintas, não.** Diferenças inferiores a ~2× não
sustentam conclusão.

## Conclusão para o projeto

O sistema real projeta **~110 mil linhas por ano e menos de 600 mil em cinco
anos de operação**. Nessa faixa, o pior caso medido do PostgreSQL fica em torno
de 250 a 400 ms, e o motor vence o padrão de acesso mais frequente do painel
(detalhamento por anúncio).

A escolha do PostgreSQL se sustenta — mas por **adequação ao volume e ao perfil
de uso**, não por superioridade de desempenho analítico. O experimento mostra
que o armazenamento colunar é consistentemente mais rápido em consultas de
varredura mesmo em volumes modestos, e que a migração passaria a ser
tecnicamente necessária caso o sistema se aproximasse da ordem de 10 milhões de
linhas — o que exigiria multiplicar por dezesseis o horizonte de cinco anos.
