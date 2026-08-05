"""Gera um refresh token OAuth 2.0 para a API do Google Ads.

Abre o navegador para autenticacao, captura o callback num servidor local e
imprime o refresh token resultante. Reaproveita ``GOOGLE_CLIENT_ID`` e
``GOOGLE_CLIENT_SECRET`` que ja estao no ``.env``.

Precisa rodar no HOST (nao no container), porque depende de abrir o navegador
e de receber o redirect em ``localhost``.

Uso:
    pip install google-auth-oauthlib
    python scripts/generate_google_refresh_token.py

O refresh token so e emitido quando o Google entende que e a primeira
autorizacao. Por isso o fluxo forca ``prompt="consent"`` — sem isso, uma conta
que ja autorizou o app antes recebe apenas um access token temporario.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

# Escopo unico da API do Google Ads — cobre leitura e escrita; o que limita as
# operacoes e o papel do usuario dentro do Google Ads, nao o escopo.
SCOPES = ["https://www.googleapis.com/auth/adwords"]

# Porta do servidor local que recebe o redirect do Google.
CALLBACK_PORT = 8081


def main() -> None:
    load_dotenv(ENV_PATH)

    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        sys.exit(
            "GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET precisam estar no .env.\n"
            "Se voce nao os tem mais, crie um OAuth Client do tipo 'Desktop app'\n"
            "em https://console.cloud.google.com/apis/credentials"
        )

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        sys.exit("Dependencia ausente. Rode: pip install google-auth-oauthlib")

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [f"http://localhost:{CALLBACK_PORT}/"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

    print("=" * 68)
    print("Abrindo o navegador para autenticacao...")
    print("IMPORTANTE: entre com o e-mail que recebeu acesso de LEITURA ao MCC.")
    print("=" * 68)

    credentials = flow.run_local_server(
        port=CALLBACK_PORT,
        prompt="consent",       # forca a emissao de um refresh token novo
        access_type="offline",  # sem isso o Google devolve so o access token
        open_browser=True,
    )

    if not credentials.refresh_token:
        sys.exit(
            "O Google nao devolveu refresh token.\n"
            "Revogue o acesso do app em https://myaccount.google.com/permissions\n"
            "e rode este script novamente."
        )

    token = credentials.refresh_token
    _write_to_env(token)

    print()
    print("=" * 68)
    print("REFRESH TOKEN GRAVADO NO .env")
    print(f"  identificacao (ultimos 6 chars): ...{token[-6:]}")
    print(f"  tamanho: {len(token)} caracteres")
    print("=" * 68)
    print("Valide com:")
    print("  docker compose run --rm etl_app python main.py \\")
    print("    --platforms google --start-date 2026-08-01 --end-date 2026-08-01")
    print("=" * 68)


def _write_to_env(token: str) -> None:
    """Substitui a linha GOOGLE_REFRESH_TOKEN no .env, preservando o resto.

    Grava um backup em ``.env.bak`` antes de alterar. Escrever direto evita o
    erro mais comum do processo: colar o valor errado manualmente.

    Args:
        token: Refresh token recem-emitido pelo Google.
    """
    if not ENV_PATH.exists():
        sys.exit(f"Arquivo nao encontrado: {ENV_PATH}")

    original = ENV_PATH.read_text(encoding="utf-8")
    # with_name, nao with_suffix: ".env" nao tem stem separavel e o
    # with_suffix produziria ".env.env.bak", que escapa do .gitignore.
    backup = ENV_PATH.with_name(ENV_PATH.name + ".bak")
    backup.write_text(original, encoding="utf-8")

    linhas = original.splitlines()
    encontrou = False
    for i, linha in enumerate(linhas):
        if linha.strip().startswith("GOOGLE_REFRESH_TOKEN"):
            linhas[i] = f"GOOGLE_REFRESH_TOKEN={token}"
            encontrou = True
            break

    if not encontrou:
        linhas.append(f"GOOGLE_REFRESH_TOKEN={token}")

    ENV_PATH.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(f"\n.env atualizado (backup em {ENV_PATH.name}.bak)")


if __name__ == "__main__":
    main()
