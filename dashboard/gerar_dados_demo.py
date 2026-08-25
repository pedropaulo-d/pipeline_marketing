"""Gera o dataset SINTETICO de demonstracao do dashboard.

Por que existe
--------------
A superficie de exposicao (`data/exposicao/metricas.csv`) e gitignorada: ela
carrega metricas reais de clientes de uma agencia e nao sobrevive a um clone
limpo. Sem uma alternativa versionada, quem clonasse o repositorio veria uma
tela de erro em vez do artefato do TCC.

Este gerador produz um arquivo **inteiramente ficticio**, no mesmo contrato de
19 colunas, que permite exercitar filtros, comparacao de periodo, rankings e
graficos sem nenhum dado de cliente.

O que NAO e
-----------
Nao e anonimizacao. Nada aqui deriva de nome, external ID, chave natural ou
metrica real: os identificadores saem de `sha256("demo|<nivel>|<indice>")` e
os numeros, de um gerador pseudoaleatorio com semente fixa. Nao existe
correspondencia com nenhuma entidade real, e a chave HMAC da fronteira de
exposicao **nao** e usada — pseudonimo real e rotulo de demonstracao sao
coisas diferentes e nao devem compartilhar primitivo.

Fidelidade ao contrato
----------------------
As ausencias reais sao reproduzidas de proposito, porque o dashboard precisa
demonstrar como lida com elas:

- `reach`, `profile_views` e `purchases` ficam zerados no Google Ads, que nao
  os fornece nesse nivel de GAQL;
- `profile_views` fica zerado tambem no Meta, como no artefato real;
- `conversion_value` fica zerado no Meta e positivo no Google, reproduzindo o
  que a superficie real apresenta;
- `conversions` sai fracionaria no Google e inteira no Meta;
- ha entidades com duas versoes SCD2, para a coluna de versao nao ficar
  constante.

Uso
---
    python dashboard/gerar_dados_demo.py
    python dashboard/gerar_dados_demo.py --destino dashboard/dados_demo

O resultado e deterministico: mesma semente, mesmo arquivo, byte a byte.
"""

import argparse
import csv
import hashlib
import io
import json
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent.parent

DESTINO_PADRAO: Path = BASE_DIR / "dashboard" / "dados_demo"

NOME_CSV: str = "metricas.csv"
NOME_MANIFESTO: str = "manifesto.json"

SEMENTE: int = 20260825

# Periodo deliberadamente distinto do periodo real do artefato, para que
# ninguem confunda um screenshot de demonstracao com um de dado real.
PRIMEIRO_DIA: date = date(2026, 6, 1)
DIAS: int = 28

PREFIXO: dict[str, str] = {
    "conta": "Cliente",
    "campanha": "Campanha",
    "adset": "AdSet",
    "anuncio": "Anuncio",
}

PLATAFORMAS: tuple[str, ...] = ("Meta Ads", "Google Ads")

COLUNAS: tuple[str, ...] = (
    "data", "plataforma",
    "conta_id", "conta_versao",
    "campanha_id", "campanha_versao",
    "adset_id", "adset_versao",
    "anuncio_id", "anuncio_versao",
    "spend", "impressions", "link_clicks", "conversions",
    "conversion_value", "video_views", "reach", "profile_views", "purchases",
)


def identificador(nivel: str, indice: int) -> str:
    """Constroi um identificador ficticio no formato da exposicao.

    A entrada e o indice sequencial da entidade sintetica. Nao ha nome real,
    external ID nem chave natural em lugar nenhum deste caminho.

    Args:
        nivel: `conta`, `campanha`, `adset` ou `anuncio`.
        indice: Numero sequencial da entidade.

    Returns:
        Rotulo como ``Cliente-1A2B3C4D``.
    """
    material = f"demo|{nivel}|{indice}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest().upper()
    return f"{PREFIXO[nivel]}-{digest[:8]}"


def montar_hierarquia(sorteio: random.Random) -> list[dict]:
    """Monta contas, campanhas, ad sets e anuncios ficticios.

    Args:
        sorteio: Gerador pseudoaleatorio ja semeado.

    Returns:
        Lista de anuncios, cada um com a cadeia hierarquica completa, a
        plataforma, o dia de estreia e o perfil de desempenho.
    """
    anuncios: list[dict] = []
    seq = {"conta": 0, "campanha": 0, "adset": 0, "anuncio": 0}

    for indice_conta in range(6):
        seq["conta"] += 1
        plataforma = PLATAFORMAS[indice_conta % 2]
        conta = identificador("conta", seq["conta"])
        # Uma conta em duas versoes SCD2: renomeada no meio do periodo.
        conta_versao_2 = indice_conta == 1

        for _ in range(sorteio.randint(2, 3)):
            seq["campanha"] += 1
            campanha = identificador("campanha", seq["campanha"])
            campanha_versao_2 = seq["campanha"] in (2, 7)

            for _ in range(2):
                seq["adset"] += 1
                adset = identificador("adset", seq["adset"])

                for _ in range(sorteio.randint(1, 2)):
                    seq["anuncio"] += 1
                    anuncios.append({
                        "plataforma": plataforma,
                        "conta_id": conta,
                        "conta_versao_2": conta_versao_2,
                        "campanha_id": campanha,
                        "campanha_versao_2": campanha_versao_2,
                        "adset_id": adset,
                        "anuncio_id": identificador("anuncio", seq["anuncio"]),
                        "anuncio_versao_2": seq["anuncio"] % 17 == 0,
                        # Anuncios que estreiam depois do inicio do periodo
                        # dao ao dashboard um caso real de entrada tardia.
                        "estreia": sorteio.choice([0, 0, 0, 5, 11]),
                        "presenca": sorteio.uniform(0.65, 1.0),
                        "escala": sorteio.uniform(0.3, 3.0),
                        "ctr": sorteio.uniform(0.005, 0.04),
                        "cpc": sorteio.uniform(0.45, 3.5),
                        "taxa_conversao": sorteio.uniform(0.01, 0.09),
                        "ticket": sorteio.uniform(35.0, 260.0),
                    })
    return anuncios


def _versao(marcado: bool, dia: int) -> int:
    """Resolve o numero de versao SCD2 de uma entidade num dia.

    Args:
        marcado: Se a entidade tem duas versoes no periodo.
        dia: Indice do dia dentro do periodo.

    Returns:
        ``2`` a partir da metade do periodo para entidades marcadas, senao
        ``1``.
    """
    return 2 if marcado and dia >= DIAS // 2 else 1


def gerar_linhas() -> list[dict]:
    """Produz todas as linhas do dataset sintetico.

    Returns:
        Linhas no contrato de exposicao, ordenadas por
        ``(data, plataforma, conta, campanha, adset, anuncio)``.
    """
    sorteio = random.Random(SEMENTE)
    anuncios = montar_hierarquia(sorteio)

    linhas: list[dict] = []
    for dia in range(DIAS):
        data = PRIMEIRO_DIA + timedelta(days=dia)
        # Fim de semana rende menos: da a serie temporal um formato
        # reconhecivel em vez de ruido puro.
        fator_semana = 0.65 if data.weekday() >= 5 else 1.0

        for anuncio in anuncios:
            if dia < anuncio["estreia"]:
                continue
            if sorteio.random() > anuncio["presenca"]:
                continue

            meta = anuncio["plataforma"] == "Meta Ads"
            base = sorteio.uniform(400, 9000) * anuncio["escala"] * fator_semana
            impressions = int(base)
            if impressions <= 0:
                continue

            link_clicks = int(impressions * anuncio["ctr"])
            spend = Decimal(str(round(link_clicks * anuncio["cpc"], 2)))
            conversoes_brutas = link_clicks * anuncio["taxa_conversao"]

            if meta:
                conversions = Decimal(int(round(conversoes_brutas)))
                # O Meta nao traz valor de conversao neste grao no artefato
                # real; reproduzir isso mantem o caso de ROAS indisponivel
                # visivel na demonstracao.
                conversion_value = Decimal("0")
                purchases = int(conversions * Decimal("0.35"))
                reach = int(impressions * sorteio.uniform(0.55, 0.9))
                video_views = int(impressions * sorteio.uniform(0.08, 0.45))
            else:
                conversions = Decimal(str(round(conversoes_brutas, 6)))
                conversion_value = Decimal(
                    str(round(float(conversions) * anuncio["ticket"], 2))
                )
                purchases = 0
                reach = 0
                video_views = int(impressions * sorteio.uniform(0.0, 0.06))

            linhas.append({
                "data": data.isoformat(),
                "plataforma": anuncio["plataforma"],
                "conta_id": anuncio["conta_id"],
                "conta_versao": _versao(anuncio["conta_versao_2"], dia),
                "campanha_id": anuncio["campanha_id"],
                "campanha_versao": _versao(anuncio["campanha_versao_2"], dia),
                "adset_id": anuncio["adset_id"],
                "adset_versao": 1,
                "anuncio_id": anuncio["anuncio_id"],
                "anuncio_versao": _versao(anuncio["anuncio_versao_2"], dia),
                "spend": spend,
                "impressions": impressions,
                "link_clicks": link_clicks,
                "conversions": conversions,
                "conversion_value": conversion_value,
                "video_views": video_views,
                "reach": reach,
                # Zerado nas duas plataformas, como no artefato real.
                "profile_views": 0,
                "purchases": purchases,
            })

    linhas.sort(key=lambda l: (
        l["data"], l["plataforma"], l["conta_id"], l["campanha_id"],
        l["adset_id"], l["anuncio_id"],
    ))
    return linhas


def serializar_csv(linhas: list[dict]) -> str:
    """Serializa as linhas no formato do artefato de exposicao.

    Args:
        linhas: Linhas geradas.

    Returns:
        Conteudo do CSV.
    """
    buffer = io.StringIO(newline="")
    escritor = csv.writer(buffer, lineterminator="\n")
    escritor.writerow(COLUNAS)
    for linha in linhas:
        escritor.writerow([str(linha[coluna]) for coluna in COLUNAS])
    return buffer.getvalue()


TIPOS: dict[str, str] = {
    "data": "date (YYYY-MM-DD)",
    "plataforma": "text",
    "conta_id": "text (Cliente-XXXXXXXX)",
    "conta_versao": "integer >= 1",
    "campanha_id": "text (Campanha-XXXXXXXX)",
    "campanha_versao": "integer >= 1",
    "adset_id": "text (AdSet-XXXXXXXX)",
    "adset_versao": "integer >= 1",
    "anuncio_id": "text (Anuncio-XXXXXXXX)",
    "anuncio_versao": "integer >= 1",
    "spend": "decimal",
    "impressions": "integer",
    "link_clicks": "integer",
    "conversions": "decimal (fracionario no Google, nunca inteiro)",
    "conversion_value": "decimal",
    "video_views": "integer",
    "reach": "integer",
    "profile_views": "integer",
    "purchases": "integer",
}

AVISO_VIDEO_VIEWS: str = (
    "video_views tem definicao diferente em cada plataforma: TrueView de 30s, "
    "video completo ou interacao no Google; a partir de 3s no Meta. A metrica "
    "e valida dentro de cada plataforma e o total cross-platform NAO tem "
    "interpretacao analitica comum — nao somar entre plataformas."
)

AVISO_METRICAS_AUSENTES: str = (
    "reach, profile_views e purchases sao zero no Google por ausencia de "
    "suporte da GAQL neste grao — ausencia de suporte, nao ausencia de dado."
)


def montar_manifesto(linhas: list[dict], conteudo: str) -> dict:
    """Monta o manifesto do dataset sintetico.

    Ele declara em texto que os dados sao ficticios: o arquivo pode ser
    copiado para fora do repositorio e precisa continuar dizendo o que e.

    O manifesto segue os campos que `scripts/auditar_dataset_exposicao.py`
    exige, de proposito — assim o dataset de demonstracao pode ser submetido ao
    MESMO auditor independente da superficie real, e o contrato fica provado
    em vez de afirmado. A unica diferenca deliberada e `fingerprint_chave`,
    que sai nulo: nenhuma chave de pseudonimizacao participou desta geracao, e
    preencher o campo sugeriria uma procedencia que nao existe.

    Args:
        linhas: Linhas geradas.
        conteudo: Conteudo exato do CSV.

    Returns:
        Dicionario serializavel do manifesto.
    """
    datas = sorted(linha["data"] for linha in linhas)
    return {
        "versao_contrato": 1,
        "modo": "demonstracao",
        "natureza": (
            "DADOS SINTETICOS E FICTICIOS. Nao derivam de nome, identificador "
            "ou metrica de cliente real, e nao usam a chave de "
            "pseudonimizacao da fronteira de exposicao."
        ),
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gerador": "dashboard/gerar_dados_demo.py",
        "semente": SEMENTE,
        "artefato": NOME_CSV,
        "sha256": hashlib.sha256(conteudo.encode("utf-8")).hexdigest(),
        "linhas": len(linhas),
        "data_min": datas[0] if datas else None,
        "data_max": datas[-1] if datas else None,
        "grao": "1 anuncio x 1 dia — chave (anuncio_id, data)",
        "colunas": list(COLUNAS),
        "tipos": dict(TIPOS),
        "cardinalidades": {
            nivel: len({linha[f"{nivel}_id"] for linha in linhas})
            for nivel in ("conta", "campanha", "adset", "anuncio")
        },
        # Nulo de proposito: nao houve chave de pseudonimizacao envolvida.
        "fingerprint_chave": None,
        "origem": "dashboard/gerar_dados_demo.py (gerador sintetico)",
        "avisos": {
            "video_views": AVISO_VIDEO_VIEWS,
            "metricas_ausentes_no_google": AVISO_METRICAS_AUSENTES,
        },
        "uso": (
            "Demonstracao do dashboard sem dado de cliente. Nao representa "
            "desempenho real de nenhuma conta."
        ),
    }


def gerar(destino: Path) -> int:
    """Gera CSV e manifesto no diretorio informado.

    Args:
        destino: Diretorio de saida.

    Returns:
        Quantidade de linhas gravadas.
    """
    linhas = gerar_linhas()
    conteudo = serializar_csv(linhas)
    manifesto = montar_manifesto(linhas, conteudo)

    destino.mkdir(parents=True, exist_ok=True)
    (destino / NOME_CSV).write_text(conteudo, encoding="utf-8")
    (destino / NOME_MANIFESTO).write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return len(linhas)


def main() -> None:
    """Entry point da CLI."""
    parser = argparse.ArgumentParser(
        description="Gera o dataset sintetico de demonstracao do dashboard.",
    )
    parser.add_argument(
        "--destino",
        default=str(DESTINO_PADRAO),
        help=f"Diretorio de saida. Default: {DESTINO_PADRAO}",
    )
    args = parser.parse_args()

    total = gerar(Path(args.destino))
    print(f"{total} linhas sinteticas gravadas em {args.destino}")


if __name__ == "__main__":
    main()
