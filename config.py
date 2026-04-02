"""Validacao centralizada de variaveis de ambiente e utilitarios de seguranca.

Importar ``settings`` garante que todas as credenciais obrigatorias existam
antes de qualquer modulo do pipeline ser executado.  Se alguma variavel faltar,
o processo encerra imediatamente com mensagem clara (sem expor valores).
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
    "Supabase": [
        "SUPABASE_DB_URL",
    ],
}


def validate_env() -> None:
    """Valida que todas as variaveis de ambiente obrigatorias estao definidas.

    Raises:
        SystemExit: Se alguma variavel estiver ausente.
    """
    missing: list[str] = []
    for group, var_names in _REQUIRED_VARS.items():
        for var in var_names:
            if not os.getenv(var):
                missing.append(f"  - {var} ({group})")

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
