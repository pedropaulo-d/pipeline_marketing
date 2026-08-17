"""Testes automatizados do pipeline.

Escritos com `unittest` da biblioteca padrao, e nao com pytest, para nao
acrescentar dependencia: rodam sem rebuild, tanto na imagem `etl_app` quanto
na do Airflow.

    python -m unittest discover -s tests -t .
"""
