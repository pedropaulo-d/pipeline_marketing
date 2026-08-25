# Camada de visualização — dashboard analítico

Documento de referência da última camada do pipeline. Serve de insumo para as
seções de Metodologia e Resultados da monografia.

Implementado em 25/08/2026, sobre o HEAD `be35cb9` (`main`).

---

## 1. Objetivo da camada

Demonstrar visualmente que o pipeline transforma dados heterogêneos do Meta Ads
e do Google Ads em uma superfície analítica consolidada e utilizável.

O dashboard responde, com poucos cliques:

- qual foi o desempenho geral no período selecionado;
- como os indicadores evoluíram dia a dia;
- como as duas plataformas se comparam sob o mesmo modelo analítico;
- quais campanhas e quais anúncios se destacaram;
- que dados existem no período — quantas contas, campanhas, anúncios, dias.

O que ele **não** pretende ser: substituto de plataforma comercial de BI. Não
há autenticação, multiusuário, editor de dashboards, alertas, exportação de
relatório, upload de planilha, IA generativa nem previsão. É uma camada
demonstrativa de consumo analítico do Data Warehouse.

## 2. Arquitetura

```
Meta Ads + Google Ads
        ↓  extractors/  (JSON bruto + manifesto de origem)
      bronze.raw_ads            append-only, JSONB
        ↓  dbt
      silver (views)            dedup por último snapshot
        ↓  dbt
      gold (tabelas)            Snowflake Schema, SCD Tipo 2
        ↓
      gold.vw_metricas_completas    travessia SCD2 oficial, escrita uma vez
        ↓  scripts/exportar_dataset_exposicao.py   (allowlist, fail closed)
      data/exposicao/metricas.csv   19 colunas, identidade pseudonimizada
        ↓
      dashboard/   Streamlit + Plotly
```

A camada de visualização é **consumidora** da superfície segura. Ela não
pseudonimiza nada — a lógica de pseudonimização continua sendo exclusiva de
`pseudonimos.py`, chamado pelo exportador, fora do pipeline ELT.

O dashboard também **não** reimplementa a travessia SCD2: quem resolve a versão
vigente de cada dimensão é a view canônica, e o exportador apenas projeta o que
ela já resolveu. Juntar dimensão SCD2 pela chave natural sem resolver a versão
transforma o join em 1:N e infla o investimento sem erro nenhum — já custou
7,8% neste projeto. O dashboard nunca escreve esse join porque não escreve
join nenhum: sua entrada é um CSV no grão do fato.

## 3. Origem dos dados

Duas origens, mutuamente exclusivas, escolhidas automaticamente:

| Modo | Arquivo | Selo na interface | Versionado |
|---|---|---|---|
| Pseudonimizado | `data/exposicao/metricas.csv` | `DADOS PSEUDONIMIZADOS` | Não (gitignored) |
| Demonstração | `dashboard/dados_demo/metricas.csv` | `DADOS DE DEMONSTRACAO` | Sim |

Ordem de precedência em `dashboard/dados.py::escolher_fonte`:

1. `DASHBOARD_DATASET` — caminho explícito de CSV;
2. `DASHBOARD_MODO=demo` — força o dataset sintético;
3. superfície de exposição local, se existir;
4. dataset sintético.

Não há passo 5. Sem nenhum dos dois arquivos, a aplicação explica o que falta e
como gerar — não abre conexão com banco, porque não existe cliente de banco no
pacote.

**Grão:** 1 anúncio × 1 dia, o mesmo do fato. O dashboard nunca reagrupa para
um grão mais fino do que recebeu.

### Estado das duas fontes na data da implementação

| | Superfície real | Demonstração |
|---|---|---|
| Linhas | 4.923 | 1.023 |
| Período | 2026-04-07 a 2026-08-18 (14 dias com dado) | 2026-06-01 a 2026-06-28 (28 dias) |
| Contas | 65 | 6 |
| Campanhas | 207 | 15 |
| Ad sets | 398 | 30 |
| Anúncios | 801 | 48 |
| Plataformas | Meta Ads, Google Ads | Meta Ads, Google Ads |

## 4. Tecnologias

| Tecnologia | Papel | Onde |
|---|---|---|
| Streamlit | Aplicação, navegação, widgets de filtro, cache | `app.py`, `componentes.py` |
| Plotly (`graph_objects`) | Séries temporais, barras comparativas, rankings | `graficos.py` |
| Python (stdlib) | Contrato, tipagem, agregação, indicadores, filtros | `dados.py`, `metricas.py`, `filtros.py` |
| Docker Compose | Serviço sem credencial, driver ou dependência de inicialização do DW | `dashboard/Dockerfile`, `docker-compose.yml` |
| Tema nativo do Streamlit | Cores dos controles (select, multiselect, data) e do modo claro forçado | `.streamlit/config.toml` |

Nenhuma dependência nova entrou em `requirements.txt`. As do painel vivem em
`dashboard/requirements.txt` e são instaladas apenas na imagem do painel.

Decisão deliberada: **`dados.py`, `metricas.py` e `filtros.py` são stdlib pura**
(`csv`, `decimal`, `datetime`, `re`). Isso permite testar toda a lógica no
container do ETL, que não tem Streamlit — e mantém a suíte sem dependência
nova, como o resto do projeto.

## 5. Páginas implementadas

Navegação por rádio na barra lateral; os filtros globais são os mesmos nas
quatro páginas.

### 5.1 Visão Geral

Ordem visual, do geral para o detalhe:

1. **cabeçalho** — nome da página, uma frase de contexto, período selecionado,
   contagem de registros em texto secundário e o selo de origem;
2. **Indicadores do período** — seis cartões de KPI, em duas linhas de três,
   com variação contra o período anterior;
3. **Eficiência** — cinco cartões menores (CTR, CPC, CPM, CPA, ROAS), com a
   fórmula no tooltip, não dentro do cartão;
4. **Evolução diária** — seletor de métrica e alternância entre série
   consolidada e uma série por plataforma;
5. **Meta Ads × Google Ads** — quatro gráficos de barras, uma métrica cada;
6. **Participação e cobertura** — barra de participação no investimento e a
   ressalva de qual métrica cada origem não fornece;
7. **Indicadores por plataforma** — tabela comparativa.

### 5.2 Campanhas

- seletor da métrica de ordenação (as nove) e do tamanho do ranking (10 ou 15);
- ranking horizontal, colorido por plataforma;
- tabela detalhada com **o conjunto filtrado completo**, não apenas o Top N,
  incluindo métricas base, derivadas, número de versões SCD2 e dias com dado.

### 5.3 Anúncios

Mesma estrutura no grão de anúncio, com a campanha e a conta pseudonimizadas
como colunas de contexto, mais um bloco de **evolução diária de um anúncio
específico** escolhido no seletor.

### 5.4 Sobre os dados

Tela de apoio à Defesa, toda calculada a partir do dataset carregado:

- linhas, dias, primeira e última data;
- plataformas, contas, campanhas, ad sets e anúncios distintos;
- entidades com mais de uma versão SCD2, por nível;
- manifesto do artefato: versão do contrato, data/hora de geração, linhas
  declaradas, intervalo, `sha256` do CSV e, quando existir, `fingerprint` da
  chave de pseudonimização;
- matriz de cobertura das nove métricas por plataforma;
- fórmulas dos cinco indicadores derivados;
- declaração explícita da fronteira de exposição.

## 6. KPIs implementados

Seis indicadores principais, escolhidos a partir das nove métricas que o
pipeline efetivamente carrega:

| KPI | Coluna | Formato | Ressalva exibida |
|---|---|---|---|
| Investimento | `spend` | moeda | — |
| Impressões | `impressions` | inteiro | — |
| Cliques no link | `link_clicks` | inteiro | — |
| Conversões | `conversions` | decimal | fracionária no Google por modelagem de atribuição; não é arredondada |
| Valor de conversão | `conversion_value` | moeda | depende de valor configurado na conta de origem |
| Compras | `purchases` | inteiro | Google Ads: não disponibilizado nesta origem |

Ficaram **fora** dos cartões, de propósito:

- **`video_views`** — existe nas duas plataformas com definições diferentes
  (TrueView de 30 s, vídeo completo ou interação no Google; a partir de 3 s no
  Meta). É válida dentro de cada plataforma e não tem interpretação comum
  somada entre elas. Continua disponível no seletor de métrica, com a ressalva
  impressa abaixo do gráfico.
- **`reach`** — não é fornecida pela GAQL neste grão e, além disso, conta
  pessoas únicas: somar dias distintos conta a mesma pessoa várias vezes. Um
  cartão de "alcance do período" seria simplesmente errado.
- **`profile_views`** — não é fornecida pela GAQL neste grão e está zerada no
  artefato real. Aparece na matriz de cobertura, não como KPI.

Essa separação é declarada uma única vez, no catálogo de `metricas.py`
(`comparavel_entre_plataformas`, `aditiva_no_tempo`,
`plataformas_sem_suporte`), e o resto da aplicação a consulta em vez de
redescobri-la.

## 7. Métricas derivadas e fórmulas

| Indicador | Fórmula | Formato |
|---|---|---|
| CTR | `link_clicks / impressions × 100` | percentual |
| CPC | `spend / link_clicks` | moeda |
| CPM | `spend / impressions × 1000` | moeda |
| CPA | `spend / conversions` | moeda |
| ROAS | `conversion_value / spend` | decimal |

Todos os operandos são métricas **consolidáveis** — coletadas nas duas
plataformas com a mesma definição. Há teste afirmando essa propriedade: um
derivado cujo operando não some entre plataformas produziria indicador sem
leitura no total consolidado.

**Divisão segura.** `metricas.dividir` devolve `None` quando o denominador é
zero, negativo ou ausente; a formatação transforma `None` em `--`. Nenhum
caminho da aplicação pode exibir `NaN`, `Infinity` ou um zero enganoso.
Indisponível e zero são coisas diferentes, e a interface as distingue.

**Precisão.** Toda agregação acontece em `Decimal`. `float` só aparece na
fronteira de apresentação, dentro de `graficos.py`, porque Plotly serializa
para JSON. Truncar `conversions` já custou ~1% das conversões no ETL legado
deste projeto.

## 8. Comparação com o período anterior

Quando há período suficiente, a aplicação calcula automaticamente a janela
imediatamente anterior, de mesma duração. Com o período padrão de sete dias, a
comparação é sempre `D-13 → D-7` contra `D-6 → D`: no artefato real, 12–18/08
compara com 05–11/08.

- a comparação respeita **todos** os filtros ativos — plataforma, conta,
  campanha e ad set continuam valendo; só a janela de datas muda
  (`filtros.aplicar_em_periodo`);
- se não houver nenhum registro na janela anterior, os cartões exibem
  "sem base de comparação" em vez de inventar variação;
- base zero ou negativa devolve indisponível, nunca divisão;
- a seta indica **direção, não julgamento**: alta de investimento e alta de CPA
  não têm a mesma leitura, e o dashboard não decide isso pelo usuário. Por isso
  a variação é apresentada em cinza nos dois sentidos, sem verde nem vermelho.

Consequência prática no dataset real: o artefato tem lacunas de calendário
(2026-04-07 isolado, depois 01–04/08 e 10–18/08). Selecionar um período cuja
janela anterior cai numa lacuna produz "sem base de comparação" — que é o
comportamento correto, não uma falha.

## 9. Filtros

| Filtro | Widget | Dependência |
|---|---|---|
| Período | intervalo de datas, limitado ao intervalo do dataset | — |
| Plataforma | multisseleção | período |
| Conta | multisseleção | período + plataforma |
| Campanha | multisseleção | período + plataforma + conta |
| Ad set | multisseleção | período + plataforma + conta + campanha |

- **hierarquia real**: escolher uma conta remove das opções as campanhas que
  não pertencem a ela. Medido no dataset real: 207 campanhas oferecidas
  passam a 15 depois de escolher uma conta; escolher "Google Ads" reduz as
  contas oferecidas de 65 para 36;
- **todos atuam simultaneamente**;
- seleção vazia num nível significa "todos", não "nenhum";
- **seleção residual é descartada, não ignorada**: `filtros.sanear` remove o
  que deixou de ser opção válida, então trocar a conta não deixa o painel vazio
  por causa de uma campanha selecionada antes;
- **"Limpar filtros"** devolve tudo ao estado inicial.

### 9.1 Período padrão — os últimos sete dias do dataset

Ao carregar um dataset, a aplicação abre em:

```
data_final   = max(data) do dataset
data_inicial = data_final - 6 dias        (recortado por min(data))
```

São **sete dias de calendário**, não sete dias com dado. No artefato real
(`max = 18/08/2026`) o painel abre em **12/08 → 18/08**; no dataset sintético
(`max = 28/06/2026`), em **22/06 → 28/06**.

Duas propriedades importam:

1. **A âncora é o dataset, nunca `date.today()`.** O artefato é um recorte
   histórico. Ancorar no relógio abriria o painel vazio no dia seguinte à
   exportação e produziria um screenshot diferente a cada execução — o oposto
   do que a Defesa precisa. Com a data do arquivo, a mesma superfície sempre
   abre na mesma tela, hoje e daqui a um ano.
2. **Lacuna de calendário não estica a janela.** O artefato real tem
   07/04/2026 isolado, meses antes do bloco de agosto. A janela padrão continua
   sendo `[max-6, max]`; o dia isolado simplesmente não entra.

Dataset com menos de sete dias de calendário abre inteiro. A seleção manual
continua livre em todo o intervalo disponível.

Implementado em `filtros.periodo_padrao`, consumido por
`filtros.selecao_inicial`.

## 10. Segurança

A fronteira de exposição é estrutural em quatro níveis independentes.

**Código.** `dashboard/dados.py` só sabe ler CSV. Não há `psycopg2`,
`sqlalchemy`, SDK do Meta, SDK do Google, `requests` ou `dbt` importado em
lugar nenhum do pacote, e há teste que varre os módulos e reprova a introdução
de qualquer um deles. Outro teste garante que nenhum módulo contém consulta
SQL, e que a porta de entrada de dados sequer menciona os schemas do DW.

**Contrato.** Antes de qualquer renderização:

- as 19 colunas obrigatórias precisam existir, na ordem do contrato;
- coluna terminada em `_nk`, `_sk`, `_external_id` ou `_nome` **recusa o
  arquivo inteiro** — não há renderização parcial;
- os quatro identificadores precisam casar com o formato de pseudonimo
  (`^Cliente-[0-9A-F]{8}$` e equivalentes). Um nome real escondido numa célula
  de identificador não passa;
- `plataforma`, único campo textual livre, precisa casar com um padrão curto:
  não trava a entrada de uma terceira fonte, mas impede texto arbitrário;
- coluna extra é **ignorada de propósito e reportada** na tela "Sobre os
  dados". Coluna nova na origem não vira coluna nova no dashboard sem decisão
  explícita — mesmo espírito de `assert_campos_extraidos_sao_consumidos` no
  dbt;
- as mensagens de falha apontam coluna e contagem e **nunca reproduzem o valor
  recusado**: um arquivo errado pode conter exatamente o que não deve vazar.

**Imagem.** `dashboard/Dockerfile` copia apenas `dashboard/` e instala apenas
Streamlit e Plotly. Não há como o container falar com o DW ou com as APIs
porque não existe biblioteca capaz disso dentro dele.

**Compose.** O serviço `dashboard` não recebe `env_file: .env`, não declara
`environment`, não declara `depends_on: db` e monta o dataset como **somente
leitura**.

**O que a interface nunca exibe:** chave HMAC, chave natural (`_nk`), chave
substituta (`_sk`), external ID, nome real ou caminho absoluto. O
`fingerprint_chave` do manifesto é exibido porque, por construção, não permite
recuperar o segredo — ele responde apenas se dois artefatos foram gerados com a
mesma chave, e portanto se os pseudônimos deles são comparáveis.

Verificação executada sobre a superfície **real**: varredura de todo o texto
renderizado nas quatro páginas (≈347 mil caracteres) contra os oito padrões
proibidos do auditor (URL, `www.`, domínio, e-mail, telefone, CNPJ, tratamento
pessoal, arroba) e contra os quatro sufixos de identidade. Nenhuma ocorrência
de identificador. Os únicos casamentos foram `@media` (regra de CSS) e as
menções literais aos sufixos no texto explicativo da própria tela "Sobre os
dados".

## 11. Modo demonstração

O repositório precisa continuar utilizável sem versionar dado de cliente. Se a
superfície de exposição não existir, o painel adota `dashboard/dados_demo/`.

O dataset sintético:

- é gerado por `dashboard/gerar_dados_demo.py`, determinístico (semente fixa
  20260825; há teste que reprova o arquivo versionado se ele divergir do
  gerador);
- **não deriva de nome, external ID, chave natural ou métrica real**: os
  identificadores saem de `sha256("demo|<nível>|<índice>")` e os números, de um
  gerador pseudoaleatório;
- **não usa a chave HMAC da fronteira de exposição** — há teste afirmando isso.
  Pseudônimo real e rótulo de demonstração não devem compartilhar primitivo, e
  o manifesto declara `fingerprint_chave: null` justamente para não sugerir uma
  procedência que não existe;
- respeita o **mesmo contrato de 19 colunas**, e reproduz de propósito as
  ausências reais: `reach`, `profile_views` e `purchases` zerados no Google;
  `profile_views` zerado também no Meta; `conversion_value` zerado no Meta e
  positivo no Google; `conversions` fracionária no Google e inteira no Meta;
- cobre 28 dias, duas plataformas, 6 contas, 15 campanhas, 30 ad sets e 48
  anúncios, com entidades em duas versões SCD2 e anúncios que estreiam no meio
  do período;
- usa um período (junho/2026) deliberadamente distinto do período real
  (abril e agosto/2026), para que nenhum screenshot de demonstração seja
  confundido com dado real.

**Evidência independente:** o dataset sintético é submetido a
`scripts/auditar_dataset_exposicao.py --sem-dw`, o mesmo auditor da superfície
real — que não importa nada do dashboard nem do exportador — e é **aprovado**.
O contrato fica provado, não afirmado.

O selo na interface vem da **fonte escolhida**, não do conteúdo: quem carrega o
dataset sintético vê `DADOS DE DEMONSTRACAO`; quem carrega a superfície vê
`DADOS PSEUDONIMIZADOS`. Não existe modo que carregue dado identificável.

## 12. Integração Docker

```yaml
dashboard:
  build:
    context: .
    dockerfile: dashboard/Dockerfile
  container_name: tcc_dashboard
  ports:
    - "8501:8501"
  volumes:
    - ./dashboard:/app/dashboard:ro
    - ./data/exposicao:/app/data/exposicao:ro
  restart: unless-stopped
  healthcheck: ...   # /_stcore/health
```

Sem `env_file`, sem `environment`, sem `depends_on`. Os sete serviços
anteriores (`db`, `etl_app`, `airflow_db`, `airflow-init`,
`airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor`) permanecem
intactos.

```bash
docker compose up -d
# http://localhost:8501
```

Portas em uso no projeto: 5433 (DW), 8082 (Airflow), **8501 (dashboard)**.
A 8080 é de outro projeto e a 8081 é do callback OAuth.

## 13. Testes implementados

`tests/test_dashboard.py`, `unittest`, sem dependência nova. **127 testes**,
distribuídos em 18 classes:

| Área | O que cobre |
|---|---|
| Carregamento | tipagem, `Decimal`, escala fracionária, célula vazia, resumo, manifesto presente e ausente |
| Contrato de schema | coluna ausente, ordem divergente, coluna extra ignorada, arquivo sem cabeçalho, data inválida, métrica não numérica, versão SCD2 inválida, linha truncada |
| Fronteira de exposição | recusa de `_nome`, `_external_id`, `_nk`, `_sk`; identificador fora do formato; plataforma com texto livre; mensagem que não reproduz o valor; ausência de import de banco/SDK; ausência de SQL; gerador que não usa a chave HMAC |
| Escolha de fonte | precedência, fallback, modo forçado, ausência total, rótulos dos selos |
| Filtros | período inclusive, plataforma, hierarquia em três níveis, simultaneidade, seleção vazia, saneamento de resíduo, filtros preservados em outro período |
| Dataset vazio | carga, resumo, seleção inicial, agregado, derivadas, ranking, série |
| Plataforma única | série, agregação, cobertura, opções |
| Agregação | soma exata, fechamento por plataforma, série diária, ranking, Top N, pais pseudonimizados, contagem de versões |
| Período anterior | 7 dias, 1 dia, virada de mês, período invertido, respeito aos filtros, ausência de base |
| Período padrão | dataset longo abre em `[max-6, max]`; janela de exatamente sete dias de calendário; dataset curto abre inteiro; lacuna não estica a janela; âncora é o dataset e não o relógio; dataset vazio; seleção manual preservada; período anterior de mesma duração; modo demo e superfície pseudonimizada abrem nos seus próprios últimos sete dias |
| Variação | alta, queda, base zero, base ausente, seta neutra |
| Derivadas | CTR, CPC, CPM, CPA, ROAS e a propriedade dos operandos |
| Divisão segura | denominador zero, negativo, ausente; numerador zero legítimo; todas as derivadas indisponíveis; formatação sem `NaN`/`Infinity` |
| Formatação | moeda, milhar, percentual, negativo, zero |
| Catálogo | nove métricas, ausências do Google, `video_views` não somável, `reach` não aditiva, métrica desconhecida |
| Dataset de demonstração | contrato, duas plataformas, dias, entidades, versões SCD2, grão único, hierarquia, ausências do Google, manifesto, determinismo, arquivo em dia com o gerador, auditor independente |
| Smoke Plotly | figuras de série, barras com rótulo de indisponível, ranking, cores distintas |
| Smoke aplicação | as quatro páginas renderizam sem exceção; filtro hierárquico ao vivo; "Limpar filtros" |

Os testes de Streamlit e Plotly são pulados onde as bibliotecas não existem —
o container do ETL, por exemplo. A lógica é sempre testada; não há teste de
screenshot.

## 14. Limitações

1. **A validação geométrica de layout não faz parte da suíte permanente.**
   Chromium/Playwright verificou nesta sessão as quatro páginas em 1366×768 e
   1920×1080, mais a Visão Geral em 1280×720 e 1024×768. O roteiro mediu
   overflow, breakpoints, interseção entre interativos, zoom e recolhimento da
   sidebar, mas continua sendo evidência de sessão, não teste de screenshot no
   repositório.
2. **`reach` do período é soma de alcance diário**, não alcance único. A
   interface avisa e mantém a métrica fora dos KPIs, mas quem escolher `reach`
   no seletor de métrica verá a soma.
3. **`profile_views` está zerada nas duas plataformas** no artefato atual. Ela
   aparece na matriz de cobertura, mas não produz informação hoje.
4. **A comparação com o período anterior depende de calendário contínuo.** O
   artefato real tem lacunas, e nelas a comparação fica corretamente
   indisponível.
5. **O dashboard não valida a origem do CSV.** Ele valida o *contrato*: um
   arquivo que satisfaça as 19 colunas e o formato de pseudônimo é aceito,
   venha de onde vier. A garantia de que o conteúdo é pseudonimizado vem do
   exportador e do auditor, a montante.
6. **Não há paginação nas tabelas.** Com 801 anúncios a tabela detalhada rola;
   no volume projetado (<600 mil linhas em 5 anos) isso continua adequado, mas
   não escala indefinidamente.
7. **A validação de UX cobre os tamanhos definidos para a Defesa, não todo
   dispositivo possível.** A menor resolução exercitada foi 1024×768; abaixo
   disso a grade continua empilhando, mas não houve inspeção humana exaustiva.
8. **O tema vive em dois lugares.** As cores estruturais estão em
   `.streamlit/config.toml`, porque os controles do Streamlit são componentes
   React que derivam suas cores do tema e ignoram CSS de página; as cores de
   layout estão no CSS de `componentes.py`. Trocar uma cor da paleta exige
   mudar nos dois. É o preço de os controles nativos conviverem com um layout
   próprio.

## 15. Identidade visual

A primeira versão da interface foi reprovada em inspeção visual: sidebar sem
contraste, controles quase pretos destoando do conteúdo claro, cartões grandes
demais, conteúdo espalhado horizontalmente e hierarquia tipográfica fraca. A
revisão de 25/08/2026 tratou disso sem tocar em arquitetura, contrato de
segurança, métricas ou fórmulas.

### 15.1 Paleta

| Papel | Cor |
|---|---|
| Fundo do conteúdo | `#F6F7F9` |
| Cartão | `#FFFFFF` |
| Borda | `#E4E7EC` |
| Texto principal | `#172033` |
| Texto secundário | `#667085` |
| Destaque (item ativo, foco, toggle) | `#E84A5F` |
| Fundo da barra lateral | `#151A23` |
| Campo na barra lateral | `#232B39` |
| Texto na barra lateral | `#E7EAF0` |

A cor de destaque aparece em poucos lugares: a barra do item de navegação
ativo, o foco dos controles e o toggle. As cores de plataforma (azul para o
Meta, âmbar para o Google) existem **apenas** dentro dos gráficos e das
legendas — não são a identidade da aplicação.

### 15.2 Onde cada camada é declarada

- **`.streamlit/config.toml`** — tema nativo. Fixa `base = "light"` no
  conteúdo, o que torna a aplicação clara **independentemente** do
  `prefers-color-scheme` do navegador, e declara um tema próprio para a barra
  lateral (`[theme.sidebar]`) com fundo escuro e `secondaryBackgroundColor` um
  degrau acima, que é o preenchimento dos campos. Era o problema dos "selects
  quase pretos": eles são componentes React e não obedecem a CSS de página.
- **`componentes.py`** — CSS de layout: container central de 1376 px,
  densidade, cartões, cabeçalho de página e de seção, tipografia e a barra
  lateral.

### 15.3 Tipografia e densidade

`Inter, system-ui, …` — pilha de sistema, sem fonte externa. Título de página
1,8 rem; título de seção 1,1 rem; valor de KPI 1,9 rem (1,35 rem nos cartões de
eficiência); rótulo de KPI 0,72 rem em caixa alta discreta; texto auxiliar
0,78–0,83 rem.

Os cartões têm altura mínima uniforme (124 px nos principais, 92 px nos de
eficiência). A grade é CSS, não `st.columns`: três colunas a partir de 1300
px, duas entre 1100 e 1299 px e uma abaixo de 1100 px. Os indicadores de
eficiência usam cinco, três e duas colunas nesses mesmos intervalos.

Em 1366×768 cabem, sem rolagem: cabeçalho, filtros, os seis KPIs, os cinco
cartões de eficiência e o início da seção seguinte.

A sidebar mede 288 px no desktop, com 228 px úteis para cada controle. No
multiselect, chip, input de busca, clear e dropdown ocupam faixas separadas; o
chip usa ellipsis e os chips adicionais quebram linha dentro do campo. Ao
recolher a sidebar, sua largura efetiva vira zero e o conteúdo usa toda a
largura disponível; ao reabrir, os 288 px são restaurados.

### 15.4 Navegação

A navegação continua sendo um `st.radio` — acessível e navegável pelo teclado —
mas sem a bolinha, que não acrescenta significado quando os itens já são uma
lista de páginas. O item ativo recebe fundo levemente mais claro e uma barra
vertical na cor de destaque. O `input` permanece no DOM: leitor de tela e
teclado continuam funcionando.

### 15.5 Ruído do Streamlit

`toolbarMode = "minimal"` remove o botão de deploy e o menu de desenvolvedor;
o CSS esconde a faixa decorativa e o rodapé. O cabeçalho **não** é removido —
é nele que mora o controle de recolher a barra lateral.

### 15.6 Verificação visual

Chromium controlado por Playwright contra o serviço Docker, nas quatro
páginas em 1366×768 e 1920×1080; a Visão Geral também em 1280×720 e
1024×768:

| Resolução | Grade principal | Overflow | Overlap interativo |
|---|---:|---|---|
| 1024×768 | 1 coluna | nenhum | nenhum |
| 1280×720 | 2 colunas | nenhum | nenhum |
| 1366×768 | 3 colunas | nenhum | nenhum |
| 1920×1080 | 3 colunas | nenhum | nenhum |

Em 1366×768 com uma conta selecionada, foram medidos separadamente label,
chip, botão de remoção, input, clear, dropdown e botão Limpar filtros:
nenhum par indevido se intersecta. A mesma checagem cobriu toggle, seletor de
métrica, badge e metadados do cabeçalho. Zoom equivalente a 90%, 100%, 110%
e 125% teve zero overflow e zero overlap. Sidebar aberta, recolhida e reaberta
mediu respectivamente 1078, 1366 e 1078 px de conteúdo.

Contraste medido (WCAG 2.1, texto normal exige 4,5:1):

| Texto | Razão |
|---|---|
| Rótulo de grupo na barra lateral | 5,85 |
| Subtítulo e navegação inativa | 6,77 |
| Rótulo de campo na barra lateral | 6,77 |
| Rótulo de KPI e variação | 4,97 |
| Descrição da página e apoio de seção | 4,64 |
| Valor de KPI | 16,27 |

Log do container revisado: zero erro, zero aviso e zero mensagem de
depreciação. A imagem foi reconstruída e o tema de `/app/.streamlit` foi
confirmado pela paleta computada dos widgets.
