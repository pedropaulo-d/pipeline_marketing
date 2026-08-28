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


### 5.13 Descoberta pelo estado corrente pode suprimir história

Na consolidação do recorte experimental de 30 dias, o teste de regressão entre
lotes encontrou 54 observações Meta com gasto positivo que existiam na Bronze
e haviam desaparecido da Silver. Elas pertenciam a uma única conta e cobriam
12 dias. A investigação do histórico completo encontrou ainda 11 observações
relacionadas que o teste anterior não alcançava: três sem gasto positivo nos
mesmos dias e oito em um 13º dia, ocultas por omissões consecutivas. Ao todo,
65 linhas e R$ 429,34 continuavam preservados na Bronze.

O incidente combinou duas decisões que isoladamente pareciam razoáveis. A
descoberta Meta aceitava somente contas com estado corrente `ACTIVE`, embora o
estado de entrega de hoje não determine a existência de métricas passadas. Em
seguida, a Silver tratava o lote mais recente de uma fonte e dia como
substituição integral do lote anterior. A conta ausente da descoberta fez o
novo lote parecer completo; ao vencer por dia, ele apagou logicamente todo o
histórico conhecido daquela entidade.

**Correção.** A descoberta passou a classificar explicitamente os estados do
SDK que ainda permitem tentar uma consulta histórica. Estado indisponível ou
desconhecido aborta a extração, em vez de produzir silenciosamente um lote
parcial. Na Silver, a deduplicação passou a escolher a observação mais recente
pela chave hierárquica natural da entidade e pela data. Assim, uma observação
presente e revisada vence a anterior, mas ausência sem tombstone não vira zero
nem exclusão.

Essa escolha é conservadora: pode reter a última observação conhecida quando a
fonte deixa de devolver uma entidade intencionalmente. O contrato bruto atual
não contém tombstone nem prova de completude por conta, portanto não existe
evidência para distinguir essa situação de uma extração parcial. Uma evolução
mais forte seria registrar completude e tombstones por conta e período, mas
isso exigiria ampliar manifesto, carga e Bronze; não era necessário para
recuperar o histórico já preservado.

**Regressão determinística.** Testes unitários simulam dois anúncios no lote
antigo e somente um no novo: o presente recebe a métrica revisada e o ausente
mantém a última observação válida. Outro caso confirma a atualização dos dois
quando ambos reaparecem; um terceiro deixa duplicatas empatadas visíveis para
os testes de grão falharem fechado. O mesmo contrato é exercitado para Google.
O teste de regressão em produção agora percorre todo o histórico Bronze, não
apenas o penúltimo lote, e falha se uma chave que já teve gasto positivo não
chegar à Silver.

**Limite da recuperação.** A Bronze recuperou integralmente as 65 observações
conhecidas, mas não prova que a conta teve zero em dias para os quais nunca há
uma observação dela. Ausência de registro não foi preenchida artificialmente.
Para afirmar completude do recorte inteiro, esses dias exigem consulta nova à
fonte, autorizada e auditada separadamente.

**Fechamento da lacuna por reextração autorizada (25/08/2026).** A consulta
nova foi autorizada e executada em três janelas restritas exatamente às 17
datas sem evidência, somente para o Meta. A descoberta devolveu 95 contas — oito
a mais do que as 87 que o filtro antigo enxergava. A conta suprimida apareceu
com estado `unsettled`, e não `active`: a causa raiz ficou confirmada
empiricamente, e não apenas por inferência sobre o código. Os estados
observados foram 85 `active`, 3 `disabled`, 5 `unsettled` e 2
`temporarily_unavailable`.

**A proteção contra snapshot parcial precisou de uma válvula explícita.** A
regra de falhar fechado diante de `temporarily_unavailable` bloqueava toda
extração do Meta enquanto qualquer conta estivesse nesse estado, inclusive a
recuperação de períodos sem relação com ela. O desvio virou opt-in por
execução, declarado na linha de comando, registrado em log e proibido à DAG;
estado desconhecido continua abortando em qualquer caso. Isso é uma
generalização do princípio de falhar fechado: a proteção precisa ter uma porta
auditável, senão o próprio conserto fica impedido pela proteção.

**Resultado.** A reextração acrescentou 3 lotes e 2.040 linhas à Bronze, sem
tocar nas 48.407 anteriores. Na Silver, 60 linhas novas — todas da conta antes
suprimida — e nenhuma entidade dimensional nova, porque os anúncios já eram
conhecidos pelas observações recuperadas. O recorte de 30 dias passou de 10.594
para 10.654 linhas, com R$ 456,06 de investimento adicional. A decomposição
separa os dois efeitos: R$ 455,62 vêm da conta recuperada e R$ 0,44 de deriva
retroativa legítima nas demais contas, o comportamento já documentado da API do
Meta. Impressões, cliques, alcance, conversões e video views seguem a mesma
separação.

**Ausência continua não sendo zero.** Em três das 17 datas a conta foi
consultada e não retornou linha nenhuma. Isso não virou registro zerado nem
tombstone: a diferença é que agora existe evidência de que a consulta cobriu o
dia, o que antes não existia. Ausência dentro de uma janela efetivamente
consultada e ausência por conta nunca consultada são fatos distintos, e só o
segundo impede afirmar completude.

**A mesma classe existia do lado do Google, um nível acima do filtro já
corrigido lá.** A consulta de descoberta de subcontas (`GAQL_DISCOVERY`, em
`extractors/google_ads.py`) filtrava `customer_client.status = 'ENABLED'`. Era
filtro por estado corrente aplicado a uma consulta cujo produto é histórico —
conceitualmente o mesmo defeito corrigido no Meta, e um nível acima de onde já
havia sido corrigido no Google: lá o filtro removido foi o de `campaign.status`,
não o de conta.

**Correção (26/08/2026).** O predicado de estado saiu do WHERE e a classificação
passou a acontecer em Python, sobre o enum `CustomerStatus` do SDK instalado —
resolvido pela versão default da própria biblioteca, para não fixar versão de
API nem duplicar número mágico. `ENABLED`, `CANCELED`, `SUSPENDED` e `CLOSED`
descrevem contas que existem e podem ter servido anúncios nos dias consultados,
e por isso entram; nenhum deles afirma ausência de histórico. `UNSPECIFIED`
(campo ausente) e `UNKNOWN` ("valor desconhecido nesta versão") não são estado
de conta, e sim contrato ausente ou mais novo do que a biblioteca: abortam a
descoberta, junto com qualquer valor fora do enum. O único predicado que
permanece no WHERE é `customer_client.manager = FALSE`, que não é estado de
entrega e sim o tipo do nó da árvore — conta gestora não tem `ad_group_ad`.

**A assimetria com o Meta é do contrato, não de rigor.** O desvio opt-in criado
para o Meta existe porque a descoberta de lá *declara* indisponibilidade de
acesso (`temporarily_unavailable`), e uma conta presa nesse estado bloquearia
toda a extração. A descoberta do Google não declara nada equivalente:
indisponibilidade de acesso só se manifesta como erro na consulta da conta
(`CUSTOMER_NOT_ENABLED`). Não havendo estado de descoberta que uma válvula
pudesse liberar, não foi criada válvula — copiar a do Meta seria cerimônia sem
contrato que a sustente.

**A dimensão do filtro só apareceu com medição.** Uma sonda de descoberta
autorizada, executada em 26/08/2026 — somente listagem de subcontas e estados,
sem métricas e sem escrita na Bronze — encontrou **117 subcontas não gestoras**
no MCC: 66 `ENABLED`, 48 `CANCELED` e 3 `CLOSED`. Nenhuma `SUSPENDED`, nenhum
status fora do enum. As **51 não-`ENABLED` estavam todas ausentes da Bronze**.
O filtro antigo, portanto, não era risco latente: ele excluía 51 subcontas de
toda extração, inclusive do *backfill* de 2026-04-07, que foi consultado em
2026-08-05 — 120 dias depois da data de referência.

**Uma segunda sonda mediu se essas contas ainda podem ser consultadas.** Para
as 51, uma consulta mínima de acessibilidade (`SELECT customer.id FROM
customer`, sem métricas e sem data): **1 conta `CANCELED` respondeu
normalmente; 47 `CANCELED` e as 3 `CLOSED` recusaram com
`CUSTOMER_NOT_ENABLED`** — *"the customer account can't be accessed because it
is not yet enabled or has been deactivated"*. Nenhum outro erro apareceu.
Nenhuma das 51 é conta de teste (`customer_client.test_account = false` em
todas), o que descarta a explicação mais conveniente para as `CLOSED`.

Na única conta acessível, a consulta histórica cobriu exatamente as datas do
recorte congelado — 2026-04-07 e 2026-07-26 a 2026-08-24 — e devolveu **zero
observações**: nenhuma linha, nenhum investimento, nenhuma impressão. Essa
conta específica está verificada e não esconde história.

**Limitação de cobertura do snapshot — registro explícito.** As outras **50
contas (47 `CANCELED` e 3 `CLOSED`) não podem ter seu histórico verificado pela
API no estado atual.** Elas nunca apareceram na Bronze, e a recusa do servidor
**não** é evidência de que não tiveram entrega: `CUSTOMER_NOT_ENABLED` fala
sobre acesso hoje, não sobre atividade no passado. Portanto o histórico dessas
contas **não pode ser afirmado como zero**, e a correção **não** pode ser
descrita como puramente preventiva. O que se pode afirmar é mais estreito e
mais honesto: o pipeline deixou de excluí-las em silêncio, e a verificação do
que elas podem ter entregue é **impossível com as credenciais e o estado atual
das contas**. O recorte experimental do Google carrega essa limitação
declarada; ele não é um snapshot comprovadamente completo.

O caso é metodologicamente diferente do Meta, onde a mesma classe de defeito
elevou a descoberta de 87 para 95 contas e permitiu recuperar R$ 455,62 de
gasto real. Lá as contas suprimidas continuavam acessíveis e a lacuna foi
fechada por reextração autorizada. Aqui a porta está fechada do lado do
servidor, e o resultado é uma limitação documentada em vez de uma recuperação.

**A correção criou um risco operacional próprio, resolvido na mesma sessão.**
A descoberta passou a oferecer 117 contas em vez de 66, e `executar_extracao`
não isola falha por conta: uma exceção em qualquer uma aborta a extração
inteira. Com 50 contas recusando a consulta, a extração Google passaria a
falhar sempre. A borda `_extrair_conta_tolerando_desativacao` resolve isso da
forma mais estreita que a evidência sustenta: captura `GoogleAdsException`,
exige que **todos** os erros da falha sejam o código oficial
`CUSTOMER_NOT_ENABLED` — comparação por código do enum, nunca por texto de
mensagem — e só então exclui a conta, **e apenas se ela for `CANCELED` ou
`CLOSED`**, que são os estados em que a recusa foi medida. A conta excluída
devolve lista vazia, que é **ausência de observação, não linha zerada**; a
Silver preserva a última observação conhecida de entidade ausente, então nada
de histórico é apagado por isso. O log final é agregado por status e sem
identificador.

Tudo o mais continua abortando: recusa vinda de conta `ENABLED` (anomalia),
qualquer erro de outra família, falha mista e exceção que não seja do SDK. E
`SUSPENDED` fica **fora** da tolerância de propósito — nenhuma subconta nesse
estado apareceu na medição, então não há evidência sobre o comportamento do
servidor, e inventar política sem medição é exatamente o hábito que este
trabalho documenta como origem de número errado. Na dúvida, *fail closed*; a
política muda quando houver medição, não antes.

### 5.14 Quando a proteção vira o bloqueio: revisão de decisão por evidência

A regra de *fail closed* diante de `temporarily_unavailable` no Meta foi
criada em 25/08/2026 e revista em 26/08/2026. A sequência importa mais do que
o desfecho, porque ela é o argumento.

1. **A regra nasceu certa para o problema de então.** Uma conta suprimida da
   descoberta havia apagado logicamente 65 observações e R$ 429,34 da Silver.
   Enquanto a deduplicação tratasse o lote mais recente como substituição
   integral do dia, uma descoberta incompleta era de fato perigosa: abortar
   protegia a recuperação histórica que estava em curso.
2. **A premissa deixou de valer na mesma leva de correções.** A macro
   `ultimo_snapshot` passou a escolher a observação mais recente por
   entidade × dia pela chave hierárquica natural. A partir daí, conta ausente
   de um snapshot **não** é zero e **não** é deleção da observação anterior —
   a última observação conhecida permanece.
3. **A evidência veio do primeiro DagRun agendado real sob a regra nova.** Em
   26/08/2026, o run `scheduled__2026-08-26T09:00:00+00:00` encontrou as
   mesmas duas contas ainda em `temporarily_unavailable`. `extrai_meta` falhou
   nas três tentativas com a mesma mensagem, `carrega_bronze` e
   `transforma_dbt` ficaram em `upstream_failed`, e a DAG inteira não
   completou. A proteção passou a impedir a operação que deveria proteger.
4. **No mesmo run, o Google demonstrou o modelo alternativo em produção.**
   `extrai_google` descobriu 117 subcontas, consultou 67 e excluiu 50 que
   responderam `CUSTOMER_NOT_ENABLED`, com log agregado, sem inventar linha e
   sem derrubar a extração. O modelo de degradação controlada por conta
   deixou de ser hipótese: rodou, com dado real, e produziu 1.440 registros.
5. **A decisão foi revista.** `temporarily_unavailable` passa a ser
   **lacuna de cobertura conhecida e auditável**. A conta nesse estado sai
   daquela execução — e só ela; o número de excluídas vai para o log em
   agregado, sem identificador; nenhuma linha artificial é criada; ausência
   não vira zero nem tombstone; nenhuma história é apagada. Status não
   classificado **continua abortando**, e erro inesperado também: a tolerância
   cobre um estado conhecido, nunca contrato novo.

Lacuna conhecida **não é completude**. O que a política nova compra é que a
lacuna fique visível e localizada, em vez de bloquear o lote inteiro ou —
pior — desaparecer em silêncio, que era o defeito original.

**A válvula opt-in foi removida junto.** `--permitir-contas-meta-indisponiveis`
existia para autorizar, execução a execução, exatamente o desvio que agora é a
política normal. Mantê-la seria conservar uma chave que não tranca nada. O
canal genérico `Plataforma.extrair(**opcoes)` permanece, porque sua garantia é
outra e continua valendo: opção dirigida à plataforma errada levanta
`TypeError` em vez de ser ignorada em silêncio. A DAG não precisa de flag
nenhuma — a degradação controlada é o comportamento padrão.

O registro honesto é que a arquitetura mudou por medição, não por conveniência:
a regra antiga não estava errada quando foi escrita, ficou errada quando a
Silver passou a proteger o histórico por conta própria. A evidência que
autorizou a mudança é um run de produção, não um argumento.

**Fechamento do gate operacional (26/08/2026).** O mesmo DagRun
`scheduled__2026-08-26T09:00:00+00:00` foi retomado por *clear* das três tasks
pendentes — `extrai_meta`, `carrega_bronze` e `transforma_dbt`. `extrai_google`
permaneceu `success` e **não foi reexecutada**: o artefato bruto que ela havia
produzido carrega o `run_id` e a janela desse run, e o manifesto valida por
versão, fonte, `run_id`, janela e `sha256` — nunca por ordem ou horário de
produção. `carrega_bronze` aceitou os dois artefatos, um extraído antes da
falha e outro depois da correção, como pertencentes à mesma execução.

Na retomada, a descoberta Meta encontrou 95 contas, registrou **2
temporariamente indisponíveis como lacuna conhecida** e consultou as 93
restantes, produzindo 764 registros na janela `2026-08-19..2026-08-25`. O
DagRun terminou `success` com as quatro tasks verdes. Nenhum segundo DagRun foi
criado.

Efeito no armazém, decomposto até o centavo: a Bronze foi de 50.447 para
**52.651** linhas e de 65 para **67** lotes — exatamente dois lotes novos, um
por fonte, ambos do mesmo `run_id`, sem nenhuma data fora da janela e sem tocar
nas 50.447 linhas anteriores. O fato foi de 10.963 para **11.326** linhas, e o
acréscimo de 363 é integralmente o dia 2026-08-25: as linhas das datas
anteriores continuam somando exatamente 10.963. As dimensões ganharam 1 data, 2
adsets e 5 anúncios, todos de primeira aparição nesse dia. O investimento subiu
R$ 5.425,935789, dos quais **R$ 5.425,516994 são o dia novo** e **R$ 0,418795 é
deriva retroativa** legítima nos dias já conhecidos. As conversões subiram 273 —
297 do dia novo menos 24 de deriva, e esses −24 batem exatamente com a soma dos
deltas diários do Google (−27, +2, +1). Nenhuma chave desapareceu: o
comparador reportou zero removidas em todas as coleções.

Com todo delta explicado, o golden foi recongelado deliberadamente
(`ca71374a…` → `78ed439a…`) e a paridade voltou a sair 0. A superfície de
exposição foi regenerada (`6b24bd25…`) e aprovada pelo auditor com 11.326
linhas e 19 colunas; o `fingerprint_chave` seguiu `4EFD314550FC2D48`,
confirmando que a chave HMAC do ciclo não mudou e que screenshots anteriores
continuam alinhados. A DAG foi **pausada de novo, deliberadamente**: a operação
real está comprovada e a base fica congelada durante a escrita da monografia —
não é falha operacional, é congelamento intencional.

### 5.15 O erro que só a conferência manual revelou

Um número correto na tela pode estar medindo a coisa errada. Foi a validação
manual do dashboard contra as interfaces das plataformas — não um teste — que
expôs a combinação `44 conversões · 0 compras · R$ 0,00 de valor`. O dado
passava em 88 testes dbt e em toda a suíte Python.

**Dois defeitos independentes, ambos no mapeamento do Meta.**

O primeiro: `conversion_value` do Meta somava o valor de `action_values` com
`action_type = 'lead'`. Lead não carrega valor monetário, e o Meta nunca emite
`lead` nesse array — medido na Bronze: **zero ocorrências em 424 linhas que
têm `action_values` preenchido**. A métrica era, portanto, **estruturalmente
zero**: nenhuma configuração de conta a faria diferente de R$ 0,00, e o ROAS
do Meta era eternamente `0,00x`. O valor real existia no payload bruto e era
descartado.

O segundo: `purchases` somava `purchase` **e** `omni_purchase`. O Meta descreve
a mesma compra em oito `action_type` simultâneos. Medição na Bronze inteira:
as duas representações coexistem em **132 de 132** payloads com compra em
`actions` e em **128 de 128** em `action_values`, sempre com **valor idêntico**;
nenhum payload traz apenas uma. Cada compra era contada **duas vezes**.

**Correções.** As compras passaram de **130 para 65** no armazém — metade
exata, o que é a assinatura da dupla contagem. E nasceu `purchase_value`,
métrica nova que carrega o valor monetário canônico das compras do Meta:
**R$ 62,00** no estado atual do Gold.

**Regra canônica, e por que não somar.** A macro `acao_canonica` lê **uma**
representação por ordem de prioridade — `omni_purchase`, com `purchase` como
fallback — via `COALESCE` sobre subqueries com `LIMIT 1`. `omni_purchase` vem
primeiro por ser a agregação omnichannel do Meta (web, app, offline, loja): se
a conta passar a ter compra em app, ela captura; `purchase` poderia não
capturar. A mesma ordem vale para quantidade e para valor, por exigência de
coerência — regra divergente entre as duas tornaria o ticket médio implícito
mentiroso. Quatro payloads têm compra em `actions` sem entrada em
`action_values`: compra sem valor configurado, que resolve para zero sem
inventar número.

`conversion_value` do Meta foi **preservado como estava**, estruturalmente
zero. Mudar duas coisas ao mesmo tempo teria confundido a auditoria do diff;
quem quer valor do Meta usa `purchase_value`, e o modelo diz isso no cabeçalho.

**A reconciliação R$ 306,00 → R$ 62,00.** A Bronze inteira soma R$ 306,00 de
valor de compra em 132 ocorrências, espalhadas por 32 lotes e 21 dias. Aplicando
a mesma semântica de `ultimo_snapshot` da Silver — partição por
`(reference_date, account_id, campaign_id, adset_id, ad_id)` ordenada por
`extracted_at desc` — sobram 22 linhas, 65 compras e R$ 62,00, que é exatamente
o que Silver e Gold reportam. A diferença é integralmente redundância de
snapshot: a Bronze Meta guarda 19.668 observações para 3.796 entidades×dia,
5,18× de redundância legítima do append-only. Nenhuma outra causa.

**Leads e compras são coisas diferentes, e a tela passou a dizer isso.**
`conversions` do Meta conta `lead`; a do Google agrega **todas** as conversion
actions da conta. Somá-las sob um cartão `Conversões` produzia um número que
não responde pergunta nenhuma. O dashboard passou a nomear cada indicador pela
plataforma:

| conceito | Meta | Google |
|---|---|---|
| resultado | Leads | Conversões |
| custo do resultado | **CPL** = investimento Meta / leads | **CPA** = investimento Google / conversões |
| valor atribuído | Valor de compras = `purchase_value` | Valor de conversões = `conversion_value` |
| retorno | ROAS Meta = valor de compras / investimento Meta | ROAS Google = valor de conversões / investimento Google |

E três indicadores consolidados explícitos: **Valor de compras — Meta**,
**Valor de conversões — Google** e **Valor atribuído total**, este último a
soma dos dois. O nome importa: não é receita, não é faturamento, não é vendas
totais — é a soma de dois valores que as plataformas atribuem por critérios
próprios, e um teste proíbe essas três palavras no rótulo e na ajuda.

**ROAS sai sempre das somas.** `ROAS total = valor atribuído total /
investimento total`, nunca a média dos ROAS por plataforma. A diferença não é
teórica: no estado atual o ROAS total é `0,0217x` contra `0,0175x` da média —
a média dá peso igual a plataformas com investimentos muito diferentes.

**Cliques, CTR e CPC também se separaram.** `link_clicks` guarda
`inline_link_clicks` no Meta e `metrics.clicks` no Google: recortes diferentes.
Os cartões passaram a ser **Cliques no link — Meta** e **Cliques — Google**, e
CTR e CPC são calculados isolando a plataforma, sempre. O CPM continua
consolidado, porque investimento e impressão têm semântica compatível entre as
duas origens — a assimetria é deliberada e documentada, não esquecimento.

**O princípio.** Nenhum desses números estava "errado" no sentido aritmético:
todos somavam corretamente. O erro era de significado — somar conceitos
incompatíveis sob um rótulo único, e procurar um valor onde a fonte nunca o
coloca. Teste de schema não pega isso; teste de soma não pega isso. Pegou
alguém abrindo a interface da plataforma e comparando.

**Fechamento.** O golden passou a proteger `purchase_value` — métrica
financeira exibida em tela precisa estar na rede de segurança, senão uma
mudança de mapeamento passa despercebida, que é exatamente o que aconteceu
aqui. A superfície de exposição ganhou a coluna e teve o **`versao_contrato`
incrementado de 1 para 2**: acrescentar coluna é mudança de schema neste
contrato, porque os consumidores — o dashboard e o auditor independente —
declaram a lista esperada e comparam por igualdade, recusando o artefato
inteiro se ela não bater. O número é o que permite dizer *por que* a leitura
falhou.

### 5.16 Dado sintético de teste que envelhece para dentro do dado real

🔍 Achado pequeno, mas ilustrativo — e reincidente.

O teste do verificador de paridade simula "um dia novo apareceu" inserindo uma
data sintética na estrutura comparada. A data escolhida era plausível
(`2026-08-05`). Quando o recorte experimental avançou, essa data passou a
existir de verdade no golden: a inserção deixou de criar chave nova e passou a
criar **duplicata**. O indexador recusou a coleção, a comparação caiu para o
modo posicional e o bloco sumiu do resultado indexado — o sintoma final foi um
`KeyError` a três camadas de distância da causa.

O que isso mostra: **fixture não é só entrada, é premissa**. "Esta data não
existe no conjunto real" era uma premissa silenciosa, e premissa silenciosa
envelhece sem avisar. O mesmo arquivo já havia caído nessa armadilha uma vez.

A correção não foi ajustar o golden para acomodar o teste — isso seria adaptar
o dado ao teste, exatamente o que a rede de segurança existe para impedir. A
data passou a ser distante do domínio real e a premissa virou asserção
executável: o módulo falha na importação, com mensagem explícita, se qualquer
chave sintética passar a existir no golden.


### 5.17 Contrato não documentado: o que a fonte devolve não é o que ela promete

🔍 Achado central da etapa de Resultado, e o mais caro em tempo de análise.

A família `results` / `cost_per_result` da API de Insights é o número que a
própria plataforma exibe como "Resultado" e "Custo por resultado" na interface
de gestão. Ela **não tem esquema publicado**: a documentação nomeia os campos,
não descreve as formas que a resposta pode assumir. A implementação inicial foi
escrita a partir da forma observada em sondagem — um item de cada lado, com
`values` e `attribution_windows` preenchidos — e tratada como se fosse *a*
forma.

**O primeiro request real desmentiu a hipótese.** Foram 901 registros num
recorte de sete dias, e o parser marcou **418 deles como inválidos**. A
primeira leitura possível era "a extração falhou". Era a leitura errada: a
extração estava correta e o parser é que supunha uma estrutura mais estreita
que a real. Três formas legítimas apareceram, nenhuma prevista:

- **Forma A** (237 registros) — o item traz apenas `indicator`, sem `values`,
  **dos dois lados**. A fonte declarou o tipo de Resultado e não entregou
  quantidade. Isso é zero resultado no grão factual, não resultado
  desconhecido.
- **Forma B** (179 registros) — `values` existe dos dois lados, mas sem
  `attribution_windows`. Acontece com indicadores que não têm janela de
  atribuição aplicável. O par é inequívoco; falta apenas a janela.
- **Forma C** (2 registros) — `results` traz um único valor zero e o custo traz
  o mesmo `indicator` sem `values`. Custo por resultado não existe quando o
  denominador é zero.

A medição que explica o padrão: no recorte observado, `attribution_windows`
(sempre `["default"]`) aparece **somente** nos indicadores de prefixo
`actions:` e em `video_thruplay_watched_actions`. Três outros indicadores
observados nunca a trazem. A ausência de janela é, portanto, uma propriedade do
indicador — não um defeito da resposta.

Disso saiu a formalização de **três estados da janela de atribuição**:
explícita; não aplicável / não fornecida (`NULL`, legítimo); e contraditória
(janela de um lado contra outra, ou contra nenhuma, do outro) — esta última
continua bloqueando o build.

O que **não** foi relaxado, e é o que impede a correção de virar tolerância
geral: mais de um item em qualquer dos lados, indicador divergente ou ausente,
mais de um valor de um lado, janela explícita contra janela ausente, custo com
valor diante de resultado sem valor — e, sobretudo, **quantidade positiva sem
custo correspondente**. A Forma C só é aceita porque o denominador é zero;
com quantidade positiva, a mesma estrutura continua bloqueando o build. A
diferença entre "custo não existe" e "custo não veio" é toda a distância entre
um estado legítimo e uma lacuna silenciosa.

Detalhe de implementação com valor didático: para distinguir "sem janela dos
dois lados" (legítimo) de "janela só de um lado" (contraditório) o pareamento
usa um **sentinela técnico** no lugar do `NULL`, porque `NULL = NULL` é
*unknown* em SQL e faria a Forma B nunca parear consigo mesma. O sentinela
existe apenas dentro da macro e é convertido de volta em `NULL` antes da
projeção; ele nunca alcança a camada Silver, a Gold, a superfície de exposição
ou o painel.

**O que o episódio ensina sobre método.** O fail closed não errou — ele fez
exatamente o que devia: recusou-se a adivinhar diante de uma estrutura que não
reconhecia, e a recusa aconteceu **antes da carga na camada Bronze**, que
permaneceu intacta. Um parser tolerante teria escolhido o primeiro elemento do
array, ou o maior valor, e produzido 901 linhas plausíveis com semântica
inventada em 418 delas. O custo do fail closed é uma parada para análise; o
custo da tolerância é um número errado que passa em todos os testes — o padrão
que este projeto já encontrou três vezes por outros mecanismos (seções 5.1,
5.7, 5.9).

Também mudou a operação da reextração: passou a ser feita em **blocos de no
máximo sete dias por request**, sequenciais, com um identificador de execução
por bloco. Isso mantém cada resposta auditável e limita o efeito de uma
suposição errada a um bloco.

### 5.18 Ausência de dado e ausência de contrato são estados diferentes

🔍 Achado derivado do anterior, e a decisão mais delicada da etapa.

Depois de aceitar as três formas, **312 dos 901 registros** continuavam sem
Resultado algum: `results` e `cost_per_result` simplesmente não vieram. Chamar
isso de "zero resultados" seria confortável e errado. São coisas distintas:

| Estado | O que a fonte disse | Como o DW registra |
|---|---|---|
| Forma A | "o tipo é X, e a quantidade não veio" | tipo preenchido, quantidade `0` |
| Ausência total | nada — nenhum tipo foi declarado | os quatro campos em `NULL` |

Achatar um no outro é inferência disfarçada de normalização: ou se afirma um
tipo que a fonte não declarou, ou se nega uma quantidade que ela declarou.

**A hipótese testada — e rejeitada.** Era tentador inferir o tipo de Resultado
de uma linha ausente a partir de outro dia da mesma campanha: se a campanha
reportou Lead na segunda-feira, o gasto de terça sem Resultado provavelmente
também é Lead. A hipótese foi verificada contra o bloco real e **não se
sustentou** — não porque tenha sido refutada, mas porque **não há um único caso
em que pudesse ser verificada**:

- 56 campanhas no bloco;
- 17 apenas com ausência total;
- 39 apenas com Resultado observado;
- **interseção: zero campanhas.**

Não existe evidência real de que uma linha sem Resultado possa herdar o tipo
observado em outro dia da mesma campanha. Implementar a herança seria escrever
uma regra sobre um caso que o dado nunca apresentou.

**A consequência no agregado.** O custo agregado por Resultado é
`SUM(investimento) / SUM(quantidade)` — nunca soma nem média dos custos
diários, porque somar razões é incorreto. A pergunta é *quais linhas entram no
numerador*. Uma linha de Forma A, com quantidade zero, entra: ela declarou o
mesmo tipo, o investimento pertence à mesma semântica, e diluir o custo pelos
dias sem resultado é justamente o comportamento correto. Uma linha de ausência
total **não** entra, e mais: sua simples presença ao lado de linhas tipadas
invalida o agregado do recorte, que passa a exibir *"Dados incompletos"*.

O rótulo é deliberadamente distinto de *"Múltiplos"*, usado quando há mais de
um tipo de Resultado no recorte. Os dois estados produzem indisponibilidade,
mas por motivos opostos: em "Múltiplos" **sobra** semântica — há dois
significados e nenhum critério neutro para escolher; em "Dados incompletos"
**falta** contrato — parte do período não diz a que semântica pertence. Coletar
os dois sob o mesmo rótulo apagaria a diferença justamente para quem precisa
agir sobre ela.

Regra que ficou explícita no código e nos testes: **`objective` e
`optimization_goal` são contexto, não contrato.** Uma campanha declarada
`OUTCOME_LEADS` com meta de otimização de geração de leads *não* implica
Resultado = Lead. São campos de configuração da campanha; o Resultado é o que a
plataforma efetivamente reporta. A distância entre os dois é exatamente onde
mora a inferência que este projeto recusa.

### 5.19 Fixture sintética não pode virar fonte de vocabulário

🔍 Achado pequeno, com a mesma raiz da seção 5.16.

O painel traduz o indicador técnico do Resultado em rótulo legível. Antes do
primeiro request real, a tabela de tradução foi montada a partir da fixture
sintética escrita para exercitar o código sem credenciais — e nela o indicador
de lead era, simplesmente, `lead`.

O contrato real usa outro vocabulário. Nas 901 observações, o Resultado do tipo
lead aparece **sempre qualificado pela origem**: conversão de pixel externo, ou
formulário nativo agrupado. O valor `lead` sem qualificação **não ocorreu
nenhuma vez**.

Manter o rótulo sintético não é neutro: ele faz o painel confirmar a própria
fixture. Se a fonte um dia devolvesse esse valor, a tela exibiria um rótulo
amigável para uma estrutura nunca observada, e a validação seria circular — o
sistema concordando consigo mesmo. O mapeamento passou a conter apenas
indicadores efetivamente observados, e as fixtures foram migradas para o
vocabulário real, de modo que teste e produção falem a mesma língua.

Cuidado registrado junto da mudança, porque a coincidência de nomes é uma
armadilha real: a **métrica** de conversões do Meta continua vindo da família
`actions`, cujo tipo de ação *é* `lead` sem qualificação. São dois vocabulários
distintos dentro da mesma resposta da API — o das ações e o dos resultados. A
remoção do rótulo atingiu apenas o segundo; confundir os dois teria alterado a
contagem de conversões e o custo por lead do trabalho inteiro.

Um indicador de Resultado observado ficou deliberadamente **sem** rótulo: o de
conversa iniciada por mensagem. Conversa iniciada não é lead — é outro
Resultado, e traduzi-lo como lead seria interpretação de negócio inventada na
camada de apresentação. Ele aparece na tela como Resultado não mapeado, que é
uma resposta honesta.



### 5.20 Dois `NULL` iguais na coluna, diferentes no significado

🔍 Achado que só apareceu quando a regra encontrou o dado real — e que teria
apagado metade do painel.

Depois de aceitar as três formas da seção 5.17, a agregação por campanha
passou a exigir uma única semântica de janela de atribuição no recorte: se
parte das linhas tem janela explícita e parte tem janela `NULL`, o número
agregado fica indisponível. A regra é correta em princípio — misturar
semânticas de atribuição produziria um total sem significado.

**Aplicada ao bloco real, ela zerou 20 das 39 campanhas com Resultado
observado.** Mais da metade. Antes de aceitar o resultado, a causa foi medida
campanha a campanha, e o diagnóstico foi unânime: as 20 tinham **um único**
tipo de Resultado, nenhuma linha da Forma B, e a suposta "segunda janela" era o
`NULL` das linhas de **Forma A**.

Aí está o erro. A coluna guarda `NULL` nos dois casos, mas eles não dizem a
mesma coisa:

| Origem do `NULL` | O que significa | Papel na comparação |
|---|---|---|
| Forma A | não há `values`, logo não há janela factual a comparar | **neutro** — ausência de evidência |
| Forma B | há quantidade e custo, e o indicador não tem janela aplicável | **informativo** — é uma semântica real de "sem janela" |

A Forma A não tem janela porque **não tem quantidade**, não porque use outra
janela. Tratá-la como uma segunda semântica é comparar uma afirmação com um
silêncio.

Confirmação estrutural no censo por indicador: para todos os indicadores de
prefixo `actions:` e para o de vídeo, as linhas com quantidade zero e as linhas
com janela `NULL` coincidem exatamente — 20/20, 4/4, 178/178, 3/3. As linhas de
janela `NULL` desses tipos *são* as linhas de Forma A.

**A correção introduziu a distinção entre janela neutra e janela `NULL`
informativa.** Só as linhas informativas — quantidade positiva, ou custo
presente, ou janela explícita — decidem a compatibilidade. Consequências:

- Forma A + janela explícita do mesmo tipo: **agrega**, e a janela efetiva do
  agregado é a que a linha informativa declarou;
- Forma B + janela explícita: **continua incompatível**, como antes;
- recorte inteiramente de Forma A: agrega com quantidade zero, tipo conhecido e
  custo indisponível — não há divisor, o que é diferente de não haver dado;
- quantidade zero **com** janela explícita continua informativa: declaração
  explícita não é neutralizada por o resultado ter sido zero.

Dois limites que a correção não cruza. Primeiro, **o investimento das linhas
neutras continua no denominador**: uma campanha que gastou em dois dias e
converteu num só custa a soma dos dois dias por conversão, não a de um. No
exemplo mínimo, 10 + 10 de investimento com 2 resultados dá 10 por resultado, e
não 5. Segundo, **nenhuma janela é imputada ao grão factual**: a linha de Forma
A permanece gravada com janela `NULL` na camada Silver e na Gold. A
neutralidade existe apenas na análise agregada, e nunca vira valor herdado de
outro dia — o que reincidiria na inferência recusada na seção 5.18.

O padrão metodológico vale registrar, porque é o mesmo das seções 5.1, 5.7 e
5.9 em roupa nova: **a regra passava em todos os testes**. Ela só falhou contra
o dado real, e o sintoma não foi erro nem exceção — foi um painel educadamente
vazio. Número ausente também é um resultado errado, e mais difícil de notar que
um número absurdo, porque parece prudência.



### 5.21 O limite da fonte é parte do sistema, e ele já se anuncia

🔍 Achado operacional: a restrição externa que só aparece quando o volume
cresce — e o instrumento que já existia sem ser lido.

A reextração para incorporar os campos de Resultado foi feita em blocos de sete
dias, sequenciais. Dois blocos completaram normalmente, cada um percorrendo 93
contas em pouco menos de quatro minutos. **O terceiro, disparado cerca de dez
minutos depois do segundo, foi cortado a um terço do caminho** — 28 de 93
contas — com HTTP 403, `code 4`, `error_subcode 1504022`, "Application request
limit reached", `is_transient: true`.

Três leituras erradas eram possíveis, e vale registrá-las porque todas são
tentadoras:

- **"o token expirou"** — não: a descoberta de contas, que também consome a
  credencial, passou normalmente nos três disparos;
- **"o pipeline quebrou"** — não: o comportamento foi o correto. A escrita do
  bruto é atômica, nenhum arquivo parcial ficou em disco, a camada Bronze
  permaneceu intacta e a execução terminou em falha, como deve;
- **"é só tentar de novo"** — pior das três: cada tentativa consome
  exatamente a cota que está faltando.

O que faltava não era resiliência, era **informação**. A pergunta operacional
real é "quanto esperar", e a resposta não estava em lugar nenhum — a decisão
virava tentativa e erro.

**A fonte já respondia essa pergunta.** A Graph API devolve, em cada resposta
HTTP, headers de utilização: percentual consumido da janela do app, utilização
específica do endpoint de Insights, uso por conta e, quando o limite estoura,
uma estimativa de tempo até a liberação. Esses headers chegavam em todas as
chamadas que o extrator já fazia e eram descartados sem serem lidos.

Foi adicionada **observabilidade passiva**, e cada palavra do termo carrega uma
decisão de projeto:

- **passiva** — nenhum request novo. Não há endpoint de quota consultado, nem
  health check, nem página repetida. O SDK expõe os headers da página corrente
  por acessor público durante a paginação, e o próprio erro de limite preserva
  os headers da resposta que o gerou — que é a leitura mais informativa que
  existe, porque é o estado exato no instante em que a cota acabou. Nada disso
  exigiu alterar o pacote de terceiro nem depender de atributo privado. Um
  teste com cursor sintético afirma que habilitar a telemetria não muda a
  contagem de chamadas HTTP;

- **observabilidade, e só** — sem `sleep`, sem *backoff*, sem *retry*, sem
  troca de conta ou de credencial, sem *circuit breaker* e, deliberadamente,
  **sem limiar**. A tentação de escrever "acima de 80% de uso, pausar" é
  grande e seria um número inventado: ainda não há uma única observação real
  desses headers neste app. Primeiro medir, depois decidir o ritmo com
  evidência. Rate limit continua sendo falha terminal.

Um detalhe de privacidade decidiu a forma da implementação. O header de uso por
caso de negócio é um objeto **indexado por identificador** — a chave é o ID do
business ou da conta. Registrar o header bruto publicaria esses IDs em todo
lugar que o log alcança, incluindo esta documentação. Por isso a leitura
**itera apenas sobre os valores, nunca sobre as chaves**, e cada métrica sai
por nome declarado numa allowlist: campo que a plataforma inventar amanhã é
ignorado até ser avaliado, em vez de capturado por padrão. É a mesma disciplina
do contrato de campos consumidos da camada Silver e do exportador da superfície
de exposição — o que sai é o que foi declarado, nunca o que sobrou de uma
cópia. Um teste dedicado injeta identificadores falsos reconhecíveis nos
pontos onde o header poderia carregá-los e prova que eles não aparecem no
retorno, no `repr` nem no log.

Robustez pelo mesmo princípio: header ausente, JSON malformado, campo novo,
tipo inesperado — tudo devolve ausência de métrica, nunca exceção. **Telemetria
não pode tornar inválida uma resposta que a API entregou corretamente.**

O achado metodológico que fica: a **restrição externa é parte do sistema**, não
um acidente que acontece com ele. Um pipeline que só funciona enquanto a fonte
não impõe limite não está pronto — e instrumentar essa fronteira custou zero
chamada adicional, porque o instrumento já vinha junto com o dado.



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
| Regressão entre lotes | Toda chave com gasto positivo já observada na Bronze permanece representada na Silver; a verificação cobre todo o histórico, inclusive omissões consecutivas (seção 5.13) |

O último passou a ser erro, não alerta. Sem tombstone ou prova de completude,
sumir da resposta não prova que a métrica histórica virou zero. Uma eventual
semântica de remoção precisa chegar como evidência explícita; até lá, apagar a
última observação válida seria uma decisão que o dado de origem não sustenta.

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
| 25/08/2026 | Correção da descoberta Meta e adoção da última observação por entidade/dia após detecção de supressão histórica por snapshot parcial |

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
