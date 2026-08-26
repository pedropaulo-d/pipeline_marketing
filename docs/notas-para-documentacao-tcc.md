# Notas para a documentação do TCC

Arquivo de trabalho. Reúne fatos, números medidos, decisões com justificativa e
achados do desenvolvimento, organizados pela estrutura típica de um TCC.

**Última atualização:** 19/08/2026 — seção 5.10 acrescentada; seção 5.4
pseudonimizada; seção 2 marcada como snapshot histórico.

⚠️ **Os números das seções 2, 6.2, 6.3 e 7 são de 06/08/2026 e foram superados
por cargas reais posteriores.** As seções 4 e 5 continuam válidas: dependem do
mecanismo e da ordem de grandeza, não do total do dia.

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

## 2. Fatos medidos sobre o sistema — SNAPSHOT HISTÓRICO DE 06/08/2026

🛑 **Esta seção inteira é um retrato congelado de 06/08/2026, quando havia cinco
dias carregados. NÃO descreve o estado atual do sistema.** Está preservada de
propósito, como evidência temporal de uma etapa do desenvolvimento.

⚠️ **Nenhum número desta seção deve ir para a monografia sem reconferência no
banco.** Execuções reais posteriores do pipeline ampliaram o armazém e
alteraram volume, período coberto e agregados. Antes de levar qualquer número
daqui para a monografia, confirmar o valor vigente no banco. O que **não**
envelhece são as decisões da seção 4 e os achados da seção 5, que dependem da
ordem de grandeza e do mecanismo, não do total do dia.


### 2.1 Volume de dados

📊 Números verificados em 06/08/2026:

| Métrica | Valor |
|---|---|
| Contas ativas descobertas — Meta Ads | 87 |
| Subcontas ativas descobertas — Google Ads | 64 |
| Registros por dia (as duas plataformas) | ~300 |
| Projeção anual | ~110 mil linhas |
| Projeção para 5 anos de histórico | < 600 mil linhas |
| Linhas na tabela fato (5 dias carregados) | 1.677 |
| Linhas na camada bronze (16 lotes acumulados) | 10.168 |
| Tamanho das camadas bronze + silver + gold | 10,3 MB |
| Tamanho da camada bronze | 9,4 MB |
| Tamanho da tabela fato (gold) | 296 kB |
| Tempo de extração — Meta (87 contas) | ~2 minutos |
| Tempo de extração — Google (64 subcontas) | ~100 segundos |
| Tempo de transformação + testes (dbt) | ~3 segundos |
| Modelos dbt | 11 (3 views silver, 7 tabelas gold, 1 view de consumo) |
| Testes de dados automatizados | 72 |

⚠️ O schema `public` do mesmo banco guarda a tabela do benchmark (seção 5.6),
cerca de 1,2 GB. Não confundir com o tamanho do armazém: o pipeline em si ocupa
os 10,3 MB acima.

**Este é o dado mais importante do trabalho para justificar escolhas de
arquitetura.** Ver seção 4.1.

### 2.2 Períodos carregados

📊 07/04/2026 e 01/08 a 04/08/2026.

A descontinuidade tem causa documentada: o acesso à API do Google Ads foi
perdido entre abril e agosto (seção 5.3).

### 2.3 Resultado analítico consolidado

📊 Agregado dos 5 dias, extraído da camada gold em 06/08/2026:

| Plataforma | Linhas | Investimento | Impressões | Cliques | Conversões | CTR | CPC | CPA |
|---|---|---|---|---|---|---|---|---|
| Meta Ads | 666 | R$ 8.210,07 | 827.932 | 6.989 | 228,00 | 0,84% | R$ 1,17 | R$ 36,01 |
| Google Ads | 1.011 | R$ 12.006,66 | 114.193 | 4.989 | 383,79 | 4,37% | R$ 2,41 | R$ 31,28 |

Esta tabela é o **resultado que demonstra o objetivo geral**: a comparação entre
plataformas só é possível porque os dois modelos foram unificados. Vale comentar
no texto o contraste de perfil: o Meta entrega volume de impressões muito maior
com CTR baixo (mídia de descoberta, interruptiva), enquanto o Google entrega
menos impressões com CTR cinco vezes maior (mídia de intenção, o usuário buscou).

🛑 **Esta tabela substitui uma versão anterior com números inflados em ~7,8%**
(Meta R$ 9.345,30, Google R$ 12.449,89, 1.778 linhas). A causa está na seção
5.9: a consulta juntava as dimensões versionadas pela chave natural sem
resolver a versão vigente, e cada entidade renomeada multiplicava as linhas do
fato. **Se algum texto já redigido citar os valores antigos, precisa ser
corrigido.** A soma das linhas por plataforma tem de fechar com o total do fato
(1.677) — é a verificação de um segundo que denuncia o erro.

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

O caminho antigo foi mantido no código enquanto durou a validação por
comparação (seção 6.1) e **removido em 06/08/2026**, quando o projeto passou a
ter uma arquitetura só. O código permanece no histórico do versionamento.

**Formulação para o texto:** manter as duas implementações em paralelo foi um
instrumento de validação com prazo, não uma decisão de arquitetura. Enquanto
coexistiam, o pipeline tinha dois caminhos com semânticas diferentes escrevendo
no mesmo banco — a fato do ETL e a fato da gold, com números que divergiam por
motivo legítimo (seção 5.2). Uma vez cumprida a função de validar, manter o
caminho antigo passaria a ser passivo: código sem uso, um schema paralelo no
armazém e a chance de alguém consultar a tabela errada numa apresentação.

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

### 4.6 Pseudonimização fora do pipeline

⚖️ **Decisão:** a pseudonimização roda na fronteira de exposição, não na
ingestão.

**Justificativa:** mantém a lógica do pipeline idêntica para dado real e dado
pseudonimizado, evitando dois caminhos de transformação que poderiam divergir.
O material principal da Defesa é exportado da view canônica do Gold para uma
superfície própria; o JSON bruto desidentificado é apenas ferramenta secundária
de reprodução.

**Princípios adotados:**

1. HMAC-SHA256 com chave local não versionada e separação de domínio por nível
   e plataforma — a mesma entidade mantém o rótulo, sem mapa persistente nem
   salt atacável por dicionário.
2. Substituição integral dos nomes — marca, datas embutidas, localidades,
   produtos, colchetes e convenções internas não sobrevivem como fingerprint.
   Nome e ID recebem a mesma identidade pública.
3. Contrato *fail closed* — coluna, campo aninhado ou tipo de ação novo exige
   revisão explícita; nada desconhecido é copiado por omissão.
4. Métricas e datas intactas — a transformação não arredonda, converte nem
   trunca valores, inclusive conversões fracionadas e itens de ação.
5. Destinos têm intenção distinta: `data/anonimizado/` é local e secundário;
   `data/exposicao/` é a superfície da Defesa; `data/publico/` exige flag e
   autorização específica da agência.

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

ℹ️ Em 06/08 o total do Google subiu para 383,79 na reextração do mesmo período:
são +3,50 conversões creditadas retroativamente pela janela de atribuição, não
alteração de método. A comparação acima continua válida como medida da
diferença entre truncar e não truncar; para citar no texto, use o par de
valores medido no mesmo instante.

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

📊 Três campanhas foram renomeadas entre abril e agosto nos dados reais.

⚠️ **Os nomes abaixo são pseudônimos documentais.** Os nomes reais carregam
marca do cliente, razão social e datas de convenção interna — identificadores
diretos e indiretos que não podem constar de material exposto (ver seção 4.6).
O que está preservado é a **estrutura** do nome e a **natureza da mudança**, que
é o que sustenta o argumento. Estes rótulos são exemplo de documentação: não
são os pseudônimos do dataset de exposição, que vêm de HMAC com chave local.

| # | Versão 1 (07/04 – 31/07) | Versão 2 (01/08 – atual) | O que mudou |
|---|---|---|---|
| A | `[MARCA_A] [OBJETIVO] [CANAL] DD/MM/AAAA` | `[MARCA_A] [OBJETIVO] [CANAL] AAMMDD` | só o formato da data embutida |
| B | `[FORMATO] [SECAO] DD/MM/AA` | `[OBJETIVO] [SECAO] [FORMATO] - DD/MM/AA` | vocabulário e ordem dos tokens |
| C | `[MARCA_C] EMPRESA_C_GRAFIA_1 DD-MM` | `[MARCA_C] EMPRESA_C_GRAFIA_2 DD-MM` | correção de erro de digitação |

A forma dos nomes é ela própria um dado do domínio e vale registrar no texto:
são cadeias de tokens entre colchetes que codificam convenção operacional
— marca, objetivo, canal, formato, seção do site — seguidas de uma data de
criação. É exatamente o que a seção 4.5 usa para justificar o SCD Tipo 2: nome
de campanha em mídia paga é campo operacional volátil, não rótulo estável.

📊 Efeito no modelo, medido em 06/08/2026: `dim_campanha` passou a ter 180
linhas para 177 entidades; `dim_adset`, 337 para 334; `dim_conta`, 58 para 57.

Serve como **evidência empírica** de que o problema que o SCD Tipo 2 resolve não
é hipotético neste domínio. Note que o caso C é correção de erro de digitação na
razão social, o que mostra que o histórico também preserva o registro de
correções — e que uma renomeação pode ser semanticamente irrelevante e ainda
assim criar uma versão nova na dimensão.

### 5.5 Perfis distintos das plataformas

🔍 Os dados consolidados evidenciam comportamentos diferentes: o Meta entrega
volume de impressões cerca de sete vezes maior com CTR de 0,84%, enquanto o
Google entrega menos impressões com CTR de 4,37%. É a diferença esperada entre
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

### 5.7 Filtro por estado atual apaga dado histórico

🔍 **Segundo achado metodológico forte.** Mesma família do 5.1: um erro que
nenhum teste de estrutura poderia detectar, revelado por comparação numérica.

**Contexto.** A consulta ao Google Ads filtrava por campanhas com status
`ENABLED`. O filtro parece inofensivo — "traga só o que está ativo" — e estava
na primeira versão do extrator desde março.

**O problema.** O status é um atributo **mutável e do presente**; as métricas
são de um **dia passado**. Ao reextrair 01–04/08/2026 em 06/08, as campanhas
pausadas nesse intervalo deixaram de ser retornadas — junto com o investimento
que elas de fato realizaram naqueles dias.

**Consequência, e é aqui que a arquitetura amplifica o erro.** A camada silver
deduplica adotando o snapshot mais recente de cada dia. Um lote menor não
convive com o anterior: ele o substitui. A reextração, que existe justamente
para *corrigir* dado histórico, **apagou** R$ 210,57 de investimento real de
04/08 — uma campanha inteira, 284 impressões, que já estavam corretamente
carregadas no armazém.

📊 Efeito medido sobre o período 01–04/08:

| Lote | Linhas | Investimento | Impressões |
|---|---:|---:|---:|
| Extração original (05/08) | 836 | R$ 9.791,28 | 104.523 |
| Reextração com o filtro (06/08) | 840 | R$ 9.580,70 | 104.272 |
| Reextração sem o filtro (06/08) | 841 | R$ 9.791,26 | 104.556 |

**Por que a contagem de linhas não denunciou.** Este é o detalhe que dá força
ao achado: no mesmo dia em que a campanha desapareceu, cinco anúncios novos
passaram a aparecer. O total do dia **subiu** de 250 para 254 linhas enquanto
o dado era perdido. Qualquer monitoramento por volume de lote — a defesa
intuitiva — teria dado sinal verde. Só a comparação no grão do anúncio revela
a subtração.

**Correção.** O filtro foi removido. Sem ele, a consulta retorna apenas
anúncios com entrega no período, que é o critério correto: quem gastou naquele
dia estava ativo naquele dia. A verificação passou a ser automatizada no teste
`assert_reextracao_nao_perde_gasto`, que compara os dois snapshots mais
recentes de cada dia no grão do anúncio e alerta quando um anúncio com gasto
desaparece. Severidade de alerta, não de erro: desaparecer pode ser legítimo
(anúncio excluído da conta); o teste não decide se está errado, obriga a olhar.

**Lição a registrar no texto:** em séries históricas, filtrar pelo estado atual
de uma entidade mutável reescreve o passado. O filtro precisa incidir sobre o
que era verdade na data do fato — ou não incidir. Vale para qualquer campo
mutável da fonte usado como critério de seleção, em qualquer API de terceiros.

**Ligação com o resto do trabalho:** a camada bronze append-only foi o que
tornou o diagnóstico possível. Os dois lotes coexistiam na tabela bruta, então
a comparação entre eles foi uma consulta SQL. Se o pipeline sobrescrevesse o
dado, a perda seria silenciosa e irrecuperável — argumento direto a favor da
decisão da seção 4.4.

### 5.8 Divergência de definição sob nome comum de métrica

🔍 Ao fechar a lacuna de `video_views` do Google, o campo `metrics.video_views`
não existia mais na versão 25 da API; o sucessor é `metrics.video_trueview_views`.
A substituição não é apenas de nome:

| Plataforma | O que conta como visualização |
|---|---|
| Meta | A partir de 3 segundos de exibição |
| Google (TrueView) | 30 segundos, vídeo completo ou interação com o anúncio |

📊 No período carregado, o Meta registra cerca de 19 mil visualizações por dia
contra cerca de 500 do Google. A ordem de grandeza da diferença é em parte real
(mix de mídia distinto) e em parte artefato de definição — e não há como separar
as duas contribuições a partir do dado.

**Decisão tomada:** a métrica ocupa a mesma coluna no modelo dimensional, com a
ressalva documentada no modelo `stg_google_ads`. Preencher com zero seria pior:
afirmaria ausência de visualizações onde há dado real. A série de cada
plataforma é válida e comparável ao longo do tempo; a soma entre plataformas
não tem significado.

**Valor argumentativo:** unificar plataformas num vocabulário comum é o objetivo
do trabalho, mas nome igual não implica definição igual. O ponto merece parágrafo
próprio na discussão sobre integração de fontes heterogêneas — é uma limitação
conceitual, não de implementação, e nenhuma engenharia a resolve.

### 5.9 SCD Tipo 2 altera a semântica do `JOIN`

🔍 **Terceiro achado da mesma família — e o mais insidioso**, porque não produz
erro nenhum: produz um número plausível, maior que o verdadeiro.

**Contexto.** Com dimensões versionadas, uma entidade renomeada passa a ter
duas linhas na dimensão, com intervalos de validade disjuntos. A chave natural
(`_nk`) é estável entre versões — é isso que a torna útil para ligar a
hierarquia sem cascatear versões.

**O erro.** Juntar o fato à dimensão pela chave natural, sem restringir à
versão vigente na data do fato, multiplica cada linha do fato pelo número de
versões da entidade. O `JOIN` deixa de ser 1:1 e vira 1:N — silenciosamente,
porque o resultado continua sendo uma tabela com colunas plausíveis.

📊 Medido sobre o armazém em 06/08/2026, com apenas 3 entidades renomeadas
entre 180 campanhas, 337 conjuntos e 57 contas:

| Rota de consulta | Linhas | Investimento total |
|---|---:|---:|
| Agregado direto do fato (correto) | 1.677 | R$ 20.216,73 |
| `JOIN` pela chave natural sem resolver versão | 1.783 | R$ 21.795,17 |

Três renomeações inflaram o investimento total em **7,8%**. O erro cresce com
o histórico: quanto mais o armazém acumula versões, maior a distorção.

**Como foi detectado:** ao recalcular a tabela de resultados consolidados
(seção 2.3) e notar que a soma das linhas por plataforma não fechava com o
total da tabela fato. A verificação é trivial e deve virar rotina.

**Forma correta:** a versão se resolve pela data do fato.

```sql
join gold.dim_adset s
  on  s.adset_nk = a.adset_nk
  and t.data between s.valido_de and s.valido_ate
```

**Lição a registrar no texto:** SCD Tipo 2 não é uma decisão apenas de
modelagem — é uma decisão que altera o contrato de consulta do armazém. Toda
consulta passa a ter a obrigação de declarar em que instante do tempo está
olhando. Um modelo dimensional versionado consultado como se não fosse
versionado devolve números errados sem sinalizar nada.

⚠️ **Consequência prática para o TCC:** qualquer número já extraído do armazém
por essa rota precisa ser recalculado antes de entrar no texto. A tabela da
seção 2.3 já foi corrigida.

---

### 5.10 Deriva retroativa medida em produção

🔍 O experimento mais forte do trabalho sobre a natureza da fonte. Uma execução
agendada do pipeline reextraiu sete dias completos anteriores e permitiu
comparar, chave a chave, o estado do armazém antes e depois — com datas de
controle deliberadamente **fora** da janela.

O desenho experimental separa três grupos de datas:

- **controle** — datas fora da janela reextraída, que não podem mudar;
- **reextração** — datas já carregadas e consultadas de novo, que podem mudar;
- **novas** — datas que entram no armazém pela primeira vez.

📊 Resultado do controle: todas as datas fora da janela permaneceram idênticas
nas duas plataformas, em todas as nove métricas. Nenhuma linha removida. É a
prova de que a reextração **substitui apenas o que estava na janela** e não
contamina o histórico.

📊 Resultado da reextração, agregado sobre os cinco dias reextraídos:

| Métrica | Google Ads | Meta Ads |
|---|---|---|
| linhas | 0 | +8 |
| investimento | −0,001698 | +121,87 |
| impressões | −4 | +8.223 |
| cliques | −2 | +140 |
| conversões | 0 | +6 |
| valor de conversão | 0 | 0 |
| video views | 0 | +33 |
| alcance | 0 | +7.209 |
| compras | 0 | +12 |

🔍 **O achado central é a assimetria entre as plataformas.** Das cinco chaves
reextraídas por plataforma, o Google manteve duas idênticas e alterou três, com
deriva desprezível e de sinal negativo — o maior desvio relativo válido ficou
abaixo de 0,1%, compatível com invalidação de cliques pela própria plataforma.
O Meta alterou **todas as cinco**, em oito métricas distintas, com desvio
relativo de até ~7,7% no dia mais antigo da janela.

O padrão é coerente com o mecanismo: a janela de atribuição do Meta credita
conversões e consolida entrega por dias depois do fato, enquanto o relatório do
Google já chega praticamente estabilizado nesse nível de agregação. A deriva
**decresce conforme a data se afasta da borda recente da janela**, o que é
exatamente o comportamento esperado de consolidação retroativa.

⚖️ Isso converte a janela móvel de sete dias de uma escolha defensável em uma
escolha **medida**. Extrair apenas o dia anterior congelaria números que ainda
iriam mudar; e o custo de reextrair sete dias é baixo justamente por causa das
duas decisões que já existiam — bronze append-only e "último snapshot vence" na
silver.

⚠️ `video_views` aparece na tabela por plataforma e **não deve ser somado entre
elas**: as definições são diferentes (seção 5.8).

⚠️ Quando o valor anterior é zero, não existe variação percentual. O caso
ocorreu com `purchases` do Meta em três dias reextraídos, que saíram de zero.
Registrar a variação absoluta e dizer que o percentual não se aplica; inventar
um denominador seria erro metodológico.

#### O que o mesmo experimento provou sobre as camadas

📊 Cada camada foi verificada de forma independente na mesma execução:

- **bronze append-only** — a reextração criou exatamente um lote novo por
  plataforma; todos os lotes anteriores permaneceram presentes, com contagem de
  linhas, intervalo de datas e assinatura de conteúdo inalterados. Nenhum lote
  foi removido ou reescrito. É o que torna a deriva **mensurável**: os dois
  snapshots do mesmo dia coexistem;
- **silver "último snapshot vence"** — para cada data reextraída a bronze passou
  a conter dois snapshots, e a silver apresentou **exatamente um**, o mais
  recente, sem duplicidade semântica por anúncio × dia;
- **gold sem inflação de grão** — o grão de um anúncio por dia permaneceu único,
  e a contagem obtida percorrendo a hierarquia versionada coincidiu com a
  contagem do fato. É a verificação que denuncia o erro da seção 5.9;
- **SCD Tipo 2** — o armazém ganhou entidades novas e **versões novas**,
  inclusive a primeira renomeação de anúncio registrada, uma dimensão que até
  então não tinha nenhuma entidade multiversão. Reforça a seção 5.4: o problema
  que o SCD2 resolve continua acontecendo, e não só em campanha.

🔍 A comparação foi feita por **chave natural** (plataforma × data), não por
posição. Isso importa metodologicamente: uma comparação posicional acusaria
divergência em cascata a partir da primeira data nova inserida no meio da
sequência, escondendo o que de fato mudou. A comparação por chave classifica
cada divergência em nova, removida, alterada ou idêntica, e foi validada por uma
análise independente que reproduziu as mesmas contagens.

**Formulação para o texto:** um armazém que consome fontes com atribuição
retroativa não pode tratar a carga como imutável nem a reextração como falha; a
combinação de camada bruta append-only, dedução do snapshot vigente e dimensões
versionadas é o que permite absorver a mudança do passado sem perder o registro
de que ela ocorreu.

### 5.11 A camada de consumo revela o que o modelo esconde

Implementada em 25/08/2026: painel em Streamlit + Plotly consumindo
exclusivamente a superfície de exposição pseudonimizada. Documentação completa
em `docs/tcc/dashboard-implementado.md`; auditoria afirmação-a-evidência em
`docs/tcc/evidencias-dashboard.md`.

O achado relevante para o texto **não** é a existência do painel — é o que
projetar a interface obrigou a explicitar. Um modelo dimensional trata as nove
métricas como nove colunas numéricas equivalentes. A tela não pode: ela precisa
decidir o que somar, o que comparar e o que recusar a comparar. Três
propriedades, invisíveis no schema, tiveram de virar declaração:

1. **Suporte por plataforma.** `reach`, `profile_views` e `purchases` não são
   fornecidas pela consulta ao Google no nível consultado. Somar as duas
   plataformas produz um total que subestima uma e sugere desempenho nulo na
   outra. A interface marca "não disponibilizado nesta origem" em vez de exibir
   zero.
2. **Comparabilidade semântica.** `video_views` existe nas duas com definições
   diferentes (seção 5.8). O total entre plataformas é aritmeticamente
   calculável e analiticamente vazio.
3. **Aditividade no tempo.** `reach` conta pessoas únicas: somar dias distintos
   conta a mesma pessoa várias vezes. Um cartão de "alcance do período" seria
   simplesmente errado — e nada no schema impediria de construí-lo.

As três propriedades passaram a viver num catálogo único
(`dashboard/metricas.py`), consultado pelo resto da aplicação. É o mesmo padrão
de `plataformas.py`: a propriedade é declarada uma vez, não redescoberta em
cada tela.

**Consequência para a redação.** Vale afirmar que o modelo dimensional
unificado permite consultar as duas plataformas pela mesma rota; **não** vale
afirmar que unifica a semântica das métricas. Unificar estrutura e unificar
significado são coisas diferentes, e a camada de consumo é onde a diferença
aparece.

**Segundo achado — a fronteira de exposição sobrevive à camada de
visualização.** O painel é o primeiro artefato do projeto feito para ser
projetado em tela e fotografado. Ele não recebe credencial, não instala driver
de banco nem SDK de plataforma, e recusa inteiro qualquer arquivo que carregue
coluna de identidade real. O dataset sintético de demonstração passa no **mesmo
auditor independente** da superfície real, o que permite ao repositório
continuar demonstrável sem nenhum dado de cliente.

**Decisão visual final.** A interface adotou dark mode nativo e fixo, não
dependente do sistema do avaliador. O acabamento não é apenas cosmético: o
tema Plotly centralizado, os rankings e comparativos horizontais e a distinção
textual `✓ Disponível` / `— Não disponível` reduzem ambiguidade de leitura.
Meta e Google usam cor, rótulo e tooltip simultaneamente; a identidade global
usa violeta apenas em foco e seleção. Na matriz Playwright de 1024×768 a
1920×1080 houve zero overflow de página, zero label de gráfico cortada e zero
toolbar Plotly visível. O muted inicialmente proposto precisou ser clareado
para atingir contraste AA em texto pequeno sobre os cards dark — evidência de
que inspeção visual e medição de acessibilidade são gates diferentes.


### 5.12 Número correto e apresentação ambígua não são a mesma coisa

Validação manual de 25/08/2026, conferindo o painel contra as interfaces do
Google Ads e do Meta Ads. Nenhum erro de cálculo foi encontrado — e ainda
assim duas leituras precisaram de correção, ambas na apresentação.

**Nome diferente para o mesmo indicador.** O que o painel chama de **CPA**
aparece no Google Ads como **"Custo / conv."**. Conferido no recorte de
validação: investimento de R$ 142,46 sobre 5 conversões dá R$ 28,49, o mesmo
valor exibido pela plataforma. O indicador estava certo; faltava dizer ao
leitor que os dois nomes designam a mesma conta.

**Mesma razão, duas convenções de escala.** O ROAS é
`valor de conversão / investimento`. Para 4,00 sobre 142,46 isso dá
aproximadamente 0,028078. O painel exibia `0,03` — arredondado a duas casas,
sem unidade, e portanto lido como se fosse um número qualquer. O Google, numa
métrica personalizada, apresentava a mesma razão como **2,81%**. Não há
divergência: `0,028078x` e `2,8078%` são a mesma quantidade em convenções
diferentes.

Duas casas decimais fixas destroem justamente a faixa em que o ROAS é baixo,
que é a faixa em que a leitura importa: `0,03` e `0,028` diferem em ordem de
grandeza para quem decide. A correção foi de apresentação, não de fórmula — o
cálculo permaneceu intacto — e tem duas partes: sufixo `x` explícito, para o
número se declarar multiplicador; e casas decimais escolhidas pela ordem de
grandeza (três abaixo de 0,1; duas a partir de 0,1), de modo que
`0,028x`, `2,00x` e `12,54x` convivam sem achatamento.
Valor não nulo abaixo de 0,001 sai como `< 0,001x`, porque `0,000x` seria
lido como ausência de retorno.

**Consequência para a redação.** Vale como quarto caso da família "número
certo, alarme silencioso" das seções 5.1, 5.7 e 5.9 — com uma diferença que
convém explicitar: aqui o pipeline estava correto de ponta a ponta e o defeito
morava na última polegada, entre o número e o leitor. Rastreabilidade não
termina no dado; termina na leitura. E a comparação com a interface da
plataforma — nome do indicador, convenção de escala, casas exibidas — é um
passo de validação distinto da conferência aritmética, porque encontra o que a
aritmética não tem como encontrar.

**Consequência para o painel.** As definições deixaram de ser conhecimento
tácito e viraram ajuda contextual por métrica, no mesmo catálogo declarativo
da seção 5.11 (`dashboard/metricas.py`): a fórmula, a leitura e a
correspondência com o nome usado pela plataforma acompanham o indicador na
tela, escondidas até serem pedidas.



## 6. Validação e evidências

### 6.1 Paridade entre implementações

Método: manter as duas implementações em execução sobre os mesmos dados e
comparar agregados por dia e por plataforma, métrica a métrica.

📊 Resultado: linhas, investimento, impressões, cliques, valor de conversão,
alcance e visualizações de vídeo **idênticos**. Única divergência: conversões do
Google, explicada e justificada na seção 5.2 como correção.

Este procedimento é o que detectou o erro da seção 5.1 e deve ser descrito na
metodologia como técnica de validação de migração.

ℹ️ A comparação foi refeita em 06/08 sobre o período 01–04/08, já com a
cobertura de visualizações de vídeo: linhas, investimento, impressões, cliques
e visualizações **idênticos** nas duas implementações; conversões do Google
283,00 (ETL, truncado) contra 287,29 (ELT) — a mesma divergência da seção 5.2,
reproduzida. Em seguida o caminho ETL foi removido do projeto. As medidas
acima são o registro final da paridade; reproduzi-las exige recuperar o código
do histórico do versionamento.

### 6.2 Testes automatizados

📊 72 testes executados a cada build (o `dbt build` reporta `PASS=83`, que é a
contagem de **nós**: 11 modelos + 72 testes — não citar 83 como número de
testes):

| Categoria | O que verifica |
|---|---|
| Unicidade | Chaves substitutas não se repetem |
| Não-nulidade | Chaves e métricas obrigatórias preenchidas |
| Domínio | Plataforma pertence ao conjunto esperado; trimestre entre 1 e 4 |
| Integridade referencial | Toda linha do fato referencia dimensão existente, em todos os cinco níveis |
| Grão | Nenhuma combinação (anúncio, dia) se repete |
| Sanidade | Nenhuma métrica de mídia é negativa |
| Consistência SCD | Intervalos de validade não se sobrepõem; exatamente uma versão corrente por entidade |
| Regressão entre lotes | Nenhum anúncio com gasto desaparece entre o snapshot anterior e o mais recente do mesmo dia (seção 5.7) |

O último é de severidade **alerta**, não erro: um anúncio pode legitimamente
sumir da fonte. A distinção entre "o pipeline deve parar" e "alguém precisa
olhar" é ela própria uma decisão de projeto que vale mencionar no texto.

### 6.3 Idempotência

Verificada empiricamente: executar o pipeline repetidamente sobre o mesmo
período mantém a tabela fato no mesmo grão, com zero duplicações. A camada
bronze cresce a cada execução — comportamento esperado e desejado, já que ela
registra o histórico de extrações.

⚠️ **Precisão necessária no texto:** idempotência aqui significa "não duplica",
não "produz o número idêntico". A reextração de 06/08 devolveu 1.677 linhas
onde havia 1.672, e o investimento do Google variou dois centavos. As causas
são legítimas e distintas — anúncios novos com entrega tardia, cliques
invalidados pela plataforma, conversões creditadas retroativamente. Confundir
os dois sentidos de idempotência levaria a apresentar a variação como falha,
quando ela é o comportamento correto diante de uma fonte que muda o passado.

**Formulação para o texto:** a idempotência é o que torna possível o
reprocessamento seguro, e o reprocessamento seguro é o que torna possível
corrigir dados históricos sem duplicá-los.

---

## 7. Limitações

⚠️ Todas devem constar no texto. Reconhecer limitação é rigor; ser questionado
sobre uma limitação não declarada é falha.

1. **Cobertura desigual de métricas.** A consulta ao Google Ads não retorna
   alcance, visualizações de perfil nem compras no nível consultado. As colunas
   ficam zeradas para a plataforma. É ausência de suporte na consulta, não
   ausência de dado — e a distinção precisa estar no texto para não induzir
   leitura errada das comparações.
   ✅ Fechada em parte: visualizações de vídeo passaram a ser extraídas em
   06/08. Mas a lacuna trocou de natureza em vez de sumir — a definição da
   métrica difere entre as plataformas (seção 5.8), então a coluna deixou de
   ser incomparável por estar vazia e passou a ser incomparável por medir
   coisas diferentes. O dia 07/04/2026 permanece zerado por decisão: reextraí-lo
   traria os nomes atuais para uma data passada e destruiria as três versões
   SCD Tipo 2 do armazém, que é a evidência da seção 4.5.
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
- ~~Camada de consumo (painel analítico).~~ ✅ Implementada em 25/08/2026 —
  Streamlit + Plotly sobre a superfície de exposição (seção 5.11).
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
5. ~~**Camada de consumo** faz parte do escopo?~~ Resolvida: implementada em
   25/08/2026 como camada demonstrativa de consumo, não como produto de BI
   (seção 5.11).
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
| 05/08/2026 | Benchmark row-store × column-store |
| 06/08/2026 | Cobertura de visualizações de vídeo do Google; detecção do filtro por status e da inflação por versão de dimensão |
| 06/08/2026 | Remoção do caminho ETL — o projeto passa a ter uma arquitetura só |

---

## 13. Avisos para a redação

- **Não alegar ganho de desempenho** na migração para ELT. Não houve, e não era
  o objetivo.
- **Não chamar de "anonimização"** o que é pseudonimização (seção 10).
- **Não apresentar a comparação de CPA entre plataformas** sem a ressalva de
  atribuição.
- **Não omitir o erro da seção 5.1.** Ele é o achado mais forte do trabalho:
  demonstra rigor metodológico e produz uma lição generalizável. As seções 5.7
  e 5.9 formam a mesma família e sustentam um argumento único: **erro de
  conteúdo não dispara alarme** — três vezes, por três mecanismos diferentes,
  o pipeline produziu números errados com todos os testes verdes.
- **Não citar a tabela antiga da seção 2.3.** Os valores foram corrigidos em
  06/08; a versão anterior estava inflada em 7,8% (seção 5.9).
- **Não somar visualizações de vídeo entre plataformas** (seção 5.8).
- **Números desta nota são de 06/08/2026** e mudarão conforme novas cargas.
  Reconferir antes da versão final — e sempre pela rota de consulta correta:
  a soma das linhas por plataforma tem de fechar com o total da tabela fato.
- **Este arquivo é versionado.** O nome da agência, de clientes, marcas, razões
  sociais, identificadores externos e nomes reais de campanha, conjunto ou
  anúncio **não podem aparecer aqui** — nem como exemplo. A seção 5.4 usa
  pseudônimos documentais por esse motivo. Identificador indireto conta:
  localidade, produto, data de convenção interna e abreviação associável a
  cliente também não entram.
- **Números vencidos.** As seções 2, 6.2, 6.3 e 7 guardam medidas de 06/08/2026
  já superadas por cargas reais posteriores — contagem de testes, linhas do
  fato, dias carregados e o estado da orquestração mudaram. A seção 2 está
  marcada como snapshot histórico; as demais ainda não foram revisadas. Confira
  no banco antes de citar qualquer número, e sempre pela rota de consulta
  correta.
