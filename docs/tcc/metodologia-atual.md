# 3 METODOLOGIA

## 3.1 Caracterização da pesquisa

Este trabalho caracteriza-se como pesquisa tecnológica aplicada, de abordagem
predominantemente quantitativa e orientada ao desenvolvimento e à avaliação de
um artefato de software. O enquadramento mantém a classificação já adotada no
artigo, sem assumir formalmente o método *Design Science Research*. O objeto de
estudo é uma arquitetura de dados construída para integrar métricas de mídia
paga do Meta Ads e do Google Ads, preservar o histórico observável nas fontes e
disponibilizar informações analíticas para acompanhamento de campanhas e
anúncios (GIL, 2017).

Os requisitos foram levantados de forma empírica e observacional no contexto
operacional de uma agência de tráfego pago. A investigação partiu da
fragmentação dos dados entre plataformas, da necessidade recorrente de
consolidação manual e das diferenças de hierarquia e semântica entre os
relatórios de cada fonte. A partir desse diagnóstico, desenvolveu-se um sistema
capaz de extrair e armazenar dados brutos, transformá-los em um modelo analítico,
produzir uma superfície de exposição pseudonimizada, apresentá-los em um
*dashboard* e classificar o desempenho relativo de campanhas e anúncios.

A avaliação combinou testes automatizados, verificações de contratos,
reconciliação de agregados, execução controlada com dados reais e análise
empírica das distribuições de desempenho. Os dados operacionais foram usados
dentro do ambiente controlado do projeto; todo artefato destinado à exposição
foi submetido a pseudonimização e auditoria. Não houve experimento controlado com
usuários nem avaliação causal do efeito das campanhas. Assim, as conclusões
referem-se à correção técnica do artefato, à consistência dos dados processados e
ao comportamento descritivo observado no conjunto analisado.

O conjunto factual final contém 11.326 observações no grão de um anúncio por
dia, distribuídas em 32 datas. A cobertura temporal não constitui uma série
diária contínua entre seus extremos: há uma observação isolada em 07/04/2026 e
um intervalo contínuo de 26/07/2026 a 25/08/2026. Essa distinção foi preservada
para evitar que os valores mínimo e máximo fossem interpretados como cobertura
ininterrupta.

## 3.2 Arquitetura e ambiente de execução

A solução foi implementada segundo o padrão ELT (*Extract, Load, Transform*).
Nesse padrão, os dados são extraídos das fontes e carregados no ambiente
analítico antes das transformações, o que permite reaplicar regras de negócio
sem repetir chamadas às APIs (HÜBNER, 2020; REIS; HOUSLEY, 2023). O fluxo final
é composto pelas seguintes etapas: APIs do Meta Ads e do Google Ads, extração
em Python, arquivos brutos temporários acompanhados de manifesto, camada Bronze
*append-only* em PostgreSQL, camadas Silver e Gold transformadas com dbt,
superfície de exposição pseudonimizada e aplicação analítica em Streamlit.

O PostgreSQL foi utilizado tanto para a persistência dos dados brutos quanto
para o repositório dimensional. O dbt concentrou as transformações SQL, os
relacionamentos entre modelos e os testes de dados. O Apache Airflow orquestrou
as etapas de extração, carga na Bronze e construção analítica por meio de uma
DAG, enquanto o Docker Compose forneceu isolamento e reprodução do ambiente
local. O Python permaneceu responsável pela integração com as fontes, pela
carga, pelos manifestos, pelas validações, pela exportação da superfície e pelo
*dashboard*. A geração do conjunto de referência de paridade e a exportação da
superfície foram mantidas como processos de validação separados da execução
ordinária da DAG.

A execução agendada foi definida para as 06:00 no fuso
*America/Sao_Paulo*, sem recuperação automática de períodos passados e com uma
única execução ativa por vez. Em cada execução ordinária, a janela móvel
corresponde aos sete dias completos anteriores, excluindo o dia corrente. A
reextração desse intervalo permite incorporar revisões recentes efetuadas pelas
plataformas, sem tratar os valores publicitários como imutáveis. O Airflow
coordena as dependências e tentativas das tarefas; uma falha de transformação,
por exemplo, não exige nova consulta às APIs quando os dados brutos já foram
carregados.

## 3.3 Aquisição dos dados

As duas fontes foram acessadas por suas APIs oficiais, em modo somente leitura.
As consultas coletaram observações diárias no nível de anúncio, incluindo a
hierarquia conta, campanha, conjunto ou grupo de anúncios e anúncio, além das
métricas de entrega e desempenho necessárias ao modelo unificado. A integração
com o Meta Ads utilizou a API de *insights* e tratou estruturas dinâmicas de
ações e valores. A integração com o Google Ads utilizou sua linguagem própria
de consulta para percorrer as subcontas vinculadas à conta gerenciadora e
obter dados no nível de anúncio.

O estado atual das entidades não foi adotado como prova de participação
histórica. Uma campanha ou conta desabilitada no momento da consulta ainda pode
ter produzido métricas no período analisado. Por essa razão, filtros baseados
apenas no estado corrente foram removidos das consultas históricas. No Meta,
contas reconhecidas pela fonte como temporariamente indisponíveis foram
registradas como lacuna de cobertura e omitidas somente naquela execução, sem
imputação de zero; estados desconhecidos ou falhas não classificadas
interromperam a operação de forma conservadora. No Google, contas atualmente
não habilitadas cujo histórico não pôde ser consultado foram classificadas como
histórico não verificável, e não como ausência factual.

Cada extração gerou um arquivo com o conteúdo bruto e um manifesto com fonte,
identificador lógico da execução, intervalo consultado, instante da extração,
quantidade de registros e resumo criptográfico do conteúdo. Antes da carga, o
manifesto foi confrontado com o arquivo efetivo. Essa verificação evita que um
arquivo remanescente de outra execução seja aceito como se pertencesse ao lote
corrente. Credenciais e identificadores de contas reais não foram incorporados
aos artefatos acadêmicos.

## 3.4 Persistência na camada Bronze e resolução temporal

A camada Bronze preserva cada registro recebido em JSONB, acompanhado da fonte,
data de referência, instante de extração e identificador de lote. Sua política
é *append-only*: uma reextração acrescenta uma nova observação e não atualiza,
remove nem sobrescreve os lotes anteriores. Essa escolha mantém a rastreabilidade
das revisões retroativas e permite reconstruir as camadas analíticas a partir
dos dados já armazenados.

A identificação lógica de execução também participa do controle de
idempotência. O par formado pela fonte e pelo *run_id* é verificado pela
aplicação antes da carga e protegido por unicidade no banco quando o
identificador está presente. Os registros brutos e o respectivo registro no
log de ingestão são gravados na mesma transação. Consequentemente, uma colisão
reverte a operação completa, e a repetição do mesmo evento lógico não produz um
segundo lote confirmado. Essa proteção contra *replay* não altera a natureza
*append-only*: reextrações legítimas, com novas identidades de execução,
continuam preservadas.

Como diferentes lotes podem observar a mesma entidade no mesmo dia, a camada
analítica resolve a última observação válida para a chave hierárquica completa
da entidade e para a data de referência. A precedência é determinada pelo
instante de ingestão. A ausência de uma entidade em lote posterior não é
interpretada como zero, não cria marca de exclusão e não invalida uma
observação anterior disponível. Quando uma nova observação está presente, ela
pode substituir o valor anterior no retrato lógico. Empates de precedência
permanecem ambíguos e são rejeitados pelos testes de grão, em vez de receberem
desempate arbitrário.

## 3.5 Transformação e modelagem analítica

### 3.5.1 Camada Silver

A Silver foi implementada como um conjunto de *views*. Dois modelos
específicos desempacotam os JSONs das plataformas, aplicam tipagem, normalizam a
nomenclatura e tratam as estruturas de métricas próprias de cada API. Um
terceiro modelo unifica as fontes em um contrato comum, preservando a
plataforma de origem e as diferenças de significado. É nessa camada que se
aplica a seleção da última observação por entidade e dia.

As colunas equivalentes são alinhadas explicitamente, pois operações de união
por posição podem produzir trocas silenciosas quando os contratos divergem. A
equivalência entre os modelos de origem e o consumo de todos os campos extraídos
são verificados por testes. Campos sem suporte em determinada plataforma podem
receber representação estrutural compatível no modelo, mas permanecem
identificados como indisponíveis para interpretação analítica; ausência de
suporte não é evidência de desempenho igual a zero.

### 3.5.2 Camada Gold e modelo dimensional

A camada Gold foi materializada em tabelas segundo um *Snowflake Schema*,
escolhido por representar diretamente a hierarquia nativa das plataformas. A
cadeia dimensional compreende plataforma, conta, campanha, conjunto ou grupo de
anúncios e anúncio; a dimensão de tempo se liga diretamente à tabela fato. O
grão factual é definido pela combinação plataforma, conta, campanha, grupo,
anúncio e dia, equivalente a uma observação de um anúncio em uma data.

As dimensões de conta, campanha, grupo e anúncio utilizam a técnica SCD Tipo 2
para representar mudanças observadas em seus atributos (GOMES, 2014). Cada
entidade possui uma chave natural estável e uma chave substituta por versão. O
fato referencia a versão vigente na data da observação, e uma *view* canônica
resolve a travessia completa da hierarquia com as respectivas condições de
validade. Isso evita a multiplicação indevida de fatos que ocorreria se
dimensões versionadas fossem unidas apenas pela chave natural.

O SCD2 preserva o histórico que o sistema conseguiu observar, não um registro
integral de todas as alterações ocorridas nas plataformas. Em reextrações
históricas, a API pode devolver o nome atual de uma entidade também para datas
passadas. Nessa situação, não é possível reconstruir com fidelidade um atributo
histórico que a fonte deixou de fornecer, embora a observação anteriormente
capturada permaneça recuperável na Bronze. A integridade referencial da Gold é
verificada após a materialização por testes de relacionamento, unicidade e
validade temporal.

## 3.6 Tratamento semântico das métricas

### 3.6.1 Heterogeneidade entre plataformas

A unificação estrutural não foi tratada como equivalência semântica. No Meta,
o campo *conversions* foi interpretado como quantidade de *leads* no contrato
adotado, e seu custo correspondente é o CPL, calculado pela razão entre
investimento e *leads*. No Google, *conversions* mantém a definição e a
atribuição da própria plataforma, inclusive valores fracionários, e fundamenta
o CPA. Essas quantidades não foram somadas sob a denominação de “conversões
totais”.

Também foram preservadas diferenças entre cliques e visualizações de vídeo.
No Meta, *link_clicks* representa *inline link clicks*; no Google, o conceito
de *clicks* é mais amplo. As definições de visualização de vídeo também
divergem. Assim, CTR, CPC e métricas de vídeo foram interpretados por
plataforma, sem assumir homogeneidade apenas porque os campos ocupam posições
correspondentes no esquema.

Para compras do Meta, os indicadores *omni_purchase* e *purchase* não foram
somados. Adotou-se *omni_purchase* como fonte canônica e *purchase* como
alternativa quando a primeira não está disponível. A mesma prioridade foi
aplicada ao valor atribuído às compras. Valores de compra e de conversão foram
descritos como valores atribuídos pelas plataformas, e não automaticamente como
receita ou faturamento.

### 3.6.2 Result e Custo por Resultado

O Meta fornece *results* e *cost_per_result* em estruturas dinâmicas cujo
indicador depende do contexto da campanha. As formas efetivamente encontradas
foram examinadas antes da definição do contrato. O parser adotou tratamento
conservador: persistiu *result_type*, *result_count*,
*result_attribution_window* e *cost_per_result* somente quando o tipo e os
valores puderam ser reconciliados. A ausência completa dos campos foi
representada por valores nulos, e não por zero.

Um indicador declarado sem valor pode representar resultado conhecido igual a
zero, caso em que o custo e a janela permanecem nulos. Também foram observados
registros com valores e sem janela explícita, nos quais a ausência da janela é
uma informação factual. O método distinguiu a ausência neutra de evidência de
janela da ausência informativa para impedir que agregações incompatíveis fossem
tratadas como equivalentes. Quantidade positiva sem custo correspondente foi
considerada inconsistente e não recebeu custo inferido. Objetivo e estratégia
de otimização foram mantidos como contexto interno do repositório e não usados
para fabricar um tipo de resultado.

Result só foi agregado quando o tipo, a cobertura e a janela de atribuição eram
semanticamente compatíveis. O Custo por Resultado agregado foi calculado por:

\[
CPR = \frac{\sum \text{investimento}}{\sum \text{quantidade de Result}}
\]

Não se somaram nem se calcularam médias dos custos por linha. Tipos distintos,
como *Lead*, *ThruPlay*, conversa iniciada e visita ao perfil, não foram
combinados em um total global de resultados.

### 3.6.3 Reach não aditivo

O alcance fornecido pelo Meta é factual no grão de um anúncio em um dia. Ao
agregar anúncios ou datas, uma mesma pessoa pode pertencer a mais de um
conjunto. Como as fontes não disponibilizam identificadores de usuários nem as
interseções entre esses conjuntos, não é possível reconstruir corretamente o
alcance único agregado. Por essa razão, o sistema apresenta *N/A* em
agregações de negócio com mais de uma linha e não utiliza a soma de *Reach*
como estimativa. Somas dessa coluna foram admitidas apenas como verificações
técnicas de integridade, sem significado de alcance consolidado.

## 3.7 Superfície de exposição e dashboard

A camada de consumo operacional foi derivada da *view* canônica da Gold e
materializada em um arquivo CSV acompanhado de manifesto. O contrato público
v3 contém 24 colunas e as 11.326 observações factuais. Os identificadores
hierárquicos são pseudonimizados, enquanto datas e métricas permanecem
inalteradas. Os quatro campos de Result são expostos; *objective* e
*optimization_goal* permanecem restritos ao repositório interno.

A pseudonimização utiliza HMAC com chave local não versionada e domínio
separado por nível hierárquico. O exportador opera por lista explícita de
permissões: uma coluna nova ou não classificada impede a geração até que sua
destinação seja decidida. A superfície operacional não é versionada, pois
contém métricas reais pseudonimizadas e sua geração não equivale a autorização
de publicação.

O *dashboard* foi desenvolvido com Streamlit e Plotly e consome somente a
superfície tabular, sem conexão com o Data Warehouse ou com as APIs. A aplicação
oferece visão geral, filtros hierárquicos e temporais, páginas de campanhas e
anúncios, métricas específicas por plataforma e classificação relativa de
desempenho. As regras semânticas ficam em módulos independentes da interface,
de modo que a camada visual apresenta resultados calculados sem reimplementar
fórmulas.

Para execução reproduzível sem credenciais ou dados operacionais, foi criada
uma superfície sintética versionada sob o mesmo contrato v3, destinada a
testes e à demonstração de métricas, Result e classificações. Esses dados não
derivam da superfície operacional e não constituem evidência do desempenho
real.

## 3.8 Classificação relativa de desempenho

### 3.8.1 Definição empírica dos critérios

A classificação foi concebida como comparação relativa, explicável e
reproduzível, sem limiares absolutos de mercado. Antes da implementação,
analisaram-se a distribuição de campanhas por cliente, a hierarquia de anúncios
por grupo e campanha, a cobertura dos KPIs, o tamanho dos conjuntos
comparáveis, a assimetria das distribuições, os quartis, a sensibilidade a
limiares de suficiência, os casos de investimento sem resultado, o efeito da
autoinclusão no conjunto de referência, a disponibilidade de tendência e a
discordância entre CTR ou CPC e o KPI primário.

As distribuições de CPR, CPL e CPA apresentaram assimetria, motivo pelo qual
mediana e quartis foram usados como referências centrais, em vez de pressupor
normalidade ou basear a classificação na média
[REFERÊNCIA PENDENTE: estatísticas robustas e quartis]. O método não produz
*score* composto e não usa Reach, CTR, CPC, CPM, ROAS, valor de compra ou valor
de conversão para determinar o estado.

Foram definidos seis estados. “Excelente”, “Boa”, “Atenção” e “Ruim”
representam posição relativa efetivamente medida. “Dados insuficientes” indica
que existe um KPI conceitualmente aplicável, mas faltam volume, duração ou
pares válidos. “Não comparável” indica que os próprios dados não sustentam
comparação semântica, por exemplo por cobertura parcial de Result, múltiplos
tipos, janelas incompatíveis ou ausência de KPI primário. Os dois últimos
estados são neutros e não constituem sinônimo de desempenho ruim.

Para todas as entidades classificáveis, o KPI primário foi escolhido nesta
ordem: no Meta com Result válido e homogêneo, CPR; no Meta sem Result
utilizável, mas com *leads*, CPL; e no Google, CPA. Recortes Meta que misturam
linhas tipadas e ausência de Result, tipos diferentes ou janelas incompatíveis
foram considerados não comparáveis. O eixo de comparação incluiu o tipo e a
janela compatível no Meta Result, um eixo próprio para Meta CPL e um eixo
próprio para Google CPA.

A entidade avaliada foi excluída do conjunto usado para calcular sua própria
referência, procedimento *leave-one-out*. Essa exclusão impede que o valor sob
avaliação altere a mediana e os quartis que o julgam. Um par só foi aceito
quando era semanticamente compatível com o eixo avaliado e apresentava KPI
calculável, investimento positivo, pelo menos três dias ativos e denominador
igual ou superior a três. Esses requisitos de evidência foram aplicados tanto
aos pares de campanhas quanto aos pares de anúncios; as diferenças entre os
dois níveis ficaram restritas à hierarquia usada para formar os grupos de
referência.

O requisito mínimo para classificação por quartis foi investimento positivo,
ao menos três dias ativos e denominador igual ou superior a três. O denominador
corresponde a Result, *leads* ou conversões, conforme o KPI. Não foi estabelecido
limiar monetário absoluto. Como todos os KPIs são custos, valores menores
representam melhor desempenho: valores até P25 recebem “Excelente”; acima de
P25 e até P50, “Boa”; acima de P50 e até P75, “Atenção”; e acima de P75,
“Ruim”.

Entidades com investimento igual a zero são classificadas como “Dados
insuficientes” pelo gate de investimento. A regra especial é aplicada quando
há investimento positivo e o denominador é igual a zero, antes do critério
mínimo de denominador. Havendo referência válida, compara-se o investimento ao
custo mediano dos pares: abaixo de 0,5 vez a mediana, o estado é “Dados
insuficientes”; de 0,5 vez até menos de 2 vezes, “Atenção”; e a partir de 2
vezes, “Ruim”. Sem referência válida, o estado permanece “Dados insuficientes”.
Essa regra evita tanto premiar quanto condenar automaticamente uma entidade
apenas porque a divisão por zero não produz um custo.

### 3.8.2 Classificação de campanhas

Para campanhas, a primeira referência é formada por outras campanhas do mesmo
cliente e do mesmo eixo semântico, exigindo-se pelo menos três pares
elegíveis. Quando esse grupo é insuficiente, as campanhas Meta podem usar um
segundo nível com pelo menos cinco outras campanhas do mesmo eixo no portfólio.
No eixo de Result, isso preserva tipo e janela compatível; no eixo de CPL,
apenas campanhas do mesmo eixo CPL são aceitas. Campanhas Google não utilizam
comparação entre clientes, pois o conjunto disponível não contém eixo semântico
suficiente para distinguir objetivos de negócio sob a mesma métrica de
conversão.

Além do estado, a classificação informa KPI, valor observado, quartis,
mediana, origem e tamanho do conjunto de referência, diferença percentual em
relação à mediana e motivo estruturado. A tendência é complementar e não altera
o estado. Ela compara o período selecionado ao período imediatamente anterior
de mesma duração, somente quando o denominador é igual ou superior a dez nos
dois intervalos. Variações inferiores a 15% em módulo são tratadas como
estáveis; reduções iguais ou superiores a 15% no custo indicam melhora, e
aumentos iguais ou superiores a 15% indicam piora.

### 3.8.3 Classificação de anúncios

Os anúncios utilizam os mesmos KPIs, critérios de suficiência, quartis e regra
de investimento sem resultado, mas adotam uma hierarquia de referência mais
local. O primeiro nível reúne outros anúncios do mesmo grupo de anúncios e do
mesmo eixo, com pelo menos três pares elegíveis. Se esse conjunto for
insuficiente, o segundo nível reúne anúncios da mesma campanha e do mesmo eixo,
também com no mínimo três pares. O benchmark nunca atravessa campanhas, contas
ou o portfólio.

Filtros de campanha, grupo ou anúncio restringem apenas as entidades
apresentadas; o universo necessário à formação dos pares é preservado. Essa
separação impede que um filtro visual altere a referência estatística do item
selecionado. Não foi adotada tendência no nível de anúncio, pois a análise
empírica encontrou baixa cobertura temporal e maior volatilidade nesse grão. A
baixa proporção de anúncios classificados é aceita como consequência do método
conservador, e os critérios não são relaxados apenas para aumentar a quantidade
de rótulos.

## 3.9 Estratégia de validação

A validação foi organizada em níveis complementares. Testes unitários em
Python verificaram funções de extração, manifestos, carga, contratos,
tratamento semântico, pseudonimização, classificação e componentes do
*dashboard*. Testes da aplicação confirmaram filtros, fórmulas, mensagens,
preservação do universo de comparação e renderização nos modos operacional e
sintético.

No Data Warehouse, testes do dbt verificaram unicidade, não nulidade,
integridade referencial, grão factual, coerência dos contratos de estágio,
validade temporal do SCD2, ausência de inflação nos relacionamentos e
tratamento de campos extraídos. A execução conjunta da materialização e dos
testes impediu que uma camada analítica reprovada fosse considerada concluída.

Um conjunto de referência, denominado Golden, registrou agregados esperados do
estado aprovado. A verificação de paridade comparou o Data Warehouse atual a
esse conjunto por chaves naturais e sem tolerância numérica, incluindo
cobertura e distribuição de Result. Em complemento, um auditor independente
comparou a superfície de exposição com o Data Warehouse e pôde validar o
artefato também em modo offline. Essa separação reduz o risco de um produtor
validar a própria implementação.

A estratégia incluiu ainda testes de segurança e pseudonimização, verificações
pontuais contra os gerenciadores das plataformas, quando aplicável, análise
manual de revisões entre extrações e validação visual do *dashboard*. O
conjunto sintético foi usado para reprodução e testes da interface, enquanto
as conclusões sobre os dados foram derivadas da superfície operacional
pseudonimizada.

## 3.10 Segurança, privacidade e reprodutibilidade

Credenciais, tokens, identificadores reais e a chave de pseudonimização foram
mantidos fora dos arquivos versionados. A configuração foi fornecida ao
ambiente por variáveis locais, e os registros de execução passaram por
sanitização para impedir a reprodução acidental de segredos presentes em
mensagens de bibliotecas externas. O acesso às plataformas foi somente de
leitura.

A fronteira de privacidade foi estabelecida na exposição, e não nas camadas
internas do pipeline. O repositório analítico conserva os identificadores
necessários à hierarquia, ao grão e ao histórico; antes do consumo externo,
esses identificadores são substituídos por pseudônimos determinísticos. A
pseudonimização reduz a associação direta com clientes, mas não foi descrita
como anonimização absoluta (PAVÃO et al., 2026). Nomes, identificadores
externos e atributos capazes de revelar clientes foram excluídos da superfície
por lista de permissão e verificados por auditorias automáticas.

A reprodutibilidade foi apoiada pela containerização do ambiente, pelo
versionamento do código e dos modelos, pelos manifestos dos lotes, pelo
contrato explícito da superfície, pelo Golden e pela demonstração sintética
determinística. A superfície operacional permaneceu fora do Git; a demo
sintética permite executar a aplicação sem Data Warehouse, credenciais ou
dados reais.

## 3.11 Limitações metodológicas

O histórico reconstruído depende do que as APIs ainda disponibilizam no
momento da consulta. Contas temporariamente indisponíveis ou atualmente não
habilitadas podem produzir lacunas que não devem ser interpretadas como zero.
Do mesmo modo, o SCD2 representa atributos observados pelo pipeline e pode não
recuperar uma versão nominal que a fonte substituiu pelo estado atual.

As diferenças de definição entre Meta e Google limitam agregações
multiplataforma. Reach é não aditivo; cliques, conversões e visualizações de
vídeo não são necessariamente equivalentes. Result foi formalizado a partir
das estruturas empiricamente observadas no Meta e possui cobertura parcial no
histórico; formatos futuros não reconhecidos exigem nova avaliação, em vez de
inferência automática.

A classificação de desempenho é relativa ao conjunto de pares disponível no
período e não estabelece causalidade nem padrão universal de mercado. Seus
benchmarks dependem da amostra observada, e a exigência de comparabilidade
reduz especialmente a cobertura no nível de anúncio. A tendência foi restrita
às campanhas com volume suficiente e não foi aplicada a anúncios. Revisões
retroativas das plataformas podem modificar valores já observados, embora a
preservação *append-only* mantenha a rastreabilidade dessas mudanças.

Por fim, as validações atestam os contratos e invariantes exercitados, mas não
eliminam limitações externas de disponibilidade, cota das APIs ou
generalização. Quando considerado, o experimento de desempenho do banco foi
realizado em um único ambiente de hardware, e a demo sintética serviu apenas à
reprodução funcional, não à comprovação dos resultados reais.
