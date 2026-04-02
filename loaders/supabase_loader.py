import datetime
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import Engine, MetaData, Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR: Path = Path(__file__).resolve().parent.parent
DIM_ADS_CSV: Path = BASE_DIR / "temp_dim_ads.csv"
FATO_CSV: Path = BASE_DIR / "temp_fato.csv"

METRIC_COLS: list[str] = [
    "spend", "impressions", "link_clicks",
    "conversions", "conversion_value", "video_views",
    "reach", "profile_views", "purchases",
]

# Type aliases para os mapas de FK
FkMap = dict[tuple[str, int], int]
PlataformaMap = dict[str, int]
TempoMap = dict[datetime.date, int]
AdIdMap = dict[str, int]


def get_engine() -> Engine:
    """Cria uma engine SQLAlchemy a partir da variável SUPABASE_DB_URL.

    Returns:
        Engine conectada ao banco Supabase.

    Raises:
        EnvironmentError: Se SUPABASE_DB_URL não estiver definida no .env.
    """
    from sqlalchemy import create_engine

    db_url = os.getenv("SUPABASE_DB_URL")
    if not db_url:
        raise EnvironmentError("Variável SUPABASE_DB_URL é obrigatória no .env")
    return create_engine(db_url)


def reflect_tables(engine: Engine) -> dict[str, Table]:
    """Reflete o schema do banco e retorna um dict de objetos Table.

    Args:
        engine: Engine SQLAlchemy conectada ao banco.

    Returns:
        Dicionário ``{nome_tabela: Table}``.
    """
    metadata = MetaData()
    metadata.reflect(bind=engine)
    return metadata.tables


# ── Helper: resolução de cadeia de FK ────────────────────────


def _resolve_fk_chain(
    row: pd.Series,
    plataforma_map: PlataformaMap,
    conta_map: FkMap,
    campanha_map: FkMap,
    adset_map: FkMap | None = None,
) -> tuple[int, ...]:
    """Resolve a cadeia de FKs internas a partir de uma linha do DataFrame
    de dimensões, descendo do nível plataforma até o nível solicitado.

    Args:
        row: Linha do DataFrame de dimensões (com colunas ``platform``,
            ``account_id``, ``campaign_id`` e opcionalmente ``adset_id``).
        plataforma_map: Mapa ``{nome: id}`` de dim_plataforma.
        conta_map: Mapa ``{(external_id, plataforma_id): id}`` de dim_conta.
        campanha_map: Mapa ``{(external_id, conta_id): id}`` de dim_campanha.
        adset_map: Mapa ``{(external_id, campanha_id): id}`` de dim_adset.
            Se fornecido, a resolução desce até o nível adset.

    Returns:
        Tupla de IDs internos resolvidos, na ordem
        ``(plat_id, conta_id, camp_id)`` ou
        ``(plat_id, conta_id, camp_id, adset_id)`` quando adset_map é fornecido.
    """
    plat_id = plataforma_map[row["platform"]]
    conta_id = conta_map[(row["account_id"], plat_id)]
    camp_id = campanha_map[(row["campaign_id"], conta_id)]

    if adset_map is not None:
        adset_id = adset_map[(row["adset_id"], camp_id)]
        return (plat_id, conta_id, camp_id, adset_id)

    return (plat_id, conta_id, camp_id)


# ── Dimensões ────────────────────────────────────────────────


def upsert_dim_plataforma(
    session: Session, tables: dict[str, Table], df_dim: pd.DataFrame
) -> PlataformaMap:
    """Faz UPSERT na tabela dim_plataforma e retorna o mapa de IDs.

    Args:
        session: Sessão SQLAlchemy ativa.
        tables: Dicionário de tabelas refletidas.
        df_dim: DataFrame de dimensões com coluna ``platform``.

    Returns:
        Mapa ``{nome_plataforma: id_interno}``.
    """
    table = tables["dim_plataforma"]
    platforms = df_dim["platform"].unique()

    for nome in platforms:
        stmt = insert(table).values(nome=nome)
        stmt = stmt.on_conflict_do_update(
            index_elements=["nome"],
            set_={"nome": stmt.excluded.nome},
        )
        session.execute(stmt)

    session.flush()
    rows = session.execute(select(table.c.id, table.c.nome))
    plataforma_map: PlataformaMap = {r.nome: r.id for r in rows}
    logger.info("dim_plataforma: %d registros carregados.", len(plataforma_map))
    return plataforma_map


def upsert_dim_conta(
    session: Session,
    tables: dict[str, Table],
    df_dim: pd.DataFrame,
    plataforma_map: PlataformaMap,
) -> FkMap:
    """Faz UPSERT na tabela dim_conta e retorna o mapa de IDs.

    Args:
        session: Sessão SQLAlchemy ativa.
        tables: Dicionário de tabelas refletidas.
        df_dim: DataFrame de dimensões.
        plataforma_map: Mapa de IDs de dim_plataforma.

    Returns:
        Mapa ``{(external_id, plataforma_id): id_interno}``.
    """
    table = tables["dim_conta"]
    df_u = df_dim.drop_duplicates(subset=["account_id", "platform"])

    rows = [
        {
            "external_id": r["account_id"],
            "nome": r["account_name"],
            "plataforma_id": plataforma_map[r["platform"]],
        }
        for _, r in df_u.iterrows()
    ]

    if rows:
        stmt = insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["external_id", "plataforma_id"],
            set_={"nome": stmt.excluded.nome},
        )
        session.execute(stmt)

    session.flush()
    result = session.execute(select(table.c.id, table.c.external_id, table.c.plataforma_id))
    conta_map: FkMap = {(r.external_id, r.plataforma_id): r.id for r in result}
    logger.info("dim_conta: %d registros carregados.", len(conta_map))
    return conta_map


def upsert_dim_campanha(
    session: Session,
    tables: dict[str, Table],
    df_dim: pd.DataFrame,
    conta_map: FkMap,
    plataforma_map: PlataformaMap,
) -> FkMap:
    """Faz UPSERT na tabela dim_campanha e retorna o mapa de IDs.

    Args:
        session: Sessão SQLAlchemy ativa.
        tables: Dicionário de tabelas refletidas.
        df_dim: DataFrame de dimensões.
        conta_map: Mapa de IDs de dim_conta.
        plataforma_map: Mapa de IDs de dim_plataforma.

    Returns:
        Mapa ``{(external_id, conta_id): id_interno}``.
    """
    table = tables["dim_campanha"]
    df_u = df_dim.drop_duplicates(subset=["campaign_id", "account_id", "platform"])

    rows = [
        {
            "external_id": r["campaign_id"],
            "nome": r["campaign_name"],
            "conta_id": conta_map[(r["account_id"], plataforma_map[r["platform"]])],
        }
        for _, r in df_u.iterrows()
    ]

    if rows:
        stmt = insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["external_id", "conta_id"],
            set_={"nome": stmt.excluded.nome},
        )
        session.execute(stmt)

    session.flush()
    result = session.execute(select(table.c.id, table.c.external_id, table.c.conta_id))
    campanha_map: FkMap = {(r.external_id, r.conta_id): r.id for r in result}
    logger.info("dim_campanha: %d registros carregados.", len(campanha_map))
    return campanha_map


def upsert_dim_adset(
    session: Session,
    tables: dict[str, Table],
    df_dim: pd.DataFrame,
    campanha_map: FkMap,
    conta_map: FkMap,
    plataforma_map: PlataformaMap,
) -> FkMap:
    """Faz UPSERT na tabela dim_adset e retorna o mapa de IDs.

    Args:
        session: Sessão SQLAlchemy ativa.
        tables: Dicionário de tabelas refletidas.
        df_dim: DataFrame de dimensões.
        campanha_map: Mapa de IDs de dim_campanha.
        conta_map: Mapa de IDs de dim_conta.
        plataforma_map: Mapa de IDs de dim_plataforma.

    Returns:
        Mapa ``{(external_id, campanha_id): id_interno}``.
    """
    table = tables["dim_adset"]
    df_u = df_dim.drop_duplicates(
        subset=["adset_id", "campaign_id", "account_id", "platform"]
    )

    rows = []
    for _, r in df_u.iterrows():
        _, _, camp_id = _resolve_fk_chain(r, plataforma_map, conta_map, campanha_map)
        rows.append({
            "external_id": r["adset_id"],
            "nome": r["adset_name"],
            "campanha_id": camp_id,
        })

    if rows:
        stmt = insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["external_id", "campanha_id"],
            set_={"nome": stmt.excluded.nome},
        )
        session.execute(stmt)

    session.flush()
    result = session.execute(select(table.c.id, table.c.external_id, table.c.campanha_id))
    adset_map: FkMap = {(r.external_id, r.campanha_id): r.id for r in result}
    logger.info("dim_adset: %d registros carregados.", len(adset_map))
    return adset_map


def upsert_dim_anuncio(
    session: Session,
    tables: dict[str, Table],
    df_dim: pd.DataFrame,
    adset_map: FkMap,
    campanha_map: FkMap,
    conta_map: FkMap,
    plataforma_map: PlataformaMap,
) -> FkMap:
    """Faz UPSERT na tabela dim_anuncio e retorna o mapa de IDs.

    Args:
        session: Sessão SQLAlchemy ativa.
        tables: Dicionário de tabelas refletidas.
        df_dim: DataFrame de dimensões.
        adset_map: Mapa de IDs de dim_adset.
        campanha_map: Mapa de IDs de dim_campanha.
        conta_map: Mapa de IDs de dim_conta.
        plataforma_map: Mapa de IDs de dim_plataforma.

    Returns:
        Mapa ``{(external_id, adset_id): id_interno}``.
    """
    table = tables["dim_anuncio"]
    df_u = df_dim.drop_duplicates(subset=["ad_id"])

    rows = []
    for _, r in df_u.iterrows():
        *_, adset_id_internal = _resolve_fk_chain(
            r, plataforma_map, conta_map, campanha_map, adset_map
        )
        rows.append({
            "external_id": r["ad_id"],
            "nome": r["ad_name"],
            "adset_id": adset_id_internal,
        })

    if rows:
        stmt = insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["external_id", "adset_id"],
            set_={"nome": stmt.excluded.nome},
        )
        session.execute(stmt)

    session.flush()
    result = session.execute(select(table.c.id, table.c.external_id, table.c.adset_id))
    anuncio_map: FkMap = {(r.external_id, r.adset_id): r.id for r in result}
    logger.info("dim_anuncio: %d registros carregados.", len(anuncio_map))
    return anuncio_map


def upsert_dim_tempo(
    session: Session,
    tables: dict[str, Table],
    dates: np.ndarray,
) -> TempoMap:
    """Faz UPSERT na tabela dim_tempo e retorna o mapa de IDs.

    Deriva automaticamente os campos dia, mes, ano, trimestre e dia_semana
    a partir de cada data.

    Args:
        session: Sessão SQLAlchemy ativa.
        tables: Dicionário de tabelas refletidas.
        dates: Array de objetos ``datetime.date`` únicos.

    Returns:
        Mapa ``{date: id_interno}``.
    """
    table = tables["dim_tempo"]

    rows = [
        {
            "data": d,
            "dia": d.day,
            "mes": d.month,
            "ano": d.year,
            "trimestre": (d.month - 1) // 3 + 1,
            "dia_semana": d.isoweekday(),
        }
        for d in dates
    ]

    if rows:
        stmt = insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["data"],
            set_={
                "dia": stmt.excluded.dia,
                "mes": stmt.excluded.mes,
                "ano": stmt.excluded.ano,
                "trimestre": stmt.excluded.trimestre,
                "dia_semana": stmt.excluded.dia_semana,
            },
        )
        session.execute(stmt)

    session.flush()
    result = session.execute(select(table.c.id, table.c.data))
    tempo_map: TempoMap = {r.data: r.id for r in result}
    logger.info("dim_tempo: %d registros carregados.", len(tempo_map))
    return tempo_map


# ── Mapa auxiliar ad_id → anuncio_id ─────────────────────────


def build_ad_id_map(
    df_dim: pd.DataFrame,
    plataforma_map: PlataformaMap,
    conta_map: FkMap,
    campanha_map: FkMap,
    adset_map: FkMap,
    anuncio_map: FkMap,
) -> AdIdMap:
    """Constrói um mapa de conveniência de ad_id externo para anuncio_id interno.

    Percorre a hierarquia completa de FKs para resolver cada anúncio
    único do DataFrame de dimensões.

    Args:
        df_dim: DataFrame de dimensões.
        plataforma_map: Mapa de IDs de dim_plataforma.
        conta_map: Mapa de IDs de dim_conta.
        campanha_map: Mapa de IDs de dim_campanha.
        adset_map: Mapa de IDs de dim_adset.
        anuncio_map: Mapa de IDs de dim_anuncio.

    Returns:
        Mapa ``{ad_external_id: anuncio_internal_id}``.
    """
    ad_id_map: AdIdMap = {}
    for _, r in df_dim.drop_duplicates(subset=["ad_id"]).iterrows():
        *_, adset_id = _resolve_fk_chain(
            r, plataforma_map, conta_map, campanha_map, adset_map
        )
        anuncio_id = anuncio_map[(r["ad_id"], adset_id)]
        ad_id_map[r["ad_id"]] = anuncio_id
    return ad_id_map


# ── Tabela Fato ──────────────────────────────────────────────


def upsert_fato_metricas(
    session: Session,
    tables: dict[str, Table],
    df_fato: pd.DataFrame,
    ad_id_map: AdIdMap,
    tempo_map: TempoMap,
) -> None:
    """Faz UPSERT na tabela fato_metricas com as metricas diarias.

    Em caso de conflito na chave composta ``(anuncio_id, tempo_id)``,
    atualiza todas as 9 colunas de metricas: ``spend``, ``impressions``,
    ``link_clicks``, ``conversions``, ``conversion_value``, ``video_views``,
    ``reach``, ``profile_views`` e ``purchases``.

    Args:
        session: Sessao SQLAlchemy ativa.
        tables: Dicionario de tabelas refletidas.
        df_fato: DataFrame com metricas diarias.
        ad_id_map: Mapa ``{ad_external_id: anuncio_internal_id}``.
        tempo_map: Mapa ``{date: tempo_internal_id}``.
    """
    table = tables["fato_metricas"]

    rows = []
    for _, r in df_fato.iterrows():
        rows.append({
            "anuncio_id": ad_id_map[r["ad_id"]],
            "tempo_id": tempo_map[r["date"]],
            "spend": r["spend"],
            "impressions": int(r["impressions"]),
            "link_clicks": int(r["link_clicks"]),
            "conversions": int(r["conversions"]),
            "conversion_value": r["conversion_value"],
            "video_views": int(r["video_views"]),
            "reach": int(r["reach"]),
            "profile_views": int(r["profile_views"]),
            "purchases": int(r["purchases"]),
        })

    if rows:
        stmt = insert(table).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["anuncio_id", "tempo_id"],
            set_={col: stmt.excluded[col] for col in METRIC_COLS},
        )
        session.execute(stmt)

    session.flush()
    logger.info("fato_metricas: %d registros carregados.", len(rows))


# ── Main ─────────────────────────────────────────────────────


def run() -> int:
    """Executa a carga completa no Supabase a partir dos CSVs transformados.

    Faz UPSERT nas tabelas de dimensão (respeitando a hierarquia de FKs)
    e na tabela fato, tudo dentro de uma única transação.

    Returns:
        Quantidade de registros carregados na tabela fato.
    """
    engine = get_engine()
    tables = reflect_tables(engine)

    logger.info("Lendo CSVs de entrada...")
    df_dim = pd.read_csv(DIM_ADS_CSV, dtype=str)
    df_fato = pd.read_csv(FATO_CSV)
    df_fato["ad_id"] = df_fato["ad_id"].astype(str)
    df_fato["date"] = pd.to_datetime(df_fato["date"], format="mixed").dt.date

    unique_dates = df_fato["date"].unique()

    with Session(engine) as session:
        try:
            # Dimensões (ordem respeita FKs)
            plataforma_map = upsert_dim_plataforma(session, tables, df_dim)
            conta_map = upsert_dim_conta(session, tables, df_dim, plataforma_map)
            campanha_map = upsert_dim_campanha(session, tables, df_dim, conta_map, plataforma_map)
            adset_map = upsert_dim_adset(session, tables, df_dim, campanha_map, conta_map, plataforma_map)
            anuncio_map = upsert_dim_anuncio(
                session, tables, df_dim, adset_map, campanha_map, conta_map, plataforma_map
            )
            tempo_map = upsert_dim_tempo(session, tables, unique_dates)

            # Mapa de conveniência
            ad_id_map = build_ad_id_map(
                df_dim, plataforma_map, conta_map, campanha_map, adset_map, anuncio_map
            )

            # Tabela Fato
            upsert_fato_metricas(session, tables, df_fato, ad_id_map, tempo_map)

            session.commit()
            logger.info("Carga concluída com sucesso.")
            return len(df_fato)

        except Exception as exc:
            session.rollback()
            logger.error(
                "Erro durante a carga. Rollback realizado. Tipo: %s",
                type(exc).__name__,
            )
            raise


def main() -> None:
    """Entry point para execução standalone via CLI."""
    run()


if __name__ == "__main__":
    main()
