# Evidências do dashboard — auditoria de `dashboard-implementado.md`

Documento de auditoria. **Não faz parte do artigo.** Para cada afirmação
técnica relevante da documentação da camada de visualização, registra o arquivo
que a comprova, o elemento correspondente (função, classe, teste ou
configuração), observações e o nível de confiança.

Auditoria realizada em 25/08/2026, sobre o HEAD `be35cb9` (`main`) mais as
alterações não commitadas descritas em `dashboard-implementado.md`. Revisada no
mesmo dia, após a reprovação da primeira versão da interface em inspeção visual
humana e a revisão visual que se seguiu.

**Limitação geral desta auditoria.** A validação do dashboard foi repetida
em 25/08/2026 com o Docker disponível: imagem reconstruída, container saudável,
Chromium/Playwright contra `localhost:8501` e os 127 testes executados dentro
da imagem com Streamlit e Plotly. A checagem geométrica continua sendo roteiro
de sessão em `/tmp`, não teste permanente de screenshot no repositório.

Convenção de confiança:

- **ALTO** — lido diretamente no código/configuração versionada, contado
  programaticamente a partir dela, ou reproduzido por execução nesta sessão.
- **MÉDIO** — sustentado por código consistente, mas não exercitado no ambiente
  de destino nesta sessão.
- **BAIXO** — apoiado apenas em documentação, sem verificação independente.

---

## 1. Arquitetura e fronteira

### 1.1 O dashboard consome exclusivamente a superfície de exposição

Evidência: `dashboard/dados.py` — `CAMINHO_PSEUDONIMIZADO`,
`CAMINHO_DEMONSTRACAO`, `escolher_fonte()`. Os dois únicos caminhos possíveis
são arquivos CSV; não há ramo que abra conexão.
Teste: `TestEscolhaDeFonte` (5 casos), incluindo
`test_sem_nenhuma_fonte_levanta_contrato_invalido` — a ausência de dataset é
erro, não convite a consultar o Gold.
Confiança: **ALTO**.

### 1.2 Não há driver de banco nem SDK de plataforma no pacote

Evidência: `tests/test_dashboard.py` —
`TestFronteiraDeExposicao::test_modulos_do_dashboard_nao_importam_banco_nem_sdk`
varre todo `dashboard/*.py` por `import`/`from` e reprova `psycopg2`,
`sqlalchemy`, `google.ads`, `google_ads`, `facebook_business`, `requests`,
`httpx` e `dbt`.
Observação: é teste de código-fonte, não de runtime — mas o import é a única
forma de o Python alcançar essas bibliotecas, e o teste roda em toda execução
da suíte.
Confiança: **ALTO**.

### 1.3 Não há SQL em nenhum módulo do dashboard

Evidência: `test_dashboard_nao_executa_sql` (regex `select ... from <schema>.`)
e `test_entrada_de_dados_nao_menciona_schema_do_data_warehouse`
(`bronze.`, `silver.`, `gold.`, `raw_ads` ausentes de `dados.py`).
Observação: a docstring de `app.py` cita `gold.vw_metricas_completas` ao
desenhar a arquitetura; o teste distingue menção de consulta.
Confiança: **ALTO**.

### 1.4 O dashboard não reimplementa pseudonimização nem travessia SCD2

Evidência: `dashboard/` não contém `import pseudonimos`, `hmac` nem `join`; a
entrada já vem no grão do fato, com as quatro colunas de versão resolvidas pelo
exportador a partir de `gold.vw_metricas_completas`.
Teste: `test_gerador_de_demo_nao_usa_a_chave_de_pseudonimizacao` cobre o caso
mais provável de deslize (o gerador sintético).
Observação: a ausência de `import pseudonimos` nos demais módulos não é
afirmada por teste dedicado — está coberta indiretamente pela lista de imports
proibidos, que **não** inclui `pseudonimos`. Melhoria possível.
Confiança: **ALTO** para SCD2 e para o gerador; **MÉDIO** para a ausência de
pseudonimização nos demais módulos.

### 1.5 A imagem do dashboard não contém driver de banco nem SDK

Evidência: `dashboard/Dockerfile` (`COPY dashboard/ /app/dashboard/`,
`pip install -r dashboard/requirements.txt`);
`dashboard/requirements.txt` (apenas `streamlit` e `plotly`).
Observação: imagem reconstruída nesta sessão; os 127 testes foram
executados nela e o serviço permaneceu saudável durante a matriz visual.
Confiança: **ALTO**.

### 1.6 O serviço do compose não recebe credencial nem depende do banco

Evidência: `docker-compose.yml`, serviço `dashboard`. Verificado por parse YAML
nesta sessão: `env_file` ausente, `environment` ausente, `depends_on` ausente,
`volumes` com sufixo `:ro` nos dois mounts, `ports` `8501:8501`.
Também verificado que os sete serviços anteriores continuam declarados.
Confiança: **ALTO** para o conteúdo declarado; **MÉDIO** para o comportamento
em execução.

## 2. Contrato de dados

### 2.1 As 19 colunas obrigatórias, na ordem do contrato

Evidência: `dashboard/dados.py` — `COLUNAS_OBRIGATORIAS`,
`validar_cabecalho()`.
Teste: `TestContratoDeSchema::test_coluna_obrigatoria_ausente_e_nomeada_no_erro`,
`test_ordem_diferente_do_contrato_e_recusada`.
Observação: a lista é redeclarada aqui em vez de importada do exportador — a
mesma razão pela qual `auditar_dataset_exposicao.py` redeclara o schema.
Confiança: **ALTO**.

### 2.2 Coluna com sufixo de identidade recusa o arquivo inteiro

Evidência: `dados.py` — `SUFIXOS_PROIBIDOS`, checado **antes** da checagem de
colunas obrigatórias em `validar_cabecalho()`.
Teste: `test_coluna_de_nome_real_recusa_o_arquivo_inteiro` (4 subcasos),
`test_coluna_de_external_id_recusa_o_arquivo_inteiro`,
`test_chave_natural_e_substituta_recusam_o_arquivo` (2 subcasos).
Confiança: **ALTO**.

### 2.3 Identificador fora do formato de pseudônimo é recusado

Evidência: `dados.py` — `FORMATO_ID`, aplicado por linha em `_converter()`.
Teste: `test_identificador_fora_do_formato_de_pseudonimo_e_recusado`.
Observação: é o que impede um nome real de se esconder numa célula de
identificador; mesmo padrão do auditor.
Confiança: **ALTO**.

### 2.4 Mensagem de falha não reproduz o valor recusado

Evidência: docstring de `ContratoInvalido`; mensagens em `_converter()` citam
coluna e número de linha.
Teste: `test_mensagem_de_erro_nao_reproduz_o_valor_recusado`.
Confiança: **ALTO**.

### 2.5 Coluna extra é ignorada de propósito e reportada

Evidência: `validar_cabecalho()` devolve as extras; `Dataset.colunas_ignoradas`;
exibição em `app.py::pagina_sobre`.
Teste: `test_coluna_extra_e_ignorada_e_reportada`.
Confiança: **ALTO**.

### 2.6 Falha de contrato não produz stack trace na interface

Evidência: `app.py::main` captura `dados.ContratoInvalido` e chama
`componentes.erro_de_contrato()`.
Observação: exceção **fora** do contrato (um erro de programação) continua
subindo como erro do Streamlit. Isso é deliberado — mascarar bug não é
tratamento de erro —, mas não está coberto por teste.
Confiança: **ALTO** para o caminho de contrato; **BAIXO** para os demais.

## 3. Métricas e aritmética

### 3.1 As nove métricas do pipeline, com suporte declarado por plataforma

Evidência: `dashboard/metricas.py` — `CATALOGO`, `suportada()`.
Teste: `TestCatalogoDeMetricas::test_cobre_as_nove_metricas_do_pipeline`
(compara com `dados.METRICAS`),
`test_metricas_sem_suporte_no_google` (`reach`, `profile_views`, `purchases`).
Confiança: **ALTO**.

### 3.2 `video_views` não é somável entre plataformas

Evidência: `CATALOGO["video_views"].comparavel_entre_plataformas = False` e a
observação com as duas definições (TrueView 30 s × 3 s).
Teste: `test_video_views_nao_soma_entre_plataformas`.
Observação: a métrica **continua** disponível no seletor, com a ressalva
impressa abaixo do gráfico — restringir o seletor esconderia dado legítimo.
Confiança: **ALTO**.

### 3.3 `reach` não é aditiva no tempo

Evidência: `CATALOGO["reach"].aditiva_no_tempo = False`.
Teste: `test_reach_nao_e_aditiva_no_tempo`.
Observação: a propriedade é **declarada e exibida**, mas a aplicação não impede
somar `reach` na série temporal — ela avisa. É a limitação 2 do documento.
Confiança: **ALTO** para a declaração; a limitação está registrada.

### 3.4 Divisão segura: nunca `NaN`, nunca `Infinity`

Evidência: `metricas.dividir()` devolve `None` para denominador `<= 0` ou
operando ausente; `formatar()` mapeia `None` para `--`.
Teste: `TestDivisaoSegura` (7 casos), incluindo
`test_derivadas_com_denominador_zerado_ficam_indisponiveis` e
`test_nenhuma_formatacao_produz_nan_ou_infinity`.
Confiança: **ALTO**.

### 3.5 Os cinco derivados usam apenas operandos consolidáveis

Evidência: `DERIVADAS`; `METRICAS_CONSOLIDAVEIS` derivado do catálogo.
Teste: `TestDerivadas::test_todos_os_operandos_sao_metricas_consolidaveis`.
Confiança: **ALTO**.

### 3.6 Agregação em `Decimal`, `float` só na apresentação

Evidência: `dados._converter()` (`Decimal`), `metricas.agregar()`,
`graficos._float()` — única conversão, documentada na docstring do módulo.
Teste: `TestAgregacao::test_soma_em_decimal_sem_erro_de_ponto_flutuante`,
`test_conversao_fracionaria_preserva_a_escala`.
Confiança: **ALTO**.

### 3.7 Soma por plataforma fecha com o total

Evidência: `metricas.agregar_por()`.
Teste: `test_soma_por_plataforma_fecha_com_o_total` — mesma verificação que o
pipeline faz contra inflação de join.
Confiança: **ALTO**.

## 4. Período anterior

### 4.1 Mesma duração, terminando na véspera

Evidência: `metricas.periodo_anterior()`.
Teste: `TestPeriodoAnterior` — 7 dias (10–16/08 → 03–09/08), 1 dia, virada de
mês, período invertido levanta `ValueError`.
Confiança: **ALTO**.

### 4.2 A comparação respeita todos os filtros ativos

Evidência: `filtros.aplicar_em_periodo()` (`dataclasses.replace` trocando
apenas as datas); chamada em `app.py::pagina_visao_geral`.
Teste: `test_comparacao_respeita_todos_os_filtros`,
`test_aplicar_em_periodo_preserva_os_filtros_de_entidade`.
Confiança: **ALTO**.

### 4.3 Sem base de comparação, nenhum percentual é inventado

Evidência: `metricas.variacao()` devolve `None` para base `<= 0` ou ausente;
`componentes.cartao_kpi()` imprime "sem base de comparação";
`app.py::pagina_visao_geral` troca o texto da seção quando não há registros
anteriores.
Teste: `test_base_zero_nao_inventa_percentual`,
`test_base_ausente_e_indisponivel`,
`test_sem_dados_anteriores_a_lista_e_vazia`.
Confiança: **ALTO**.

### 4.4 A variação não é classificada como boa ou ruim

Evidência: `metricas.formatar_variacao()` usa `▲`/`▼`/`▬` sem cor;
`componentes.ESTILO` pinta `.kpi-delta` com o cinza neutro do tema, sem regra
condicional.
Teste: `test_formatacao_usa_seta_sem_julgamento`.
Confiança: **ALTO**.

## 5. Filtros

### 5.1 Hierarquia real entre conta, campanha e ad set

Evidência: `filtros.opcoes()` — recorta o escopo nível a nível, de cima para
baixo.
Teste: `test_opcoes_de_campanha_respeitam_a_conta`,
`test_opcoes_de_adset_respeitam_a_campanha`,
`test_opcoes_de_conta_respeitam_a_plataforma`,
`test_opcoes_respeitam_o_periodo`.
Verificação ao vivo nesta sessão, sobre a superfície real: 207 campanhas
oferecidas → 15 após escolher uma conta; 65 contas → 36 após escolher
"Google Ads".
Confiança: **ALTO**.

### 5.2 Seleção residual é descartada

Evidência: `filtros.sanear()`; `app.py::_multiselect` poda o `session_state`
antes de instanciar o widget.
Teste: `test_sanear_descarta_selecao_que_deixou_de_ser_valida`,
`test_sanear_descarta_plataforma_fora_do_periodo`.
Confiança: **ALTO**.

### 5.3 Todos os filtros atuam simultaneamente

Evidência: `filtros.aplicar()`.
Teste: `test_filtros_atuam_simultaneamente` (período + plataforma + conta +
campanha + ad set, resultando em uma linha).
Confiança: **ALTO**.

### 5.4 "Limpar filtros" devolve o estado inicial

Evidência: `app.py::barra_lateral` — remove `CHAVES_FILTRO` do `session_state`
e chama `st.rerun()`.
Teste: `TestSmokeAplicacao::test_limpar_filtros_devolve_a_selecao_vazia`
(exercitado com Streamlit real).
Confiança: **ALTO**.

### 4.5 Período padrão: os últimos sete dias do dataset

Evidência: `filtros.periodo_padrao()` — `max(inicio, fim - 6 dias)`, com
`JANELA_PADRAO_DIAS = 7`; consumido por `filtros.selecao_inicial()`.
Testes (`TestPeriodoPadrao`, 10 casos): dataset longo abre em `[max-6, max]`;
a janela tem exatamente sete dias de calendário; dataset com menos de sete dias
abre inteiro; lacuna de calendário não estica a janela e deixa o dia isolado de
fora; a âncora é o dataset e não o relógio; dataset vazio devolve intervalo
nulo; seleção manual continua valendo; o período anterior derivado do padrão
tem a mesma duração; o dataset de demonstração e a superfície pseudonimizada
abrem cada um nos seus próprios últimos sete dias.
Verificação ao vivo nesta sessão: superfície real abre em `12 ago — 18 ago
2026` comparando com `05 ago — 11 ago 2026`; modo demonstração abre em
`22 jun — 28 jun 2026` comparando com `15 jun — 21 jun 2026`.
Observação: `date.today()` permanece em `filtros.selecao_inicial` **apenas**
para o caso de dataset vazio, em que não há data a inferir.
Confiança: **ALTO**.

## 6. Modo demonstração

### 6.1 O dataset sintético não deriva de dado real

Evidência: `gerar_dados_demo.identificador()` —
`sha256("demo|<nível>|<índice>")`; métricas de `random.Random(SEMENTE)`.
Teste: `test_identificadores_nao_dependem_de_entrada_real`,
`test_gerador_de_demo_nao_usa_a_chave_de_pseudonimizacao`.
Confiança: **ALTO**.

### 6.2 Respeita o mesmo contrato da superfície de exposição

Evidência: `COLUNAS` idêntico às 19 colunas; identificadores no formato de
pseudônimo.
Teste: `TestDatasetDeDemonstracao` — contrato, grão único, hierarquia com um
único pai por filho, ausências do Google, duas plataformas, ≥14 dias,
entidades multiversão.
**Evidência independente:** `scripts/auditar_dataset_exposicao.py --sem-dw
--diretorio dashboard/dados_demo` → `AUDITORIA APROVADA — 1023 linhas, 19
colunas`, exit 0, executado nesta sessão. O auditor não importa nada do
dashboard nem do exportador.
Teste que o mantém: `test_passa_no_auditor_independente_da_superficie_real`.
Confiança: **ALTO**.

### 6.3 Geração determinística e arquivo versionado em dia

Evidência: semente fixa; `gerar()` grava CSV e manifesto.
Teste: `test_geracao_e_deterministica`,
`test_arquivo_versionado_esta_em_dia_com_o_gerador` (compara byte a byte com o
arquivo versionado).
Confiança: **ALTO**.

### 6.4 O selo vem da fonte, não do conteúdo

Evidência: `dados.Fonte.modo` é decidido em `escolher_fonte()`;
`Dataset.rotulo_modo` consulta `ROTULO_MODO`; `app.py` passa isso a
`componentes.cabecalho()`.
Teste: `test_rotulo_do_modo_e_explicito_na_interface`,
`TestEscolhaDeFonte` (precedência).
Confiança: **ALTO**.

### 6.5 O dataset sintético é versionado apesar do `.gitignore`

Evidência: `.gitignore` linha 44 — `!dashboard/dados_demo/*.csv`, exceção
explícita à regra global `*.csv`.
Verificação: `git status --porcelain -uall dashboard/` lista
`dashboard/dados_demo/metricas.csv` como untracked (rastreável), executado
nesta sessão.
Observação: a exceção foi inserida com edição programática, não com
`printf >>` — a armadilha nº 12 do projeto.
Confiança: **ALTO**.

## 7. Interface

### 7.1 Quatro páginas renderizam sem exceção

Evidência: `app.py` — `PAGINAS`, despacho em `main()`.
Teste: `TestSmokeAplicacao::test_todas_as_paginas_renderizam_sem_excecao`, via
`streamlit.testing.v1.AppTest`, em modo demonstração.
Verificação adicional nesta sessão: as quatro páginas também foram executadas
contra a **superfície real**, com zero exceção.
Confiança: **ALTO**.

### 7.2 Seis KPIs principais e cinco derivados

Evidência: `app.py` — `KPIS_PRINCIPAIS` (2 linhas × 3), `KPIS_DERIVADOS`.
Confiança: **ALTO**.

### 7.3 Métrica sem suporte não aparece como desempenho zero

Evidência: `graficos.barras_plataforma()` pinta a barra de cinza e escreve
`metricas.AVISO_NAO_DISPONIVEL`; `app.py::nota_cobertura()` acrescenta a
ressalva ao cartão; o quadro de cobertura lista os pares métrica × plataforma.
Teste: `TestSmokeStreamlitEPlotly::test_graficos_produzem_figura` afirma que o
texto da barra de `reach` contém `não disponibilizado nesta origem`.
Confiança: **ALTO**.

### 7.4 Uma métrica por gráfico

Evidência: `graficos.serie_temporal()` recebe uma única métrica; a alternância
é entre séries por plataforma, não entre métricas.
Confiança: **ALTO**.

### 7.5 Cores de plataforma consistentes e moderadas

Evidência: `graficos.COR_PLATAFORMA` — azul `#3B6FE0` (Meta), âmbar `#D9902B`
(Google), com fallback cinza para origem desconhecida.
Teste: `test_cores_de_plataforma_sao_distintas`.
Observação: referência moderada, não reprodução de identidade visual oficial.
Confiança: **ALTO**.

### 7.6 Layout legível de 1024×768 a 1920×1080

Evidência: `componentes.ESTILO` — `max-width: 1376px` centralizado, grid CSS
próprio para KPIs e media queries em 1439/1299/1099/991/640 px. A grade
principal usa 3 colunas em 1366 e 1920, 2 em 1280 e 1 em 1024; eficiência usa
5/3/2 colunas nos mesmos intervalos.
Verificação executada nesta sessão, com Chromium via Playwright contra o container:
as quatro páginas em 1366×768 e 1920×1080, mais a Visão Geral em 1280×720 e
1024×768. Em todas, `document.scrollWidth == clientWidth`, sem interseção
entre elementos interativos não aninhados. Em 1366, os seis KPIs, os cinco
derivados e o início de Evolução diária ficam na primeira dobra.
Confiança: **ALTO** para o medido; a verificação não faz parte da suíte
(limitação 1).

### 7.6.1 Multiselect e sidebar não disputam espaço

Evidência: `componentes.ESTILO` — sidebar de 288 px, 228 px úteis por campo;
seletores apoiados em `stMultiSelectTagsContainer`, `data-tag`, `aria-label` e
`data-rac`, sem classes geradas. Com uma conta selecionada, Playwright mediu
campo de 228×46 px, chip de 114×28, input de 40×28, clear de 28×40 e dropdown
de 32×40; nenhum par indevido se intersecta. O estado
`aria-expanded="false"` reduz a largura efetiva da sidebar a zero: o conteúdo
passa de 1078 para 1366 px e volta a 1078 px ao reabrir, sem margem fantasma.
Confiança: **ALTO**.

### 7.6.2 Zoom não cria overlap

Verificação: viewport CSS equivalente a 90%, 100%, 110% e 125% sobre
1366×768. Resultados: zero overflow e zero interseção interativa nos quatro
níveis; a grade passa de 3 para 2 e 1 coluna conforme o espaço diminui.
Confiança: **ALTO**.

### 7.7 Conteúdo claro independente do tema do navegador

Evidência: `.streamlit/config.toml` — `[theme] base = "light"` e
`[theme.sidebar]` com `backgroundColor = "#151A23"`,
`secondaryBackgroundColor = "#232B39"` e `textColor = "#E7EAF0"`;
`componentes.ESTILO` fixa `color-scheme: light` e repete os tokens dentro de
`@media (prefers-color-scheme: dark)`.
Verificação: computados no navegador — fundo da aplicação `rgb(246,247,249)`,
campo de multisseleção `rgb(35,43,57)` com texto `rgb(231,234,240)` e borda
`rgb(51,60,76)`.
Observação: era a causa raiz dos "selects quase pretos". Controles do Streamlit
são componentes React que derivam cores do tema; CSS de página não os alcança.
Confiança: **ALTO**.

### 7.8 Contraste AA em todo texto medido

Evidência: medição WCAG 2.1 no navegador, nesta sessão, sobre as cores
computadas: rótulo de grupo na barra lateral 5,85; subtítulo e navegação
inativa 6,77; rótulo de campo 6,77; rótulo de KPI e variação 4,97; descrição de
página e apoio de seção 4,64; valor de KPI 16,27. Mínimo exigido para texto
normal: 4,5.
Observação: `--sb-rotulo` foi clareado de `#78849A` para `#8B96AB` justamente
porque a medição apontou 4,4.
Confiança: **ALTO**.

### 7.9 Navegação sem bolinha, com acessibilidade preservada

Evidência: `componentes.ESTILO` esconde apenas o marcador
(`[data-testid="stRadioOption"] div:has(> [data-testid="stMarkdownContainer"])
> div:first-child`), mantendo o `<input type="radio">` no DOM; o item ativo usa
`[data-selected="true"]`.
Verificação: no navegador, `display: none` no marcador e
`innerText == "Visão Geral"` no item — texto presente, marcador ausente.
Observação: a primeira tentativa escondia `label > div:first-child`, que teria
escondido o rótulo inteiro. Foi corrigida depois de inspecionar o DOM real.
Confiança: **ALTO**.

## 8. Testes e execução

### 8.1 127 testes, sem dependência nova

Evidência: `tests/test_dashboard.py`; dentro da imagem reconstruída do
dashboard, com Streamlit e Plotly instalados, `python -m unittest
tests.test_dashboard` → `Ran 127 tests ... OK (skipped=1)`. O único skip é o
auditor independente, cuja dependência pertence ao ETL e não à imagem
deliberadamente mínima do dashboard.
Confiança: **ALTO**.

### 8.2 A lógica é testável sem Streamlit

Evidência: `dados.py`, `metricas.py` e `filtros.py` importam apenas stdlib.
Verificação: a suíte roda inteira no interpretador do sistema, sem Streamlit e
sem Plotly, pulando 5 testes (3 de apresentação, 1 de aplicação e 1 que depende
das dependências do auditor).
Confiança: **ALTO**.

### 8.3 A suíte existente do projeto não foi afetada

Evidência: nenhum arquivo fora de `dashboard/`, `tests/test_dashboard.py`,
`docker-compose.yml` e `.gitignore` foi alterado (`git status`).
Observação: no ambiente local, `tests/test_verificar_paridade` já apresentava
3 falhas e 2 erros **antes** desta implementação — reproduzido em uma cópia
limpa de `HEAD` (`git archive HEAD`) nesta sessão. Seis módulos de teste também
falham ao importar localmente por ausência de dependências do ETL. A suíte
completa precisa ser reexecutada no container `etl_app` quando o Docker
voltar.
Confiança: **ALTO** para a não-interferência; **MÉDIO** para o estado verde da
suíte completa.

### 8.4 A superfície de exposição continua aprovada

Evidência: `python scripts/auditar_dataset_exposicao.py --sem-dw` →
`AUDITORIA APROVADA — 4923 linhas, 19 colunas`, exit 0, executado nesta sessão.
Observação: escopo "somente artefato" — o cruzamento com o DW não foi feito,
porque o banco não estava no ar.
Confiança: **ALTO** para os checks offline; **MÉDIO** para os que exigem DW.

## 9. Segurança verificada em execução

### 9.1 Nenhum identificador real na saída renderizada

Evidência: varredura executada nesta sessão sobre a **superfície real**, nas
quatro páginas, do texto de `markdown`, `caption`, `dataframe`, `selectbox` e
`multiselect` (346.865 caracteres), contra os oito padrões proibidos do auditor
(URL, `www.`, domínio, e-mail, telefone, CNPJ, tratamento pessoal, arroba) e
contra os quatro sufixos de identidade.
Resultado: nenhuma ocorrência de identificador. Os únicos casamentos foram
`@media` (regra de CSS injetada) e as menções literais a `_nk`, `_sk`,
`_external_id` e `_nome` no texto explicativo da tela "Sobre os dados".
Observação: varredura ad hoc, **não** incorporada à suíte — depende de
Streamlit e da presença do artefato real. Candidata a virar teste opcional.
Confiança: **ALTO** para a execução; **MÉDIO** para a permanência.

### 9.2 Nenhuma credencial aparece em log

Evidência: o pacote não lê `.env`, não importa `config` e não recebe
`env_file` no compose. `dados.py` só lê `DASHBOARD_DATASET` e `DASHBOARD_MODO`,
nenhum dos quais é segredo.
Verificação nesta sessão: os logs das duas execuções do servidor (superfície
real e modo demonstração) foram varridos contra os 12 valores do `.env` com 8+
caracteres — **zero ocorrências** — e contra `deprecat|warning|error|traceback`
— **zero ocorrências**.
Observação: `docker compose logs --no-color dashboard` foi inspecionado após
a matriz visual: zero erro, zero aviso e zero mensagem de depreciação.
Confiança: **ALTO**.

### 9.3 Caminho absoluto não é exibido

Evidência: `dados.Fonte.caminho_relativo` converte para caminho relativo à raiz
do projeto, com fallback para o nome do arquivo.
Observação: sem teste dedicado. Melhoria possível.
Confiança: **MÉDIO**.

---

## 10. Pendências de verificação

A validação específica do dashboard está encerrada. A suíte completa do
projeto continua fora deste passe visual; ela inclui dependências e estados do
ETL que não foram alterados aqui. A validação permanente continua sendo os 127
testes do dashboard; o roteiro Playwright permanece evidência de sessão.
