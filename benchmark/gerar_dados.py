"""Gera dados sinteticos em escala para o benchmark row-store x column-store.

Os dados reais do projeto (~1,7 mil linhas) sao pequenos demais para revelar
diferenca entre os motores. Este gerador produz um fato dimensional com a mesma
FORMA do modelo real, em escalas crescentes, para localizar o ponto onde o
armazenamento colunar passa a compensar.

Realismo do dado sintetico
--------------------------
Uma geracao ingenua (todos os valores uniformes) favoreceria artificialmente o
armazenamento colunar, cuja compressao se beneficia de baixa cardinalidade e
distribuicao previsivel. Para evitar esse vies:

- `spend` segue distribuicao lognormal — em midia paga poucos anuncios
  concentram a maior parte do investimento (cauda longa).
- `impressions` correlaciona com `spend` mais ruido multiplicativo, em vez de
  ser independente.
- cliques e conversoes derivam de taxas por anuncio, nao globais.
- a hierarquia respeita cardinalidades reais: muitos anuncios por conjunto,
  muitos conjuntos por campanha.
- o numero de anuncios cresce sublinearmente em relacao ao fato, porque na
  pratica o fato cresce por DIAS, nao por novas entidades.

Uso:
    python benchmark/gerar_dados.py --escalas 10000 1000000
    python benchmark/gerar_dados.py --escalas 10000 100000 1000000 10000000
"""

import argparse
import math
import shutil
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

BASE_DIR = Path(__file__).resolve().parent
DADOS_DIR = BASE_DIR / "dados"

# Proporcoes da hierarquia, calibradas pelos dados reais do projeto:
# 673 anuncios / 334 conjuntos / 177 campanhas / 57 contas / 2 plataformas.
ANUNCIOS_POR_ADSET = 2
ADSETS_POR_CAMPANHA = 2
CAMPANHAS_POR_CONTA = 3

# Linhas por bloco de escrita — limita o pico de memoria em escalas grandes.
TAMANHO_BLOCO = 1_000_000

SCHEMA = pa.schema([
    ("anuncio_id", pa.int32()),
    ("adset_id", pa.int32()),
    ("campanha_id", pa.int32()),
    ("conta_id", pa.int32()),
    ("plataforma_id", pa.int8()),
    ("data", pa.date32()),
    ("spend", pa.float64()),
    ("impressions", pa.int64()),
    ("link_clicks", pa.int32()),
    ("conversions", pa.float64()),
    ("conversion_value", pa.float64()),
    ("video_views", pa.int64()),
    ("reach", pa.int64()),
])


def dimensionar(linhas: int) -> tuple[int, int]:
    """Escolhe quantos anuncios e quantos dias produzem o total desejado.

    O fato de midia cresce sobretudo pelo eixo temporal: um anunciante nao
    multiplica seus anuncios todo dia. Manter os anuncios crescendo com a raiz
    do total reproduz esse comportamento e evita uma dimensao artificialmente
    gigante.

    Args:
        linhas: Total de linhas desejado na tabela fato.

    Returns:
        Tupla ``(n_anuncios, n_dias)``.
    """
    n_anuncios = max(50, int(math.sqrt(linhas) * 3))
    n_dias = max(1, linhas // n_anuncios)
    return n_anuncios, n_dias


def gerar_bloco(
    rng: np.random.Generator,
    anuncios: np.ndarray,
    ctr_por_anuncio: np.ndarray,
    cvr_por_anuncio: np.ndarray,
    dia_offset: int,
    n_dias_bloco: int,
) -> dict[str, np.ndarray]:
    """Gera as linhas de fato de um intervalo de dias, para todos os anuncios.

    Args:
        rng: Gerador aleatorio (semente fixa garante reprodutibilidade).
        anuncios: Vetor de IDs de anuncio.
        ctr_por_anuncio: Taxa de clique caracteristica de cada anuncio.
        cvr_por_anuncio: Taxa de conversao caracteristica de cada anuncio.
        dia_offset: Deslocamento do primeiro dia do bloco.
        n_dias_bloco: Quantidade de dias neste bloco.

    Returns:
        Mapa de coluna para vetor de valores.
    """
    n_anuncios = anuncios.size
    total = n_anuncios * n_dias_bloco

    anuncio_id = np.tile(anuncios, n_dias_bloco)
    dias = np.repeat(np.arange(dia_offset, dia_offset + n_dias_bloco), n_anuncios)

    # Investimento: lognormal → cauda longa, poucos anuncios concentram gasto.
    spend = rng.lognormal(mean=2.5, sigma=1.2, size=total).round(4)

    # Impressoes derivam do investimento (CPM variavel) e nao de sorteio
    # independente — preserva a correlacao que existe no dado real.
    cpm = rng.uniform(5.0, 40.0, size=total)
    impressions = np.maximum(0, (spend / cpm * 1000).astype(np.int64))

    ctr = np.tile(ctr_por_anuncio, n_dias_bloco) * rng.uniform(0.6, 1.4, size=total)
    link_clicks = (impressions * ctr).astype(np.int32)

    cvr = np.tile(cvr_por_anuncio, n_dias_bloco) * rng.uniform(0.5, 1.5, size=total)
    conversions = (link_clicks * cvr).round(2)

    ticket = rng.uniform(50.0, 500.0, size=total)
    conversion_value = (conversions * ticket).round(4)

    video_views = (impressions * rng.uniform(0.0, 0.3, size=total)).astype(np.int64)
    reach = (impressions * rng.uniform(0.4, 0.9, size=total)).astype(np.int64)

    adset_id = anuncio_id // ANUNCIOS_POR_ADSET
    campanha_id = adset_id // ADSETS_POR_CAMPANHA
    conta_id = campanha_id // CAMPANHAS_POR_CONTA

    return {
        "anuncio_id": anuncio_id.astype(np.int32),
        "adset_id": adset_id.astype(np.int32),
        "campanha_id": campanha_id.astype(np.int32),
        "conta_id": conta_id.astype(np.int32),
        "plataforma_id": (anuncio_id % 2).astype(np.int8),
        "data": dias.astype("datetime64[D]").astype("int32"),
        "spend": spend,
        "impressions": impressions,
        "link_clicks": link_clicks,
        "conversions": conversions,
        "conversion_value": conversion_value,
        "video_views": video_views,
        "reach": reach,
    }


def gerar(linhas: int, destino: Path, semente: int = 42) -> int:
    """Gera um arquivo Parquet com o volume solicitado.

    Args:
        linhas: Total aproximado de linhas.
        destino: Caminho do arquivo Parquet a criar.
        semente: Semente do gerador, para reprodutibilidade.

    Returns:
        Numero de linhas efetivamente geradas.
    """
    rng = np.random.default_rng(semente)
    n_anuncios, n_dias = dimensionar(linhas)

    anuncios = np.arange(n_anuncios, dtype=np.int64)
    # Cada anuncio tem taxas caracteristicas estaveis ao longo do tempo.
    ctr_por_anuncio = rng.uniform(0.002, 0.08, size=n_anuncios)
    cvr_por_anuncio = rng.uniform(0.01, 0.25, size=n_anuncios)

    dias_por_bloco = max(1, TAMANHO_BLOCO // n_anuncios)

    destino.parent.mkdir(parents=True, exist_ok=True)
    escritor = pq.ParquetWriter(destino, SCHEMA, compression="snappy")

    gerados = 0
    dia = 0
    try:
        while dia < n_dias:
            bloco_dias = min(dias_por_bloco, n_dias - dia)
            dados = gerar_bloco(
                rng, anuncios, ctr_por_anuncio, cvr_por_anuncio, dia, bloco_dias
            )
            tabela = pa.table(
                {
                    nome: pa.array(valores, type=SCHEMA.field(nome).type)
                    for nome, valores in dados.items()
                },
                schema=SCHEMA,
            )
            escritor.write_table(tabela)
            gerados += tabela.num_rows
            dia += bloco_dias
    finally:
        escritor.close()

    return gerados


def rotulo(linhas: int) -> str:
    """Formata a escala de forma legivel (10k, 1M, 10M)."""
    if linhas >= 1_000_000:
        return f"{linhas // 1_000_000}M"
    if linhas >= 1_000:
        return f"{linhas // 1_000}k"
    return str(linhas)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera dados sinteticos para o benchmark.")
    parser.add_argument(
        "--escalas",
        type=int,
        nargs="+",
        default=[10_000, 100_000, 1_000_000, 10_000_000],
        help="Volumes de linhas a gerar.",
    )
    parser.add_argument(
        "--limpar", action="store_true", help="Apaga os dados gerados anteriormente."
    )
    args = parser.parse_args()

    if args.limpar and DADOS_DIR.exists():
        shutil.rmtree(DADOS_DIR)

    for linhas in sorted(args.escalas):
        nome = rotulo(linhas)
        destino = DADOS_DIR / f"fato_{nome}.parquet"
        n_anuncios, n_dias = dimensionar(linhas)

        gerados = gerar(linhas, destino)
        tamanho_mb = destino.stat().st_size / 1024 / 1024
        print(
            f"  {nome:>5}: {gerados:>10,} linhas | "
            f"{n_anuncios:>6,} anuncios x {n_dias:>5,} dias | "
            f"{tamanho_mb:6.1f} MB"
        )


if __name__ == "__main__":
    main()
