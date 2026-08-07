FROM python:3.11-slim

RUN groupadd --gid 1000 etl && \
    useradd --uid 1000 --gid etl --create-home etl

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Instalacao editavel: torna `config`, `plataformas`, `extractors`, `loaders` e
# `benchmark` importaveis de qualquer diretorio, sem `sys.path.insert`. O
# apontador vai para site-packages, fora do /app que o compose sobrepoe com o
# bind mount — o codigo continua vindo do host, sem rebuild a cada edicao.
# `--no-deps` porque as dependencias ja vieram do requirements.txt acima.
RUN pip install --no-cache-dir --no-deps -e .

RUN chown -R etl:etl /app

USER etl
