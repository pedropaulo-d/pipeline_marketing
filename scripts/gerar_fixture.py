"""Gera dados brutos SINTETICOS no formato exato das duas APIs.

Por que sintetico e nao uma amostra do dado real
------------------------------------------------
Os dados de producao sao de clientes de uma agencia e a autorizacao por
escrito para publicar qualquer recorte ainda nao existe — nem pseudonimizado.
Um gerador resolve isso sem depender de autorizacao: o que entra no
repositorio e codigo, revisavel, e nao dado de terceiro.

O que a fixture exercita de proposito
-------------------------------------
Nao e dado bonito: cada peculiaridade abaixo ja causou bug ou esta protegida
por teste, e a fixture existe para que a refatoracao passe por todas elas.

- Meta devolve conversoes como ARRAY de {action_type, value}, nao coluna.
- Um registro do Meta sem a chave `actions` — exercita o COALESCE da macro
  `sum_action_value`.
- Google devolve conversoes FRACIONADAS (modelagem de atribuicao). Truncar
  para inteiro ja perdeu ~1% das conversoes no ETL antigo.
- Um registro do Google sem `video_trueview_views`, como nos lotes anteriores
  a 06/08 — exercita o coalesce da silver.
- Uma campanha RENOMEADA no ultimo dia — exercita o SCD Tipo 2 inteiro.
- Um anuncio que aparece so no primeiro dia e some depois.
- Um anuncio do Meta e um do Google com o MESMO external_id — a colisao que
  as chaves naturais encadeadas existem para evitar. Ela e real: os espacos
  de ID das duas plataformas sao independentes.

Os identificadores sao unicos por (conta, campanha, anuncio) dentro de cada
plataforma, como nas APIs reais — reciclar um ID entre contas tornaria a
fixture infiel a fonte que ela imita.

Uso:
    python scripts/gerar_fixture.py
    python scripts/gerar_fixture.py --saida /tmp/fixture
"""

import argparse
import json
import random
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent.parent
SAIDA_PADRAO: Path = BASE_DIR / "tests" / "fixtures"

# Semente fixa: a fixture precisa ser identica a cada geracao, senao deixa de
# servir como base de comparacao entre execucoes da refatoracao.
SEMENTE: int = 20260806

DATAS: list[str] = ["2026-01-01", "2026-01-02", "2026-01-03"]

# A campanha `c_meta_2` muda de nome no ultimo dia — e o que produz uma
# segunda versao em dim_campanha.
NOME_ANTIGO: str = "[LEADS] [DEMO] [FORM] 01/01/2026"
NOME_NOVO: str = "[Leads] [Demo] [Form] - 010126"

# Coordenadas do anuncio do Google cujo ID e reaproveitado no Meta para
# produzir a colisao entre plataformas.
COLISAO: tuple[int, int, int] = (1, 1, 1)


def id_anuncio_google(conta: int, campanha: int, anuncio: int) -> str:
    """Monta o identificador de um anuncio do Google.

    Existe como funcao, e nao interpolada nos dois lugares que precisam dela,
    porque a colisao deliberada entre plataformas depende de os dois lados
    produzirem exatamente a mesma string. Escrever a regra duas vezes ja fez
    a colisao passar despercebida uma vez.

    Args:
        conta: Indice da conta.
        campanha: Indice da campanha.
        anuncio: Indice do anuncio.

    Returns:
        Identificador do anuncio.
    """
    return f"230000{conta}{campanha}{anuncio:03d}"


def _registro_meta(
    rng: random.Random, data: str, conta: int, campanha: int, anuncio: int,
    *, com_acoes: bool = True,
) -> dict:
    """Monta um registro no formato do Meta Ads Insights.

    Args:
        rng: Gerador com semente fixa.
        data: Dia de referencia (``YYYY-MM-DD``).
        conta: Indice da conta.
        campanha: Indice da campanha dentro da conta.
        anuncio: Indice do anuncio.
        com_acoes: Se ``False``, omite `actions`/`action_values` — o caso que
            exercita o COALESCE da macro.

    Returns:
        Dict com as mesmas chaves que `INSIGHT_FIELDS` produz.
    """
    impressoes = rng.randint(500, 20_000)
    cliques = rng.randint(5, int(impressoes * 0.03) + 6)

    nome_campanha = NOME_ANTIGO
    if campanha == 2 and data == DATAS[-1]:
        nome_campanha = NOME_NOVO
    elif campanha != 2:
        nome_campanha = f"[VENDAS] [DEMO] [CONV] {campanha}"

    # ID COLIDIDO de proposito: este anuncio do Meta recebe o mesmo
    # external_id de um anuncio do Google. So a cadeia hierarquica na chave
    # natural impede que os dois virem a mesma entidade.
    ad_id = (
        id_anuncio_google(*COLISAO)
        if (conta, campanha, anuncio) == COLISAO
        else f"120000000{conta}{campanha}{anuncio:02d}"
    )

    registro = {
        "date_start": data,
        "date_stop": data,
        "account_id": f"90000000{conta}",
        "account_name": f"Conta Demo {conta}",
        "campaign_id": f"12000000{conta}000{campanha}",
        "campaign_name": nome_campanha,
        "adset_id": f"12000000{conta}010{campanha}",
        "adset_name": f"Conjunto Demo {conta}-{campanha}",
        "ad_id": ad_id,
        "ad_name": f"Anuncio Demo {conta}-{campanha}-{anuncio}",
        "spend": f"{rng.uniform(10, 900):.2f}",
        "impressions": str(impressoes),
        "inline_link_clicks": str(cliques),
        "reach": str(int(impressoes * rng.uniform(0.6, 0.95))),
    }

    if com_acoes:
        registro["actions"] = [
            {"action_type": "lead", "value": str(rng.randint(0, 12))},
            {"action_type": "video_view", "value": str(rng.randint(0, 3000))},
            {"action_type": "onsite_conversion.ig_profile_view",
             "value": str(rng.randint(0, 40))},
            {"action_type": "purchase", "value": str(rng.randint(0, 4))},
            # Ruido deliberado: action_type que a silver ignora.
            {"action_type": "post_engagement", "value": str(rng.randint(0, 500))},
        ]
        registro["action_values"] = [
            {"action_type": "lead", "value": f"{rng.uniform(0, 2000):.2f}"},
        ]

    return registro


def _registro_google(
    rng: random.Random, data: str, conta: int, campanha: int, anuncio: int,
    *, com_video: bool = True,
) -> dict:
    """Monta um registro no formato produzido pelo extrator do Google Ads.

    Args:
        rng: Gerador com semente fixa.
        data: Dia de referencia (``YYYY-MM-DD``).
        conta: Indice da conta.
        campanha: Indice da campanha.
        anuncio: Indice do anuncio.
        com_video: Se ``False``, omite `video_trueview_views` — o formato dos
            lotes anteriores a 06/08/2026.

    Returns:
        Dict com as mesmas chaves que `extract_daily_ads` produz.
    """
    impressoes = rng.randint(100, 4_000)

    registro = {
        "date": data,
        "account_id": f"80000000{conta}",
        "account_name": f"Cliente Demo {conta}",
        "campaign_id": f"230000{conta}00{campanha}",
        "campaign_name": f"[DEMO] Search - Regiao {conta}-{campanha}",
        "ad_group_id": f"230000{conta}01{campanha}",
        "ad_group_name": f"Grupo Demo {conta}-{campanha}",
        # O anuncio em COLISAO tem o mesmo ID de um anuncio do Meta.
        "ad_id": id_anuncio_google(conta, campanha, anuncio),
        "ad_name": f"Anuncio Search {conta}-{campanha}-{anuncio}",
        "impressions": impressoes,
        "clicks": rng.randint(1, int(impressoes * 0.1) + 2),
        "cost": round(rng.uniform(5, 400), 6),
        # Fracionada de proposito: e assim que a API reporta.
        "conversions": round(rng.uniform(0, 9), 2),
        "conversions_value": round(rng.uniform(0, 800), 2),
    }

    if com_video:
        registro["video_trueview_views"] = rng.randint(0, 400)

    return registro


def gerar() -> tuple[list[dict], list[dict]]:
    """Gera as duas listas de registros brutos.

    Returns:
        Tupla ``(registros_meta, registros_google)``.
    """
    rng = random.Random(SEMENTE)
    meta: list[dict] = []
    google: list[dict] = []

    for i, data in enumerate(DATAS):
        for conta in (1, 2):
            for campanha in (1, 2):
                for anuncio in (1, 2, 3):
                    # O anuncio 3 da conta 2 so existe no primeiro dia.
                    if anuncio == 3 and conta == 2 and i > 0:
                        continue
                    meta.append(_registro_meta(
                        rng, data, conta, campanha, anuncio,
                        # Um unico registro sem arrays de acoes.
                        com_acoes=not (i == 0 and conta == 1
                                       and campanha == 1 and anuncio == 1),
                    ))
                    google.append(_registro_google(
                        rng, data, conta, campanha, anuncio,
                        # Registros do primeiro dia no formato antigo.
                        com_video=(i > 0),
                    ))

    return meta, google


def main() -> None:
    """Entry point da CLI."""
    parser = argparse.ArgumentParser(
        description="Gera dados brutos sinteticos no formato das APIs.",
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=SAIDA_PADRAO,
        help=f"Diretorio de saida (default: {SAIDA_PADRAO.relative_to(BASE_DIR)}).",
    )
    args = parser.parse_args()

    meta, google = gerar()
    args.saida.mkdir(parents=True, exist_ok=True)

    for nome, registros in (("meta", meta), ("google", google)):
        caminho = args.saida / f"temp_{nome}_raw.json"
        caminho.write_text(
            json.dumps(registros, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{caminho}: {len(registros)} registros")


if __name__ == "__main__":
    main()
