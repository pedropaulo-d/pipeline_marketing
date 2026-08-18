"""Pseudonimos deterministicos da fronteira de exposicao.

Por que existe
--------------
O material exposto — dashboard, screenshot, slide, dataset — nao pode permitir
vincular metrica a cliente. Este modulo produz o rotulo que substitui a
identidade real, e faz **so** isso: nao conhece SQL, CSV, auditoria nem
metrica.

Determinismo sem mapa
---------------------
O rotulo vem de `HMAC-SHA256(chave_local, "<nivel>|<nk>")`. Duas consequencias
deliberadas:

1. **Nao existe mapa persistente.** Um arquivo `{cliente real: pseudonimo}`
   seria o artefato mais perigoso do repositorio — reidentifica o dataset
   inteiro e mora ao lado dele. O HMAC dispensa esse arquivo: a mesma chave
   com a mesma entrada devolve sempre o mesmo rotulo.
2. **A chave nao esta versionada.** A versao anterior desta camada usava um
   salt fixo escrito no proprio codigo (`scripts/anonimizar_dataset.py`), o que
   torna o pseudonimo reversivel por dicionario: quem tem a lista de clientes
   candidatos calcula os hashes e recupera o mapeamento inteiro. Medido em
   17/08/2026 na auditoria: 48 de 48 contas recuperadas em menos de 1 ms. Com
   HMAC e segredo fora do repositorio esse ataque deixa de existir.

Entrada assinada
----------------
A entrada e a chave natural (`_nk`) do Gold, nunca o nome nem o external ID.
O `_nk` e estavel entre reextracoes e entre versoes SCD2 da mesma entidade —
por isso duas versoes da mesma campanha recebem o MESMO `campanha_id`, e o que
as distingue e a coluna de versao. O nivel entra no material assinado para
separar dominios: a mesma `_nk` em niveis diferentes nao produz o mesmo rotulo.

Estabilidade
------------
Trocar a chave troca todos os pseudonimos, sem erro nenhum — screenshots
antigos deixam de casar com o dataset novo em silencio. Por isso a mesma chave
deve valer por todo o ciclo da Defesa, e o manifesto do artefato carrega o
`fingerprint_chave()`, que denuncia a troca sem revelar o segredo.
"""

import hashlib
import hmac
import os

VARIAVEL: str = "PSEUDONIMIZACAO_CHAVE"

# Valor que vai no `.env_template`. Nunca e aceito como chave: o template
# existe para documentar a variavel, nao para funcionar.
PLACEHOLDER: str = "GERAR_LOCALMENTE_NAO_VERSIONAR"

# Nao e medida de entropia — e um piso grosseiro contra o descuido obvio
# ("chave123"). A entropia vem de como a chave e gerada, e a forma
# recomendada esta em `INSTRUCAO_DE_GERACAO`.
TAMANHO_MINIMO: int = 32

INSTRUCAO_DE_GERACAO: str = (
    'python -c "import secrets; print(secrets.token_urlsafe(32))"'
)

# Prefixo humano de cada nivel. O rotulo e o proprio nome publico da entidade:
# nao existe coluna de nome na superficie de exposicao.
NIVEIS: dict[str, str] = {
    "conta": "Cliente",
    "campanha": "Campanha",
    "adset": "AdSet",
    "anuncio": "Anuncio",
}

# 8 hex = 32 bits. Medido sobre as entidades reais do DW em 18/08/2026: com
# 4 hex ja havia colisao (2 adsets, 7 anuncios); com 6 e 8 nenhuma. Ainda
# assim o exportador confere unicidade — o argumento probabilistico nao
# substitui a checagem.
TAMANHO_ID: int = 8

# O fingerprint nao aparece em rotulo, entao nao ha limite visual: 16 hex
# tornam a colisao irrelevante para a unica pergunta que ele responde ("a
# chave e a mesma de quando gerei aquele screenshot?").
TAMANHO_FINGERPRINT: int = 16

_MATERIAL_FINGERPRINT: bytes = b"fingerprint-da-chave-de-pseudonimizacao"


class ChaveInvalida(Exception):
    """A chave de pseudonimizacao esta ausente ou e inaceitavel.

    A mensagem nunca contem o valor da chave — nem truncado, nem mascarado.
    """


def _chave() -> bytes:
    """Le e valida a chave de pseudonimizacao do ambiente.

    Returns:
        A chave em bytes, pronta para o HMAC.

    Raises:
        ChaveInvalida: Se estiver ausente, vazia, igual ao placeholder do
            template ou curta demais. Nao ha fallback nem valor default: sem
            chave valida nao se gera artefato de exposicao.
    """
    bruto = os.environ.get(VARIAVEL)

    if bruto is None or not bruto.strip():
        raise ChaveInvalida(
            f"{VARIAVEL} ausente ou vazia. Gere uma chave local com:\n"
            f"    {INSTRUCAO_DE_GERACAO}\n"
            f"e grave em .env (que nao e versionado)."
        )

    valor = bruto.strip()

    if valor == PLACEHOLDER:
        raise ChaveInvalida(
            f"{VARIAVEL} ainda esta com o placeholder do .env_template. "
            f"Gere uma chave real com:\n    {INSTRUCAO_DE_GERACAO}"
        )

    if len(valor) < TAMANHO_MINIMO:
        raise ChaveInvalida(
            f"{VARIAVEL} tem menos de {TAMANHO_MINIMO} caracteres. "
            f"Gere uma chave com:\n    {INSTRUCAO_DE_GERACAO}"
        )

    return valor.encode("utf-8")


def _assinar(material: bytes) -> str:
    """Aplica HMAC-SHA256 com a chave local.

    Args:
        material: Bytes a assinar.

    Returns:
        Digest hexadecimal completo, em maiusculas.

    Raises:
        ChaveInvalida: Se a chave nao for utilizavel.
    """
    return hmac.new(_chave(), material, hashlib.sha256).hexdigest().upper()


def gerar_id_publico(nivel: str, nk: str) -> str:
    """Gera o identificador publico de uma entidade.

    Args:
        nivel: Um de ``conta``, ``campanha``, ``adset``, ``anuncio``.
        nk: Chave natural da entidade no Gold (``<nivel>_nk``).

    Returns:
        Rotulo no formato ``Cliente-A7F21C0B``, deterministico para a mesma
        chave e a mesma entrada.

    Raises:
        ValueError: Se o nivel for desconhecido ou a chave natural for vazia.
            Nivel novo tem de ser declarado aqui de proposito — cair num
            prefixo generico silenciosamente misturaria dominios.
        ChaveInvalida: Se a chave de pseudonimizacao nao for utilizavel.
    """
    if nivel not in NIVEIS:
        raise ValueError(
            f"Nivel desconhecido: {nivel!r}. Conhecidos: {sorted(NIVEIS)}."
        )
    if not nk:
        raise ValueError(f"Chave natural vazia para o nivel {nivel!r}.")

    digest = _assinar(f"{nivel}|{nk}".encode("utf-8"))
    return f"{NIVEIS[nivel]}-{digest[:TAMANHO_ID]}"


def fingerprint_chave() -> str:
    """Gera uma impressao digital da chave, segura para publicar.

    E o HMAC da chave sobre um material fixo. Nao permite recuperar o segredo
    e serve para responder se dois artefatos foram gerados com a mesma chave —
    portanto se os pseudonimos deles sao comparaveis.

    Returns:
        Prefixo hexadecimal do digest, em maiusculas.

    Raises:
        ChaveInvalida: Se a chave nao for utilizavel.
    """
    return _assinar(_MATERIAL_FINGERPRINT)[:TAMANHO_FINGERPRINT]


def chave_disponivel() -> bool:
    """Diz se ha chave utilizavel, sem levantar excecao.

    Serve para teste e para mensagem de diagnostico. Nao devolve nada derivado
    da chave.

    Returns:
        ``True`` se `_chave` aceitaria o valor atual do ambiente.
    """
    try:
        _chave()
    except ChaveInvalida:
        return False
    return True
