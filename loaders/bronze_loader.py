"""Carga da camada bronze — o ``L`` do ELT.

Le os arquivos brutos produzidos pelos extractors e grava cada registro no
Postgres **sem transformar nada**: o payload original vai integro para uma
coluna JSONB, acompanhado dos metadados de ingestao.

A tabela e append-only. Reprocessar o mesmo periodo cria um lote novo em vez
de sobrescrever o anterior; a deduplicacao acontece na camada silver, que
considera apenas o snapshot mais recente de cada dia.

Uso:
    docker compose run --rm etl_app python loaders/bronze_loader.py
"""

import json
import logging
import sys
import uuid
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

# Permite `python loaders/bronze_loader.py` alem de `python -m loaders...`,
# garantindo que o pacote raiz (config.py) seja importavel nos dois casos.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR: Path = Path(__file__).resolve().parent.parent
DDL_PATH: Path = BASE_DIR / "sql" / "bronze" / "init_bronze.sql"

# Cada fonte tem seu arquivo bruto e o campo que carrega o dia de referencia.
SOURCES: dict[str, dict] = {
    "meta_ads": {
        "path": BASE_DIR / "temp_meta_raw.json",
        "date_field": "date_start",
    },
    "google_ads": {
        "path": BASE_DIR / "temp_google_raw.json",
        "date_field": "date",
    },
}


def get_engine() -> Engine:
    """Cria a engine SQLAlchemy apontando para o Data Warehouse.

    Returns:
        Engine conectada.

    Raises:
        EnvironmentError: Se a URL do banco nao estiver configurada.
    """
    from sqlalchemy import create_engine

    from config import get_db_url

    db_url = get_db_url()
    if not db_url:
        raise EnvironmentError(
            "Defina DW_DB_URL (ou SUPABASE_DB_URL) com a URL do Data Warehouse."
        )
    return create_engine(db_url)


def ensure_schema(engine: Engine) -> None:
    """Aplica o DDL da camada bronze (idempotente).

    Args:
        engine: Engine conectada ao banco.
    """
    ddl = DDL_PATH.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(ddl))
    logger.info("Schema bronze verificado.")


def _parse_reference_date(raw_value: str | None) -> date | None:
    """Converte o campo de data do payload para ``date``.

    Args:
        raw_value: Valor bruto, esperado no formato ``YYYY-MM-DD``.

    Returns:
        A data correspondente, ou ``None`` se ausente ou invalida.
    """
    if not raw_value:
        return None
    try:
        return datetime.strptime(str(raw_value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def load_source(
    session: Session, source: str, path: Path, date_field: str, batch_id: uuid.UUID
) -> int:
    """Carrega um arquivo bruto na tabela ``bronze.raw_ads``.

    Args:
        session: Sessao SQLAlchemy ativa.
        source: Identificador da plataforma (``meta_ads`` ou ``google_ads``).
        path: Caminho do arquivo JSON bruto.
        date_field: Nome do campo que contem o dia de referencia.
        batch_id: Identificador desta execucao.

    Returns:
        Quantidade de registros inseridos.
    """
    if not path.exists():
        logger.warning("Arquivo bruto ausente, fonte ignorada: %s", path.name)
        return 0

    registros = json.loads(path.read_text(encoding="utf-8"))
    if not registros:
        logger.warning("Arquivo bruto vazio: %s", path.name)
        return 0

    linhas = []
    descartados = 0
    for registro in registros:
        referencia = _parse_reference_date(registro.get(date_field))
        if referencia is None:
            descartados += 1
            continue
        linhas.append({
            "source": source,
            "reference_date": referencia,
            "batch_id": str(batch_id),
            "payload": json.dumps(registro, ensure_ascii=False),
        })

    if descartados:
        logger.warning(
            "%s: %d registros sem '%s' valido foram descartados.",
            source, descartados, date_field,
        )

    if not linhas:
        return 0

    session.execute(
        text(
            "INSERT INTO bronze.raw_ads (source, reference_date, batch_id, payload) "
            "VALUES (:source, :reference_date, :batch_id, CAST(:payload AS JSONB))"
        ),
        linhas,
    )

    datas = [linha["reference_date"] for linha in linhas]
    session.execute(
        text(
            "INSERT INTO bronze.ingestion_log "
            "(batch_id, source, start_date, end_date, row_count) "
            "VALUES (:batch_id, :source, :start_date, :end_date, :row_count)"
        ),
        {
            "batch_id": str(batch_id),
            "source": source,
            "start_date": min(datas),
            "end_date": max(datas),
            "row_count": len(linhas),
        },
    )

    logger.info(
        "bronze.raw_ads: %d registros de %s (%s a %s).",
        len(linhas), source, min(datas), max(datas),
    )
    return len(linhas)


def run() -> int:
    """Carrega todos os arquivos brutos disponiveis na camada bronze.

    Returns:
        Total de registros inseridos.
    """
    engine = get_engine()
    ensure_schema(engine)

    total = 0
    with Session(engine) as session:
        try:
            for source, cfg in SOURCES.items():
                # batch_id por fonte — cada arquivo e uma unidade de carga.
                batch_id = uuid.uuid4()
                total += load_source(
                    session, source, cfg["path"], cfg["date_field"], batch_id
                )
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error(
                "Erro na carga da bronze. Rollback realizado. Tipo: %s",
                type(exc).__name__,
            )
            raise

    logger.info("Carga da bronze concluida. Total: %d registros.", total)
    return total


def main() -> None:
    """Entry point para execucao standalone via CLI."""
    from dotenv import load_dotenv

    load_dotenv()
    run()


if __name__ == "__main__":
    main()
