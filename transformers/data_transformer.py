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
    "reach", "profile_views", "purchases",
]
DIM_COLS: list[str] = [
    "ad_id", "ad_name", "adset_id", "adset_name",
    "campaign_id", "campaign_name", "account_id", "account_name", "platform",
]


def _sum_action_values(
    entries: list[dict] | None, action_type: str
) -> float:
    """Soma os values de entries cujo action_type seja exatamente o informado.

    Args:
        entries: Lista de dicts ``{"action_type": ..., "value": ...}``
            retornada pela API do Meta (actions ou action_values), ou None.
        action_type: Valor exato esperado no campo ``action_type``.

    Returns:
        Soma dos valores correspondentes.
    """
    if not isinstance(entries, list):
        return 0
    total = 0.0
    for entry in entries:
        if entry.get("action_type") == action_type:
            total += float(entry.get("value", 0))
    return total


def transform_meta(path: Path) -> pd.DataFrame:
    """Transforma os dados brutos do Meta Ads para o formato padronizado.

    Normaliza nomes de colunas, converte ``reach`` (campo de primeiro nivel)
    para inteiro, extrai ``conversions``, ``video_views``, ``profile_views``
    e ``purchases`` das listas ``actions``/``action_values``, e adiciona a
    coluna ``platform``.

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
        lambda r: _sum_action_values(r.get("actions"), "lead"), axis=1,
    )
    df["conversion_value"] = df.apply(
        lambda r: _sum_action_values(r.get("action_values"), "lead"), axis=1,
    )
    df["video_views"] = df.apply(
        lambda r: _sum_action_values(r.get("actions"), "video_view"), axis=1,
    ).astype(int)

    df["reach"] = pd.to_numeric(df.get("reach", 0), errors="coerce").fillna(0).astype(int)

    df["profile_views"] = df.apply(
        lambda r: _sum_action_values(r.get("actions"), "onsite_conversion.ig_profile_view"),
        axis=1,
    ).astype(int)

    df["purchases"] = df.apply(
        lambda r: (
            _sum_action_values(r.get("actions"), "purchase")
            + _sum_action_values(r.get("actions"), "omni_purchase")
        ),
        axis=1,
    ).astype(int)

    df["platform"] = "Meta Ads"

    df.drop(columns=["date_stop", "actions", "action_values"], inplace=True, errors="ignore")
    logger.info("Transformação Meta concluída.")
    return df


def transform_google(path: Path) -> pd.DataFrame:
    """Transforma os dados brutos do Google Ads para o formato padronizado.

    Renomeia colunas para alinhar com o schema unificado, define
    ``video_views``, ``reach``, ``profile_views`` e ``purchases`` como ``0``
    (Google nao retorna essas metricas neste nivel de query GAQL) e
    adiciona a coluna ``platform``.

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
    df["reach"] = 0
    df["profile_views"] = 0
    df["purchases"] = 0
    df["platform"] = "Google Ads"

    logger.info("Transformação Google concluída.")
    return df


def run() -> tuple[int, int]:
    """Executa a transformação completa e gera os CSVs de dimensão e fato.

    Processa apenas as plataformas cujo arquivo bruto existe — o pipeline
    pode ter sido executado com ``--platforms`` restrito a uma delas.

    Returns:
        Tupla ``(total_fato, total_dim)`` com a contagem de registros gerados.

    Raises:
        FileNotFoundError: Se nenhum arquivo bruto estiver disponível.
    """
    frames: list[pd.DataFrame] = []

    for path, transform in ((META_RAW, transform_meta), (GOOGLE_RAW, transform_google)):
        if path.exists():
            frames.append(transform(path))
        else:
            logger.warning("Arquivo bruto ausente, plataforma ignorada: %s", path.name)

    if not frames:
        raise FileNotFoundError(
            "Nenhum arquivo bruto encontrado. Execute a extração antes da transformação."
        )

    df = pd.concat(frames, ignore_index=True)
    logger.info("DataFrames concatenados. Total: %d registros", len(df))

    # --- Tabela Fato ---
    df_fato = df[FATO_COLS].copy()
    df_fato.fillna(0, inplace=True)
    df_fato.to_csv(OUTPUT_FATO, index=False)
    logger.info("Fato salva em %s (%d registros)", OUTPUT_FATO, len(df_fato))

    # --- Dimensão Anúncios ---
    df_dim_ads = df[DIM_COLS].copy()
    df_dim_ads.drop_duplicates(subset=["ad_id"], inplace=True)
    df_dim_ads.to_csv(OUTPUT_DIM_ADS, index=False)
    logger.info("Dimensão salva em %s (%d anúncios únicos)", OUTPUT_DIM_ADS, len(df_dim_ads))

    return len(df_fato), len(df_dim_ads)


def main() -> None:
    """Entry point para execução standalone via CLI."""
    try:
        run()
    except Exception as exc:
        logger.error("Erro na transformação dos dados. Tipo: %s", type(exc).__name__)
        raise


if __name__ == "__main__":
    main()
