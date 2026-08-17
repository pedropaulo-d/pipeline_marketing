# Imagem do Airflow com as dependencias do pipeline instaladas dentro.
#
# Estrategia: bind mount + BashOperator. O projeto inteiro e montado em
# /opt/project e as tasks chamam os MESMOS comandos que rodariam no terminal
# (`python -m extractors.meta_ads`, `python -m loaders.bronze_loader`). Nao ha
# um segundo container por task — o que exigiria expor o socket do Docker ao
# scheduler.
#
# A variante `-python3.11` nao e detalhe: a imagem `apache/airflow:3.3.0` sem
# sufixo traz Python 3.13, e o pipeline e verificado em 3.11 (mesma versao do
# `Dockerfile` da raiz, `requires-python` do pyproject e dos 72 testes dbt).
# Orquestrar codigo num runtime diferente do que foi testado e trocar uma
# garantia por uma suposicao.
FROM apache/airflow:3.3.0-python3.11

# O contexto de build e a raiz do repositorio (definido no docker-compose.yml),
# entao o requirements.txt esta acessivel por caminho relativo.
COPY requirements.txt /requirements.txt

# Instalado como `airflow`: a imagem oficial bloqueia pip como root.
#
# Sem pin `==`: as versoes sao resolvidas contra o que a imagem do Airflow ja
# fixa. Verificado com `pip install --dry-run` antes de escrever este arquivo —
# resolve sem conflito, acrescentando dbt-core 1.12, dbt-postgres 1.11,
# facebook-business 26 e duckdb. O `google-ads` ja vem satisfeito pelo provider
# Google da propria imagem.
USER airflow
RUN pip install --no-cache-dir -r /requirements.txt
