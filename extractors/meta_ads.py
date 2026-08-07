import logging
import os
from typing import Any

from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.business import Business
from facebook_business.api import FacebookAdsApi

from config import mask, validate_env
from extractors.comum import executar_cli, executar_extracao
from plataformas import PLATAFORMAS, Plataforma

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
    "reach",
    "actions",
    "action_values",
]

ACCOUNT_FIELDS: list[str] = ["account_id", "name", "account_status"]

ACCOUNT_STATUS_ACTIVE: int = 1

PLATAFORMA: Plataforma = PLATAFORMAS["meta"]


def init_api() -> None:
    """Inicializa a API do Meta Ads com as credenciais do .env.

    As credenciais já foram conferidas por ``validate_env`` em ``run``, que é a
    única fonte da lista de variáveis obrigatórias.
    """
    FacebookAdsApi.init(
        os.getenv("META_APP_ID"),
        os.getenv("META_APP_SECRET"),
        os.getenv("META_ACCESS_TOKEN"),
    )
    logger.info("API do Meta Ads inicializada.")


def _paginate_accounts(cursor: Any) -> dict[str, dict]:
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
    """
    business_id = os.getenv("META_BUSINESS_ID", "")
    business = Business(business_id)
    params = {"limit": 100}

    logger.info("Buscando contas owned do Business ID: %s", mask(business_id))
    owned = _paginate_accounts(
        business.get_owned_ad_accounts(fields=ACCOUNT_FIELDS, params=params)
    )
    logger.info("Contas owned encontradas: %d", len(owned))

    logger.info("Buscando contas client do Business ID: %s", mask(business_id))
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


def extract_daily_ads(
    account_id: str, account_name: str, start_date: str, end_date: str
) -> list[dict]:
    """Extrai métricas a nível de anúncio para uma conta num período.

    Args:
        account_id: ID da conta de anúncios (com ou sem prefixo ``act_``).
        account_name: Nome descritivo da conta.
        start_date: Data inicial no formato ``YYYY-MM-DD``.
        end_date: Data final no formato ``YYYY-MM-DD``.

    Returns:
        Lista de dicts com campos de hierarquia e métricas por anúncio.
    """
    account = AdAccount(f"act_{account_id.removeprefix('act_')}")

    params = {
        "level": "ad",
        "time_range": {"since": start_date, "until": end_date},
        "time_increment": 1,
    }

    logger.info(
        "Processando conta: %s (ID: %s) — período: %s a %s",
        account_name, mask(account_id), start_date, end_date,
    )
    cursor = account.get_insights(fields=INSIGHT_FIELDS, params=params)

    rows: list[dict] = []
    for item in cursor:
        row = dict(item)
        row["account_id"] = account_id
        row["account_name"] = account_name
        rows.append(row)

    logger.info("Registros extraídos da conta %s: %d", mask(account_id), len(rows))
    return rows


def run(start_date: str, end_date: str) -> int:
    """Executa a extração completa do Meta Ads para o período informado.

    Args:
        start_date: Data inicial no formato ``YYYY-MM-DD``.
        end_date: Data final no formato ``YYYY-MM-DD``.

    Returns:
        Quantidade total de registros extraídos.

    Raises:
        SystemExit: Se alguma credencial obrigatória estiver ausente.
    """
    validate_env(groups=[PLATAFORMA.nome])
    init_api()

    return executar_extracao(
        PLATAFORMA,
        descobrir_contas=discover_accounts,
        extrair_conta=extract_daily_ads,
        start_date=start_date,
        end_date=end_date,
    )


def main() -> None:
    """Entry point para execução standalone via CLI."""
    executar_cli(PLATAFORMA, run)


if __name__ == "__main__":
    main()
