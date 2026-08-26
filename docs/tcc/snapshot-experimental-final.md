# Snapshot experimental final — 26/07/2026 a 24/08/2026

Registro reproduzível do estado congelado do Data Warehouse usado como base
experimental do TCC. Documenta o período, o método de extração, os dois
defeitos encontrados na apuração, a estratégia de correção, a recuperação e a
reextração autorizada, os números finais, os hashes dos artefatos e as
limitações que continuam valendo.

Gerado em 25/08/2026. Nenhum commit, push ou publicação externa acompanha este
documento.

## 1. Propósito do snapshot

O trabalho precisa de um recorte estável de dados reais sobre o qual as
análises, as tabelas da monografia e as capturas de tela do painel possam ser
produzidas e reproduzidas. Sem um estado congelado, cada nova execução do
pipeline moveria os números — legitimamente, porque as plataformas revisam
métricas retroativamente — e nenhum resultado apresentado seria verificável
depois.

O recorte escolhido são os 30 dias completos de **2026-07-26 a 2026-08-24**.
O Data Warehouse contém também um dia isolado de 2026-04-07, anterior ao
recorte, preservado de propósito: é ele que sustenta a evidência de
versionamento SCD Tipo 2, e por isso nunca foi reextraído.

## 2. Método de extração

O pipeline é ELT em camadas: extratores gravam JSON bruto, o carregador o
deposita íntegro em `bronze.raw_ads` (JSONB, append-only) e o dbt materializa
`silver` (views) e `gold` (tabelas, Snowflake Schema). O grão do fato é
**1 anúncio × 1 dia**.

O recorte foi montado por execuções manuais da DAG `pipeline_marketing_diario`
em cinco janelas não sobrepostas, disparadas pela interface do Airflow com os
dois parâmetros de data:

| Janela | Meta | Google |
|---|---:|---:|
| 2026-07-26..2026-08-01 | 912 | 1.766 |
| 2026-08-02..2026-08-08 | 835 | 1.675 |
| 2026-08-09..2026-08-15 | 682 | 1.790 |
| 2026-08-16..2026-08-22 | 781 | 1.481 |
| 2026-08-23..2026-08-24 | 214 | 393 |

Uma tentativa anterior de extrair os 30 dias numa única janela falhou por
limite de requisições da Meta (`Application request limit reached`), com as
tasks seguintes em `upstream_failed` e nenhum lote gravado. O fracionamento em
janelas menores foi a resposta operacional.

A esses lotes somam-se os das execuções agendadas anteriores, que já haviam
carregado parte do período, e os três lotes da reextração descrita na
seção 6. A camada bronze é append-only: nenhum lote sobrescreve outro, e a
deduplicação acontece na silver.

## 3. Primeiro defeito — filtro por estado atual na descoberta de contas

A descoberta de contas do Meta aceitava exclusivamente contas com
`account_status == ACTIVE`. O estado de uma conta descreve a **situação atual**
de entrega e faturamento; não diz nada sobre a existência de métricas
passadas. Uma conta que entregou anúncios em julho e mudou de estado em agosto
deixava de ser consultada — inclusive para as datas em que ela estava
plenamente ativa.

Esta é a mesma classe de defeito já registrada anteriormente no projeto, quando
a consulta GAQL filtrava `campaign.status = 'ENABLED'` e uma reextração
apagava do armazém as campanhas pausadas desde então. **Filtro por campo
mutável da fonte, aplicado a consulta histórica, apaga dado.**

A verificação empírica, feita na descoberta real, confirmou a hipótese: a conta
suprimida estava em `unsettled`, e não em `active`. A descoberta corrigida
devolveu 95 contas contra as 87 que o filtro antigo enxergava.

## 4. Segundo defeito — substituição integral do dia pelo lote mais recente

A camada silver escolhia o lote mais recente de cada `(fonte, dia)` e o tratava
como substituição integral daquele dia. A premissa embutida é que todo snapshot
posterior é completo — e nem o manifesto nem a bronze carregam prova de
completude por conta, nem qualquer forma de *tombstone* que declare "esta
entidade deixou de existir".

Combinados, os dois defeitos produzem supressão histórica: basta que uma conta
saia da descoberta para que um lote posterior, incompleto, apague da silver
todas as observações dela — inclusive as de dias já corretamente apurados e
preservados na bronze.

O efeito medido foi de **54 chaves com gasto positivo desaparecendo em 12
dias**, somando R$ 387,52. A varredura do histórico completo elevou o total
para **65 linhas em 13 dias, R$ 429,34**.

Vale registrar por que nenhum teste pegou isso antes: contagem de linhas por
lote não detecta perda. No dia do incidente análogo anterior, cinco anúncios
novos entraram e o total **subiu** enquanto uma campanha inteira sumia.
Comparação só serve no grão de anúncio.

## 5. Estratégia final — última observação por entidade e dia

A correção substitui "o último lote vence o dia" por **"a última observação
vence a entidade naquele dia"**:

- a deduplicação particiona por fonte, data e a chave natural hierárquica
  (`account` / `campaign` / `adset` ou `ad_group` / `ad`), ordenando por
  `extracted_at` decrescente;
- entidade presente num lote posterior recebe a métrica revisada — a deriva
  retroativa continua funcionando, e é comportamento desejado;
- entidade ausente de um lote posterior **conserva sua última observação
  válida**. Ausência sem tombstone não é zero;
- a mesma regra conceitual vale para Meta e Google, em macro única
  (`ultimo_snapshot`), para que as duas implementações não divirjam em
  silêncio — a categoria exata do defeito de `union all` já vivida no projeto;
- o `dense_rank` preserva empates de propósito: se a fonte ou o carregador
  duplicar a mesma chave dentro de um lote, as duas linhas sobrevivem e os
  testes de grão e de duplicidade falham fechado, em vez de a ordenação
  escolher uma arbitrariamente;
- nome e métrica **nunca** participam da deduplicação.

A descoberta do Meta passou a classificar explicitamente os estados conhecidos
do SDK. Estados historicamente consultáveis participam da tentativa; a
indisponibilidade temporária e qualquer status não classificado abortam a
extração, para não produzir snapshot parcial silencioso.

O teste de regressão `assert_reextracao_nao_perde_gasto` deixou de comparar
apenas os dois últimos lotes: ele percorre **todo o histórico bronze** contra a
silver, tem severidade de erro e falha se qualquer chave que já teve gasto
positivo não chegar à camada derivada.

## 6. Recuperação e reextração

### 6.1 Recuperação a partir da própria bronze

Como a bronze é append-only, tudo que já havia sido observado continuava lá. A
reconstrução das camadas derivadas, sem nenhuma chamada de API, recuperou
**65 linhas, 13 datas, 14 anúncios e R$ 429,34**. A silver do Meta passou de
3.563 para 3.628 linhas e o fato de 10.838 para 10.903.

### 6.2 Lacuna remanescente

A conta afetada não tinha **nenhuma** observação na bronze em 17 dos 30 dias:
26 a 31/07, 05 a 09/08 e 19 a 24/08. Esses dias não podiam ser declarados zero:
ausência de registro não é evidência de ausência de entrega. O snapshot ficou
em NO-GO até que uma consulta nova, autorizada, cobrisse exatamente essas
datas.

A coincidência não é acidental. Antes de 25/08 a conta ainda estava ativa e
entrava nas execuções agendadas, que cobriram justamente 01 a 04/08 e 10 a
18/08. As 17 datas restantes só foram carregadas pelas cinco execuções manuais
de 25/08 — quando a conta já havia mudado de estado e o filtro a excluiu.

### 6.3 Reextração autorizada

Autorizada explicitamente e restrita às 17 datas, somente Meta, em três
intervalos contíguos:

| Janela | Registros | Lote |
|---|---:|---:|
| 2026-07-26..07-31 | 823 | 1 |
| 2026-08-05..08-09 | 561 | 1 |
| 2026-08-19..08-24 | 656 | 1 |

Em todas as execuções: 95 contas descobertas, 93 consultáveis, 2 excluídas,
nenhum status desconhecido, nenhuma exceção. A conta afetada foi consultada nas
três.

**Classificação das 17 datas** — todas receberam consulta válida:

- **14 datas com observações retornadas**: 26 a 31/07, 05 a 09/08 e 19 a 21/08;
- **3 datas com consulta válida e zero linhas**: 22, 23 e 24/08;
- **0 datas inacessíveis**;
- **0 datas inconclusivas ou com erro**.

Os três dias sem linha não viraram registro zerado nem tombstone. O que mudou é
que agora existe evidência de que a consulta cobriu o dia — e é essa diferença,
entre ausência dentro de janela consultada e ausência por conta nunca
consultada, que permite afirmar completude.

### 6.4 Decomposição dos deltas da reextração

Medida reconstruindo a silver anterior a partir da própria bronze:

| Métrica | Conta recuperada | Deriva retroativa nas demais | Total |
|---|---:|---:|---:|
| Linhas | +60 | 0 | +60 |
| Investimento | +455,62 | +0,44 | +456,06 |
| Impressões | +7.900 | +22 | +7.922 |
| Cliques | +89 | 0 | +89 |
| Conversões | +22 | 0 | +22 |
| Alcance | +7.587 | +12 | +7.599 |
| Video views (Meta) | +2.384 | +4 | +2.388 |

Valor de conversão, compras e *profile views* não mudaram; o Google não mudou
em nenhuma métrica. A coluna de deriva é revisão retroativa legítima da API do
Meta sobre entidades que já existiam: nenhuma linha nova, apenas métrica
revisada.

A reextração não criou nem colapsou nenhuma versão SCD2: a contagem de pares
distintos `(identificador, nome)` ficou idêntica em conta, campanha, adset e
anúncio.

## 7. Desvio excepcional para `temporarily_unavailable`

A regra de falhar fechado diante de `temporarily_unavailable` bloqueava **toda**
extração do Meta enquanto qualquer conta estivesse nesse estado — inclusive a
recuperação de períodos sem nenhuma relação com ela. A proteção impedia o
próprio conserto.

A saída foi a menor exceção auditável possível, e não o afrouxamento da regra:

- o **default continua fail-closed**: sem opt-in, indisponibilidade temporária
  aborta, exatamente como antes;
- **status desconhecido aborta em qualquer caso**, com ou sem o desvio. O
  desvio cobre indisponibilidade conhecida, não contrato novo;
- o opt-in é uma flag de linha de comando do orquestrador
  (`--permitir-contas-meta-indisponiveis`), declarada execução a execução. Foi
  preferida a variável de ambiente justamente porque uma variável sobrevive à
  execução seguinte sem ninguém notar;
- a flag recusa companhia incoerente: erro de uso sem extração ou sem a
  plataforma que a consome;
- a exclusão é registrada em log, com contagem e **sem identificador**;
- **a DAG não tem acesso ao desvio**. Ela chama o extrator standalone, cuja CLI
  não expõe a flag, e há teste de código-fonte afirmando isso;
- treze testes cobrem default fechado, escopo do desvio, status desconhecido
  abortando com o desvio ligado, log sem identificador, propagação na
  descoberta e ausência do desvio na DAG.

O princípio geral que fica registrado: **uma proteção que falha fechado precisa
de uma porta auditável**, senão ela também impede a correção do problema que a
motivou.

## 8. Números finais

### 8.1 Camadas

| Camada | Estado |
|---|---|
| `bronze.raw_ads` | 50.447 linhas, 65 lotes (Meta 18.904 / 33; Google 31.543 / 32) |
| `silver.stg_meta_ads` | 3.688 linhas |
| `silver.stg_google_ads` | 7.275 linhas |
| `silver.stg_ads_unified` | 10.963 linhas |
| `gold.fato_metricas` | 10.963 linhas |
| `gold.vw_metricas_completas` | 10.963 linhas |
| Período do fato | 2026-04-07 a 2026-08-24 (31 dias) |

Dimensões (versões / entidades / multiversão): conta 67 / 65 / 2; campanha
221 / 217 / 4; adset 448 / 444 / 4; anúncio 905 / 905 / 0. Todas as quatro
campanhas multiversão têm a primeira versão iniciando em 2026-04-07: a
evidência de SCD2 nasce da fronteira abril↔agosto e continua intacta.

### 8.2 Recorte experimental de 30 dias

| Métrica | Valor |
|---|---:|
| Linhas | 10.654 |
| Contas | 57 |
| Campanhas | 173 |
| AdSets | 363 |
| Anúncios | 727 |
| Investimento | 128.964,611465 |
| Impressões | 4.483.865 |
| Cliques em link | 79.611 |
| Conversões | 5.252,942581 |
| Valor de conversão | 2.733,083150 |
| Alcance | 3.470.719 |
| Compras | 130 |
| Video views — Meta Ads | 462.705 |
| Video views — Google Ads | 15.692 |

**As video views aparecem separadas de propósito e não devem ser somadas.** O
TrueView do Google conta 30 segundos, vídeo completo ou interação; o Meta conta
a partir de 3 segundos. A métrica é válida dentro de cada plataforma e não tem
significado agregado entre elas.

Os zeros de `reach`, `profile_views` e `purchases` no Google significam
**ausência de suporte** nesse nível da GAQL, não ausência de dado.

### 8.3 Hashes dos artefatos

| Artefato | SHA-256 |
|---|---|
| `tests/golden/agregados_gold.json` | `ca71374a86097ccf9db309e3a30869d9129faa8ed9b384ec6244fec7197a69d1` |
| `data/exposicao/metricas.csv` | `ee44fae8dd2fbf755b121a597bb41e94995d0fa8153c6df327a76be9ad64cbad` |
| `data/exposicao/manifesto.json` | `3bf16b9497376039e6f2c532fcc3d3a89102ee7227ee21cc553d69b8d37308e6` |

O `fingerprint_chave` do manifesto permanece `4EFD314550FC2D48`, idêntico ao do
artefato anterior: a mesma chave HMAC local vale por todo o ciclo da Defesa, e
os pseudônimos já usados em capturas de tela continuam válidos.

A superfície de exposição tem 10.963 linhas e 19 colunas, com cardinalidades
pseudonimizadas de 65 contas, 217 campanhas, 444 adsets e 905 anúncios —
iguais às do armazém, o que confirma que a pseudonimização não colidiu
identificadores.

## 9. Testes e gates

| Suíte | Resultado |
|---|---|
| Python (`unittest`) | 426 testes, 0 falhas, 0 erros |
| dbt `build` | 11 modelos, 77 data tests, 4 unit tests — PASS=92, WARN=0, ERROR=0, SKIP=0 |
| dbt `test` | 81/81 |
| Paridade (`verificar_paridade.py verificar`) | `PARIDADE OK`, exit 0 |
| Auditoria de exposição (artefato + DW) | APROVADA |
| Auditoria de exposição (somente artefato) | APROVADA |
| Testes do painel | 139 testes, 1 skip |

Gates específicos aprovados: `assert_reextracao_nao_perde_gasto`,
`assert_snapshot_sem_chave_duplicada`, `assert_grao_unico_fato`,
`assert_grao_unico_silver`, `assert_metricas_nao_negativas`,
`assert_join_dimensional_nao_infla`, `assert_staging_mesmo_contrato` e
`assert_campos_extraidos_sao_consumidos`.

Verificações estruturais adicionais: uma única versão vigente por entidade nas
quatro dimensões SCD2; cardinalidade e as nove somas da view idênticas às do
fato, portanto sem inflação de join; 30 de 30 dias presentes em Meta e Google
no recorte.

## 10. Limitações conhecidas

**Duas contas em `temporarily_unavailable` ficaram fora do snapshot.** Elas não
possuem **nenhuma** linha em toda a bronze, nos 65 lotes: nunca foram
observadas, e portanto não há histórico conhecido perdido. Se em algum momento
se tornarem consultáveis, o período delas passa a constituir uma lacuna de
cobertura própria, a ser tratada como tal — não como recuperação.

**A silver não tem prova de completude por conta.** A estratégia de última
observação por entidade é robusta contra lote parcial, mas continua sendo uma
inferência: sem tombstone, não há como distinguir "a entidade deixou de
existir" de "a entidade não veio neste lote". Uma solução mais forte exigiria
registrar completude e encerramento por conta e período no manifesto, na carga
e na bronze.

**Reextrair um período passado achata o versionamento SCD2.** A API devolve o
nome atual para datas passadas; como a silver adota a observação mais recente,
uma renomeação anterior deixa de aparecer. É por isso que 2026-04-07 nunca foi
reextraído. A reextração das 17 datas não alterou nenhuma versão, mas a
propriedade continua valendo para qualquer reextração futura do recorte.

**As métricas continuam mudando retroativamente.** O Meta revisa por até 28
dias. O snapshot é um congelamento deliberado de um estado que a fonte ainda
pode alterar; a paridade contra o golden é o que torna qualquer alteração
posterior visível em vez de silenciosa.

**`video_views` não é comparável entre plataformas**, e `reach` não é aditivo
no tempo, por contar pessoas únicas. Nenhuma das duas entra nos indicadores
principais do painel.

## 11. Fronteira de exposição

Todo material exposto — painel, capturas de tela, tabelas da monografia — sai
da superfície de exposição, nunca do Gold diretamente: a view canônica carrega
nome real e identificador externo real.

O exportador classifica **todas** as colunas da view por allowlist e aborta
diante de coluna não classificada, em vez de deixá-la escorregar para o
artefato. Nenhum nome real, identificador externo, `_nk` ou `_sk` sai no CSV;
as chaves naturais são lidas apenas como entrada do HMAC. Métricas e datas são
reais e intactas — a pseudonimização troca identidade, nunca número.

O auditor é independente do exportador: não importa o módulo de pseudônimos nem
o produtor do artefato, porque um auditor que compartilha código com quem
produziu validaria a si mesmo.

Gerar o artefato não autoriza publicar. `data/exposicao/` é material de Defesa
e painel local; `data/publico/` continua exigindo autorização por escrito da
agência.
