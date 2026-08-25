"""Camada de visualizacao do pipeline.

Consome exclusivamente a superficie de exposicao pseudonimizada
(`data/exposicao/metricas.csv`) ou o dataset sintetico de demonstracao
(`dashboard/dados_demo/metricas.csv`). Nao fala com o Data Warehouse, com a
bronze, com a silver, com a gold nem com as APIs de anuncios.
"""
