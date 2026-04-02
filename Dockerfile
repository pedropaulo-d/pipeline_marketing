FROM python:3.11-slim

RUN groupadd --gid 1000 etl && \
    useradd --uid 1000 --gid etl --create-home etl

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R etl:etl /app

USER etl
