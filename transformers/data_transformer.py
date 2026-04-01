import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
META_RAW = BASE_DIR / "temp_meta_raw.json"
GOOGLE_RAW = BASE_DIR / "temp_google_raw.json"
OUTPUT_FATO = BASE_DIR / "temp_fato.csv"
OUTPUT_DIM_ADS = BASE_DIR / "temp_dim_ads.csv"

FATO_COLS = [
    "date", "ad_id", "spend", "impressions",
    "link_clicks", "conversions", "conversion_value", "video_views",
]
DIM_COLS = [
    "ad_id", "ad_name", "adset_id", "adset_name",
    "campaign_id", "campaign_name", "account_id", "account_name", "platform",
]


def _extract_from_actions(actions, keyword):
    """Soma os values de actions cujo action_type contenha a keyword."""
    if not isinstance(actions, list):
        return 0
    total = 0
    for entry in actions:
        if keyword in entry.get("action_type", ""):
            total += float(entry.get("value", 0))
    return total


def _extract_from_action_values(action_values, keyword):
    """Soma os values de action_values cujo action_type contenha a keyword."""
    if not isinstance(action_values, list):
        return 0
    total = 0
    for entry in action_values:
        if keyword in entry.get("action_type", ""):
            total += float(entry.get("value", 0))
    return total


def transform_meta(path):
    logger.info("Lendo dados brutos do Meta Ads: %s", path)
    df = pd.read_json(path)
    logger.info("Registros Meta carregados: %d", len(df))

    df["spend"] = pd.to_numeric(df["spend"], errors="coerce").fillna(0)
    df["impressions"] = pd.to_numeric(df["impressions"], errors="coerce").fillna(0).astype(int)
    df["inline_link_clicks"] = pd.to_numeric(
        df.get("inline_link_clicks", 0), errors="coerce"
    ).fillna(0).astype(int)

    df.rename(columns={
        "date_start": "date",
        "inline_link_clicks": "link_clicks",
    }, inplace=True)

    df["conversions"] = df.apply(
        lambda r: (
            _extract_from_actions(r.get("actions"), "conversion")
            + _extract_from_actions(r.get("actions"), "lead")
        ), axis=1,
    )
    df["conversion_value"] = df.apply(
        lambda r: (
            _extract_from_action_values(r.get("action_values"), "conversion")
            + _extract_from_action_values(r.get("action_values"), "lead")
        ), axis=1,
    )
    df["video_views"] = df.apply(
        lambda r: _extract_from_actions(r.get("actions"), "video_view"), axis=1,
    ).astype(int)

    df["platform"] = "Meta Ads"

    df.drop(columns=["date_stop", "actions", "action_values"], inplace=True, errors="ignore")
    logger.info("Transformação Meta concluída.")
    return df


def transform_google(path):
    logger.info("Lendo dados brutos do Google Ads: %s", path)
    df = pd.read_json(path)
    logger.info("Registros Google carregados: %d", len(df))

    df.rename(columns={
        "cost": "spend",
        "clicks": "link_clicks",
        "ad_group_id": "adset_id",
        "ad_group_name": "adset_name",
    }, inplace=True)

    df["video_views"] = 0
    df["platform"] = "Google Ads"

    # Google já retorna conversions e conversions_value; renomear para padrão
    df.rename(columns={"conversions_value": "conversion_value"}, inplace=True)

    logger.info("Transformação Google concluída.")
    return df


def main():
    df_meta = transform_meta(META_RAW)
    df_google = transform_google(GOOGLE_RAW)

    df = pd.concat([df_meta, df_google], ignore_index=True)
    logger.info("DataFrames concatenados. Total: %d registros", len(df))

    # --- Tabela Fato ---
    df_fato = df[FATO_COLS].copy()
    df_fato.fillna(0, inplace=True)
    df_fato.to_csv(OUTPUT_FATO, index=False)
    logger.info("Fato salva em %s (%d registros)", OUTPUT_FATO, len(df_fato))
    print("\n=== df_fato.head() ===")
    print(df_fato.head().to_string())

    # --- Dimensão Anúncios ---
    df_dim_ads = df[DIM_COLS].copy()
    df_dim_ads.drop_duplicates(subset=["ad_id"], inplace=True)
    df_dim_ads.to_csv(OUTPUT_DIM_ADS, index=False)
    logger.info("Dimensão salva em %s (%d anúncios únicos)", OUTPUT_DIM_ADS, len(df_dim_ads))
    print("\n=== df_dim_ads.head() ===")
    print(df_dim_ads.head().to_string())


if __name__ == "__main__":
    main()
