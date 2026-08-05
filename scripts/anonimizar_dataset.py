"""Gera uma copia anonimizada dos dados brutos, publicavel no TCC.

Os dados de producao sao reais, de clientes de uma agencia: nomes de empresas,
campanhas e valores investidos. Publicar isso num repositorio academico exige
autorizacao de terceiros que a agencia nem sempre pode dar. Anonimizando, a
autorizacao da propria agencia passa a ser suficiente.

Principios
----------
1. **Determinismo.** O mesmo nome sempre vira o mesmo pseudonimo. Sem isso,
   cada execucao criaria entidades novas nas dimensoes e o pipeline
   inflaria `dim_conta` e `dim_campanha` a cada rodada.
2. **Preservar estrutura, trocar identidade.** Nomes de campanha seguem
   convencoes operacionais — `[OBJETIVO][TIPO][DATA]`. Os marcadores
   estruturais sao mantidos; so os tokens identificaveis sao substituidos.
   A taxonomia de nomenclatura continua analisavel.
3. **Metricas intactas.** spend, cliques e conversoes nao identificam ninguem
   depois que os nomes saem, e alterar valores destruiria a validade
   analitica do dataset.
4. **Fora do pipeline.** Roda na fronteira da publicacao, nao na ingestao.
   A logica do pipeline permanece identica para dado real e anonimizado.

Uso:
    python scripts/anonimizar_dataset.py
    python scripts/anonimizar_dataset.py --entrada temp_meta_raw.json --saida meu.json
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SAIDA_PADRAO = BASE_DIR / "data" / "publico"

# Salt fixo: garante determinismo entre execucoes. Nao e segredo criptografico
# — o objetivo e desidentificar para publicacao, nao resistir a um atacante
# com acesso ao codigo e a lista de clientes.
SALT = "tcc-pipeline-dados-2026"

# Campos que carregam identidade e precisam de pseudonimo.
CAMPOS_NOME = [
    "account_name", "campaign_name", "adset_name",
    "ad_name", "ad_group_name",
]

# Campos de ID: pseudonimizados preservando o formato numerico, para que o
# pipeline continue tratando-os como IDs de plataforma.
CAMPOS_ID = [
    "account_id", "campaign_id", "adset_id",
    "ad_id", "ad_group_id",
]

# Tokens entre colchetes e datas. ATENCAO: o conteudo dos colchetes NAO e
# seguro por padrao — na pratica ele costuma carregar a marca do cliente
# (ex: "[ECLIPSE]", "[MARCA_C]"). Por isso todo token e pseudonimizado, exceto
# os termos genericos da lista abaixo.
RE_TOKEN = re.compile(r"\[([^\]]*)\]")
RE_DATA = re.compile(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}")

# Vocabulario operacional de midia paga: descreve objetivo, formato ou canal,
# nao identifica anunciante. Preserva-lo mantem a taxonomia analisavel.
# Revise esta lista antes de publicar — o criterio e "este termo poderia
# aparecer na conta de qualquer anunciante?".
TERMOS_GENERICOS = {
    "conversao", "conversão", "conversoes", "conversões",
    "lead", "leads", "vendas", "venda", "trafego", "tráfego",
    "alcance", "remarketing", "retargeting", "captacao", "captação",
    "capt", "formulario", "formulário", "form", "home", "aberto",
    "wpp", "whatsapp", "ig", "instagram", "fb", "facebook", "site",
    "video", "vídeo", "vd", "criativo", "criativos", "teste", "testes",
    "topo", "meio", "fundo", "frio", "quente", "geral", "novo", "nova",
}

PREFIXOS = {
    "account_name": "Cliente",
    "campaign_name": "Campanha",
    "adset_name": "Conjunto",
    "ad_name": "Anuncio",
    "ad_group_name": "Conjunto",
}


def _hash(valor: str, tamanho: int = 8) -> str:
    """Gera um hash curto e deterministico.

    Args:
        valor: Texto de entrada.
        tamanho: Numero de caracteres hexadecimais a retornar.

    Returns:
        Hash hexadecimal truncado.
    """
    return hashlib.sha256(f"{SALT}|{valor}".encode()).hexdigest()[:tamanho]


def _pseudonimo_token(token: str) -> str:
    """Pseudonimiza um token de colchete, preservando termos genericos.

    Args:
        token: Conteudo de um par de colchetes.

    Returns:
        O proprio token se for vocabulario operacional generico; caso
        contrario um rotulo deterministico ``TK-XXXX``.
    """
    limpo = token.strip()
    if not limpo:
        return token

    # Datas e numeros nao identificam anunciante.
    if RE_DATA.fullmatch(limpo) or limpo.isdigit():
        return limpo

    # Termo generico isolado ou composto so por termos genericos.
    palavras = [p for p in re.split(r"[\s/_-]+", limpo.lower()) if p]
    if palavras and all(p in TERMOS_GENERICOS for p in palavras):
        return limpo

    return f"TK-{_hash(limpo.lower(), 4).upper()}"


def pseudonimo_nome(valor: str, campo: str, mapa: dict[str, str]) -> str:
    """Substitui a identidade preservando a estrutura do nome.

    Mantem o esqueleto da convencao de nomenclatura (numero e ordem dos
    colchetes, datas) e o vocabulario operacional generico, substituindo
    apenas os tokens que podem identificar o anunciante. Como a substituicao
    e deterministica, o mesmo token vira o mesmo rotulo em todo o dataset —
    a taxonomia de nomenclatura continua analisavel.

    Args:
        valor: Nome original.
        campo: Campo de origem, define o prefixo do pseudonimo.
        mapa: Dicionario acumulador ``{original: pseudonimo}``, para auditoria.

    Returns:
        Nome pseudonimizado.
    """
    if not valor:
        return valor
    if valor in mapa:
        return mapa[valor]

    prefixo = PREFIXOS.get(campo, "Entidade")
    identificador = _hash(valor, 6).upper()

    tokens = RE_TOKEN.findall(valor)
    if tokens:
        estrutura = " ".join(f"[{_pseudonimo_token(t)}]" for t in tokens)
        pseudo = f"{estrutura} {prefixo}-{identificador}"
    else:
        # Sem colchetes: preserva apenas datas soltas, se houver.
        datas = RE_DATA.findall(valor)
        sufixo = f" {' '.join(datas)}" if datas else ""
        pseudo = f"{prefixo}-{identificador}{sufixo}"

    mapa[valor] = pseudo
    return pseudo


def pseudonimo_id(valor: str) -> str:
    """Gera um ID numerico deterministico a partir do original.

    Args:
        valor: ID original da plataforma.

    Returns:
        ID pseudonimizado, com formato numerico preservado.
    """
    if not valor:
        return valor
    digitos = int(_hash(str(valor), 12), 16) % (10 ** 12)
    return str(digitos).zfill(12)


def anonimizar_registro(
    registro: dict, mapa_nomes: dict[str, str], mapa_ids: dict[str, str]
) -> dict:
    """Aplica a pseudonimizacao a um registro bruto.

    Args:
        registro: Registro original da API.
        mapa_nomes: Acumulador de nomes, para o relatorio de auditoria.
        mapa_ids: Acumulador de IDs.

    Returns:
        Novo dicionario com os campos identificaveis substituidos.
    """
    saida = dict(registro)

    for campo in CAMPOS_NOME:
        if campo in saida and isinstance(saida[campo], str):
            saida[campo] = pseudonimo_nome(saida[campo], campo, mapa_nomes)

    for campo in CAMPOS_ID:
        if campo in saida and saida[campo]:
            original = str(saida[campo])
            novo = pseudonimo_id(original)
            mapa_ids[original] = novo
            saida[campo] = novo

    return saida


def anonimizar_arquivo(entrada: Path, saida: Path) -> tuple[int, int, int]:
    """Anonimiza um arquivo JSON bruto inteiro.

    Args:
        entrada: Caminho do arquivo original.
        saida: Caminho do arquivo anonimizado a gerar.

    Returns:
        Tupla ``(registros, nomes_unicos, ids_unicos)``.
    """
    registros = json.loads(entrada.read_text(encoding="utf-8"))

    mapa_nomes: dict[str, str] = {}
    mapa_ids: dict[str, str] = {}
    anonimizados = [
        anonimizar_registro(r, mapa_nomes, mapa_ids) for r in registros
    ]

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(
        json.dumps(anonimizados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return len(anonimizados), len(mapa_nomes), len(mapa_ids)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera copia anonimizada dos dados brutos para publicacao."
    )
    parser.add_argument("--entrada", help="Arquivo JSON especifico a anonimizar.")
    parser.add_argument("--saida", help="Arquivo de saida (usado com --entrada).")
    parser.add_argument(
        "--diretorio-saida",
        default=str(SAIDA_PADRAO),
        help=f"Diretorio de saida no modo lote. Default: {SAIDA_PADRAO}",
    )
    args = parser.parse_args()

    if args.entrada:
        entrada = Path(args.entrada)
        saida = Path(args.saida) if args.saida else Path(args.diretorio_saida) / entrada.name
        arquivos = [(entrada, saida)]
    else:
        destino = Path(args.diretorio_saida)
        arquivos = [
            (BASE_DIR / nome, destino / nome)
            for nome in ("temp_meta_raw.json", "temp_google_raw.json")
        ]

    total = 0
    for entrada, saida in arquivos:
        if not entrada.exists():
            print(f"  ignorado (nao existe): {entrada.name}")
            continue
        n, nomes, ids = anonimizar_arquivo(entrada, saida)
        print(f"  {entrada.name}: {n} registros | {nomes} nomes | {ids} IDs -> {saida}")
        total += n

    if total == 0:
        sys.exit("Nenhum arquivo processado.")

    print(f"\n{total} registros anonimizados.")
    print("As metricas foram preservadas; apenas nomes e IDs foram substituidos.")
    print("A pseudonimizacao e deterministica: reexecutar produz o mesmo resultado.")


if __name__ == "__main__":
    main()
