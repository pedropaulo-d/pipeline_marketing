---
title: Plano de refatoração
data: 2026-08-06
tags:
  - tcc
  - refatoracao
status: em execucao — Fase 0 concluida
---

# Plano de refatoração

Levantamento feito em 06/08/2026 sobre a árvore pós-remoção do ETL (commit
`e4577a9`). Cada fase é independente e verificável isoladamente.

---

## ▶️ Retomada — leia isto primeiro

**Onde paramos:** Fase 8 concluída em 07/08/2026, **ainda não commitada**.
Commitadas no mesmo dia: Fases 1 a 7 (`b5f8f40`, `101165a`, `a05c6b6`,
`20c8dc3`, `9382683`, `2b20c99`, `ad02ae9`); Fase 0 em 06/08 (`18b85df`).
**Só resta a Fase 9, que é opcional.**

⚠️ A Fase 2 mexeu no Dockerfile — quem clonar ou trocar de branch precisa de
`docker compose build etl_app` antes de rodar qualquer coisa.

**Primeiro comando ao retomar** — confirma que o armazém continua no estado
congelado antes de qualquer mudança:

```bash
docker compose up -d db
docker compose run --rm etl_app python scripts/verificar_paridade.py verificar
```

Esperado: `PARIDADE OK — 1677 linhas no fato` (e 76 testes dbt desde a Fase 4).
Se divergir, **investigue antes de refatorar** — ou alguém rodou uma extração nova (legítimo: recongele de
propósito), ou algo mudou sozinho.

**Próximo passo:** decidir se a Fase 9 entra. Ela é a única do plano que
**acrescenta conceito** em vez de remover duplicação — um teste que confronte
os campos extraídos com os campos lidos pela silver. Não é dívida existente;
é cobertura nova. Se ficar de fora, o plano está encerrado.

**Bloqueios:** nenhum. D1 e D2 foram fechadas em 07/08/2026 (ver "Decisões
fechadas", no fim deste documento) — todas as nove fases estão liberadas.

**Contexto que não está no código:** o dado real de 01–04/08 vive em
`temp_meta_raw.json` / `temp_google_raw.json` na raiz, que são gitignored. São
eles que permitem `--skip-extract`. Se sumirem, o replay do Python se perde
(a bronze no banco continua íntegra e `dbt build` sozinho reconstrói silver e
gold). Para testar código sem eles, use `scripts/gerar_fixture.py`.

---

## O diagnóstico

O código não está feio: o SQL tem CTEs nomeadas, as docstrings seguem o padrão
Google, os comentários explicam o porquê. O problema é outro e é mais sério —
**duplicação conceitual**: a mesma decisão escrita em vários lugares, que
precisam ser mantidos em sincronia manualmente.

É exatamente a família dos três bugs encontrados em 06/08. Nenhum deles foi
erro de sintaxe; todos foram uma verdade registrada num lugar e esquecida em
outro. Refatorar aqui não é estética, é **remover a possibilidade de o erro
acontecer de novo**.

### Regra que vale para o plano inteiro

⚠️ **Refatoração não pode mudar número.** O critério de sucesso de cada fase é
o pipeline produzir exatamente os mesmos agregados de antes. Este repositório
já demonstrou três vezes que "os testes passaram" não é evidência de correção
(seções 5.1, 5.7 e 5.9 das notas do TCC). A Fase 0 existe para isso.

---

## Fase 0 — Rede de segurança

**Antes de tocar em qualquer linha.** Hoje não existe nenhum teste de Python no
repositório; toda a verificação é do dbt, que cobre o dado depois de
transformado, não o código que o transporta.

✅ **Concluída em 06/08/2026.**

| Item | Entregue |
|---|---|
| 0.1 | `tests/golden/agregados_gold.json` — agregados canônicos por plataforma e dia, totais lidos direto do fato, contagens estruturais e a contagem da travessia |
| 0.2 | `scripts/verificar_paridade.py congelar` / `verificar`. Sai com código 1 em qualquer divergência |
| 0.3 | `scripts/gerar_fixture.py` — dados brutos **sintéticos** no formato das duas APIs |

Depois de cada fase: `verificar_paridade.py verificar` tem de sair OK. Sem
isso o resto do plano é chute.

> Sem a Fase 0, uma refatoração que troque duas métricas de lugar passa nos 75
> testes do dbt exatamente como o bug do `union all` passou nos 65.

### Mudança em relação ao plano original

O item 0.3 previa commitar uma **amostra pseudonimizada** do dado real. Isso
conflita com a restrição do projeto: a agência ainda não deu autorização por
escrito para publicar recorte nenhum, e pseudonimizado continua sendo dado
derivado de cliente. A fixture passou a ser **sintética e gerada por código** —
o que entra no repositório é um gerador revisável, não dado de terceiro, e a
autorização deixa de ser pré-requisito.

A fixture não é dado bonito: cada peculiaridade existe porque já causou bug ou
está protegida por teste — arrays de `actions` do Meta, um registro sem a
chave `actions`, conversões fracionadas do Google, um registro sem
`video_trueview_views` (formato anterior a 06/08), uma campanha renomeada no
último dia (exercita o SCD Tipo 2 inteiro) e um anúncio que some depois do
primeiro dia.

### O que a Fase 0 já pegou

Três defeitos apareceram durante a própria construção da rede de segurança:

1. **O `.gitignore` engoliria a fixture.** O padrão `temp_meta_raw.json` não
   estava ancorado, então casava também `tests/fixtures/temp_meta_raw.json`.
   A fixture seria excluída do commit em silêncio. Corrigido ancorando na raiz
   (`/temp_meta_raw.json`), o que também torna a regra mais correta: esses
   arquivos só existem na raiz.
2. **A fixture reciclava IDs de campanha entre contas**, coisa que API real
   nunca faz. Corrigido; os identificadores passaram a ser únicos por
   (conta, campanha, anúncio) dentro de cada plataforma.
3. **A colisão de ID entre plataformas não estava sendo exercitada.** O ID que
   eu havia fixado no lado do Meta não batia com o que a expressão do Google
   gerava — porque a regra de formação estava escrita duas vezes. Corrigido
   extraindo `id_anuncio_google()`, usada pelos dois lados. É o próprio tema
   deste plano se manifestando dentro dele.

### Validações executadas

- Controle negativo: adulterar **um centavo** no golden faz o `verificar`
  acusar a divergência e sair com código 1.
- A fixture é determinística: duas gerações produzem arquivos idênticos.
- A fixture atravessa o pipeline inteiro num banco descartável — 75 testes dbt
  passando — e exercita o que deveria: 2 versões SCD2 da campanha renomeada,
  conversões do Google preservadas fracionadas, `video_views` zerado no dia de
  formato antigo e populado nos demais, e o mesmo `external_id` produzindo duas
  entidades distintas, uma em cada plataforma.

### Pendência herdada

O `dbt build` emite `MissingArgumentsPropertyInGenericTestDeprecation`. Não
afeta resultado nem foi introduzido aqui, mas vale endereçar antes que vire
erro numa versão futura do dbt.

---

## Fase 1 — "Plataforma" declarada em 6 lugares

✅ **Concluída em 07/08/2026.** Paridade OK — 1677 linhas, 75 testes dbt
passando.

O conceito mais central do sistema está espalhado. Adicionar uma terceira
plataforma (ou renomear um arquivo temporário) exige seis edições coordenadas,
e esquecer uma delas falha em silêncio.

| Onde | O que declara |
|---|---|
| `config.py:22` `_REQUIRED_VARS` | Nomes dos grupos e credenciais de cada plataforma |
| `main.py:34` `PLATFORMS` | Chave de CLI → nome do grupo de credenciais |
| `main.py:40` `BRONZE_SOURCES` | Chave de CLI → identificador da fonte na bronze |
| `main.py:162-172` | `if "meta" in platforms` / `if "google" in platforms` — qual módulo chamar |
| `loaders/bronze_loader.py:39` `SOURCES` | Identificador → caminho do arquivo bruto + campo de data |
| `extractors/*.py` `OUTPUT_PATH` | O mesmo caminho de arquivo, declarado de novo |

**O acoplamento silencioso:** o extrator escreve em `temp_meta_raw.json`
(`meta_ads.py:43`) e o loader lê o mesmo caminho (`bronze_loader.py:41`), sem
nenhuma ligação entre as duas declarações. Renomear de um lado produz "arquivo
bruto ausente, fonte ignorada" — um `warning`, não um erro. O pipeline
terminaria com sucesso tendo carregado nada.

**Alvo:** um registro único (`plataformas.py` ou dataclass em `config.py`) com
uma entrada por plataforma: chave de CLI, grupo de credenciais, fonte da
bronze, arquivo bruto, campo de data, função de extração. Todo o resto deriva
dele — inclusive o `--platforms` do argparse, que passa a validar contra o
registro.

Ganho: adicionar TikTok Ads vira **uma** entrada, e o acoplamento
extrator↔loader deixa de existir porque os dois passam a ler o mesmo lugar.

### O que foi entregue

`plataformas.py` na raiz, com a dataclass congelada `Plataforma` e o dicionário
`PLATAFORMAS`. Cada entrada declara chave de CLI, nome (que é também o grupo de
credenciais), fonte da bronze, arquivo bruto, campo de data, módulo do extrator
e as variáveis de ambiente obrigatórias. Os seis pontos passaram a derivar dele:

| Antes | Depois |
|---|---|
| `config._REQUIRED_VARS` com as 9 variáveis escritas à mão | Derivado por comprehension sobre o registro |
| `main.PLATFORMS` | Removido — `PLATAFORMAS[p].nome` |
| `main.BRONZE_SOURCES` | Removido — `PLATAFORMAS[p].fonte_bronze` |
| `if "meta" in platforms` / `if "google" in platforms` | Laço sobre o registro |
| `bronze_loader.SOURCES` | Removido — `por_fonte(source)` |
| `OUTPUT_PATH` em cada extrator | `PLATAFORMAS["meta"].arquivo_bruto` |

Dois detalhes que exigiram cuidado:

1. **O import tardio do SDK precisava sobreviver.** O registro guarda o módulo
   do extrator como *string* e `Plataforma.extrair()` resolve com
   `importlib.import_module`. Se guardasse a função, importar o registro
   carregaria os dois SDKs, e uma execução `--platforms meta` pagaria o custo
   de carregar o SDK do Google. Verificado: importar `plataformas` não traz
   `facebook_business` nem `google.ads` para `sys.modules`.
2. **A ajuda da CLI também derivou.** O texto do `--skip-extract` listava os
   nomes dos arquivos brutos e o do `--platforms` listava as plataformas
   aceitas — duas cópias a mais, que agora saem do registro. Renomear um
   arquivo bruto atualiza o `--help` junto.

### Verificação

- O extrator e o loader apontam para o mesmo arquivo — afirmado por asserção,
  não por leitura: `meta_ads.OUTPUT_PATH == PLATAFORMAS["meta"].arquivo_bruto`.
  É o acoplamento silencioso fechado: existe **uma** declaração do caminho.
- `--platforms tiktok` sai com código 2 e mensagem listando os valores aceitos,
  vindos do registro.
- `main.py --skip-extract` completo: bronze recarregada, `dbt build` com 75
  testes passando.
- `verificar_paridade.py verificar` → `PARIDADE OK — 1677 linhas`.

### Pendência empurrada para a Fase 2

`scripts/anonimizar_dataset.py:256` e `scripts/gerar_fixture.py:244` ainda
montam os nomes dos arquivos brutos à mão. Ligá-los ao registro hoje exigiria
um **quarto** `sys.path.insert` — justamente o que a Fase 2 vai remover. Fica
para depois da instalação editável, quando `import plataformas` passa a
funcionar de qualquer diretório sem gambiarra.

---

## Fase 2 — Infraestrutura transversal

✅ **Concluída em 07/08/2026.** Paridade OK — 1677 linhas, 75 testes dbt
passando.

| Item | Situação | Alvo |
|---|---|---|
| 2.1 | `logging.basicConfig()` em 4 módulos (`main.py:23`, `meta_ads.py:18`, `google_ads.py:15`, `bronze_loader.py:29`). Só a primeira chamada tem efeito — as outras três são no-op silencioso | Uma `configurar_logging()` em `config.py`, chamada pelos entrypoints |
| 2.2 | `load_dotenv()` em 4 módulos, no import | Uma vez, no entrypoint. `config.py` já faz no import dele |
| 2.3 | `sys.path.insert` em `bronze_loader.py:27`, `benchmark/executar.py:43` e `scripts/verificar_paridade.py:45` | ✅ `pyproject.toml` + `pip install -e .` no Dockerfile (D1) |
| 2.4 | Imports locais gratuitos: `config.py:70` (urllib), `main.py:202-203` (os, subprocess) | Subir para o topo. **Manter** os lazy dos SDKs em `main.py:163,169` — evitam carregar o SDK do Google numa execução só do Meta |

O item 2.3 era a **armadilha nº 8 do CLAUDE.md**. Foi eliminada.

### O que foi entregue

**2.3 — `pyproject.toml` + instalação editável.** O Dockerfile ganhou
`RUN pip install --no-cache-dir --no-deps -e .` depois do `COPY . .`. O
`pyproject.toml` declara só o necessário para o projeto ser importável
(`py-modules = ["config", "plataformas"]`, `packages = ["extractors",
"loaders", "benchmark"]`); as dependências continuam em `requirements.txt`,
instalado numa camada anterior — mexer no código não invalida o cache do pip.
`main` ficou de fora de propósito: é entrypoint, não biblioteca.

Os três `sys.path.insert` saíram (`loaders/bronze_loader.py`,
`scripts/verificar_paridade.py`, `benchmark/executar.py`), junto com os
`# noqa: E402` que existiam só para calar o linter sobre imports fora do topo.

**2.1 — `configurar_logging()` em `config.py`.** Os quatro `basicConfig` no
import viraram uma função chamada pelos entrypoints (`main.main()`, e os
`main()` dos dois extratores e do loader). O motivo importa: `basicConfig` é
no-op se o logging raiz já tem handler, então três das quatro chamadas não
faziam nada e **qual delas vencia dependia da ordem de importação**.

**2.2 — `load_dotenv()` uma vez.** Ficou só o de `config.py`, que roda no
import. Como todo módulo que precisa de variável de ambiente importa `config`,
importá-lo é o que garante o `.env` carregado. Os `load_dotenv(ENV_PATH)` de
`oauth_manual.py` e `generate_google_refresh_token.py` **não** foram tocados:
são outra coisa — apontam para um arquivo específico para rotacionar o refresh
token, e pertencem à Fase 8.

**2.4 — Imports locais.** `urllib.parse` em `config.dbt_env`, `os`/`subprocess`
e `config.dbt_env` em `main.run_dbt`, e `create_engine`/`get_db_url` em
`bronze_loader.get_engine` subiram para o topo. Os imports tardios dos SDKs
continuam tardios — hoje moram em `Plataforma.extrair()`.

**Pendência da Fase 1, fechada aqui.** Com a raiz importável,
`scripts/anonimizar_dataset.py` e `scripts/gerar_fixture.py` passaram a tirar
os nomes dos arquivos brutos do registro em vez de montá-los à mão.

### A armadilha que entrou no lugar da nº 8

A instalação editável do setuptools grava o mapeamento dos **módulos de topo**
em site-packages no momento do build. Criar `foo.py` na raiz e importá-lo sem
`docker compose build etl_app` dá `ModuleNotFoundError` mesmo com o arquivo
presente, porque o bind mount não atualiza esse mapeamento. Arquivo novo dentro
de pacote já declarado (`extractors/`, `loaders/`, `benchmark/`) funciona sem
rebuild — aí o mapeamento é por diretório. Medido nos dois casos, não deduzido.
É um custo menor que o anterior: falha alto e claro no primeiro import, em vez
de silenciosamente.

### Verificação

- `import config, plataformas, loaders, extractors, benchmark` a partir de
  `/tmp`, sem nenhuma manipulação de `sys.path`.
- `python /app/scripts/verificar_paridade.py` rodando com `-w /tmp` — o caso
  que motivava o `sys.path.insert`.
- `grep -rn "sys.path" --include=*.py .` → nenhum resultado.
- Fixture regenerada: `git diff tests/fixtures/` vazio, determinismo intacto.
- `main.py --skip-extract` completo, 75 testes dbt, e o formato de log
  configurado aparecendo na saída.
- `verificar_paridade.py verificar` → `PARIDADE OK — 1677 linhas`.

---

## Fase 3 — Extratores: contrato comum

✅ **Concluída em 07/08/2026.** Paridade OK — 1677 linhas, 75 testes dbt
passando.

`meta_ads.py` e `google_ads.py` duplicam a estrutura inteira: `save_raw`,
`_parse_args`, `main`, e o esqueleto de `run` (init → discover → loop →
save). São ~50 linhas quase idênticas em cada.

⚠️ **Não unificar demais.** As duas APIs são genuinamente diferentes —
paginação por cursor no Meta, GAQL no Google. `discover_accounts` e
`extract_daily_ads` devem continuar separadas. O alvo é só a casca:
`save_raw`, o CLI e o laço.

**Validação de credenciais duplicada em três lugares:**

- `config.py:22` lista 4 variáveis do Meta e 5 do Google
- `meta_ads.py:53-60` verifica 3 delas (`META_BUSINESS_ID` fica de fora, é
  checada separadamente em `discover_accounts:102`)
- `google_ads.py:65-76` verifica as 5 de novo

Três listas para manter em sincronia. Alvo: `config.validate_env()` é a única
fonte; os extratores chamam e confiam.

### O que foi entregue

`extractors/comum.py`, com a casca e só a casca:

| Função | Substitui |
|---|---|
| `salvar_bruto(plataforma, linhas)` | os dois `save_raw`, que só diferiam no `OUTPUT_PATH` |
| `executar_extracao(plataforma, descobrir_contas, extrair_conta, ...)` | o esqueleto de `run`: percorrer contas, acumular, salvar, logar o total |
| `_parse_args(plataforma)` | os dois `_parse_args`, que só diferiam na descrição |
| `executar_cli(plataforma, run)` | os dois `main()` |

Cada extrator ficou com o que é genuinamente seu — `init`, `discover_accounts`,
`extract_daily_ads` — mais um `run` que valida, inicializa e delega:

```python
def run(start_date: str, end_date: str) -> int:
    validate_env(groups=[PLATAFORMA.nome])
    client = init_client()
    return executar_extracao(
        PLATAFORMA,
        descobrir_contas=partial(discover_accounts, client),
        extrair_conta=partial(extract_daily_ads, client),
        start_date=start_date, end_date=end_date,
    )
```

O `client` do Google é o único estado que a casca não conhece. `functools.partial`
o fixa e devolve exatamente as assinaturas que `executar_extracao` espera —
alternativa a passar o client para dentro da casca, que a obrigaria a saber que
uma das duas plataformas tem client e a outra não.

**Validação de credenciais.** As três listas viraram uma: `validate_env` é
chamada no início de cada `run` e os `init` passaram a confiar. Os `if not
all([...])` e o `missing = [v for v in required...]` saíram, junto com a lista
de 5 variáveis repetida em `google_ads.init_client`. Ganho colateral: a
mensagem agora nomeia **todas** as variáveis ausentes de uma vez, com o grupo
de cada uma, em vez de estourar na primeira.

### O que deliberadamente não foi unificado

`discover_accounts` e `extract_daily_ads` continuam separadas. O Meta pagina por
cursor sobre `owned` + `client` e filtra por status de conta; o Google roda GAQL
sobre `customer_client` no MCC. Uma função só para os dois casos precisaria de
um `if plataforma` dentro — que é a duplicação disfarçada de abstração.

### Verificação

Como exercitar `run` de verdade custaria uma chamada real de API (e
sobrescreveria os arquivos brutos que sustentam o `--skip-extract`), a casca foi
testada com dublês:

- `executar_extracao` com 2 contas falsas: confere as 4 chamadas de
  `extrair_conta` com os argumentos certos, o acúmulo e o conteúdo gravado.
- `meta_ads.run`: a ordem observada é `init → discover → extract:111 →
  extract:222`, com o resultado no caminho do registro.
- `google_ads.run`: o mesmo objeto `client` chega intacto a `discover_accounts`
  **e** a `extract_daily_ads` — o que valida o `partial`.
- `Plataforma.extrair()` delega para o `run` do módulo resolvido por importlib.
- Credencial ausente (`META_ACCESS_TOKEN=`) → `SystemExit(1)` com
  `- META_ACCESS_TOKEN (Meta Ads)`.
- `python -m extractors.meta_ads --help` e o do Google seguem funcionando.
- `main.py --skip-extract`, 75 testes dbt, `PARIDADE OK — 1677 linhas`.

**Sobre o tamanho:** os dois extratores perderam 118 linhas e ganharam 46; a
casca comum tem 103. O total ficou praticamente igual — o ganho não é volume, é
existir **uma** definição de cada coisa em vez de duas que podem divergir.

---

## Fase 4 — Silver: deduplicação duplicada

✅ **Concluída em 07/08/2026.** Paridade OK — 1677 linhas, agora com **76**
testes dbt.

`stg_meta_ads.sql:14-36` e `stg_google_ads.sql:19-41` contêm o **mesmo bloco**
`bruto` + `ultimo_snapshot`, palavra por palavra, mudando só o valor de
`where source =`.

Alvo: macro `ultimo_snapshot(fonte)`. Além de encurtar, fecha a porta para os
dois modelos divergirem — que é a categoria exata do bug do `union all`
(armadilha nº 5).

**Guarda a acrescentar:** um teste que afirme que os dois modelos de staging
expõem os mesmos nomes de coluna, na mesma ordem. Hoje a proteção é um
comentário em `stg_ads_unified.sql:13-17` pedindo atenção humana.

### O que foi entregue

**Macro `ultimo_snapshot(fonte)`** (`dbt/macros/ultimo_snapshot.sql`). Devolve
um `select` completo, para ser usado como corpo de CTE — assim o modelo mantém
o nome da CTE e o resto dele não mudou:

```sql
with ultimo_snapshot as (
    {{ ultimo_snapshot('meta_ads') }}
)
```

**Teste `assert_staging_mesmo_contrato`.** Compara `information_schema.columns`
dos dois modelos com `full outer join` por nome e falha quando a posição
diverge — o que cobre de uma vez coluna faltando de um lado, coluna renomeada
num só e ordem trocada.

### Um achado durante a fase

**Os dois modelos já estavam com as métricas em ordens diferentes.** No Meta,
`reach` vinha logo após `link_clicks`; no Google, depois de `video_views`. Não
causava erro porque `stg_ads_unified` lista as colunas explicitamente por nome
— mas essa proteção é uma convenção, não um contrato: bastaria alguém
simplificar para `select *`, que parece uma limpeza inofensiva, para trocar
métricas de lugar em silêncio.

Isso mudou o item em relação ao plano: em vez de só escrever o teste, foi
preciso **primeiro alinhar a ordem** de `stg_meta_ads` à de `stg_google_ads` e
então afirmá-la. As duas colunas ficaram comentadas nos dois modelos explicando
que a ordem é intencional e verificada.

Alternativa considerada e descartada: testar apenas o *conjunto* de nomes,
ignorando a ordem, já que hoje ela não afeta o resultado. Ficaria um teste que
não protege contra a armadilha nº 5 — que é sobre posição.

### Verificação

- 76 testes dbt passando (75 + o novo).
- **Controle negativo:** devolver `reach` à posição antiga em `stg_meta_ads` faz
  `assert_staging_mesmo_contrato` acusar **4 divergências** (`reach`,
  `conversions`, `conversion_value`, `video_views` — todas deslocadas) e o
  `dbt build` sair com erro. Revertido em seguida.
- `verificar_paridade.py verificar` → `PARIDADE OK — 1677 linhas`. A macro e a
  reordenação não mudaram um centavo, que é o esperado: `stg_ads_unified`
  seleciona por nome.

---

## Fase 5 — Gold: derivação de chave duplicada

✅ **Concluída em 07/08/2026.** Paridade OK — 1677 linhas, 76 testes dbt. O item
5.3 mudou de forma: ver abaixo.

| Item | Onde | Problema |
|---|---|---|
| 5.1 | `dim_tempo.sql:16` e `fato_metricas.sql:26` | `md5(data::text)` escrito nos dois. Mudar a fórmula da chave num só lugar quebra o join sem erro de sintaxe |
| 5.2 | `assert_scd2_sem_sobreposicao.sql:11` e `assert_scd2_uma_versao_atual.sql:10` | A lista `dimensoes` hardcoded nos dois testes |
| 5.3 | `profiles.yml:15` | `schema: public` sobrou do ETL. Só é usado quando não há schema customizado — hoje, nunca |

Alvos: macro `chave_tempo(coluna)` para 5.1; `vars:` no `dbt_project.yml` para
5.2; remover 5.3.

### O que foi entregue

**5.1 — macro `chave_tempo(coluna)`.** Usada por `dim_tempo` (`chave_tempo('data')`)
e por `fato_metricas` (`chave_tempo('u.data')`). Confirmado no SQL compilado que
os dois lados produzem a mesma expressão: `md5(data::text)` e `md5(u.data::text)`.
A partir daqui a fórmula da chave não tem como divergir entre quem a gera e quem
aponta para ela.

**5.2 — var `dimensoes_scd2` no `dbt_project.yml`.** A lista `[modelo, chave
natural]` das quatro dimensões versionadas saiu de dentro dos dois testes.
Dimensão nova entra num lugar só e passa a ser coberta pelos dois.

**5.3 — o item não era executável como escrito.** `schema` é **propriedade
obrigatória** do adapter Postgres: removê-lo do `profiles.yml` faz o dbt abortar
com `Credentials in profile "tcc_marketing", target "dev" invalid: 'schema' is a
required property`. Verificado, não deduzido.

Em vez de manter `public`, o valor virou `sem_schema_customizado`. O raciocínio:
o campo é um fallback que hoje nunca é usado — todo modelo declara `+schema` e o
override de `generate_schema_name` devolve o nome exato. Mas se um modelo futuro
esquecer o `+schema`, cair em `public` seria **silencioso**, porque o schema
existe e ainda guarda a tabela do benchmark; cair num nome obviamente errado
torna o objeto órfão visível de imediato. Trocou-se uma remoção impossível por
uma melhoria real na forma de falhar.

### Verificação

- 76 testes dbt passando.
- **Controle negativo da var:** removendo `dim_anuncio` de `dimensoes_scd2`, o
  SQL compilado de `assert_scd2_uma_versao_atual` passa a cobrir só três
  dimensões; restaurando, volta a cobrir as quatro. (Primeira tentativa deste
  controle usou `dbt parse`, que só monta o manifesto e não regrava o SQL
  compilado — o arquivo lido era do build anterior. Refeito com `dbt compile`.)
- Nenhum schema órfão criado no banco: continuam apenas `bronze`, `silver`,
  `gold` e `public`.
- `verificar_paridade.py verificar` → `PARIDADE OK — 1677 linhas`.

---

## Fase 6 — A travessia da hierarquia (a lição dos 7,8%)

✅ **Concluída em 07/08/2026.** Paridade OK — 1677 linhas, agora com **82**
testes dbt.

A travessia correta das 5 dimensões, com a cláusula de validade em cada nível,
está escrita **4 vezes**: três em `queries_demo.sql` (queries 2, 3 e 6) e uma
em `assert_join_dimensional_nao_infla.sql`. Todo consumidor futuro precisa
lembrar de escrevê-la certa — e já sabemos o que acontece quando alguém
esquece: 7,8% de inflação sem nenhum sinal de erro.

**Alvo:** um modelo `gold.vw_metricas_completas` (view) que faz a travessia uma
vez, corretamente, expondo fato + nomes de toda a hierarquia já resolvidos na
versão vigente. Consumidores passam a fazer `select ... from
vw_metricas_completas group by plataforma` e **não têm como errar**.

É a melhor refatoração disponível no repositório: transforma uma armadilha
documentada em erro impossível. Também é a mais defensável na banca — o
argumento "documentei a pegadinha" é fraco perto de "tornei o caminho errado
inacessível". Decidida como view em 07/08/2026 (D2, fechada).

### O que foi entregue

`dbt/models/gold/vw_metricas_completas.sql`, materializada como view. Expõe o
fato com tempo, hierarquia (chave natural **e** nome, em cada nível) e as 9
métricas, no mesmo grão — 1 anúncio × 1 dia.

Consumidores migrados:

| Onde | Antes | Depois |
|---|---|---|
| `queries_demo.sql` 2, 3 e 6 | 6 joins cada, 4 com cláusula de validade | `from gold.vw_metricas_completas` |
| `assert_join_dimensional_nao_infla` | reimplementava a travessia e verificava **a própria cópia** | verifica a view, que é o que os consumidores usam |

O teste mudou de alvo, e isso é mais do que cosmético: antes ele afirmava que
*uma* travessia estava correta enquanto as outras três seguiam sem guarda.
Agora existe uma travessia e é ela que o teste protege.

### A exceção deliberada

`scripts/verificar_paridade.py` **continua com a travessia escrita à mão**, e
isso é intencional — está comentado no arquivo para ninguém "consertar".

Ele é o oráculo da rede de segurança: o valor dele está em ser uma segunda
implementação, independente, que precisa concordar com a primeira. Se lesse a
view, um erro na view viraria um erro no verificador, a divergência deixaria de
ser detectável e o golden passaria a validar a si mesmo. É o único lugar do
repositório onde duplicar é o certo.

### Verificação

- A view reproduz a travessia manual **exatamente**: `except` nos dois sentidos
  sobre os agregados por plataforma e dia → **0 divergências**. 1677 linhas na
  view, 1677 no fato, R$ 20.216,73 de investimento total — o valor correto, não
  o inflado de R$ 21.795,17.
- 82 testes dbt (76 + 6 do contrato da view no `_gold.yml`).
- `queries_demo.sql` roda inteiro. A saída da query 3 foi comparada linha a
  linha com a versão anterior: **idêntica**.
- `PARIDADE OK — 1677 linhas`.

### Um ajuste de rota durante a fase

Na primeira escrita, a query 3 passou a agrupar por `campanha_nk` em vez de
pelo nome — tecnicamente melhor, porque consolida as versões de uma campanha
renomeada numa linha só. Mas isso **muda a saída de uma query de demonstração**
que pode estar citada na monografia, e a regra da refatoração é não mudar
número. Revertido para o agrupamento por nome, com o critério alternativo
registrado em comentário. A troca de fonte para a view ficou sendo a única
mudança.

---

## Fase 7 — `main.py`: orquestração

✅ **Concluída em 07/08/2026.** Paridade OK — 1677 linhas, 82 testes dbt.

| Item | Onde | Problema |
|---|---|---|
| 7.1 | `main.py:250-286` | Três blocos `try/except` de forma idêntica: chama, loga "FALHA NA X", `sys.exit(1)`. Alvo: helper `executar_etapa(nome, funcao)` |
| 7.2 | `run_extraction:157`, `run_bronze:222`, `run_dbt:208` | Os rótulos `ETAPA 1/3`, `2/3`, `3/3` hardcoded em três funções. Adicionar uma etapa exige renumerar tudo à mão |
| 7.3 | `main.py:73` | `yesterday` recalculado no parse; `meta_ads.py:209` e `google_ads.py:216` recalculam o mesmo default |

### O que foi entregue

**7.2 — registro `ETAPAS`.** Uma tupla com as três etapas na ordem de execução,
desempacotada em constantes (`ETAPA_EXTRACAO`, `ETAPA_BRONZE`, `ETAPA_DBT`). O
helper `_cabecalho` deriva a numeração dela: `ETAPA {posicao}/{len(ETAPAS)}`.
Acrescentar uma etapa deixou de exigir renumerar rótulos à mão em três funções.

**7.1 — `executar_etapa(etapa, funcao, ...)`.** Substitui os três `try/except`
idênticos em forma. As funções `run_extraction`, `run_bronze` e `run_dbt`
perderam o log de cabeçalho, que passou para o helper — elas voltaram a fazer
só o trabalho delas.

**7.3 — `config.ontem()`.** O default de período era recalculado no parser do
`main.py` e no dos extratores (que a Fase 3 já tinha reduzido de dois para um).
Agora os dois derivam da mesma função.

### Uma diferença que parecia inconsistência e não era

Os três blocos `try/except` não eram exatamente iguais: extração e bronze
registravam `type(exc).__name__`, enquanto o dbt registrava `exc` inteiro.

Isso é deliberado e foi preservado como parâmetro `detalhar_erro`, com o
default no lado conservador. Mensagens de exceção de SDK de API podem carregar
token ou payload, e log não é lugar de segredo. Só a etapa do dbt detalha,
porque a mensagem dela é nossa (`RuntimeError` com o código de saída) e não
passa por credencial. Unificar os três "por consistência" teria trocado uma
decisão de segurança por simetria estética.

### Verificação

- Rótulos na execução real: `ETAPA 1/3`, `2/3`, `3/3`, na ordem.
- **Numeração derivada:** acrescentando uma quarta etapa em memória, os
  cabeçalhos passam a `1/4 … 4/4` sozinhos.
- **Caminho de falha:** com `DW_DB_URL` apontando para host inexistente, a
  etapa da bronze sai com código 1 e registra
  `FALHA NA ETAPA CARGA BRONZE ... Erro: OperationalError`. A senha colocada na
  URL de teste **não aparece em nenhuma linha do log** (0 ocorrências).
- `config.ontem()`, o default do `main.py` e o dos extratores devolvem a mesma
  data.
- `PARIDADE OK — 1677 linhas`, 82 testes dbt.

---

## Fase 8 — `scripts/`: `_write_to_env` duplicado

✅ **Concluída em 07/08/2026.**

`oauth_manual.py` e `generate_google_refresh_token.py` têm duas
implementações quase idênticas da mesma função — e elas **já divergiram**: a
do `generate_` verifica se o `.env` existe antes de escrever, a do
`oauth_manual` não (estoura com `FileNotFoundError`).

As duas carregam o mesmo comentário sobre a armadilha do `with_name`
(armadilha nº 4), o que é a prova de que a duplicação é real e não
convergência acidental.

Alvo: `scripts/_env_utils.py` com uma implementação. Manter os dois scripts —
um é o fallback do outro quando o servidor local não funciona.

✅ **Concluída em 07/08/2026.**

### O que foi entregue

`scripts/_env_utils.py` com duas funções:

- `gravar_refresh_token(token)` — substitui a linha no `.env` preservando o
  resto, com backup. A implementação que ficou é a **defensiva**: confere se o
  arquivo existe e sai com mensagem clara. A outra estourava
  `FileNotFoundError` no meio do fluxo, **depois do token já emitido** — o pior
  momento possível, porque obriga a refazer a autorização.
- `ler_credenciais_oauth()` — os dois scripts também duplicavam a leitura de
  `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`, com mensagens de erro diferentes.
  Não estava listada no plano, mas é a mesma duplicação no mesmo par de
  arquivos. Ficou a mensagem mais útil das duas, que ensina a recriar o OAuth
  Client.

Os dois scripts continuam existindo, como o plano pedia.

**Sobre o import:** `from _env_utils import ...`, como módulo irmão. Estes
scripts rodam como `python scripts/<nome>.py`, então o próprio diretório é o
`sys.path[0]` — não depende da instalação editável, o que importa porque o
`generate_` roda no **host**, fora do container, onde o projeto não está
instalado.

### Verificação

Exercitada em diretório temporário, sem tocar no `.env` real:

- Substitui a linha existente e preserva as demais.
- Acrescenta a variável quando ela não existe.
- Backup criado como `.env.bak` e **não** `.env.env.bak` — a armadilha nº 4,
  agora afirmada por asserção em vez de comentário.
- `.env` ausente → `SystemExit` com `Arquivo nao encontrado: ...`, que é
  exatamente a divergência que existia entre as duas cópias.
- Nenhum `.env.bak` apareceu na raiz do projeto: o `.env` real ficou intacto.
- 82 testes dbt e `PARIDADE OK — 1677 linhas` (os scripts de OAuth não fazem
  parte do pipeline, mas a conferência é barata).

---

## Fase 9 — Opcional: cobertura de campo

Nada liga `INSIGHT_FIELDS` (`meta_ads.py:24`) e a lista do `GAQL_ADS_TEMPLATE`
(`google_ads.py:39`) aos modelos silver que leem essas chaves do payload.
Acrescentar um campo no extrator e esquecer do modelo é silencioso — foi
literalmente a pendência nº 1 que fechamos hoje, na direção inversa.

Alvo possível: teste dbt que confronte as chaves presentes no lote mais recente
da bronze com as chaves que a silver lê. Fica por último porque é o único item
do plano que adiciona conceito novo em vez de remover duplicação.

---

## Fora de escopo

| O quê | Por quê |
|---|---|
| `benchmark/` (717 linhas) | Experimento concluído, com resultados já citados nos números do TCC. Refatorar arrisca invalidar medição publicada sem ganho nenhum. Mexer só se quebrar |
| Estilo do SQL do dbt | CTEs em português, comentário de cabeçalho por modelo, ASCII nos comentários. Está consistente — não é dívida |
| `docs/` | São entregáveis, não código. Atualizar só o que cada fase mudar |
| `.env` / credenciais | Fora do alcance de refatoração |

---

## Decisões fechadas

Ambas decididas com o usuário em 07/08/2026. Nenhuma fase do plano continua
bloqueada.

**D1 — Como resolver o `sys.path.insert` (Fase 2.3)? → `pyproject.toml` +
instalação editável.**

Um `pyproject.toml` na raiz e `RUN pip install --no-cache-dir -e .` no
Dockerfile, depois do `COPY . .` e antes do `chown`. Elimina os três
`sys.path.insert` (`loaders/bronze_loader.py:27`, `benchmark/executar.py:43`,
`scripts/verificar_paridade.py:45`) e a armadilha nº 8 do CLAUDE.md junto.

O custo levantado no plano original estava superestimado. O compose faz
bind-mount de `.:/app` e o `WORKDIR` já é `/app`; a instalação editável grava o
apontador em `site-packages`, que fica **fora** do caminho sombreado pelo mount.
Resultado: `import config` passa a funcionar de qualquer diretório e **nenhum
comando documentado muda** — só o Dockerfile, com uma linha, mais o rebuild da
imagem (`docker compose build etl_app`).

Descartadas: `ENV PYTHONPATH=/app` (vale só dentro do container — quem clonar o
repo e rodar no host reencontra a armadilha) e `python -m` (muda os comandos do
README e do CLAUDE.md, e o caminho antigo continua existindo e quebrando).

**D2 — A travessia da hierarquia (Fase 6) vira view no banco.**

Modelo dbt `gold.vw_metricas_completas`, materializado como view, com a
cláusula de validade SCD2 em cada um dos cinco níveis. Serve qualquer
consumidor — psql, queries de demonstração, testes e o dashboard da pendência
nº 1 — enquanto a macro só resolveria a duplicação dentro do dbt e deixaria
quem consulta o banco direto ainda escrevendo o join à mão.

Não conflita com a regra de paridade: a view não altera fato nem dimensões,
apenas expõe uma leitura correta do que já existe. Os agregados congelados
continuam válidos sem recongelamento.

Descartada a combinação view + macro: a view já é o único lugar onde a
travessia aparece, então a indireção extra custaria explicação na defesa sem
ganho correspondente.

---

## Ordem sugerida

```
Fase 0  ───► rede de segurança          (bloqueia todas as outras)
  │
  ├─ Fase 1  registro de plataformas    ← maior ganho, maior alcance
  ├─ Fase 2  infra transversal
  │     └─ Fase 3  extratores           (depende de 1 e 2)
  │
  ├─ Fase 4  silver                     ┐
  ├─ Fase 5  gold                       ├─ independentes entre si
  ├─ Fase 6  travessia                  ┘
  │
  ├─ Fase 7  main.py                    (depende de 1)
  └─ Fase 8  scripts                    (isolada, pode ir a qualquer momento)

Fase 9  ───► opcional, por último
```

Fases 1 a 3 são um bloco: mexem nos mesmos arquivos e não vale separar em
commits diferentes. As fases 4, 5, 6 e 8 são isoladas e podem ser feitas em
qualquer ordem, uma por commit.

## Registro de execução

| Fase | Status | Commit | Paridade |
|---|---|---|---|
| 0 | ✅ concluída | `18b85df` | golden congelado |
| 1 | ✅ concluída | `b5f8f40` | OK — 1677 linhas |
| 2 | ✅ concluída | `101165a` | OK — 1677 linhas |
| 3 | ✅ concluída | | OK — 1677 linhas |
| 4 | ✅ concluída | | OK — 1677 linhas |
| 5 | ✅ concluída | | OK — 1677 linhas |
| 6 | ✅ concluída | | OK — 1677 linhas |
| 7 | ✅ concluída | | OK — 1677 linhas |
| 8 | ✅ concluída | | n/a — fora do pipeline |
| 9 | ⬜ pendente | | |
