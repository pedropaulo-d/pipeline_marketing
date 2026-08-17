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
import logging
import sys
from collections.abc import Callable

import manifesto
from config import configurar_logging, ontem
from plataformas import Plataforma

logger = logging.getLogger(__name__)

# Assinatura que cada extrator expoe para a casca percorrer as contas.
DescobrirContas = Callable[[], list[dict]]
ExtrairConta = Callable[[str, str, str, str], list[dict]]


def salvar_bruto(plataforma: Plataforma, linhas: list[dict]) -> None:
    """Salva os registros brutos no arquivo declarado no registro.

    A escrita e atomica (arquivo vizinho + ``os.replace``): uma interrupcao no
    meio da serializacao deixa o arquivo anterior intacto, em vez de um JSON
    truncado ocupando o caminho final — que e a entrada do ``--skip-extract``.

    Args:
        plataforma: Entrada do registro; define o caminho de saida.
        linhas: Registros a serializar, exatamente como vieram da API.
    """
    caminho = plataforma.arquivo_bruto
    manifesto.escrever_json_atomico(caminho, linhas, ensure_ascii=False, indent=2)
    logger.info("Dados brutos salvos em %s (%d registros)", caminho, len(linhas))


def executar_extracao(
    plataforma: Plataforma,
    descobrir_contas: DescobrirContas,
    extrair_conta: ExtrairConta,
    start_date: str,
    end_date: str,
    run_id: str | None = None,
) -> int:
    """Percorre as contas da plataforma e grava o resultado bruto.

    Grava tambem o manifesto ao lado do arquivo bruto. Sem ele, o loader nao
    tem como distinguir o arquivo desta execucao de um sobrado de outra — e
    passaria a reingerir dado antigo como lote novo.

    A ordem importa: o bruto primeiro, o manifesto depois. Uma interrupcao
    entre os dois deixa o manifesto antigo apontando para um conteudo que
    mudou, e a checagem de ``sha256`` rejeita o par.

    Args:
        plataforma: Entrada do registro.
        descobrir_contas: Devolve a lista de contas, cada uma com ``id`` e
            ``name``. Especifica de cada API.
        extrair_conta: Recebe ``(id, nome, start_date, end_date)`` e devolve os
            registros daquela conta. Especifica de cada API.
        start_date: Data inicial no formato ``YYYY-MM-DD``.
        end_date: Data final no formato ``YYYY-MM-DD``.
        run_id: Identificador da execucao, gravado no manifesto. ``None`` em
            execucao local sem orquestrador.

    Returns:
        Quantidade total de registros extraidos.
    """
    contas = descobrir_contas()

    linhas: list[dict] = []
    for conta in contas:
        linhas.extend(extrair_conta(conta["id"], conta["name"], start_date, end_date))

    salvar_bruto(plataforma, linhas)
    manifesto.gravar(
        plataforma,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
        registros=len(linhas),
    )
    logger.info(
        "Extracao %s concluida. Total: %d registros | janela %s a %s | run_id %s",
        plataforma.nome, len(linhas), start_date, end_date, run_id or "(local)",
    )
    return len(linhas)


def _parse_args(plataforma: Plataforma) -> argparse.Namespace:
    """Parseia o periodo de extracao para execucao standalone.

    Args:
        plataforma: Entrada do registro; nomeia o extrator na ajuda da CLI.

    Returns:
        Namespace com ``start_date`` e ``end_date``.
    """
    padrao = ontem()
    parser = argparse.ArgumentParser(description=f"Extrator {plataforma.nome}")
    parser.add_argument("--start-date", default=padrao, help="Data inicial (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=padrao, help="Data final (YYYY-MM-DD)")
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Identificador da execucao (o `run_id` do DagRun). Vai para o "
            "manifesto e e o que prova ao loader que o arquivo bruto veio "
            "desta execucao."
        ),
    )
    return parser.parse_args()


def executar_cli(
    plataforma: Plataforma, run: Callable[[str, str, str | None], int]
) -> None:
    """Entrypoint standalone comum aos extratores.

    Qualquer excecao e registrada pelo logging do projeto e o processo sai com
    codigo 1 — a task do Airflow continua falhando, como deve. O que muda e o
    caminho do texto: sem este bloco, a excecao subiria ate o interpretador e o
    traceback seria impresso pelo ``excepthook`` padrao, fora do logging e
    portanto sem passar pela redacao de segredos. Uma falha de rede no SDK do
    Meta carrega a URL da requisicao, e nela viaja o ``access_token``.

    Args:
        plataforma: Entrada do registro.
        run: Funcao ``run(start_date, end_date, run_id)`` do extrator.
    """
    configurar_logging()
    args = _parse_args(plataforma)

    try:
        run(args.start_date, args.end_date, args.run_id)
    except SystemExit:
        raise
    except Exception as exc:
        logger.exception(
            "FALHA na extracao %s (%s). Traceback sanitizado abaixo.",
            plataforma.nome, type(exc).__name__,
        )
        sys.exit(1)
