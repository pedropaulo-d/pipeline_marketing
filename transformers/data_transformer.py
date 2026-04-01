import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR: Path = Path(__file__).resolve().parent.parent
META_RAW: Path = BASE_DIR / "temp_meta_raw.json"
GOOGLE_RAW: Path = BASE_DIR / "temp_google_raw.json"
OUTPUT_FATO: Path = BASE_DIR / "temp_fato.csv"
OUTPUT_DIM_ADS: Path = BASE_DIR / "temp_dim_ads.csv"

FATO_COLS: list[str] = [
    "date", "ad_id", "spend", "impressions",
    "link_clicks", "conversions", "conversion_value", "video_views",
]
DIM_COLS: list[str] = [
    "ad_id", "ad_name", "adset_id", "adset_name",
    "campaign_id", "campaign_name", "account_id", "account_name", "platform",
]


def _extract_from_actions(actions: list[dict] | None, keyword: str) -> float:
    """Soma os values de actions cujo action_type contenha a keyword.

    Args:
        actions: Lista de dicts ``{"action_type": ..., "value": ...}``
            retornada pela API do Meta, ou None.
        keyword: Substring a procurar no campo ``action_type``.

    Returns:
        Soma dos valores correspondentes.
    """
    if not isinstance(actions, list):
        return 0
    total = 0.0
    for entry in actions:
        if keyword in entry.get("action_type", ""):
            total += float(entry.get("value", 0))
    return total


def _extract_from_action_values(
    action_values: list[dict] | None, keyword: str
) -> float:
    """Soma os values de action_values cujo action_type contenha a keyword.

    Args:
        action_values: Lista de dicts ``{"action_type": ..., "value": ...}``
            retornada pela API do Meta, ou None.
        keyword: Substring a procurar no campo ``action_type``.

    Returns:
        Soma dos valores monetários correspondentes.
    """
    if not isinstance(action_values, list):
        return 0
    total = 0.0
    for entry in action_values:
        if keyword in entry.get("action_type", ""):
            total += float(entry.get("value", 0))
    return total


def transform_meta(path: Path) -> pd.DataFrame:
    """Transforma os dados brutos do Meta Ads para o formato padronizado.

    Normaliza nomes de colunas, extrai conversões e video_views das
    listas ``actions``/``action_values``, e adiciona a coluna ``platform``.

    Args:
        path: Caminho para o arquivo JSON bruto do Meta.

    Returns:
        DataFrame com colunas padronizadas prontas para concatenação.
    """
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


def transform_google(path: Path) -> pd.DataFrame:
    """Transforma os dados brutos do Google Ads para o formato padronizado.

    Renomeia colunas para alinhar com o schema unificado, define
    ``video_views = 0`` (Google não retorna essa métrica neste nível)
    e adiciona a coluna ``platform``.

    Args:
        path: Caminho para o arquivo JSON bruto do Google.

    Returns:
        DataFrame com colunas padronizadas prontas para concatenação.
    """
    logger.info("Lendo dados brutos do Google Ads: %s", path)
    df = pd.read_json(path)
    logger.info("Registros Google carregados: %d", len(df))

    df.rename(columns={
        "cost": "spend",
        "clicks": "link_clicks",
        "ad_group_id": "adset_id",
        "ad_group_name": "adset_name",
        "conversions_value": "conversion_value",
    }, inplace=True)

    df["video_views"] = 0
    df["platform"] = "Google Ads"

    logger.info("Transformação Google concluída.")
    return df


def main() -> None:
    """Orquestra a transformação: lê JSONs brutos de cada plataforma,
    concatena em um DataFrame unificado e gera os CSVs de dimensão e fato.
    """
    try:
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

    except Exception:
        logger.exception("Erro na transformação dos dados.")
        raise


if __name__ == "__main__":
    main()
