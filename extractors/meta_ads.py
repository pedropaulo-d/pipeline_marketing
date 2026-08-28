import logging
import os
from collections import Counter
from typing import Any

from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.business import Business
from facebook_business.api import FacebookAdsApi

from config import mask, validate_env
from extractors.comum import executar_cli, executar_extracao
from extractors.meta_rate_limit import (
    Coletor, observar_cursor, observar_excecao,
)
from plataformas import PLATAFORMAS, Plataforma

logger = logging.getLogger(__name__)

# Telemetria passiva dos headers de uso que a Meta ja devolve. Vive no modulo
# porque `executar_extracao` e comum as duas plataformas e nao deve conhecer
# detalhe do SDK do Meta. Ver `extractors/meta_rate_limit.py`.
_COLETOR: Coletor = Coletor()

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
    "objective",
    "optimization_goal",
    "results",
    "cost_per_result",
]

ACCOUNT_FIELDS: list[str] = ["account_id", "name", "account_status"]

# Estado de entrega atual nao decide se a conta participa de uma consulta
# historica. Contas desabilitadas, em revisao, sem saldo ou em fechamento ainda
# podem ter insights de dias anteriores. Os valores vem do enum do SDK
# instalado, para nao duplicar numeros magicos do contrato da Meta.
ACCOUNT_STATUSES_CONSULTAVEIS: frozenset[int] = frozenset({
    AdAccount.AccountStatus.active,
    AdAccount.AccountStatus.disabled,
    AdAccount.AccountStatus.unsettled,
    AdAccount.AccountStatus.pending_review,
    AdAccount.AccountStatus.in_grace_period,
    AdAccount.AccountStatus.pending_closure,
})

# Estado em que a conta existe mas a API nao a serve agora. Nao entra na
# extracao e nao aborta: e lacuna de cobertura conhecida, registrada em log
# agregado. Ver `_selecionar_contas_consultaveis`.
ACCOUNT_STATUSES_INDISPONIVEIS: frozenset[int] = frozenset({
    AdAccount.AccountStatus.temporarily_unavailable,
})

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


def _selecionar_contas_consultaveis(contas: list[dict]) -> list[dict]:
    """Seleciona contas que podem participar de consultas historicas.

    O status descreve a situacao atual de entrega/faturamento, nao a
    existencia de metricas passadas. Por isso todos os estados conhecidos em
    que a conta continua consultavel entram.

    ``temporarily_unavailable`` e **lacuna de cobertura conhecida e
    auditavel**, nao motivo para abortar o lote inteiro. A conta nesse estado
    sai desta execucao, e so ela; as demais seguem normalmente. Nada e
    inventado no lugar dela: sem linha artificial, sem zero, sem tombstone. A
    Silver escolhe a observacao mais recente por entidade × dia pela chave
    hierarquica natural, entao ausencia numa execucao **nao** apaga a ultima
    observacao conhecida — foi essa mudanca que tornou o aborto desnecessario.
    Ausencia continua nao sendo prova de completude.

    Status nao classificado continua abortando: ali o contrato mudou e nao ha
    o que assumir.

    Args:
        contas: Contas deduplicadas retornadas pelo Business.

    Returns:
        Contas aptas a uma tentativa de consulta historica.

    Raises:
        ValueError: Se o SDK devolver um status ainda nao classificado.
    """
    por_status = Counter(conta["status"] for conta in contas)
    desconhecidos = {
        status: quantidade
        for status, quantidade in por_status.items()
        if status not in ACCOUNT_STATUSES_CONSULTAVEIS
        and status not in ACCOUNT_STATUSES_INDISPONIVEIS
    }

    # O desconhecido decide primeiro: contrato novo nao vira exclusao de
    # rotina so porque veio junto de uma indisponibilidade conhecida.
    if desconhecidos:
        resumo = ", ".join(
            f"status {status}: {quantidade}"
            for status, quantidade in sorted(desconhecidos.items())
        )
        raise ValueError(
            "Descoberta Meta devolveu status nao classificado "
            f"({resumo}). A extracao foi abortada para revisao."
        )

    indisponiveis = sum(
        quantidade
        for status, quantidade in por_status.items()
        if status in ACCOUNT_STATUSES_INDISPONIVEIS
    )
    if indisponiveis:
        # Agregado e sem identificador: registro de auditoria, nao relatorio
        # de clientes.
        logger.warning(
            "LACUNA DE COBERTURA CONHECIDA: %d conta(s) temporariamente "
            "indisponivel(is) fora desta execucao. Ausencia registrada como "
            "ausencia — nenhuma linha zerada foi inventada para elas.",
            indisponiveis,
        )

    return [
        conta
        for conta in contas
        if conta["status"] in ACCOUNT_STATUSES_CONSULTAVEIS
    ]


def discover_accounts() -> list[dict]:
    """Descobre contas consultaveis (owned + client) do Business.

    Returns:
        Lista de dicts com ``id``, ``name`` e ``status`` de cada conta que
        pode participar de uma consulta historica.
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
    consultaveis = _selecionar_contas_consultaveis(all_accounts)

    logger.info(
        "Contas consultaveis para historico: %d", len(consultaveis)
    )
    return consultaveis


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
    # `observar_cursor` le os headers de uso que cada pagina ja trouxe. Nao
    # emite request, nao muda a paginacao e nao toca no item devolvido.
    for item in observar_cursor(cursor, _COLETOR):
        row = dict(item)
        row["account_id"] = account_id
        row["account_name"] = account_name
        rows.append(row)

    logger.info("Registros extraídos da conta %s: %d", mask(account_id), len(rows))
    return rows


def run(start_date: str, end_date: str, run_id: str | None = None) -> int:
    """Executa a extração completa do Meta Ads para o período informado.

    Args:
        start_date: Data inicial no formato ``YYYY-MM-DD``.
        end_date: Data final no formato ``YYYY-MM-DD``.
        run_id: Identificador da execução, gravado no manifesto do artefato.

    Returns:
        Quantidade total de registros extraídos.

    Raises:
        SystemExit: Se alguma credencial obrigatória estiver ausente.
    """
    validate_env(groups=[PLATAFORMA.nome])
    init_api()

    try:
        total = executar_extracao(
            PLATAFORMA,
            descobrir_contas=discover_accounts,
            extrair_conta=extract_daily_ads,
            start_date=start_date,
            end_date=end_date,
            run_id=run_id,
        )
    except Exception as erro:
        # O 403 de limite carrega os headers de uso da resposta que o gerou —
        # a leitura mais informativa que existe, porque e o estado exato em que
        # a quota acabou. Ler nao trata: o erro segue subindo e a execucao
        # continua terminando em falha.
        observar_excecao(erro, _COLETOR)
        _COLETOR.registrar_resumo()
        raise

    _COLETOR.registrar_resumo()
    return total


def main() -> None:
    """Entry point para execução standalone via CLI."""
    executar_cli(PLATAFORMA, run)


if __name__ == "__main__":
    main()
