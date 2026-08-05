"""Validacao centralizada de variaveis de ambiente e utilitarios de seguranca.

A funcao ``validate_env()`` garante que todas as credenciais obrigatorias
existam antes de qualquer modulo do pipeline ser executado.  Se alguma
variavel faltar, o processo encerra imediatamente com mensagem clara
(sem expor valores).  A funcao ``mask()`` oculta parcialmente valores
sensiveis para uso seguro em logs.
"""

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Variaveis obrigatorias por modulo ──────────────────────────

_REQUIRED_VARS: dict[str, list[str]] = {
    "Meta Ads": [
        "META_APP_ID",
        "META_APP_SECRET",
        "META_ACCESS_TOKEN",
        "META_BUSINESS_ID",
    ],
    "Google Ads": [
        "GOOGLE_DEVELOPER_TOKEN",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
        "GOOGLE_LOGIN_CUSTOMER_ID",
    ],
}

# Variaveis alternativas: basta uma delas estar definida.
# DW_DB_URL aponta para o Data Warehouse (local ou Supabase); SUPABASE_DB_URL
# permanece aceita por compatibilidade com a configuracao original.
_DB_URL_VARS: list[str] = ["DW_DB_URL", "SUPABASE_DB_URL"]


def get_db_url() -> str | None:
    """Retorna a URL de conexao do Data Warehouse.

    Returns:
        Primeiro valor definido entre ``DW_DB_URL`` e ``SUPABASE_DB_URL``,
        ou ``None`` se nenhuma estiver preenchida.
    """
    for var in _DB_URL_VARS:
        value = os.getenv(var)
        if value:
            return value
    return None


def dbt_env() -> dict[str, str]:
    """Traduz a URL do Data Warehouse em variaveis de ambiente do dbt.

    O ``profiles.yml`` le ``DBT_HOST``, ``DBT_PORT``, ``DBT_USER``,
    ``DBT_PASSWORD`` e ``DBT_DBNAME``. Derivar esses valores de
    ``DW_DB_URL`` mantem uma unica fonte de verdade para a conexao: mudar a
    URL move o pipeline inteiro, Python e dbt, para o mesmo banco.

    Returns:
        Mapa de variaveis de ambiente para injetar no processo do dbt.
        Vazio se a URL nao estiver definida (o dbt cai nos defaults).
    """
    from urllib.parse import unquote, urlparse

    db_url = get_db_url()
    if not db_url:
        return {}

    parsed = urlparse(db_url)
    env: dict[str, str] = {}
    if parsed.hostname:
        env["DBT_HOST"] = parsed.hostname
    if parsed.port:
        env["DBT_PORT"] = str(parsed.port)
    if parsed.username:
        env["DBT_USER"] = unquote(parsed.username)
    if parsed.password:
        env["DBT_PASSWORD"] = unquote(parsed.password)
    if parsed.path and parsed.path != "/":
        env["DBT_DBNAME"] = parsed.path.lstrip("/")
    return env


def validate_env(groups: list[str] | None = None) -> None:
    """Valida que as variaveis de ambiente obrigatorias estao definidas.

    Args:
        groups: Grupos de credenciais a validar (ex: ``["Meta Ads"]``).
            Se ``None``, valida todos. A URL do banco e sempre exigida.

    Raises:
        SystemExit: Se alguma variavel estiver ausente.
    """
    selected = _REQUIRED_VARS if groups is None else {
        g: _REQUIRED_VARS[g] for g in groups if g in _REQUIRED_VARS
    }

    missing: list[str] = []
    for group, var_names in selected.items():
        for var in var_names:
            if not os.getenv(var):
                missing.append(f"  - {var} ({group})")

    if not get_db_url():
        missing.append(f"  - {' ou '.join(_DB_URL_VARS)} (Data Warehouse)")

    if missing:
        logger.error(
            "Variaveis de ambiente obrigatorias ausentes:\n%s",
            "\n".join(missing),
        )
        sys.exit(1)


# ── Utilitario de mascaramento para logs ───────────────────────


def mask(value: str | None, visible: int = 4) -> str:
    """Retorna uma versao mascarada de ``value`` para uso seguro em logs.

    Args:
        value: Valor a mascarar. Se ``None`` ou vazio, retorna ``"***"``.
        visible: Quantidade de caracteres finais visiveis (default 4).

    Returns:
        String no formato ``"***<ultimos N chars>"``.
    """
    if not value:
        return "***"
    if len(value) <= visible:
        return "***"
    return f"***{value[-visible:]}"
