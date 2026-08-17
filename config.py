"""Validacao centralizada de variaveis de ambiente e utilitarios de seguranca.

A funcao ``validate_env()`` garante que todas as credenciais obrigatorias
existam antes de qualquer modulo do pipeline ser executado.  Se alguma
variavel faltar, o processo encerra imediatamente com mensagem clara
(sem expor valores).  A funcao ``mask()`` oculta parcialmente valores
sensiveis para uso seguro em logs.
"""

import logging
import os
import re
import sys
from datetime import datetime, timedelta
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv

from plataformas import PLATAFORMAS

# Unica chamada de load_dotenv() do projeto. Como todo modulo que precisa de
# variavel de ambiente importa este aqui, importar `config` e o que garante o
# .env carregado — nao ha razao para repetir a chamada em cada arquivo.
load_dotenv()

logger = logging.getLogger(__name__)

LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(message)s"


# ── Redacao de segredos ────────────────────────────────────────

# Marcador unico: procurar por ele num log responde "algo foi redigido aqui".
REDIGIDO: str = "***REDIGIDO***"

# Parametros que carregam segredo em query string, corpo de requisicao ou
# repr de dict. Preserva o NOME e apaga so o valor — diagnostico sem vazamento.
_PARAMETROS_SENSIVEIS: re.Pattern = re.compile(
    r"(?i)\b(access_token|refresh_token|developer_token|client_secret|"
    r"app_secret|appsecret_proof|password|api_key)"
    r"(\s*[=:]\s*[\"']?)([^\s\"'&,;}\)]+)"
)

# Formatos reconheciveis, para o caso de o segredo aparecer solto (sem o nome
# do parametro ao lado) — token do Meta, client secret e refresh token do
# Google.
_FORMATOS_DE_SEGREDO: tuple[re.Pattern, ...] = (
    re.compile(r"EAA[A-Za-z0-9]{20,}"),
    re.compile(r"GOCSPX-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"1//[A-Za-z0-9_\-]{20,}"),
)

# Variaveis cujo VALOR nunca pode aparecer em log. Derivadas do registro de
# plataformas: credencial nova entra na lista sozinha.
_NOMES_SECRETOS: tuple[str, ...] = ("SECRET", "TOKEN", "PASSWORD", "KEY")


def _valores_secretos() -> list[str]:
    """Coleta os valores de ambiente que nao podem vazar para log.

    Lidos a cada chamada, e nao no import: o ``.env`` pode ser carregado depois
    e o processo pode receber variaveis do orquestrador.

    Returns:
        Valores literais a suprimir, dos mais longos para os mais curtos (para
        que um segredo que contenha outro seja substituido primeiro).
    """
    valores: list[str] = []

    for plataforma in PLATAFORMAS.values():
        for nome in plataforma.variaveis_obrigatorias:
            if any(marca in nome.upper() for marca in _NOMES_SECRETOS):
                valor = os.getenv(nome)
                if valor and len(valor) >= 8:
                    valores.append(valor)

    # A senha do banco viaja dentro da URL, entao o valor a suprimir e so ela.
    for var in _DB_URL_VARS:
        url = os.getenv(var)
        if url:
            senha = urlparse(url).password
            if senha and len(senha) >= 8:
                valores.append(unquote(senha))

    return sorted(set(valores), key=len, reverse=True)


def redigir(texto: str) -> str:
    """Remove segredos de um texto destinado a log.

    Tres camadas, deliberadamente redundantes: os valores que estao no ambiente
    agora, os parametros conhecidos por nome e os formatos reconheciveis. A
    terceira cobre o caso em que o segredo nem esta no ambiente deste processo.

    O motivo e concreto: o SDK do Meta manda o token na query string, e uma
    falha de REDE (nao de API) faz o ``requests`` colocar a URL inteira na
    mensagem da excecao — ``...?access_token=EAA...``. O extrator roda como
    processo proprio na DAG, entao esse traceback iria cru para o log da task.

    Args:
        texto: Texto a sanitizar.

    Returns:
        O mesmo texto com cada segredo substituido por :data:`REDIGIDO`.
    """
    if not texto:
        return texto

    limpo = texto
    for valor in _valores_secretos():
        limpo = limpo.replace(valor, REDIGIDO)

    limpo = _PARAMETROS_SENSIVEIS.sub(rf"\1\2{REDIGIDO}", limpo)

    for formato in _FORMATOS_DE_SEGREDO:
        limpo = formato.sub(REDIGIDO, limpo)

    return limpo


class FormatadorSeguro(logging.Formatter):
    """Formatter que redige segredos, inclusive dentro de traceback.

    A sanitizacao acontece no formatter, e nao num ``logging.Filter``, porque o
    traceback so existe depois de formatado: um filtro veria a mensagem, mas
    nao o ``exc_info`` renderizado, que e justamente onde a URL com token
    apareceria.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Formata o registro e remove segredos do resultado.

        Args:
            record: Registro de log.

        Returns:
            Texto formatado e sanitizado.
        """
        return redigir(super().format(record))


def configurar_logging(nivel: int = logging.INFO) -> None:
    """Configura o logging do processo. Deve ser chamada pelos entrypoints.

    ``logging.basicConfig`` so tem efeito na primeira vez que roda: se o
    logging raiz ja tiver handler, a chamada e ignorada em silencio. Quando
    quatro modulos chamavam basicConfig no import, tres eram no-op e qual delas
    vencia dependia da ordem de importacao. Centralizar aqui torna a
    configuracao previsivel: quem inicia o processo configura, os modulos
    importados apenas pegam seu logger.

    Todo handler do logger raiz recebe :class:`FormatadorSeguro`, entao nenhum
    log deste processo pode imprimir credencial — nem no texto, nem no
    traceback.

    Args:
        nivel: Nivel minimo de log. Default ``logging.INFO``.
    """
    logging.basicConfig(level=nivel, format=LOG_FORMAT)

    for handler in logging.getLogger().handlers:
        handler.setFormatter(FormatadorSeguro(LOG_FORMAT))

# ── Variaveis obrigatorias por modulo ──────────────────────────

# Derivado do registro de plataformas: as credenciais de cada plataforma sao
# declaradas junto com o resto da configuracao dela, num lugar so.
_REQUIRED_VARS: dict[str, list[str]] = {
    p.nome: list(p.variaveis_obrigatorias) for p in PLATAFORMAS.values()
}

# Variaveis alternativas: basta uma delas estar definida.
# DW_DB_URL aponta para o Data Warehouse (local ou Supabase); SUPABASE_DB_URL
# permanece aceita por compatibilidade com a configuracao original.
_DB_URL_VARS: list[str] = ["DW_DB_URL", "SUPABASE_DB_URL"]


def ontem() -> str:
    """Retorna a data de ontem, default de periodo em todas as CLIs.

    Era recalculada em tres lugares (o parser do `main.py` e o dos dois
    extratores). Nao chegava a ser um bug, mas e a mesma decisao — "sem
    argumento, extraia o dia anterior" — escrita repetidas vezes.

    Returns:
        Data de ontem no formato ``YYYY-MM-DD``.
    """
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


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
