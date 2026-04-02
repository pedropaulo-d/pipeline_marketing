"""Orquestrador do pipeline ETL (Extração → Transformação → Carga).

Uso:
    docker compose run --rm etl_app python main.py --start-date 2026-03-30 --end-date 2026-03-31

Sem argumentos, extrai apenas o dia anterior (yesterday).
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("pipeline")

from config import validate_env

SEPARATOR: str = "=" * 60


# ── Validação de argumentos ──────────────────────────────────


def _valid_date(value: str) -> str:
    """Valida que o valor está no formato YYYY-MM-DD.

    Args:
        value: String de data fornecida pelo usuário.

    Returns:
        A mesma string se válida.

    Raises:
        argparse.ArgumentTypeError: Se o formato for inválido.
    """
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Data inválida: '{value}'. Use o formato YYYY-MM-DD."
        )
    return value


def parse_args() -> argparse.Namespace:
    """Parseia e valida os argumentos de linha de comando.

    Returns:
        Namespace com ``start_date`` e ``end_date`` validados.

    Raises:
        SystemExit: Se start_date > end_date.
    """
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(
        description="Pipeline ETL: Meta/Google Ads → Supabase",
    )
    parser.add_argument(
        "--start-date",
        type=_valid_date,
        default=yesterday,
        help="Data inicial (YYYY-MM-DD). Default: yesterday.",
    )
    parser.add_argument(
        "--end-date",
        type=_valid_date,
        default=yesterday,
        help="Data final (YYYY-MM-DD). Default: yesterday.",
    )

    args = parser.parse_args()

    if args.start_date > args.end_date:
        parser.error(
            f"--start-date ({args.start_date}) não pode ser maior que "
            f"--end-date ({args.end_date})."
        )

    return args


# ── Execução das etapas ──────────────────────────────────────


def run_extraction(start_date: str, end_date: str) -> tuple[int, int]:
    """Executa a extração de ambas as plataformas.

    Args:
        start_date: Data inicial no formato ``YYYY-MM-DD``.
        end_date: Data final no formato ``YYYY-MM-DD``.

    Returns:
        Tupla ``(registros_meta, registros_google)``.
    """
    from extractors import meta_ads, google_ads

    logger.info(SEPARATOR)
    logger.info("ETAPA 1/3: EXTRAÇÃO  (período: %s a %s)", start_date, end_date)
    logger.info(SEPARATOR)

    logger.info("Extraindo Meta Ads...")
    meta_count = meta_ads.run(start_date, end_date)

    logger.info("Extraindo Google Ads...")
    google_count = google_ads.run(start_date, end_date)

    return meta_count, google_count


def run_transformation() -> tuple[int, int]:
    """Executa a transformação dos dados brutos em CSVs padronizados.

    Returns:
        Tupla ``(registros_fato, registros_dim)``.
    """
    from transformers import data_transformer

    logger.info(SEPARATOR)
    logger.info("ETAPA 2/3: TRANSFORMAÇÃO")
    logger.info(SEPARATOR)

    return data_transformer.run()


def run_load() -> int:
    """Executa a carga dos CSVs no Supabase.

    Returns:
        Quantidade de registros carregados na tabela fato.
    """
    from loaders import supabase_loader

    logger.info(SEPARATOR)
    logger.info("ETAPA 3/3: CARGA (Supabase)")
    logger.info(SEPARATOR)

    return supabase_loader.run()


# ── Main ─────────────────────────────────────────────────────


def main() -> None:
    """Orquestra o pipeline ETL completo com interrupção em caso de falha."""
    args = parse_args()
    t0 = time.time()

    logger.info(SEPARATOR)
    logger.info("PIPELINE ETL INICIADO")
    logger.info("Período: %s a %s", args.start_date, args.end_date)
    logger.info(SEPARATOR)

    # ── Validação de credenciais ──
    validate_env()

    # ── Extração ──
    try:
        meta_count, google_count = run_extraction(args.start_date, args.end_date)
    except Exception as exc:
        logger.error("FALHA NA EXTRAÇÃO. Pipeline interrompido. Erro: %s", type(exc).__name__)
        sys.exit(1)

    if meta_count + google_count == 0:
        logger.warning("Nenhum registro extraído. Pipeline interrompido.")
        sys.exit(0)

    # ── Transformação ──
    try:
        fato_count, dim_count = run_transformation()
    except Exception as exc:
        logger.error("FALHA NA TRANSFORMAÇÃO. Pipeline interrompido. Erro: %s", type(exc).__name__)
        sys.exit(1)

    # ── Carga ──
    try:
        loaded = run_load()
    except Exception as exc:
        logger.error("FALHA NA CARGA. Pipeline interrompido. Erro: %s", type(exc).__name__)
        sys.exit(1)

    # ── Resumo ──
    elapsed = time.time() - t0
    logger.info(SEPARATOR)
    logger.info("PIPELINE CONCLUÍDO COM SUCESSO (%.1fs)", elapsed)
    logger.info(
        "Resumo: Meta=%d | Google=%d | Fato=%d | Dim=%d | Carregados=%d",
        meta_count, google_count, fato_count, dim_count, loaded,
    )
    logger.info(SEPARATOR)


if __name__ == "__main__":
    main()
