import argparse
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient

from config import mask
from plataformas import PLATAFORMAS

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

GAQL_DISCOVERY: str = """
    SELECT
        customer_client.id,
        customer_client.descriptive_name,
        customer_client.status,
        customer_client.manager
    FROM customer_client
    WHERE customer_client.status = 'ENABLED'
      AND customer_client.manager = FALSE
"""

# NAO filtrar por `campaign.status`: o status e o de HOJE, mas as metricas sao
# do dia consultado. Filtrar por 'ENABLED' faz a reextracao de um periodo
# passado perder as linhas das campanhas pausadas desde entao — e, como a
# silver adota o snapshot mais recente, o gasto ja carregado seria apagado do
# DW. Medido: uma campanha pausada levava consigo R$ 210,57 de 04/08/2026.
# Sem filtro, so retornam anuncios com entrega no periodo, que e o criterio
# correto: quem gastou naquele dia estava ativo naquele dia.
#
# `metrics.video_trueview_views` e o sucessor de `metrics.video_views`, que
# deixou de existir na v25 da API. A definicao NAO equivale a do Meta: o Google
# conta a visualizacao TrueView (30s, video completo ou interacao), enquanto o
# Meta conta a partir de 3 segundos. Somar as duas plataformas nessa metrica
# produz um numero sem significado — ver ressalva em stg_google_ads.sql.
GAQL_ADS_TEMPLATE: str = """
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
        metrics.conversions_value,
        metrics.video_trueview_views
    FROM ad_group_ad
    WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
"""

# Vem do registro, e nao de um literal repetido aqui: e exatamente o caminho
# que o bronze_loader vai ler depois.
OUTPUT_PATH: Path = PLATAFORMAS["google"].arquivo_bruto


def init_client() -> GoogleAdsClient:
    """Inicializa o GoogleAdsClient com as credenciais do .env.

    Returns:
        Instância configurada do GoogleAdsClient.

    Raises:
        EnvironmentError: Se alguma variável obrigatória estiver ausente.
    """
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


def discover_accounts(client: GoogleAdsClient) -> list[dict]:
    """Descobre subcontas ativas sob a conta MCC.

    Args:
        client: Instância autenticada do GoogleAdsClient.

    Returns:
        Lista de dicts com ``id`` e ``name`` de cada subconta ativa.
    """
    login_id: str = os.getenv("GOOGLE_LOGIN_CUSTOMER_ID", "")
    ga_service = client.get_service("GoogleAdsService")

    logger.info("Buscando subcontas ativas via customer_client (MCC: %s)", mask(login_id))
    response = ga_service.search(customer_id=login_id, query=GAQL_DISCOVERY)

    accounts: list[dict] = []
    for row in response:
        cc = row.customer_client
        accounts.append({
            "id": str(cc.id),
            "name": cc.descriptive_name,
        })

    logger.info("Subcontas ativas encontradas: %d", len(accounts))
    return accounts


def extract_daily_ads(
    client: GoogleAdsClient, account_id: str, account_name: str,
    start_date: str, end_date: str,
) -> list[dict]:
    """Extrai métricas a nível de anúncio para uma conta num período.

    Args:
        client: Instância autenticada do GoogleAdsClient.
        account_id: ID numérico da conta Google Ads.
        account_name: Nome descritivo da conta.
        start_date: Data inicial no formato ``YYYY-MM-DD``.
        end_date: Data final no formato ``YYYY-MM-DD``.

    Returns:
        Lista de dicts com campos de hierarquia e métricas por anúncio.
    """
    ga_service = client.get_service("GoogleAdsService")
    query = GAQL_ADS_TEMPLATE.format(start_date=start_date, end_date=end_date)

    logger.info(
        "Processando conta: %s (ID: %s) — período: %s a %s",
        account_name, mask(account_id), start_date, end_date,
    )
    response = ga_service.search(customer_id=account_id, query=query)

    rows: list[dict] = []
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
            "video_trueview_views": row.metrics.video_trueview_views,
        })

    logger.info("Registros extraídos da conta %s: %d", mask(account_id), len(rows))
    return rows


def save_raw(rows: list[dict]) -> None:
    """Salva a lista de registros brutos em JSON.

    Args:
        rows: Lista de dicts a serem serializados.
    """
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    logger.info("Dados brutos salvos em %s (%d registros)", OUTPUT_PATH, len(rows))


def run(start_date: str, end_date: str) -> int:
    """Executa a extração completa do Google Ads para o período informado.

    Args:
        start_date: Data inicial no formato ``YYYY-MM-DD``.
        end_date: Data final no formato ``YYYY-MM-DD``.

    Returns:
        Quantidade total de registros extraídos.
    """
    client = init_client()
    accounts = discover_accounts(client)

    all_rows: list[dict] = []
    for acc in accounts:
        rows = extract_daily_ads(client, acc["id"], acc["name"], start_date, end_date)
        all_rows.extend(rows)

    save_raw(all_rows)
    logger.info("Extração Google concluída. Total: %d registros", len(all_rows))
    return len(all_rows)


def _parse_args() -> argparse.Namespace:
    """Parseia argumentos de linha de comando para período de extração."""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(description="Extrator Google Ads")
    parser.add_argument("--start-date", default=yesterday, help="Data inicial (YYYY-MM-DD)")
    parser.add_argument("--end-date", default=yesterday, help="Data final (YYYY-MM-DD)")
    return parser.parse_args()


def main() -> None:
    """Entry point para execução standalone via CLI."""
    args = _parse_args()
    run(args.start_date, args.end_date)


if __name__ == "__main__":
    main()
