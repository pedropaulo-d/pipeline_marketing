import importlib
import logging
import os
from collections import Counter
from functools import partial

from google.ads.googleads.client import _DEFAULT_VERSION, GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from config import mask, validate_env
from extractors.comum import executar_cli, executar_extracao
from plataformas import PLATAFORMAS, Plataforma

logger = logging.getLogger(__name__)

# `customer_client.manager` continua no WHERE de proposito: nao e estado de
# entrega, e o tipo do no da arvore. Conta gestora (MCC) nao tem `ad_group_ad`,
# entao consultar metricas nela e erro de dominio, nao perda de historia.
#
# O que saiu daqui foi `customer_client.status = 'ENABLED'`. O status descreve a
# situacao CORRENTE da conta, mas o produto da consulta e historico: uma conta
# cancelada, suspensa ou fechada hoje pode ter servido anuncios nos dias da
# janela. Excluir por ele na propria GAQL e o mesmo defeito do filtro por
# `campaign.status`, um nivel acima — e pior, porque a exclusao e silenciosa: a
# conta some da descoberta, o lote parece completo e a Silver, ao adotar o
# snapshot mais recente, deixaria de enxergar aquela entidade.
GAQL_DISCOVERY: str = """
    SELECT
        customer_client.id,
        customer_client.descriptive_name,
        customer_client.status,
        customer_client.manager
    FROM customer_client
    WHERE customer_client.manager = FALSE
"""

# O enum vem do SDK instalado, resolvido pela versao default da propria
# biblioteca, para nao duplicar numeros magicos do contrato do Google nem
# fixar uma versao de API no codigo. Uma troca de versao que mexa nesses
# valores quebra na suite (`tests/test_google_ads.py`), nao em producao.
CustomerStatus = importlib.import_module(
    f"google.ads.googleads.{_DEFAULT_VERSION}.enums"
).CustomerStatusEnum.CustomerStatus

# Estados em que a conta existe e pode ter servido anuncios no periodo
# consultado. Nenhum deles descreve ausencia de historico: `CANCELED` e
# reativavel por administrador, `SUSPENDED` pelo suporte do Google e `CLOSED` e
# permanente, mas nao apaga o que a conta ja entregou.
CUSTOMER_STATUSES_CONSULTAVEIS: frozenset[int] = frozenset({
    CustomerStatus.ENABLED,
    CustomerStatus.CANCELED,
    CustomerStatus.SUSPENDED,
    CustomerStatus.CLOSED,
})

# Nao existe aqui o equivalente ao `temporarily_unavailable` do Meta: a
# descoberta do Google nao declara indisponibilidade de acesso, ela so aparece
# como erro na consulta da conta. Por isso esta classificacao nao tem valvula
# opt-in — nao ha estado de descoberta que ela pudesse liberar. `UNSPECIFIED`
# (campo ausente) e `UNKNOWN` ("valor desconhecido nesta versao") sao contrato
# mudado, nao estado de conta, e abortam junto com qualquer valor fora do
# enum.

# Estados em que o servidor pode recusar a consulta com `CUSTOMER_NOT_ENABLED`
# sem que isso seja anomalia. Medido em 26/08/2026 sobre as 51 subcontas
# nao-ENABLED do MCC: 47 de 48 `CANCELED` e as 3 `CLOSED` recusaram; uma
# `CANCELED` respondeu normalmente. Sem esta tolerancia, uma unica conta
# desativada aborta toda extracao Google para sempre.
#
# `SUSPENDED` esta FORA de proposito: nenhuma subconta nesse estado apareceu na
# medicao, entao nao ha evidencia sobre o comportamento do servidor. Na duvida,
# fail closed — recusa vinda de conta suspensa aborta, e a politica so muda
# quando houver medicao.
CUSTOMER_STATUSES_DESATIVACAO_ESPERADA: frozenset[int] = frozenset({
    CustomerStatus.CANCELED,
    CustomerStatus.CLOSED,
})

# Codigo oficial de "conta nao acessivel porque nao esta habilitada ou foi
# desativada". Vem do enum do SDK, e a comparacao e por codigo — nunca por
# texto da mensagem, que muda sem aviso.
_AUTORIZACAO = importlib.import_module(
    f"google.ads.googleads.{_DEFAULT_VERSION}.errors"
).AuthorizationErrorEnum.AuthorizationError
CUSTOMER_NOT_ENABLED: int = int(_AUTORIZACAO.CUSTOMER_NOT_ENABLED)

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

PLATAFORMA: Plataforma = PLATAFORMAS["google"]


def init_client() -> GoogleAdsClient:
    """Inicializa o GoogleAdsClient com as credenciais do .env.

    As credenciais já foram conferidas por ``validate_env`` em ``run``, que é a
    única fonte da lista de variáveis obrigatórias.

    Returns:
        Instância configurada do GoogleAdsClient.
    """
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


def _selecionar_contas_consultaveis(contas: list[dict]) -> list[dict]:
    """Seleciona subcontas que podem participar de consultas historicas.

    O status de ``customer_client`` descreve a situacao corrente da conta, nao
    a existencia de metricas passadas. Por isso todos os estados conhecidos em
    que a conta ja existiu entram, inclusive os que nao servem mais anuncios.
    Um status nao classificado aborta a descoberta: seguir com as demais contas
    produziria um lote parcial que, ao vencer por dia na Silver, deixaria de
    enxergar a entidade omitida.

    Diferente do Meta, o contrato de descoberta do Google nao tem estado de
    indisponibilidade de acesso — ela so se manifesta como erro na consulta da
    conta. Logo nao ha desvio opt-in a oferecer aqui: ou o estado e conhecido e
    a conta e consultada, ou o contrato mudou e a extracao para.

    Args:
        contas: Subcontas devolvidas pela GAQL de descoberta, cada uma com
            ``id``, ``name`` e ``status``.

    Returns:
        Subcontas aptas a uma tentativa de consulta historica, na ordem em que
        vieram.

    Raises:
        ValueError: Se a API devolver um status ainda nao classificado —
            inclusive ``UNSPECIFIED`` e ``UNKNOWN``.
    """
    por_status = Counter(conta["status"] for conta in contas)
    desconhecidos = {
        status: quantidade
        for status, quantidade in por_status.items()
        if status not in CUSTOMER_STATUSES_CONSULTAVEIS
    }

    if desconhecidos:
        resumo = ", ".join(
            f"status {status}: {quantidade}"
            for status, quantidade in sorted(desconhecidos.items())
        )
        raise ValueError(
            "Descoberta Google devolveu status nao classificado "
            f"({resumo}). A extracao foi abortada para revisao."
        )

    return [
        conta
        for conta in contas
        if conta["status"] in CUSTOMER_STATUSES_CONSULTAVEIS
    ]


def discover_accounts(client: GoogleAdsClient) -> list[dict]:
    """Descobre subcontas consultaveis sob a conta MCC.

    A GAQL nao filtra por estado corrente: a classificacao acontece em Python,
    onde cada status conhecido fica explicito e um status novo aborta.

    Args:
        client: Instância autenticada do GoogleAdsClient.

    Returns:
        Lista de dicts com ``id``, ``name`` e ``status`` de cada subconta que
        pode participar de uma consulta historica.

    Raises:
        ValueError: Se a API devolver um status ainda nao classificado.
    """
    login_id: str = os.getenv("GOOGLE_LOGIN_CUSTOMER_ID", "")
    ga_service = client.get_service("GoogleAdsService")

    logger.info("Buscando subcontas via customer_client (MCC: %s)", mask(login_id))
    response = ga_service.search(customer_id=login_id, query=GAQL_DISCOVERY)

    accounts: list[dict] = []
    for row in response:
        cc = row.customer_client
        accounts.append({
            "id": str(cc.id),
            "name": cc.descriptive_name,
            "status": cc.status,
        })

    logger.info("Subcontas nao gestoras encontradas: %d", len(accounts))
    consultaveis = _selecionar_contas_consultaveis(accounts)

    # O resumo por status e sem identificador de proposito: e a evidencia de
    # que nenhuma conta saiu em silencio, nao um relatorio de clientes.
    logger.info(
        "Subcontas consultaveis para historico: %d (%s)",
        len(consultaveis),
        ", ".join(
            f"{CustomerStatus(status).name}: {quantidade}"
            for status, quantidade in sorted(
                Counter(conta["status"] for conta in consultaveis).items()
            )
        )
        or "nenhuma",
    )
    return consultaveis


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


def _e_somente_customer_not_enabled(excecao: GoogleAdsException) -> bool:
    """Informa se a falha e exclusivamente ``CUSTOMER_NOT_ENABLED``.

    A checagem e por codigo do enum e exige que TODOS os erros do
    ``GoogleAdsFailure`` sejam esse codigo. Falha mista ou de qualquer outro
    tipo devolve ``False`` e volta a subir: a tolerancia cobre desativacao de
    conta, nao erro de rede, de quota, de credencial ou de consulta.

    Args:
        excecao: Excecao levantada pelo SDK na consulta de uma conta.

    Returns:
        ``True`` somente se todo erro da falha for ``CUSTOMER_NOT_ENABLED``.
    """
    codigos = set()
    for erro in excecao.failure.errors:
        qual = type(erro.error_code).pb(erro.error_code).WhichOneof("error_code")
        codigos.add((qual, int(getattr(erro.error_code, qual)) if qual else None))
    return codigos == {("authorization_error", CUSTOMER_NOT_ENABLED)}


def _extrair_conta_tolerando_desativacao(
    client: GoogleAdsClient,
    status_por_conta: dict[str, int],
    excluidas: Counter,
    account_id: str,
    account_name: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Extrai uma conta, tolerando recusa esperada de conta desativada.

    A descoberta corrigida passou a oferecer contas `CANCELED` e `CLOSED`, que
    o servidor costuma recusar com ``CUSTOMER_NOT_ENABLED``. Sem esta borda,
    uma unica conta nesse estado derrubaria toda a extracao Google, porque a
    casca comum nao isola falha por conta.

    A conta recusada sai da execucao devolvendo **lista vazia**, que e ausencia
    de observacao — nao linha zerada. A Silver preserva a ultima observacao
    conhecida de entidade ausente, entao nada de historico e apagado por isso.

    A tolerancia e estreita de proposito: so o codigo oficial
    ``CUSTOMER_NOT_ENABLED``, so nos estados em que ela foi medida
    (:data:`CUSTOMER_STATUSES_DESATIVACAO_ESPERADA`). Recusa vinda de conta
    `ENABLED` ou `SUSPENDED` e anomalia e continua abortando.

    Args:
        client: Instância autenticada do GoogleAdsClient.
        status_por_conta: Status devolvido pela descoberta, por ``id`` de conta.
        excluidas: Acumulador por status, para o log agregado ao fim do run.
        account_id: ID numérico da conta Google Ads.
        account_name: Nome descritivo da conta.
        start_date: Data inicial no formato ``YYYY-MM-DD``.
        end_date: Data final no formato ``YYYY-MM-DD``.

    Returns:
        Registros da conta, ou lista vazia se a recusa for esperada.

    Raises:
        GoogleAdsException: Em qualquer falha que nao seja recusa esperada de
            conta desativada.
    """
    try:
        return extract_daily_ads(
            client, account_id, account_name, start_date, end_date
        )
    except GoogleAdsException as excecao:
        status = status_por_conta.get(account_id)
        esperada = (
            status in CUSTOMER_STATUSES_DESATIVACAO_ESPERADA
            and _e_somente_customer_not_enabled(excecao)
        )
        if not esperada:
            raise
        excluidas[status] += 1
        return []


def run(start_date: str, end_date: str, run_id: str | None = None) -> int:
    """Executa a extração completa do Google Ads para o período informado.

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
    client = init_client()

    # O status descoberto precisa alcancar a extracao para decidir se uma
    # recusa e esperada. A casca comum passa so `(id, nome, datas)` — e nao
    # deve mudar por causa do Google, senao o Meta paga por uma borda que nao
    # e dele. O mapa e preenchido pela descoberta e lido na extracao.
    status_por_conta: dict[str, int] = {}
    excluidas: Counter = Counter()

    def descobrir() -> list[dict]:
        contas = discover_accounts(client)
        status_por_conta.update(
            {conta["id"]: conta["status"] for conta in contas}
        )
        return contas

    total = executar_extracao(
        PLATAFORMA,
        descobrir_contas=descobrir,
        extrair_conta=partial(
            _extrair_conta_tolerando_desativacao,
            client,
            status_por_conta,
            excluidas,
        ),
        start_date=start_date,
        end_date=end_date,
        run_id=run_id,
    )

    if excluidas:
        # Agregado e sem identificador: e registro de auditoria, nao relatorio
        # de clientes.
        logger.warning(
            "Contas desativadas que recusaram a consulta (%s): %d no total. "
            "Ausencia registrada como ausencia — nenhuma linha zerada foi "
            "inventada para elas.",
            ", ".join(
                f"{CustomerStatus(status).name}: {quantidade}"
                for status, quantidade in sorted(excluidas.items())
            ),
            sum(excluidas.values()),
        )

    return total


def main() -> None:
    """Entry point para execução standalone via CLI."""
    executar_cli(PLATAFORMA, run)


if __name__ == "__main__":
    main()
