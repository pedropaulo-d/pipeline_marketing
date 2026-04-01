import logging
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, MetaData, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DIM_ADS_CSV = BASE_DIR / "temp_dim_ads.csv"
FATO_CSV = BASE_DIR / "temp_fato.csv"

METRIC_COLS = [
    "spend", "impressions", "link_clicks",
    "conversions", "conversion_value", "video_views",
]


def get_engine():
    db_url = os.getenv("SUPABASE_DB_URL")
    if not db_url:
        raise EnvironmentError("Variável SUPABASE_DB_URL é obrigatória no .env")
    return create_engine(db_url)


def reflect_tables(engine):
    metadata = MetaData()
    metadata.reflect(bind=engine)
    return metadata.tables


# ── Dimensões ────────────────────────────────────────────────


def upsert_dim_plataforma(session, tables, df_dim):
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
    plataforma_map = {r.nome: r.id for r in rows}
    logger.info("dim_plataforma: %d registros carregados.", len(plataforma_map))
    return plataforma_map


def upsert_dim_conta(session, tables, df_dim, plataforma_map):
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
    conta_map = {(r.external_id, r.plataforma_id): r.id for r in result}
    logger.info("dim_conta: %d registros carregados.", len(conta_map))
    return conta_map


def upsert_dim_campanha(session, tables, df_dim, conta_map, plataforma_map):
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
    campanha_map = {(r.external_id, r.conta_id): r.id for r in result}
    logger.info("dim_campanha: %d registros carregados.", len(campanha_map))
    return campanha_map


def upsert_dim_adset(session, tables, df_dim, campanha_map, conta_map, plataforma_map):
    table = tables["dim_adset"]
    df_u = df_dim.drop_duplicates(
        subset=["adset_id", "campaign_id", "account_id", "platform"]
    )

    rows = []
    for _, r in df_u.iterrows():
        plat_id = plataforma_map[r["platform"]]
        conta_id = conta_map[(r["account_id"], plat_id)]
        camp_id = campanha_map[(r["campaign_id"], conta_id)]
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
    adset_map = {(r.external_id, r.campanha_id): r.id for r in result}
    logger.info("dim_adset: %d registros carregados.", len(adset_map))
    return adset_map


def upsert_dim_anuncio(session, tables, df_dim, adset_map, campanha_map,
                        conta_map, plataforma_map):
    table = tables["dim_anuncio"]
    df_u = df_dim.drop_duplicates(subset=["ad_id"])

    rows = []
    for _, r in df_u.iterrows():
        plat_id = plataforma_map[r["platform"]]
        conta_id = conta_map[(r["account_id"], plat_id)]
        camp_id = campanha_map[(r["campaign_id"], conta_id)]
        adset_id = adset_map[(r["adset_id"], camp_id)]
        rows.append({
            "external_id": r["ad_id"],
            "nome": r["ad_name"],
            "adset_id": adset_id,
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
    anuncio_map = {(r.external_id, r.adset_id): r.id for r in result}
    logger.info("dim_anuncio: %d registros carregados.", len(anuncio_map))
    return anuncio_map


def upsert_dim_tempo(session, tables, dates):
    table = tables["dim_tempo"]

    rows = []
    for d in dates:
        rows.append({
            "data": d,
            "dia": d.day,
            "mes": d.month,
            "ano": d.year,
            "trimestre": (d.month - 1) // 3 + 1,
            "dia_semana": d.isoweekday(),
        })

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
    tempo_map = {r.data: r.id for r in result}
    logger.info("dim_tempo: %d registros carregados.", len(tempo_map))
    return tempo_map


# ── Mapa auxiliar ad_id → anuncio_id ─────────────────────────


def build_ad_id_map(df_dim, plataforma_map, conta_map, campanha_map,
                    adset_map, anuncio_map):
    ad_id_map = {}
    for _, r in df_dim.drop_duplicates(subset=["ad_id"]).iterrows():
        plat_id = plataforma_map[r["platform"]]
        conta_id = conta_map[(r["account_id"], plat_id)]
        camp_id = campanha_map[(r["campaign_id"], conta_id)]
        adset_id = adset_map[(r["adset_id"], camp_id)]
        anuncio_id = anuncio_map[(r["ad_id"], adset_id)]
        ad_id_map[r["ad_id"]] = anuncio_id
    return ad_id_map


# ── Tabela Fato ──────────────────────────────────────────────


def upsert_fato_metricas(session, tables, df_fato, ad_id_map, tempo_map):
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


def main():
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

        except Exception:
            session.rollback()
            logger.exception("Erro durante a carga. Rollback realizado.")
            raise


if __name__ == "__main__":
    main()
