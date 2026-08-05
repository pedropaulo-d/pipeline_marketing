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

from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent

SEPARATOR: str = "=" * 60

# Plataformas suportadas → grupo de credenciais correspondente em config.py
PLATFORMS: dict[str, str] = {
    "meta": "Meta Ads",
    "google": "Google Ads",
}


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
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help=(
            "Pula a extração e reprocessa os arquivos brutos já existentes "
            "(temp_meta_raw.json / temp_google_raw.json). Útil para "
            "demonstrar transformação e carga sem consumir a API."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=["elt", "etl"],
        default="elt",
        help=(
            "Arquitetura a executar. 'elt' (default): bronze (JSONB bruto) → "
            "silver → gold via dbt, com testes de dados. 'etl': caminho "
            "original, transformação em pandas e carga direta no schema public."
        ),
    )
    parser.add_argument(
        "--platforms",
        default="meta,google",
        help=(
            "Plataformas a extrair, separadas por vírgula: meta, google. "
            "Default: meta,google. Permite rodar o pipeline quando as "
            "credenciais de uma das plataformas estão indisponíveis."
        ),
    )

    args = parser.parse_args()

    args.platforms = [p.strip().lower() for p in args.platforms.split(",") if p.strip()]
    invalid = set(args.platforms) - PLATFORMS.keys()
    if invalid:
        parser.error(
            f"--platforms inválido: {', '.join(sorted(invalid))}. "
            f"Valores aceitos: {', '.join(PLATFORMS)}."
        )
    if not args.platforms:
        parser.error("--platforms exige ao menos uma plataforma.")

    if args.start_date > args.end_date:
        parser.error(
            f"--start-date ({args.start_date}) não pode ser maior que "
            f"--end-date ({args.end_date})."
        )

    return args


# ── Execução das etapas ──────────────────────────────────────


def run_extraction(
    start_date: str, end_date: str, platforms: list[str]
) -> dict[str, int]:
    """Executa a extração das plataformas selecionadas.

    Args:
        start_date: Data inicial no formato ``YYYY-MM-DD``.
        end_date: Data final no formato ``YYYY-MM-DD``.
        platforms: Plataformas a extrair (``"meta"`` e/ou ``"google"``).

    Returns:
        Mapa ``{plataforma: registros_extraidos}``.
    """
    logger.info(SEPARATOR)
    logger.info("ETAPA 1/3: EXTRAÇÃO  (período: %s a %s)", start_date, end_date)
    logger.info(SEPARATOR)

    counts: dict[str, int] = {}

    if "meta" in platforms:
        from extractors import meta_ads

        logger.info("Extraindo Meta Ads...")
        counts["meta"] = meta_ads.run(start_date, end_date)

    if "google" in platforms:
        from extractors import google_ads

        logger.info("Extraindo Google Ads...")
        counts["google"] = google_ads.run(start_date, end_date)

    return counts


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
    """Executa a carga dos CSVs no Data Warehouse (caminho ETL).

    Returns:
        Quantidade de registros carregados na tabela fato.
    """
    from loaders import supabase_loader

    logger.info(SEPARATOR)
    logger.info("ETAPA 3/3: CARGA (Data Warehouse)")
    logger.info(SEPARATOR)

    return supabase_loader.run()


# ── Caminho ELT (bronze → silver → gold) ─────────────────────


def run_bronze() -> int:
    """Carrega os arquivos brutos na camada bronze, sem transformar.

    Returns:
        Quantidade de registros inseridos.
    """
    from loaders import bronze_loader

    logger.info(SEPARATOR)
    logger.info("ETAPA 2/3: CARGA BRONZE (dado bruto imutável)")
    logger.info(SEPARATOR)

    return bronze_loader.run()


def run_dbt() -> None:
    """Executa ``dbt build`` — materializa silver e gold e roda os testes.

    Raises:
        RuntimeError: Se o dbt terminar com código de saída diferente de zero.
    """
    import os
    import subprocess

    from config import dbt_env

    logger.info(SEPARATOR)
    logger.info("ETAPA 3/3: TRANSFORMAÇÃO dbt (silver → gold) + TESTES")
    logger.info(SEPARATOR)

    dbt_dir = BASE_DIR / "dbt"
    env = {**os.environ, **dbt_env()}

    resultado = subprocess.run(
        [
            "dbt", "build",
            "--project-dir", str(dbt_dir),
            "--profiles-dir", str(dbt_dir),
        ],
        env=env,
        check=False,
    )

    if resultado.returncode != 0:
        raise RuntimeError(
            f"dbt build falhou (exit {resultado.returncode}). "
            "Verifique os modelos e testes acima."
        )


# ── Main ─────────────────────────────────────────────────────


def main() -> None:
    """Orquestra o pipeline ETL completo com interrupção em caso de falha."""
    args = parse_args()
    t0 = time.time()

    logger.info(SEPARATOR)
    logger.info("PIPELINE INICIADO — modo %s", args.mode.upper())
    logger.info("Período: %s a %s", args.start_date, args.end_date)
    logger.info(SEPARATOR)

    # ── Validação de credenciais ──
    # Só são exigidas as credenciais das plataformas efetivamente extraídas;
    # a URL do Data Warehouse é sempre obrigatória.
    groups = [] if args.skip_extract else [PLATFORMS[p] for p in args.platforms]
    validate_env(groups=groups)

    # ── Extração ──
    counts: dict[str, int] = {}
    if args.skip_extract:
        logger.info(SEPARATOR)
        logger.info("ETAPA 1/3: EXTRAÇÃO IGNORADA (--skip-extract)")
        logger.info("Reprocessando os arquivos brutos já existentes.")
        logger.info(SEPARATOR)
    else:
        try:
            counts = run_extraction(args.start_date, args.end_date, args.platforms)
        except Exception as exc:
            logger.error("FALHA NA EXTRAÇÃO. Pipeline interrompido. Erro: %s", type(exc).__name__)
            sys.exit(1)

        if sum(counts.values()) == 0:
            logger.warning("Nenhum registro extraído. Pipeline interrompido.")
            sys.exit(0)

    if args.mode == "elt":
        # ── Carga bruta na bronze ──
        try:
            bronze_count = run_bronze()
        except Exception as exc:
            logger.error("FALHA NA CARGA BRONZE. Pipeline interrompido. Erro: %s", type(exc).__name__)
            sys.exit(1)

        # ── Transformação no banco + testes de dados ──
        try:
            run_dbt()
        except Exception as exc:
            logger.error("FALHA NO DBT. Pipeline interrompido. Erro: %s", exc)
            sys.exit(1)

        resultado = f"Bronze={bronze_count}"
    else:
        # ── Transformação em pandas ──
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

        resultado = f"Fato={fato_count} | Dim={dim_count} | Carregados={loaded}"

    # ── Resumo ──
    elapsed = time.time() - t0
    extraidos = (
        "extração ignorada"
        if args.skip_extract
        else " | ".join(f"{p}={n}" for p, n in counts.items())
    )
    logger.info(SEPARATOR)
    logger.info("PIPELINE CONCLUÍDO COM SUCESSO (%.1fs) — modo %s", elapsed, args.mode.upper())
    logger.info("Resumo: %s | %s", extraidos, resultado)
    logger.info(SEPARATOR)


if __name__ == "__main__":
    main()
