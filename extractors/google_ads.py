import json
import logging
from pathlib import Path

from dotenv import load_dotenv
import os

from google.ads.googleads.client import GoogleAdsClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

GAQL_DISCOVERY = """
    SELECT
        customer_client.id,
        customer_client.descriptive_name,
        customer_client.status,
        customer_client.manager
    FROM customer_client
    WHERE customer_client.status = 'ENABLED'
      AND customer_client.manager = FALSE
"""

GAQL_ADS = """
    SELECT
        customer.id,
        customer.descriptive_name,
        campaign.id,
        campaign.name,
        ad_group.id,
        ad_group.name,
        ad_group_ad.ad.id,
        ad_group_ad.ad.name,
        segments.date,
        metrics.impressions,
        metrics.clicks,
        metrics.cost_micros,
        metrics.conversions,
        metrics.conversions_value
    FROM ad_group_ad
    WHERE segments.date DURING YESTERDAY
      AND campaign.status = 'ENABLED'
"""

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "temp_google_raw.json"


def init_client():
    required = [
        "GOOGLE_DEVELOPER_TOKEN",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
        "GOOGLE_LOGIN_CUSTOMER_ID",
    ]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        raise EnvironmentError(
            f"Variáveis obrigatórias ausentes no .env: {', '.join(missing)}"
        )

    config = {
        "developer_token": os.getenv("GOOGLE_DEVELOPER_TOKEN"),
        "client_id": os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "refresh_token": os.getenv("GOOGLE_REFRESH_TOKEN"),
        "login_customer_id": os.getenv("GOOGLE_LOGIN_CUSTOMER_ID"),
        "use_proto_plus": False,
    }

    client = GoogleAdsClient.load_from_dict(config)
    logger.info("GoogleAdsClient inicializado.")
    return client


def discover_accounts(client):
    login_id = os.getenv("GOOGLE_LOGIN_CUSTOMER_ID")
    ga_service = client.get_service("GoogleAdsService")

    logger.info("Buscando subcontas ativas via customer_client (MCC: %s)", login_id)
    response = ga_service.search(customer_id=login_id, query=GAQL_DISCOVERY)

    accounts = []
    for row in response:
        cc = row.customer_client
        accounts.append({
            "id": str(cc.id),
            "name": cc.descriptive_name,
        })

    logger.info("Subcontas ativas encontradas: %d", len(accounts))
    return accounts


def extract_daily_ads(client, account_id, account_name):
    ga_service = client.get_service("GoogleAdsService")

    logger.info("Processando conta: %s (ID: %s)", account_name, account_id)
    response = ga_service.search(customer_id=account_id, query=GAQL_ADS)

    rows = []
    for row in response:
        rows.append({
            "date": row.segments.date,
            "account_id": str(row.customer.id),
            "account_name": row.customer.descriptive_name,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "ad_id": str(row.ad_group_ad.ad.id),
            "ad_name": row.ad_group_ad.ad.name,
            "impressions": row.metrics.impressions,
            "clicks": row.metrics.clicks,
            "cost": row.metrics.cost_micros / 1_000_000,
            "conversions": row.metrics.conversions,
            "conversions_value": row.metrics.conversions_value,
        })

    logger.info("Registros extraídos da conta %s: %d", account_id, len(rows))
    return rows


def save_raw(rows):
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    logger.info("Dados brutos salvos em %s (%d registros)", OUTPUT_PATH, len(rows))


def main():
    client = init_client()
    accounts = discover_accounts(client)

    all_rows = []
    for acc in accounts:
        rows = extract_daily_ads(client, acc["id"], acc["name"])
        all_rows.extend(rows)

    save_raw(all_rows)
    logger.info("Extração concluída. Total geral: %d registros", len(all_rows))


if __name__ == "__main__":
    main()
