import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.business import Business
from facebook_business.api import FacebookAdsApi

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

INSIGHT_FIELDS: list[str] = [
    "campaign_id",
    "campaign_name",
    "adset_id",
    "adset_name",
    "ad_id",
    "ad_name",
    "spend",
    "impressions",
    "inline_link_clicks",
    "actions",
    "action_values",
]

ACCOUNT_FIELDS: list[str] = ["account_id", "name", "account_status"]

ACCOUNT_STATUS_ACTIVE: int = 1

OUTPUT_PATH: Path = Path(__file__).resolve().parent.parent / "temp_meta_raw.json"


def init_api() -> None:
    """Inicializa a API do Meta Ads com as credenciais do .env.

    Raises:
        EnvironmentError: Se META_APP_ID, META_APP_SECRET ou
            META_ACCESS_TOKEN não estiverem definidas.
    """
    app_id = os.getenv("META_APP_ID")
    app_secret = os.getenv("META_APP_SECRET")
    access_token = os.getenv("META_ACCESS_TOKEN")

    if not all([app_id, app_secret, access_token]):
        raise EnvironmentError(
            "Variáveis META_APP_ID, META_APP_SECRET e META_ACCESS_TOKEN são obrigatórias no .env"
        )

    FacebookAdsApi.init(app_id, app_secret, access_token)
    logger.info("API do Meta Ads inicializada.")


def _paginate_accounts(cursor) -> dict[str, dict]:
    """Percorre todas as páginas de um cursor de contas e retorna um dict
    sem duplicatas, indexado pelo account_id.

    Args:
        cursor: Cursor paginado retornado pela API do Meta.

    Returns:
        Dicionário ``{account_id: {"id", "name", "status"}}``.
    """
    accounts: dict[str, dict] = {}
    while True:
        for acc in cursor:
            acc_id = acc["account_id"]
            if acc_id not in accounts:
                accounts[acc_id] = {
                    "id": acc_id,
                    "name": acc["name"],
                    "status": acc["account_status"],
                }
        if cursor.load_next_page():
            logger.info("Carregando próxima página de contas...")
        else:
            break
    return accounts


def discover_accounts() -> list[dict]:
    """Descobre todas as contas de anúncio ativas (owned + client) do Business.

    Returns:
        Lista de dicts com ``id``, ``name`` e ``status`` de cada conta ativa.

    Raises:
        EnvironmentError: Se META_BUSINESS_ID não estiver definida.
    """
    business_id = os.getenv("META_BUSINESS_ID")
    if not business_id:
        raise EnvironmentError("Variável META_BUSINESS_ID é obrigatória no .env")

    business = Business(business_id)
    params = {"limit": 100}

    logger.info("Buscando contas owned do Business ID: %s", business_id)
    owned = _paginate_accounts(
        business.get_owned_ad_accounts(fields=ACCOUNT_FIELDS, params=params)
    )
    logger.info("Contas owned encontradas: %d", len(owned))

    logger.info("Buscando contas client do Business ID: %s", business_id)
    client = _paginate_accounts(
        business.get_client_ad_accounts(fields=ACCOUNT_FIELDS, params=params)
    )
    logger.info("Contas client encontradas: %d", len(client))

    merged = {**owned, **client}
    logger.info(
        "Total bruto (owned + client, sem duplicatas): %d", len(merged),
    )

    all_accounts = list(merged.values())
    active = [a for a in all_accounts if a["status"] == ACCOUNT_STATUS_ACTIVE]
    skipped = len(all_accounts) - len(active)

    logger.info("Contas ativas: %d | Ignoradas (inativas): %d", len(active), skipped)
    return active


def extract_daily_ads(account_id: str, account_name: str) -> list[dict]:
    """Extrai métricas do dia anterior a nível de anúncio para uma conta.

    Args:
        account_id: ID da conta de anúncios (com ou sem prefixo ``act_``).
        account_name: Nome descritivo da conta.

    Returns:
        Lista de dicts com campos de hierarquia e métricas por anúncio.
    """
    account = AdAccount(f"act_{account_id.removeprefix('act_')}")

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    params = {
        "level": "ad",
        "time_range": {"since": yesterday, "until": yesterday},
        "time_increment": 1,
    }

    logger.info("Processando conta: %s (ID: %s) — data: %s", account_name, account_id, yesterday)
    cursor = account.get_insights(fields=INSIGHT_FIELDS, params=params)

    rows: list[dict] = []
    for item in cursor:
        row = dict(item)
        row["account_id"] = account_id
        row["account_name"] = account_name
        rows.append(row)

    logger.info("Registros extraídos da conta %s: %d", account_id, len(rows))
    return rows


def save_raw(rows: list[dict]) -> None:
    """Salva a lista de registros brutos em JSON.

    Args:
        rows: Lista de dicts a serem serializados.
    """
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    logger.info("Dados brutos salvos em %s (%d registros)", OUTPUT_PATH, len(rows))


def main() -> None:
    """Orquestra a extração completa do Meta Ads: inicializa a API,
    descobre contas ativas e extrai métricas diárias de cada uma.
    """
    try:
        init_api()
        accounts = discover_accounts()

        all_rows: list[dict] = []
        for acc in accounts:
            rows = extract_daily_ads(acc["id"], acc["name"])
            all_rows.extend(rows)

        save_raw(all_rows)
        logger.info("Extração concluída. Total geral: %d registros", len(all_rows))

    except Exception:
        logger.exception("Erro na extração do Meta Ads.")
        raise


if __name__ == "__main__":
    main()
