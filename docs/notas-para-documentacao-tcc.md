# Notas para a documentação do TCC

Arquivo de trabalho. Reúne fatos, números medidos, decisões com justificativa e
achados do desenvolvimento, organizados pela estrutura típica de um TCC.

**Última atualização:** 05/08/2026

---

## Como usar este arquivo

Este documento foi escrito para ser lido por quem vai redigir a monografia sem
ter acompanhado o desenvolvimento. Ele é autocontido: todos os números são
medidos, não estimados, e cada decisão vem com o porquê.

Convenções:

- 📊 **fato medido** — número verificado no sistema, pode ir direto para o texto
- ⚖️ **decisão** — escolha de projeto com a justificativa que a sustenta
- 🔍 **achado** — resultado do desenvolvimento com valor argumentativo
- ⚠️ **limitação** — restrição conhecida, deve aparecer no texto
- ❓ **pendente** — depende de decisão do orientador ou de trabalho futuro

---

## 1. Identificação do trabalho

**Tema:** Pipeline de dados para integração e análise unificada de métricas de
campanhas de marketing digital em múltiplas plataformas.

**Problema:** Agências que operam campanhas simultaneamente em Meta Ads e
Google Ads não conseguem comparar desempenho entre plataformas sem trabalho
manual. Cada plataforma expõe um modelo de dados próprio, com hierarquias,
nomenclaturas e métricas distintas. A consolidação costuma ser feita em
planilhas, sem histórico, sem rastreabilidade e sem garantia de reprodutibilidade.

**Objetivo geral:** Projetar e implementar um pipeline de dados que extraia,
padronize e consolide métricas diárias de campanhas de Meta Ads e Google Ads em
um Data Warehouse dimensional que permita análise comparativa entre plataformas.

**Objetivos específicos sugeridos:**

1. Implementar extração automatizada das APIs oficiais das duas plataformas.
2. Projetar um modelo dimensional capaz de acomodar as hierarquias de ambas.
3. Garantir idempotência e reprodutibilidade do processamento.
4. Preservar o dado bruto para permitir reprocessamento sem nova extração.
5. Validar a qualidade dos dados por testes automatizados.
6. ❓ Comparar empiricamente o desempenho analítico entre armazenamento
   orientado a linhas e a colunas (ver seção 9).

**Contexto de origem dos dados:** contas reais de clientes de uma agência de
marketing (referida como "a agência" no texto). O autor teve acesso concedido
formalmente, em nível somente-leitura.

---

## 2. Fatos medidos sobre o sistema

### 2.1 Volume de dados

📊 Números verificados em 05/08/2026:

| Métrica | Valor |
|---|---|
| Contas ativas descobertas — Meta Ads | 87 |
| Subcontas ativas descobertas — Google Ads | 64 |
| Registros por dia (as duas plataformas) | ~300 |
| Projeção anual | ~110 mil linhas |
| Projeção para 5 anos de histórico | < 600 mil linhas |
| Linhas na tabela fato (5 dias carregados) | 1.672 |
| Linhas na camada bronze (8 lotes acumulados) | 5.761 |
| Tamanho do banco completo | 16 MB |
| Tamanho da camada bronze | 6,2 MB |
| Tamanho da tabela fato (gold) | 296 kB |
| Tempo de extração — Meta (87 contas) | ~2 minutos |
| Tempo de transformação + testes (dbt) | ~3 segundos |
| Modelos dbt | 10 (3 views silver, 7 tabelas gold) |
| Testes de dados automatizados | 73 |

**Este é o dado mais importante do trabalho para justificar escolhas de
arquitetura.** Ver seção 4.1.

### 2.2 Períodos carregados

📊 07/04/2026 e 01/08 a 04/08/2026.

A descontinuidade tem causa documentada: o acesso à API do Google Ads foi
perdido entre abril e agosto (seção 5.3).

### 2.3 Resultado analítico consolidado

📊 Agregado dos 5 dias, extraído da camada gold:

| Plataforma | Linhas | Investimento | Impressões | Cliques | Conversões | CTR | CPC | CPA |
|---|---|---|---|---|---|---|---|---|
| Meta Ads | 727 | R$ 9.345,30 | 893.378 | 7.405 | 250,00 | 0,83% | R$ 1,26 | R$ 37,38 |
| Google Ads | 1.051 | R$ 12.449,89 | 117.012 | 5.134 | 405,29 | 4,39% | R$ 2,42 | R$ 30,72 |

Esta tabela é o **resultado que demonstra o objetivo geral**: a comparação entre
plataformas só é possível porque os dois modelos foram unificados. Vale comentar
no texto o contraste de perfil: o Meta entrega volume de impressões muito maior
com CTR baixo (mídia de descoberta, interruptiva), enquanto o Google entrega
menos impressões com CTR cinco vezes maior (mídia de intenção, o usuário buscou).

⚠️ A comparação de CPA entre plataformas tem ressalva metodológica: as
plataformas contam conversões com modelos de atribuição diferentes. Não é
comparação de igual para igual e o texto deve dizer isso.

---

## 3. Arquitetura

### 3.1 Evolução

O trabalho passou por duas arquiteturas, e **a transição é conteúdo do TCC**,
não deve ser escondida:

**Versão 1 — ETL clássico.** Extração em Python → transformação em pandas →
carga via `INSERT ... ON CONFLICT` em PostgreSQL. Arquivos intermediários
(JSON e CSV) sobrescritos a cada execução.

**Versão 2 — ELT em camadas (arquitetura medalhão).** Extração → carga do dado
bruto íntegro em PostgreSQL (bronze) → transformações em SQL declarativo com
dbt (silver → gold).

O caminho antigo foi mantido no código para permitir validação por comparação
(seção 6.1).

### 3.2 Camadas

**Bronze — `bronze.raw_ads`**

Payload JSON exatamente como a API devolveu, em coluna `JSONB`, com metadados
de ingestão: fonte, data de referência, momento da extração e identificador do
lote. Tabela **append-only**: reprocessar um período cria um lote novo em vez de
sobrescrever.

Tabela auxiliar `bronze.ingestion_log` registra cada carga (lote, fonte,
período, volume, momento) — base de observabilidade.

**Silver — três views**

- `stg_meta_ads`: tipagem e desempacotamento das métricas que a API do Meta
  devolve como arrays de objetos `{action_type, value}`.
- `stg_google_ads`: tipagem e alinhamento de nomenclatura ao vocabulário comum.
- `stg_ads_unified`: união das duas plataformas e criação das chaves naturais.

Deduplicação: como a bronze acumula snapshots do mesmo dia, a silver aplica
`dense_rank()` particionado por (fonte, data de referência) ordenado por momento
de extração decrescente. Vence o snapshot mais recente.

**Gold — modelo dimensional**

Seis dimensões e uma tabela fato, materializadas como tabelas.

### 3.3 Modelo dimensional

⚖️ **Snowflake Schema**, não Star Schema.

Hierarquia normalizada em cadeia:

```
Plataforma → Conta → Campanha → AdSet/AdGroup → Anúncio → Fato
dim_tempo → Fato
```

**Grão da tabela fato:** um anúncio por dia.

**Nove métricas:** investimento (spend), impressões, cliques em link,
conversões, valor de conversão, visualizações de vídeo, alcance, visualizações
de perfil e compras.

**Sistema de chaves (após implementação de SCD Tipo 2):**

| Chave | Definição | Propriedade |
|---|---|---|
| `<entidade>_nk` | Chave natural: hash MD5 da cadeia hierárquica de IDs externos | Estável entre renomeações |
| `<entidade>_sk` | Chave substituta: hash MD5 de (chave natural + número da versão) | Única por versão |

Os níveis referenciam o **nível superior pela chave natural**, de modo que criar
uma nova versão de uma campanha não force novas versões em todos os seus
anúncios descendentes.

A tabela fato aponta para a **versão vigente na data da métrica**, resolvida por
junção na chave natural filtrada pelo intervalo de validade — o padrão que
Kimball chama de *surrogate key pipeline*.

### 3.4 Stack

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.11 |
| Containerização | Docker + Docker Compose |
| Extração | facebook-business SDK, google-ads SDK |
| Armazenamento | PostgreSQL 16 |
| Transformação | dbt (dbt-core + dbt-postgres) |
| Testes de dados | dbt tests |
| ❓ Orquestração | Apache Airflow (planejado, não implementado) |

---

## 4. Decisões de projeto

Cada decisão abaixo deve aparecer no texto **com a justificativa**, não apenas
como constatação. É o que diferencia relato de projeto.

### 4.1 PostgreSQL em vez de banco colunar

⚖️ **Decisão:** manter armazenamento orientado a linhas.

⚠️ **Atenção ao redigir:** a justificativa intuitiva — "o volume não justifica
colunar porque a vantagem só aparece em dezenas de milhões de linhas" — foi
**refutada pela medição** (seção 5.6). O ponto de cruzamento em consultas de
varredura ocorre entre 10 mil e 100 mil linhas, duas ordens de grandeza antes.
Não use essa formulação no texto.

**Justificativa que o experimento sustenta:** o data mart projetado não
ultrapassa 600 mil linhas em cinco anos e, nessa faixa, o pior tempo medido no
PostgreSQL fica em torno de 250 a 400 ms — imperceptível para uso interativo.
Além disso, o motor vence o padrão de acesso mais frequente de um painel
operacional (detalhamento por anúncio) em todas as escalas testadas.

A escolha se sustenta por **adequação ao volume e ao perfil de uso**, não por
superioridade de desempenho analítico.

**Justificativas complementares:**

1. **Padrão de escrita.** A carga é reprocessamento diário idempotente. Bancos
   orientados a linhas lidam bem com atualização pontual; colunares
   tipicamente tratam atualização como operação cara ou assíncrona.
2. **Integridade referencial.** O Snowflake Schema depende de relacionamentos
   entre cinco níveis. A maioria dos colunares não implementa chaves
   estrangeiras.
3. **Caminho de evolução.** Havendo crescimento, existem alternativas sem troca
   de banco: extensões colunares no próprio PostgreSQL (Citus columnar,
   TimescaleDB) ou espelhamento dos marts em um motor analítico.

**Argumento a registrar:** migrar para colunar no volume atual seria decisão
orientada por tecnologia e não por requisito.

### 4.2 Snowflake Schema em vez de Star Schema

⚖️ **Decisão:** manter as dimensões normalizadas em cadeia.

**Justificativa:** a hierarquia espelha a estrutura nativa das duas APIs, o que
torna a carga incremental por nível natural e evita anomalias de atualização em
nomes que mudam com frequência. Cada nível tem chave única composta por
(identificador externo + pai), o que permite que identificadores externos iguais
em plataformas distintas coexistam sem colisão.

**Contra-argumento a reconhecer no texto:** o Star Schema exigiria menos junções
em consultas analíticas. No volume deste trabalho a diferença de desempenho é
irrelevante, então a escolha privilegia integridade e fidelidade ao domínio.

### 4.3 ELT em camadas em vez de ETL

⚖️ **Decisão:** migrar para arquitetura medalhão com dbt.

**Justificativa principal — rastreabilidade.** No ETL original, os arquivos com
o dado bruto eram sobrescritos a cada execução. Consequência prática: corrigir
um erro de transformação exigia nova extração da API. Isso é frágil porque a
disponibilidade da API não está sob controle do projeto — e neste trabalho a
API do Google ficou inacessível por meses (seção 5.3).

**Ganhos secundários:** testes de dados automatizados, documentação e grafo de
dependências gerados pela ferramenta, e lógica de negócio expressa em SQL
versionado em vez de código imperativo.

**Custo assumido:** as chaves estrangeiras deixaram de ser restrições do banco e
passaram a ser testes de integridade referencial executados após a
materialização. É uma garantia mais fraca em natureza — **detecta** violação em
vez de **impedir** — mas cobre os mesmos relacionamentos e roda a cada execução.
⚠️ Esta troca deve estar explícita no texto.

**Nota sobre desempenho:** no volume deste trabalho não há diferença mensurável
entre ETL e ELT. A escolha é sobre manutenibilidade e rastreabilidade. O texto
não deve alegar ganho de desempenho.

### 4.4 Camada bronze append-only

⚖️ **Decisão:** nunca sobrescrever o dado bruto; cada extração gera novo lote.

**Justificativa:** além de permitir reprocessamento, preserva o histórico das
respostas da API. Isso habilita uma análise impossível no modelo anterior: medir
a **deriva retroativa** das métricas. A janela de atribuição do Meta revisa
conversões por até 28 dias, então o mesmo dia extraído em momentos diferentes
retorna números diferentes. Com a bronze append-only, essa diferença fica
registrada e é mensurável.

❓ Esta é uma **oportunidade de contribuição original**: quantificar em quanto as
métricas de um dia mudam ao longo dos 28 dias seguintes é análise que raramente
aparece em trabalhos da área e que os dados já permitem fazer.

### 4.5 SCD Tipo 2

⚖️ **Decisão:** versionar as dimensões `conta`, `campanha`, `adset` e `anuncio`.

**Justificativa:** nomes de campanha em mídia paga carregam convenções
operacionais (objetivo, público, formato, data de criação) e são renomeados com
frequência pelos gestores. Com SCD Tipo 1, renomear reescreve retroativamente
todo o histórico: um relatório de abril passa a exibir o nome de agosto,
destruindo a capacidade de auditar o que foi executado.

`dim_plataforma` permanece em SCD Tipo 0 (não tem atributo que mude).

⚠️ **Ressalva metodológica que precisa ir para o texto.** O histórico é
reconstruído a partir dos snapshots da bronze, não da API. Consultada hoje, a
API devolve o nome **atual** mesmo para datas passadas — ela não expõe histórico
de alterações. Portanto o versionamento reflete *o que foi observado no momento
de cada extração*, não o estado real da plataforma naquele dia. É uma
aproximação, e a única possível sem *change data capture* na origem. Ela
subestima renomeações ocorridas entre duas extrações.

### 4.6 Anonimização fora do pipeline

⚖️ **Decisão:** a anonimização roda na fronteira da publicação, não na ingestão.

**Justificativa:** mantém a lógica do pipeline idêntica para dado real e dado
anonimizado, evitando dois caminhos de código que poderiam divergir.

**Princípios adotados:**

1. Pseudonimização determinística — o mesmo nome sempre gera o mesmo
   pseudônimo. Sem isso, cada execução criaria entidades novas e inflaria as
   dimensões.
2. Preservação da estrutura, substituição da identidade — a convenção de
   nomenclatura permanece analisável.
3. Métricas intactas — sem os nomes, valores não identificam ninguém, e
   alterá-los destruiria a validade analítica do dataset.

---

## 5. Achados do desenvolvimento

Esta seção contém o material com maior valor argumentativo do trabalho. São
resultados obtidos, não escolhas de projeto.

### 5.1 Teste de schema não detecta erro de conteúdo

🔍 **Achado principal.**

Durante a migração de ETL para ELT, os 65 testes automatizados então existentes
passavam integralmente enquanto o pipeline produzia **números errados**.

**Causa:** o operador `UNION ALL` do SQL casa colunas por **posição, não por
nome**. Os dois modelos de staging emitiam as colunas de alcance, conversões e
valor de conversão em ordens diferentes. As métricas do Google entravam trocadas
entre si.

**Por que nenhum teste pegou:** os tipos eram compatíveis, as chaves eram
únicas, nenhum valor era nulo, nenhum era negativo. Todas as asserções sobre
*estrutura* continuavam verdadeiras.

**Como foi detectado:** pela validação de paridade contra a implementação
anterior, comparando métrica a métrica (seção 6.1).

**Lição a registrar no texto:** testes de schema verificam estrutura, não
conteúdo. A reescrita de um pipeline exige comparação numérica com a
implementação anterior — "os testes passaram" não constitui evidência de
correção. Esta é uma contribuição metodológica defensável.

### 5.2 Truncamento silencioso de conversões fracionadas

🔍 A mesma validação revelou um erro na implementação **original**.

O Google Ads reporta conversões **fracionadas**, porque a modelagem de
atribuição credita uma conversão parcialmente a vários anúncios. O ETL
convertia cada linha com `int()`, que trunca.

📊 Somando as 1.672 linhas:

| Implementação | Conversões do Google |
|---|---|
| ETL original (truncado linha a linha) | 376,00 |
| ELT (valor real da API) | 380,29 |

O modelo original descartava cerca de 1% das conversões da plataforma, de forma
silenciosa. A coluna passou a ser numérica na camada gold.

**Valor argumentativo:** demonstra como uma escolha aparentemente inócua de tipo
de dado (inteiro para "contagem de conversões") introduz erro sistemático quando
o domínio não corresponde ao pressuposto do modelo.

### 5.3 Fragilidade de acesso como risco de projeto

🔍 O acesso à API do Google Ads foi perdido quando o autor deixou a agência: a
conta corporativa que autorizou o OAuth foi excluída, invalidando o token de
atualização. O pipeline ficou sem a fonte por aproximadamente quatro meses.

**Recuperação:** acesso somente-leitura concedido no nível da conta de
gerenciamento (MCC), novo token gerado, extração restabelecida sem alteração de
código.

**Detalhe técnico relevante:** o nível em que o acesso é concedido importa. A
descoberta automática de subcontas consulta a entidade `customer_client` usando
o MCC como contexto; acesso concedido apenas em contas individuais quebraria a
descoberta.

**Valor argumentativo:** dependência de APIs de terceiros é risco de projeto com
consequência concreta sobre a continuidade do dado, e a arquitetura precisa
prever isso. É exatamente o que motiva a camada bronze imutável (seção 4.4).

### 5.4 Renomeações reais no período observado

📊 Três campanhas foram renomeadas entre abril e agosto nos dados reais:

| Versão 1 (07/04 – 31/07) | Versão 2 (01/08 – atual) |
|---|---|
| `[MARCA_A] [OBJETIVO] [CANAL] DD/MM/AAAA` | `[MARCA_A] [OBJETIVO] [CANAL] AAMMDD` |
| `[FORMATO] [SECAO] DD/MM/AA` | `[OBJETIVO] [SECAO] [FORMATO] - DD/MM/AA` |
| `[MARCA_C] EMPRESA_C_GRAFIA_1 DD-MM` | `[MARCA_C] EMPRESA_C_GRAFIA_2 DD-MM` |

📊 Efeito no modelo: `dim_campanha` passou a ter 180 linhas para 177 entidades;
`dim_adset`, 337 para 334; `dim_conta`, 58 para 57.

Serve como **evidência empírica** de que o problema que o SCD Tipo 2 resolve não
é hipotético neste domínio. Note que uma das renomeações é correção de erro de
digitação ("EMPRESA_C_GRAFIA_1" → "EMPRESA_C_GRAFIA_2"), o que mostra que o histórico também preserva
o registro de correções.

### 5.5 Perfis distintos das plataformas

🔍 Os dados consolidados evidenciam comportamentos diferentes: o Meta entrega
volume de impressões cerca de sete vezes maior com CTR de 0,83%, enquanto o
Google entrega menos impressões com CTR de 4,39%. É a diferença esperada entre
mídia de descoberta e mídia de intenção, e o pipeline permite demonstrá-la
quantitativamente — o que sustenta o objetivo geral do trabalho.

---

### 5.6 Benchmark row-store × column-store — a contribuição experimental

🔍 Experimento executado para responder empiricamente à pergunta que a escolha
de arquitetura levanta. **É o resultado mais substancial do trabalho para uma
seção de "Resultados".**

**Método resumido** (detalhes em `benchmark/README.md`): dados sintéticos com a
forma do modelo dimensional real em quatro escalas (10 mil a 10 milhões de
linhas), carregados nos dois motores com índices equivalentes, cinco
repetições medidas por consulta após aquecimento, reportada a mediana.

**Cuidado metodológico que deve constar no texto:** o conjunto de consultas foi
montado deliberadamente para não favorecer um dos motores. Três consultas de
varredura (perfil favorável ao colunar) e duas de acesso seletivo (perfil
favorável ao orientado a linhas). Um benchmark composto apenas de agregações
sobre a tabela inteira produziria conclusão pré-determinada.

📊 **Resultado — fator de vantagem do vencedor:**

| Escala | Q1 varredura | Q2 varredura+cálculo | Q3 alta cardinalidade | Q4 janela 7d | Q5 pontual |
|---|---|---|---|---|---|
| 10 mil | DuckDB 1,8× | DuckDB 2,4× | **PostgreSQL 1,5×** | **PostgreSQL 1,5×** | **PostgreSQL 4,6×** |
| 100 mil | DuckDB 4,6× | DuckDB 7,4× | DuckDB 4,5× | DuckDB 1,2× | **PostgreSQL 4,3×** |
| 1 milhão | DuckDB 13,5× | DuckDB 27,5× | DuckDB 27,9× | DuckDB 3,1× | **PostgreSQL 3,6×** |
| 10 milhões | DuckDB 23,1× | DuckDB 49,4× | DuckDB 64,8× | DuckDB 7,6× | **PostgreSQL 5,0×** |

📊 **Tempos absolutos do PostgreSQL (ms)** — o dado que define usabilidade:

| Escala | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---:|---:|---:|---:|---:|
| 10 mil | 1,7 | 4,2 | 2,6 | 0,5 | 0,2 |
| 100 mil | 11,2 | 24,1 | 34,7 | 1,0 | 0,3 |
| 1 milhão | 56,4 | 160,9 | 384,3 | 3,3 | 0,8 |
| 10 milhões | 502,3 | 1.256,2 | **5.337,6** | 10,0 | 1,9 |

📊 **Carga e armazenamento:** aos 10 milhões de linhas, PostgreSQL ocupa
1.187 MB e carrega em 93 s; DuckDB ocupa 472 MB e carrega em 11 s. Vantagem de
2,5× em espaço e 8× em tempo de carga, efeito da compressão colunar.

**Conclusões defensáveis:**

1. **O ponto de cruzamento não é único.** Depende do perfil de acesso: entre
   10 mil e 100 mil linhas para varredura; entre 100 mil e 1 milhão para filtro
   seletivo; não observado para busca pontual dentro do intervalo testado.
   Falar em "o volume a partir do qual usar colunar" é simplificação.
2. **Os motores escalam de forma diferente.** Multiplicando o volume por mil, a
   Q1 fica 295× mais lenta no PostgreSQL e 24× mais lenta no DuckDB. O colunar
   tem custo fixo maior — por isso perde em bases pequenas — mas cresce
   sublinearmente.
3. **A Q3 no PostgreSQL cresce superlinearmente** (2,6 → 34,7 → 384 → 5.338 ms):
   o agrupamento de alta cardinalidade com `COUNT(DISTINCT)` excede a memória de
   trabalho e passa a usar disco.
4. **Existe um limite prático identificável.** Aos 10 milhões de linhas a Q3
   ultrapassa 5 segundos, latência que inviabiliza uso interativo. Abaixo disso
   o pior caso do PostgreSQL permanece sob 400 ms.
5. **O índice B-tree mantém uma vantagem que não se perde.** O PostgreSQL vence
   a busca pontual em todas as escalas, com vantagem crescente.

⚠️ **Limitações do experimento, a declarar no texto:**

- O DuckDB é embarcado; o PostgreSQL paga serialização e transporte por socket
  mesmo em conexão local. Parte da diferença em consultas rápidas é custo fixo
  de protocolo, não do motor de armazenamento.
- Ambiente containerizado compartilhando CPU com o host. Duas execuções
  independentes da Q3 aos 10 milhões produziram 4.173 ms e 5.338 ms — variação
  de 28%. **Razões dentro de uma mesma execução são confiáveis; valores
  absolutos entre execuções distintas, não.** Diferenças inferiores a ~2× não
  sustentam conclusão.
- Uma única configuração de hardware; os resultados não se extrapolam para
  perfis de I/O muito distintos.
- Dados sintéticos. Foram tomados cuidados contra viés (distribuição lognormal
  do investimento, correlação entre métricas, cardinalidades calibradas pelo
  dado real), mas continuam sendo uma aproximação.

## 6. Validação e evidências

### 6.1 Paridade entre implementações

Método: manter as duas implementações em execução sobre os mesmos dados e
comparar agregados por dia e por plataforma, métrica a métrica.

📊 Resultado: linhas, investimento, impressões, cliques, valor de conversão,
alcance e visualizações de vídeo **idênticos**. Única divergência: conversões do
Google, explicada e justificada na seção 5.2 como correção.

Este procedimento é o que detectou o erro da seção 5.1 e deve ser descrito na
metodologia como técnica de validação de migração.

### 6.2 Testes automatizados

📊 73 testes executados a cada build:

| Categoria | O que verifica |
|---|---|
| Unicidade | Chaves substitutas não se repetem |
| Não-nulidade | Chaves e métricas obrigatórias preenchidas |
| Domínio | Plataforma pertence ao conjunto esperado; trimestre entre 1 e 4 |
| Integridade referencial | Toda linha do fato referencia dimensão existente, em todos os cinco níveis |
| Grão | Nenhuma combinação (anúncio, dia) se repete |
| Sanidade | Nenhuma métrica de mídia é negativa |
| Consistência SCD | Intervalos de validade não se sobrepõem; exatamente uma versão corrente por entidade |

### 6.3 Idempotência

Verificada empiricamente: executar o pipeline repetidamente sobre o mesmo
período mantém a tabela fato em 1.672 linhas, com zero duplicações no grão. A
camada bronze cresce a cada execução — comportamento esperado e desejado, já que
ela registra o histórico de extrações.

**Formulação para o texto:** a idempotência é o que torna possível o
reprocessamento seguro, e o reprocessamento seguro é o que torna possível
corrigir dados históricos sem duplicá-los.

---

## 7. Limitações

⚠️ Todas devem constar no texto. Reconhecer limitação é rigor; ser questionado
sobre uma limitação não declarada é falha.

1. **Cobertura desigual de métricas.** A consulta ao Google Ads não retorna
   alcance, visualizações de vídeo, visualizações de perfil nem compras no nível
   consultado. As colunas ficam zeradas para a plataforma. É ausência de suporte
   na consulta, não ausência de dado — e a distinção precisa estar no texto para
   não induzir leitura errada das comparações.
   ❓ Correção parcial identificada: `metrics.video_views` existe na linguagem de
   consulta do Google e não está sendo extraído.
2. **SCD Tipo 2 limitado pela granularidade da extração** — detecta renomeações
   entre extrações, não no instante em que ocorrem (seção 4.5).
3. **Materialização full-refresh** — a camada gold é reconstruída integralmente
   a cada execução. Adequado ao volume atual, insuficiente em outra ordem de
   grandeza.
4. **Integridade referencial mais fraca** que no modelo anterior (seção 4.3).
5. **Ausência de orquestração** — a execução é sequencial, sem política de
   repetição em caso de falha e sem agendamento.
6. **Comparação de conversões entre plataformas** tem ressalva de atribuição
   (seção 2.3).
7. **Série temporal curta** — cinco dias carregados. Suficiente para demonstrar
   a mecânica, insuficiente para análise de sazonalidade ou tendência.

---

## 8. Trabalhos futuros

- Orquestração com Apache Airflow.
- Materialização incremental da camada gold.
- Camada de consumo (painel analítico).
- Quantificação da deriva retroativa de métricas (seção 4.4).
- Extensão a outras plataformas (TikTok Ads, LinkedIn Ads) — o modelo
  dimensional já acomoda, bastaria um novo extrator e um novo modelo de staging.
- Detecção de anomalias em investimento e desempenho.

---

## 9. Questões pendentes de decisão

❓ Dependem do orientador ou de escolha ainda não feita:

1. **Benchmark PostgreSQL × DuckDB** como contribuição experimental —
   comparação de tempo de resposta em consultas analíticas com volumes
   crescentes (10 mil, 1 milhão, 50 milhões de linhas sintéticas). Transformaria
   a decisão da seção 4.1 de argumentação em evidência. Não implementado.
2. **Metodologia a declarar** — estudo de caso, Design Science Research ou
   pesquisa aplicada. Afeta como as evidências precisam ser registradas.
3. **Referencial teórico de modelagem dimensional** — Kimball, Inmon, ou
   contraste entre os dois.
4. **Autorização formal de uso dos dados** e forma de publicação do dataset.
5. **Camada de consumo** faz parte do escopo?
6. **Volume de dados** a ser demonstrado — dados reais apenas ou também volume
   sintético.

---

## 10. Conceitos a fundamentar teoricamente

Termos usados no trabalho que pedem referência na fundamentação:

- **Modelagem dimensional**, tabela fato, dimensão, grão, chave substituta,
  *surrogate key pipeline* — Kimball & Ross, *The Data Warehouse Toolkit*.
- **Star Schema × Snowflake Schema** — normalização de dimensões.
- **Slowly Changing Dimensions**, Tipos 0, 1 e 2 — Kimball.
- **Inmon × Kimball** — abordagens top-down e bottom-up de Data Warehouse.
- **ETL × ELT** — deslocamento da transformação para dentro do warehouse.
- **Arquitetura medalhão** (bronze/silver/gold) — organização em camadas de
  refinamento progressivo.
- **Idempotência** em processamento de dados.
- **Armazenamento orientado a linhas × orientado a colunas** — implicações para
  carga analítica.
- **Qualidade e testes de dados**.
- **Modelos de atribuição** em mídia paga — necessário para explicar conversões
  fracionadas e deriva retroativa.
- **LGPD** — tratamento de dados de terceiros, anonimização e pseudonimização.
  Atenção: a lei distingue os dois conceitos, e o que o trabalho faz é
  **pseudonimização** (reversível por quem detém o mapeamento), não anonimização
  irreversível. O texto deve usar o termo correto.

---

## 11. Glossário do domínio

Para o texto usar os termos com precisão:

| Termo | Significado |
|---|---|
| Conta de anúncios | Unidade de faturamento e organização; geralmente um cliente |
| MCC / Conta de gerenciamento | Conta que administra várias contas de anúncios |
| Campanha | Agrupamento com objetivo e orçamento definidos |
| AdSet (Meta) / Ad Group (Google) | Nível intermediário: define público, segmentação e lances |
| Anúncio | Peça criativa efetivamente exibida |
| Impressão | Exibição do anúncio |
| CTR | Cliques ÷ impressões |
| CPC | Investimento ÷ cliques |
| CPA | Investimento ÷ conversões |
| Alcance | Pessoas únicas atingidas (≠ impressões) |
| Conversão | Ação de valor definida pelo anunciante |
| Janela de atribuição | Prazo em que uma conversão é creditada a um anúncio |
| GAQL | Linguagem de consulta da API do Google Ads |

---

## 12. Cronologia do desenvolvimento

Útil caso a metodologia adotada exija registro de iterações (Design Science
Research, por exemplo):

| Período | Etapa |
|---|---|
| Mar–Abr/2026 | Versão 1: pipeline ETL, extratores, modelo dimensional, segurança |
| Abr–Ago/2026 | Interrupção do acesso ao Google Ads |
| 05/08/2026 | Restabelecimento do acesso; Data Warehouse local containerizado |
| 05/08/2026 | Migração para ELT em camadas com dbt; detecção do erro de união |
| 05/08/2026 | Implementação de SCD Tipo 2 e da pseudonimização |

---

## 13. Avisos para a redação

- **Não alegar ganho de desempenho** na migração para ELT. Não houve, e não era
  o objetivo.
- **Não chamar de "anonimização"** o que é pseudonimização (seção 10).
- **Não apresentar a comparação de CPA entre plataformas** sem a ressalva de
  atribuição.
- **Não omitir o erro da seção 5.1.** Ele é o achado mais forte do trabalho:
  demonstra rigor metodológico e produz uma lição generalizável.
- **Números desta nota são de 05/08/2026** e mudarão conforme novas cargas.
  Reconferir antes da versão final.
- O nome da agência e dos clientes **não deve aparecer** no texto publicado,
  ainda que apareça neste arquivo de trabalho.
