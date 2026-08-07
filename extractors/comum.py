"""Casca compartilhada pelos extratores.

Os dois extratores repetiam a mesma estrutura de borda: salvar o JSON bruto,
parsear os argumentos de linha de comando, o entrypoint standalone e o esqueleto
de ``run`` (descobrir contas, percorrer, acumular, salvar). Eram ~50 linhas
quase identicas em cada arquivo.

O que **nao** vive aqui, de proposito: ``discover_accounts`` e
``extract_daily_ads``. As duas APIs sao genuinamente diferentes — paginacao por
cursor no Meta, GAQL no Google — e unifica-las produziria uma abstracao que
precisa de um ``if plataforma`` dentro para funcionar. A fronteira e a casca,
nao o miolo.
"""

import argparse
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from config import configurar_logging
from plataformas import Plataforma

logger = logging.getLogger(__name__)

# Assinatura que cada extrator expoe para a casca percorrer as contas.
DescobrirContas = Callable[[], list[dict]]
ExtrairConta = Callable[[str, str, str, str], list[dict]]


def salvar_bruto(plataforma: Plataforma, linhas: list[dict]) -> None:
    """Salva os registros brutos no arquivo declarado no registro.

    Args:
        plataforma: Entrada do registro; define o caminho de saida.
        linhas: Registros a serializar, exatamente como vieram da API.
    """
    caminho = plataforma.arquivo_bruto
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(linhas, f, ensure_ascii=False, indent=2)
    logger.info("Dados brutos salvos em %s (%d registros)", caminho, len(linhas))


def executar_extracao(
    plataforma: Plataforma,
    descobrir_contas: DescobrirContas,
    extrair_conta: ExtrairConta,
    start_date: str,
    end_date: str,
) -> int:
    """Percorre as contas da plataforma e grava o resultado bruto.

    Args:
        plataforma: Entrada do registro.
        descobrir_contas: Devolve a lista de contas, cada uma com ``id`` e
            ``name``. Especifica de cada API.
        extrair_conta: Recebe ``(id, nome, start_date, end_date)`` e devolve os
            registros daquela conta. Especifica de cada API.
        start_date: Data inicial no formato ``YYYY-MM-DD``.
        end_date: Data final no formato ``YYYY-MM-DD``.

    Returns:
        Quantidade total de registros extraidos.
    """
    contas = descobrir_contas()

    linhas: list[dict] = []
    for conta in contas:
        linhas.extend(extrair_conta(conta["id"], conta["name"], start_date, end_date))

    salvar_bruto(plataforma, linhas)
    logger.info(
        "Extracao %s concluida. Total: %d registros", plataforma.nome, len(linhas)
    )
    return len(linhas)


def _parse_args(plataforma: Plataforma) -> argparse.Namespace:
    """Parseia o periodo de extracao para execucao standalone.

    Args:
        plataforma: Entrada do registro; nomeia o extrator na ajuda da CLI.

    Returns:
        Namespace com ``start_date`` e ``end_date``.
    """
    ontem = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(description=f"Extrator {plataforma.nome}")
    parser.add_argument("--start-date", default=ontem, help="Data inicial (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=ontem, help="Data final (YYYY-MM-DD)")
    return parser.parse_args()


def executar_cli(plataforma: Plataforma, run: Callable[[str, str], int]) -> None:
    """Entrypoint standalone comum aos extratores.

    Args:
        plataforma: Entrada do registro.
        run: Funcao ``run(start_date, end_date)`` do extrator.
    """
    configurar_logging()
    args = _parse_args(plataforma)
    run(args.start_date, args.end_date)
