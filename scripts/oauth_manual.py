"""Fluxo OAuth manual para a API do Google Ads, em dois passos.

Alternativa ao ``generate_google_refresh_token.py`` para quando o servidor
local nao funciona (firewall, navegador em outra maquina, sessao remota).
Nenhum servidor e aberto: voce copia o ``code`` da barra de enderecos.

Passo 1 — gerar a URL de autorizacao:
    python scripts/oauth_manual.py url

Passo 2 — trocar o code pelo refresh token (grava no .env):
    python scripts/oauth_manual.py exchange "4/0AX4Xf..."
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from _env_utils import gravar_refresh_token, ler_credenciais_oauth

SCOPE = "https://www.googleapis.com/auth/adwords"
# Precisa ser identico no passo 1 e no passo 2 — o Google valida o par.
REDIRECT_URI = "http://localhost:8081/"

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def print_url() -> None:
    """Monta e imprime a URL de autorizacao."""
    client_id, _ = ler_credenciais_oauth()

    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",   # necessario para receber refresh token
        "prompt": "consent",        # forca novo consentimento e novo refresh token
    })

    print()
    print("=" * 70)
    print("PASSO 1 — abra esta URL no navegador:")
    print()
    print(f"{AUTH_ENDPOINT}?{params}")
    print()
    print("=" * 70)
    print("Faca login com o e-mail que tem acesso de LEITURA ao MCC.")
    print()
    print("Ao final o navegador vai tentar abrir http://localhost:8081/... e")
    print("mostrar erro de conexao. ISSO E ESPERADO. O que importa esta na")
    print("barra de enderecos:")
    print()
    print("   http://localhost:8081/?code=4%2F0AX4Xf...&scope=...")
    print("                               ^^^^^^^^^^^^^^^^^^")
    print("                               copie este trecho, ate o '&'")
    print()
    print("PASSO 2 — troque o code pelo refresh token:")
    print('   python scripts/oauth_manual.py exchange "COLE_O_CODE_AQUI"')
    print("=" * 70)


def exchange(code: str) -> None:
    """Troca o authorization code por um refresh token e grava no .env.

    Args:
        code: Authorization code copiado da barra de enderecos.
    """
    client_id, client_secret = ler_credenciais_oauth()

    # O navegador url-encoda a barra do code ("4/0A..." vira "4%2F0A...").
    code = urllib.parse.unquote(code.strip())

    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()

    try:
        req = urllib.request.Request(TOKEN_ENDPOINT, data=data)
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        detalhe = exc.read().decode("utf-8", "replace")
        print("FALHA na troca do code:\n", detalhe[:400], file=sys.stderr)
        if "invalid_grant" in detalhe:
            print(
                "\nCausa mais comum: o code ja foi usado ou expirou "
                "(validade ~10 min). Refaca o passo 1.",
                file=sys.stderr,
            )
        sys.exit(1)

    token = payload.get("refresh_token")
    if not token:
        sys.exit(
            "O Google devolveu apenas access_token, sem refresh_token.\n"
            "Revogue o app em https://myaccount.google.com/permissions "
            "e refaca o passo 1."
        )

    gravar_refresh_token(token)

    print()
    print("=" * 70)
    print("REFRESH TOKEN GRAVADO NO .env")
    print(f"  identificacao (ultimos 6 chars): ...{token[-6:]}")
    print(f"  tamanho: {len(token)} caracteres")
    print("=" * 70)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"url", "exchange"}:
        sys.exit(__doc__)

    if sys.argv[1] == "url":
        print_url()
    else:
        if len(sys.argv) < 3:
            sys.exit('Informe o code: python scripts/oauth_manual.py exchange "4/0A..."')
        exchange(sys.argv[2])


if __name__ == "__main__":
    main()
