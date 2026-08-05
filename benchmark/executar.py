"""Executa o benchmark comparativo PostgreSQL (row-store) x DuckDB (column-store).

Metodo
------
Para cada escala de dados:

1. Carrega o MESMO arquivo Parquet nos dois motores.
2. Cria indices equivalentes em ambos — a comparacao e entre motores bem
   configurados, nao entre um motor otimizado e outro negligenciado.
3. Executa cada consulta uma vez para aquecer cache e, em seguida, N vezes
   medidas. Reporta a MEDIANA, que resiste melhor a outliers de escalonamento
   de CPU e concorrencia do que a media.
4. Materializa todo o resultado (`fetchall`) para que nenhum motor se
   beneficie de avaliacao preguicosa.

Assimetrias conhecidas, declaradas
----------------------------------
- O DuckDB e embarcado: le do disco no mesmo processo, sem custo de protocolo
  de rede. O PostgreSQL paga serializacao e transporte via socket, mesmo local.
  Parte da diferenca em consultas rapidas e esse custo fixo, nao o motor de
  armazenamento.
- Por padrao os dois usam multiplas threads. Use `--threads-duckdb 1` para
  medir o motor colunar sem paralelismo.

Uso:
    python benchmark/executar.py
    python benchmark/executar.py --escalas 10k 1M --repeticoes 7
"""

import argparse
import csv
import io
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR.parent))

from benchmark.consultas import CONSULTAS  # noqa: E402

DADOS_DIR = BASE_DIR / "dados"
RESULTADOS_DIR = BASE_DIR / "resultados"

DDL_FATO = """
    CREATE TABLE fato_bench (
        anuncio_id       INTEGER          NOT NULL,
        adset_id         INTEGER          NOT NULL,
        campanha_id      INTEGER          NOT NULL,
        conta_id         INTEGER          NOT NULL,
        plataforma_id    SMALLINT         NOT NULL,
        data             DATE             NOT NULL,
        spend            DOUBLE PRECISION NOT NULL,
        impressions      BIGINT           NOT NULL,
        link_clicks      INTEGER          NOT NULL,
        conversions      DOUBLE PRECISION NOT NULL,
        conversion_value DOUBLE PRECISION NOT NULL,
        video_views      BIGINT           NOT NULL,
        reach            BIGINT           NOT NULL
    )
"""

COLUNAS = [
    "anuncio_id", "adset_id", "campanha_id", "conta_id", "plataforma_id",
    "data", "spend", "impressions", "link_clicks", "conversions",
    "conversion_value", "video_views", "reach",
]


# ── PostgreSQL ───────────────────────────────────────────────


def conectar_postgres():
    """Abre conexao com o PostgreSQL usando a URL do Data Warehouse.

    Returns:
        Conexao psycopg2.

    Raises:
        SystemExit: Se a URL nao estiver configurada.
    """
    import psycopg2

    from config import get_db_url

    url = get_db_url()
    if not url:
        sys.exit("Defina DW_DB_URL com a URL do PostgreSQL.")
    return psycopg2.connect(url)


def carregar_postgres(conn, parquet: Path) -> float:
    """Recria a tabela do benchmark no PostgreSQL e carrega o Parquet.

    Args:
        conn: Conexao aberta.
        parquet: Arquivo de dados.

    Returns:
        Tempo de carga em segundos, incluindo indices e ANALYZE.
    """
    inicio = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS fato_bench")
        cur.execute(DDL_FATO)

        arquivo = pq.ParquetFile(parquet)
        for lote in arquivo.iter_batches(batch_size=200_000):
            buffer = io.StringIO()
            escritor = csv.writer(buffer)
            escritor.writerows(zip(*[lote.column(c).to_pylist() for c in COLUNAS]))
            buffer.seek(0)
            cur.copy_expert(
                f"COPY fato_bench ({','.join(COLUNAS)}) FROM STDIN WITH CSV",
                buffer,
            )

        # Indices que qualquer DBA criaria num data mart com este padrao de
        # acesso: filtro por periodo e detalhamento por anuncio.
        cur.execute("CREATE INDEX idx_bench_data ON fato_bench (data)")
        cur.execute("CREATE INDEX idx_bench_anuncio ON fato_bench (anuncio_id)")
    conn.commit()

    # VACUUM nao pode rodar dentro de transacao, e o psycopg2 abre uma
    # implicitamente. Sem ANALYZE o planejador opera com estatisticas vazias e
    # escolhe planos ruins — a comparacao mediria o planejador, nao o motor.
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("VACUUM ANALYZE fato_bench")
    conn.autocommit = False

    return time.perf_counter() - inicio


def tamanho_postgres(conn) -> str:
    """Retorna o tamanho da tabela do benchmark, formatado."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_size_pretty(pg_total_relation_size('fato_bench'))")
        return cur.fetchone()[0]


# ── DuckDB ───────────────────────────────────────────────────


def carregar_duckdb(con, parquet: Path) -> float:
    """Cria a tabela do benchmark no DuckDB e carrega o Parquet.

    Args:
        con: Conexao DuckDB.
        parquet: Arquivo de dados.

    Returns:
        Tempo de carga em segundos, incluindo indices.
    """
    inicio = time.perf_counter()
    con.execute("DROP TABLE IF EXISTS fato_bench")
    con.execute(DDL_FATO)
    con.execute(
        f"INSERT INTO fato_bench SELECT {','.join(COLUNAS)} "
        f"FROM read_parquet('{parquet.as_posix()}')"
    )
    # Indices equivalentes aos do PostgreSQL, para nao penalizar o motor
    # colunar nas consultas seletivas.
    con.execute("CREATE INDEX idx_bench_data ON fato_bench (data)")
    con.execute("CREATE INDEX idx_bench_anuncio ON fato_bench (anuncio_id)")
    con.execute("CHECKPOINT")
    return time.perf_counter() - inicio


# ── Medicao ──────────────────────────────────────────────────


def medir(executar_sql, sql: str, repeticoes: int) -> tuple[float, float]:
    """Mede o tempo de execucao de uma consulta.

    Args:
        executar_sql: Funcao que executa o SQL e materializa o resultado.
        sql: Consulta a medir.
        repeticoes: Numero de execucoes medidas (alem do aquecimento).

    Returns:
        Tupla ``(mediana_ms, minimo_ms)``.
    """
    executar_sql(sql)  # aquecimento, descartado

    tempos: list[float] = []
    for _ in range(repeticoes):
        inicio = time.perf_counter()
        executar_sql(sql)
        tempos.append((time.perf_counter() - inicio) * 1000)

    return statistics.median(tempos), min(tempos)


def intervalo_datas(parquet: Path) -> tuple[date, date]:
    """Descobre os ultimos 7 dias presentes no arquivo.

    Args:
        parquet: Arquivo de dados.

    Returns:
        Tupla ``(data_inicio, data_fim)`` cobrindo os 7 dias finais.
    """
    con = duckdb.connect()
    minimo, maximo = con.execute(
        f"SELECT MIN(data), MAX(data) FROM read_parquet('{parquet.as_posix()}')"
    ).fetchone()
    con.close()
    inicio = max(minimo, maximo - timedelta(days=6))
    return inicio, maximo


# ── Orquestracao ─────────────────────────────────────────────


def rodar_escala(
    parquet: Path, rotulo: str, repeticoes: int, threads_duckdb: int | None
) -> list[dict]:
    """Executa todas as consultas nos dois motores para uma escala.

    Args:
        parquet: Arquivo de dados da escala.
        rotulo: Rotulo legivel da escala (ex: "1M").
        repeticoes: Execucoes medidas por consulta.
        threads_duckdb: Limite de threads do DuckDB, ou None para o padrao.

    Returns:
        Lista de resultados, um por consulta e motor.
    """
    linhas = pq.ParquetFile(parquet).metadata.num_rows
    data_inicio, data_fim = intervalo_datas(parquet)
    print(f"\n=== Escala {rotulo} — {linhas:,} linhas ===")

    conn_pg = conectar_postgres()
    con_duck = duckdb.connect(str(BASE_DIR / "bench.duckdb"))
    if threads_duckdb:
        con_duck.execute(f"SET threads TO {threads_duckdb}")

    try:
        t_pg = carregar_postgres(conn_pg, parquet)
        t_duck = carregar_duckdb(con_duck, parquet)

        arquivo_duck = BASE_DIR / "bench.duckdb"
        mb_duck = arquivo_duck.stat().st_size / 1024 / 1024 if arquivo_duck.exists() else 0
        print(
            f"  carga: PostgreSQL {t_pg:6.1f}s ({tamanho_postgres(conn_pg)}) | "
            f"DuckDB {t_duck:6.1f}s ({mb_duck:.0f} MB)"
        )

        cursor_pg = conn_pg.cursor()

        def exec_pg(sql: str) -> None:
            cursor_pg.execute(sql)
            cursor_pg.fetchall()

        def exec_duck(sql: str) -> None:
            con_duck.execute(sql).fetchall()

        resultados: list[dict] = []
        for chave, consulta in CONSULTAS.items():
            sql = consulta["sql"].format(
                data_inicio=data_inicio.isoformat(),
                data_fim=data_fim.isoformat(),
            )

            pg_mediana, pg_min = medir(exec_pg, sql, repeticoes)
            duck_mediana, duck_min = medir(exec_duck, sql, repeticoes)
            razao = pg_mediana / duck_mediana if duck_mediana else float("inf")

            vencedor = "DuckDB" if razao > 1 else "PostgreSQL"
            fator = razao if razao > 1 else (1 / razao if razao else 0)

            resultados.append({
                "escala": rotulo,
                "linhas": linhas,
                "consulta": chave,
                "nome": consulta["nome"],
                "perfil": consulta["perfil"],
                "postgres_ms": round(pg_mediana, 2),
                "duckdb_ms": round(duck_mediana, 2),
                "postgres_min_ms": round(pg_min, 2),
                "duckdb_min_ms": round(duck_min, 2),
                "vencedor": vencedor,
                "fator": round(fator, 2),
            })

            print(
                f"  {chave} {consulta['perfil'][:30]:32} "
                f"PG {pg_mediana:9.2f}ms | Duck {duck_mediana:9.2f}ms | "
                f"{vencedor} {fator:.1f}x"
            )

        cursor_pg.close()
        return resultados

    finally:
        conn_pg.close()
        con_duck.close()


def gravar_resultados(resultados: list[dict]) -> None:
    """Grava os resultados em CSV e em tabela Markdown.

    Args:
        resultados: Linhas de resultado acumuladas.
    """
    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = RESULTADOS_DIR / "benchmark.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=list(resultados[0]))
        escritor.writeheader()
        escritor.writerows(resultados)

    md_path = RESULTADOS_DIR / "benchmark.md"
    with md_path.open("w", encoding="utf-8") as f:
        f.write("# Resultados do benchmark\n\n")
        f.write("Tempos em milissegundos (mediana). Menor e melhor.\n\n")
        escalas = sorted({r["escala"] for r in resultados},
                         key=lambda e: next(x["linhas"] for x in resultados if x["escala"] == e))
        for escala in escalas:
            linhas_escala = [r for r in resultados if r["escala"] == escala]
            total = linhas_escala[0]["linhas"]
            f.write(f"## Escala {escala} — {total:,} linhas\n\n")
            f.write("| Consulta | Perfil | PostgreSQL | DuckDB | Vencedor | Fator |\n")
            f.write("|---|---|---:|---:|---|---:|\n")
            for r in linhas_escala:
                f.write(
                    f"| {r['consulta']} — {r['nome']} | {r['perfil']} | "
                    f"{r['postgres_ms']:.1f} ms | {r['duckdb_ms']:.1f} ms | "
                    f"{r['vencedor']} | {r['fator']:.1f}x |\n"
                )
            f.write("\n")

    print(f"\nResultados em {csv_path.name} e {md_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark PostgreSQL x DuckDB.")
    parser.add_argument("--escalas", nargs="+", help="Rotulos a executar (ex: 10k 1M).")
    parser.add_argument("--repeticoes", type=int, default=5, help="Execucoes medidas.")
    parser.add_argument(
        "--threads-duckdb", type=int, default=None,
        help="Limita as threads do DuckDB. Sem o parametro, usa o padrao.",
    )
    args = parser.parse_args()

    arquivos = sorted(
        DADOS_DIR.glob("fato_*.parquet"),
        key=lambda p: pq.ParquetFile(p).metadata.num_rows,
    )
    if not arquivos:
        sys.exit("Nenhum dado gerado. Rode antes: python benchmark/gerar_dados.py")

    if args.escalas:
        alvos = {e.lower() for e in args.escalas}
        arquivos = [p for p in arquivos if p.stem.replace("fato_", "").lower() in alvos]

    resultados: list[dict] = []
    for parquet in arquivos:
        rotulo = parquet.stem.replace("fato_", "")
        resultados.extend(
            rodar_escala(parquet, rotulo, args.repeticoes, args.threads_duckdb)
        )

    if resultados:
        gravar_resultados(resultados)


if __name__ == "__main__":
    main()
