# Imagem do painel analitico.
#
# Copia apenas `dashboard/`. O resto do projeto — extratores, loaders, dbt,
# scripts de exportacao — fica de fora porque o dashboard nao precisa dele, e
# o que nao esta na imagem nao pode ser chamado por engano.
FROM python:3.11-slim

RUN groupadd --gid 1000 painel && \
    useradd --uid 1000 --gid painel --create-home painel

WORKDIR /app

COPY dashboard/requirements.txt /tmp/requirements-dashboard.txt
RUN pip install --no-cache-dir -r /tmp/requirements-dashboard.txt

COPY dashboard/ /app/dashboard/

# Tema do painel. O Streamlit le a configuracao do diretorio de trabalho, que
# aqui e /app — o mesmo arquivo que serve a execucao local a partir da raiz do
# repositorio. E declaracao de cor: nao ha segredo nem codigo nele.
COPY .streamlit/config.toml /app/.streamlit/config.toml

# `streamlit run` poe o diretorio do script no sys.path, nao a raiz. O
# PYTHONPATH torna `from dashboard import ...` previsivel; `app.py` mantem o
# mesmo ajuste para funcionar fora do container.
ENV PYTHONPATH=/app \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

USER painel

EXPOSE 8501

CMD ["streamlit", "run", "dashboard/app.py"]
