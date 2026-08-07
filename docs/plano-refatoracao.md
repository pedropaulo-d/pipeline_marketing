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

**Onde paramos:** Fase 1 concluída em 07/08/2026 e **ainda não commitada** —
`plataformas.py` é arquivo novo. Fase 0 commitada em 06/08 (`18b85df`).

**Primeiro comando ao retomar** — confirma que o armazém continua no estado
congelado antes de qualquer mudança:

```bash
docker compose up -d db
docker compose run --rm etl_app python scripts/verificar_paridade.py verificar
```

Esperado: `PARIDADE OK — 1677 linhas no fato`. Se divergir, **investigue antes
de refatorar** — ou alguém rodou uma extração nova (legítimo: recongele de
propósito), ou algo mudou sozinho.

**Próximo passo:** Fase 2 (infraestrutura transversal), com D1 já decidida:
`pyproject.toml` + instalação editável. Ela também destrava a pendência que a
Fase 1 empurrou — os dois scripts que ainda montam o nome do arquivo bruto à
mão. Fases 1 a 3 mexem nos mesmos arquivos e valem um bloco só de commits.

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

| Item | Situação | Alvo |
|---|---|---|
| 2.1 | `logging.basicConfig()` em 4 módulos (`main.py:23`, `meta_ads.py:18`, `google_ads.py:15`, `bronze_loader.py:29`). Só a primeira chamada tem efeito — as outras três são no-op silencioso | Uma `configurar_logging()` em `config.py`, chamada pelos entrypoints |
| 2.2 | `load_dotenv()` em 4 módulos, no import | Uma vez, no entrypoint. `config.py` já faz no import dele |
| 2.3 | `sys.path.insert` em `bronze_loader.py:27`, `benchmark/executar.py:43` e `scripts/verificar_paridade.py:45` | `pyproject.toml` + `pip install -e .` no Dockerfile (D1, fechada) |
| 2.4 | Imports locais gratuitos: `config.py:70` (urllib), `main.py:202-203` (os, subprocess) | Subir para o topo. **Manter** os lazy dos SDKs em `main.py:163,169` — evitam carregar o SDK do Google numa execução só do Meta |

O item 2.3 é a **armadilha nº 8 do CLAUDE.md**. Hoje ela é documentada; a
refatoração pode eliminá-la.

---

## Fase 3 — Extratores: contrato comum

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

---

## Fase 4 — Silver: deduplicação duplicada

`stg_meta_ads.sql:14-36` e `stg_google_ads.sql:19-41` contêm o **mesmo bloco**
`bruto` + `ultimo_snapshot`, palavra por palavra, mudando só o valor de
`where source =`.

Alvo: macro `ultimo_snapshot(fonte)`. Além de encurtar, fecha a porta para os
dois modelos divergirem — que é a categoria exata do bug do `union all`
(armadilha nº 5).

**Guarda a acrescentar:** um teste que afirme que os dois modelos de staging
expõem os mesmos nomes de coluna, na mesma ordem. Hoje a proteção é um
comentário em `stg_ads_unified.sql:13-17` pedindo atenção humana.

---

## Fase 5 — Gold: derivação de chave duplicada

| Item | Onde | Problema |
|---|---|---|
| 5.1 | `dim_tempo.sql:16` e `fato_metricas.sql:26` | `md5(data::text)` escrito nos dois. Mudar a fórmula da chave num só lugar quebra o join sem erro de sintaxe |
| 5.2 | `assert_scd2_sem_sobreposicao.sql:11` e `assert_scd2_uma_versao_atual.sql:10` | A lista `dimensoes` hardcoded nos dois testes |
| 5.3 | `profiles.yml:15` | `schema: public` sobrou do ETL. Só é usado quando não há schema customizado — hoje, nunca |

Alvos: macro `chave_tempo(coluna)` para 5.1; `vars:` no `dbt_project.yml` para
5.2; remover 5.3.

---

## Fase 6 — A travessia da hierarquia (a lição dos 7,8%)

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

---

## Fase 7 — `main.py`: orquestração

| Item | Onde | Problema |
|---|---|---|
| 7.1 | `main.py:250-286` | Três blocos `try/except` de forma idêntica: chama, loga "FALHA NA X", `sys.exit(1)`. Alvo: helper `executar_etapa(nome, funcao)` |
| 7.2 | `run_extraction:157`, `run_bronze:222`, `run_dbt:208` | Os rótulos `ETAPA 1/3`, `2/3`, `3/3` hardcoded em três funções. Adicionar uma etapa exige renumerar tudo à mão |
| 7.3 | `main.py:73` | `yesterday` recalculado no parse; `meta_ads.py:209` e `google_ads.py:216` recalculam o mesmo default |

---

## Fase 8 — `scripts/`: `_write_to_env` duplicado

`oauth_manual.py` e `generate_google_refresh_token.py` têm duas
implementações quase idênticas da mesma função — e elas **já divergiram**: a
do `generate_` verifica se o `.env` existe antes de escrever, a do
`oauth_manual` não (estoura com `FileNotFoundError`).

As duas carregam o mesmo comentário sobre a armadilha do `with_name`
(armadilha nº 4), o que é a prova de que a duplicação é real e não
convergência acidental.

Alvo: `scripts/_env_utils.py` com uma implementação. Manter os dois scripts —
um é o fallback do outro quando o servidor local não funciona.

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
| 1 | ✅ concluída | | OK — 1677 linhas |
| 2 | ⬜ pendente | | |
| 3 | ⬜ pendente | | |
| 4 | ⬜ pendente | | |
| 5 | ⬜ pendente | | |
| 6 | ⬜ pendente | | |
| 7 | ⬜ pendente | | |
| 8 | ⬜ pendente | | |
| 9 | ⬜ pendente | | |
