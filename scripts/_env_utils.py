"""Utilitarios compartilhados pelos scripts que leem e escrevem no ``.env``.

Os dois scripts de OAuth — ``generate_google_refresh_token.py`` (servidor
local) e ``oauth_manual.py`` (copia-e-cola do code) — fazem o mesmo trabalho
por caminhos diferentes, e por isso terminam igual: gravar o refresh token
recem-emitido no ``.env``. Ambos existem de proposito, um e o fallback do
outro quando o servidor local nao funciona.

O que nao devia existir em duplicata era a gravacao. As duas implementacoes de
``_write_to_env`` eram quase identicas — e ja tinham DIVERGIDO: a do
``generate_`` conferia se o arquivo existe antes de escrever, a do
``oauth_manual`` nao, e estourava com ``FileNotFoundError`` no meio do fluxo,
depois do token ja emitido. As duas ainda carregavam a mesma nota sobre a
armadilha do ``with_name``, prova de que a duplicacao era copia e nao
convergencia acidental.

Importado como modulo irmao (``from _env_utils import ...``): estes scripts
rodam como ``python scripts/<nome>.py``, entao o proprio diretorio entra no
``sys.path``. Nao depende da instalacao editavel do projeto, o que importa
porque o ``generate_`` roda no HOST, fora do container.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR: Path = Path(__file__).resolve().parent.parent
ENV_PATH: Path = BASE_DIR / ".env"

_VARIAVEL_TOKEN: str = "GOOGLE_REFRESH_TOKEN"


def ler_credenciais_oauth() -> tuple[str, str]:
    """Le ``GOOGLE_CLIENT_ID`` e ``GOOGLE_CLIENT_SECRET`` do ``.env``.

    Returns:
        Tupla ``(client_id, client_secret)``.

    Raises:
        SystemExit: Se alguma das duas estiver ausente.
    """
    load_dotenv(ENV_PATH)

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        sys.exit(
            "GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET precisam estar no .env.\n"
            "Se voce nao os tem mais, crie um OAuth Client do tipo 'Desktop app'\n"
            "em https://console.cloud.google.com/apis/credentials"
        )

    return client_id, client_secret


def gravar_refresh_token(token: str) -> None:
    """Substitui a linha do refresh token no ``.env``, preservando o resto.

    Grava um backup em ``.env.bak`` antes de alterar. Escrever direto evita o
    erro mais comum do processo: colar o valor errado manualmente.

    Args:
        token: Refresh token recem-emitido pelo Google.

    Raises:
        SystemExit: Se o ``.env`` nao existir. Falhar aqui com mensagem clara
            e melhor que estourar ``FileNotFoundError`` depois do token ja
            emitido — que era o comportamento de uma das duas copias.
    """
    if not ENV_PATH.exists():
        sys.exit(f"Arquivo nao encontrado: {ENV_PATH}")

    original = ENV_PATH.read_text(encoding="utf-8")

    # with_name, nao with_suffix: ".env" nao tem stem separavel e o
    # with_suffix produziria ".env.env.bak", que escapa do .gitignore.
    backup = ENV_PATH.with_name(ENV_PATH.name + ".bak")
    backup.write_text(original, encoding="utf-8")

    linhas = original.splitlines()
    for i, linha in enumerate(linhas):
        if linha.strip().startswith(_VARIAVEL_TOKEN):
            linhas[i] = f"{_VARIAVEL_TOKEN}={token}"
            break
    else:
        linhas.append(f"{_VARIAVEL_TOKEN}={token}")

    ENV_PATH.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"\n.env atualizado (backup em {ENV_PATH.name}.bak)")
