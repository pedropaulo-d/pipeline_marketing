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

import sys

from _env_utils import gravar_refresh_token, ler_credenciais_oauth

# Escopo unico da API do Google Ads — cobre leitura e escrita; o que limita as
# operacoes e o papel do usuario dentro do Google Ads, nao o escopo.
SCOPES = ["https://www.googleapis.com/auth/adwords"]

# Porta do servidor local que recebe o redirect do Google.
CALLBACK_PORT = 8081


def main() -> None:
    client_id, client_secret = ler_credenciais_oauth()

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
    gravar_refresh_token(token)

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


if __name__ == "__main__":
    main()
