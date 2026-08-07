FROM python:3.11-slim

RUN groupadd --gid 1000 etl && \
    useradd --uid 1000 --gid etl --create-home etl

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Instalacao editavel: torna o projeto importavel de qualquer diretorio, sem
# `sys.path.insert`. O apontador vai para site-packages, fora do /app que o
# compose sobrepoe com o bind mount — o codigo continua vindo do host, sem
# rebuild a cada edicao. `--no-deps` porque as dependencias ja vieram do
# requirements.txt acima.
#
# `editable_mode=compat` NAO e detalhe de estilo. No modo padrao (strict) o
# setuptools grava em site-packages um dicionario nome->arquivo resolvido no
# momento do build: um modulo novo na raiz nao e encontrado ate a imagem ser
# reconstruida, mesmo com o arquivo presente no bind mount. No modo compat o
# que se grava e um .pth com o caminho `/app`, entao a raiz inteira entra no
# sys.path e arquivo novo funciona na hora.
#
# Se uma versao futura do setuptools remover essa opcao, o substituto e trivial
# e nao depende de setuptools nenhum:
#   RUN echo /app > /usr/local/lib/python3.11/site-packages/tcc_pipeline.pth
RUN pip install --no-cache-dir --no-deps -e . --config-settings editable_mode=compat

RUN chown -R etl:etl /app

USER etl
