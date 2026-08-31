"""Carga da camada bronze — o ``L`` do ELT.

Le os arquivos brutos produzidos pelos extractors e grava cada registro no
Postgres **sem transformar nada**: o payload original vai integro para uma
coluna JSONB, acompanhado dos metadados de ingestao.

A tabela e append-only. Reprocessar o mesmo periodo cria um lote novo em vez
de sobrescrever o anterior; a deduplicacao acontece na camada silver, que
considera apenas o snapshot mais recente de cada dia.

Contrato com a extracao
-----------------------
Quando a carga recebe ``--run-id`` (o caso da DAG), cada arquivo bruto so e
aceito se o manifesto ao lado dele provar que veio DESTA execucao: mesma fonte,
mesmo ``run_id``, mesma janela e ``sha256`` batendo com o conteudo em disco.
Sem essa prova a carga falha — antes, um arquivo sobrado de execucao anterior
era reingerido em silencio como lote novo, e como a silver adota o snapshot
mais recente, dado velho voltaria a valer.

Sem ``--run-id`` (execucao local, `main.py --skip-extract`) a checagem e
dispensada de proposito: ali os arquivos em disco SAO a entrada pretendida.

Carga unica por execucao
------------------------
O manifesto prova que o artefato e DESTA execucao; ele nao impede rodar a
carga duas vezes com o mesmo artefato. O ``batch_id`` e sorteado a cada carga,
entao a segunda execucao nascia com identidade nova e a bronze terminava com
tudo duplicado, sem erro em lugar nenhum.

A identidade operacional e ``(source, run_id)``: ``bronze.ingestion_log``
guarda o ``run_id`` e um indice unico parcial impede a segunda confirmacao.
Antes de inserir, :func:`_conferir_replay` consulta o log e falha cedo; o
indice e a garantia, a consulta e a mensagem util. Sem ``run_id`` nao ha o que
comparar, e a carga local segue sem essa protecao.

Uso:
    docker compose run --rm etl_app python loaders/bronze_loader.py
    python -m loaders.bronze_loader --sources meta_ads,google_ads \\
        --run-id manual__2026-08-17T12:00:00 \\
        --start-date 2026-08-10 --end-date 2026-08-16
"""

import argparse
import json
import logging
import uuid
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

import manifesto
from config import configurar_logging, get_db_url
from plataformas import fontes, por_fonte

logger = logging.getLogger(__name__)

BASE_DIR: Path = Path(__file__).resolve().parent.parent
DDL_PATH: Path = BASE_DIR / "sql" / "bronze" / "init_bronze.sql"

# O arquivo bruto de cada fonte e o campo que carrega o dia de referencia vem
# do registro de plataformas — o mesmo lugar de onde o extrator tira o caminho
# em que escreve. Sem isso, renomear o arquivo de um lado so faz o loader
# emitir "arquivo bruto ausente" e o pipeline terminar sem carregar nada.


class LoteJaCarregado(RuntimeError):
    """Replay: a execucao ja tem lote confirmado para esta fonte.

    Nao e sucesso. A carga pedida nao aconteceu, e fingir que sim esconderia
    exatamente o caso que motivou esta checagem — reexecutar um artefato ja
    ingerido e acabar com a bronze duplicada, sem erro nenhum no caminho.
    """


def get_engine() -> Engine:
    """Cria a engine SQLAlchemy apontando para o Data Warehouse.

    Returns:
        Engine conectada.

    Raises:
        EnvironmentError: Se a URL do banco nao estiver configurada.
    """
    db_url = get_db_url()
    if not db_url:
        raise EnvironmentError(
            "Defina DW_DB_URL (ou SUPABASE_DB_URL) com a URL do Data Warehouse."
        )
    return create_engine(db_url)


def ensure_schema(engine: Engine) -> None:
    """Aplica o DDL da camada bronze (idempotente).

    Args:
        engine: Engine conectada ao banco.
    """
    ddl = DDL_PATH.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(ddl))
    logger.info("Schema bronze verificado.")


def _parse_reference_date(raw_value: str | None) -> date | None:
    """Converte o campo de data do payload para ``date``.

    Args:
        raw_value: Valor bruto, esperado no formato ``YYYY-MM-DD``.

    Returns:
        A data correspondente, ou ``None`` se ausente ou invalida.
    """
    if not raw_value:
        return None
    try:
        return datetime.strptime(str(raw_value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _preparar_linhas(
    registros: list[dict], source: str, date_field: str, batch_id: uuid.UUID
) -> list[dict]:
    """Converte os registros brutos nas linhas que a bronze recebe.

    E a metade PURA de :func:`load_source`: nao le disco, nao abre sessao e nao
    emite instrucao nenhuma. Registro sem dia de referencia utilizavel e
    descartado aqui, antes de qualquer contato com o banco — a bronze so
    aceita linha que sabe a que dia pertence.

    O aviso de descarte fica junto porque descreve esta decisao, e nao a
    gravacao que vem depois.

    Args:
        registros: Registros lidos do arquivo bruto.
        source: Identificador da plataforma (``meta_ads`` ou ``google_ads``).
        date_field: Nome do campo que contem o dia de referencia. Difere entre
            as plataformas, entao vem do registro em ``plataformas.py`` — o
            loader nao presume o nome do Meta.
        batch_id: Identificador desta unidade de carga.

    Returns:
        Linhas prontas para o insert, na ordem original. Lista vazia quando
        nenhum registro tinha data utilizavel.
    """
    linhas = []
    descartados = 0
    for registro in registros:
        referencia = _parse_reference_date(registro.get(date_field))
        if referencia is None:
            descartados += 1
            continue
        linhas.append({
            "source": source,
            "reference_date": referencia,
            "batch_id": str(batch_id),
            "payload": json.dumps(registro, ensure_ascii=False),
        })

    if descartados:
        logger.warning(
            "%s: %d registros sem '%s' valido foram descartados.",
            source, descartados, date_field,
        )
    return linhas


def load_source(
    session: Session,
    source: str,
    path: Path,
    date_field: str,
    batch_id: uuid.UUID,
    run_id: str | None,
) -> int:
    """Carrega um arquivo bruto na tabela ``bronze.raw_ads``.

    Args:
        session: Sessao SQLAlchemy ativa.
        source: Identificador da plataforma (``meta_ads`` ou ``google_ads``).
        path: Caminho do arquivo JSON bruto.
        date_field: Nome do campo que contem o dia de referencia.
        batch_id: Identificador FISICO deste lote — sorteado a cada carga.
        run_id: Identificador LOGICO da execucao que produziu o artefato, ou
            ``None`` em carga local. Gravado no ``ingestion_log``, onde o
            indice unico parcial impede que a mesma execucao confirme duas
            vezes a mesma fonte. Parametro obrigatorio de proposito: com valor
            default, um chamador novo perderia a protecao em silencio.

    Returns:
        Quantidade de registros inseridos.
    """
    if not path.exists():
        logger.warning("Arquivo bruto ausente, fonte ignorada: %s", path.name)
        return 0

    registros = json.loads(path.read_text(encoding="utf-8"))
    if not registros:
        logger.warning("Arquivo bruto vazio: %s", path.name)
        return 0

    linhas = _preparar_linhas(registros, source, date_field, batch_id)

    if not linhas:
        return 0

    session.execute(
        text(
            "INSERT INTO bronze.raw_ads (source, reference_date, batch_id, payload) "
            "VALUES (:source, :reference_date, :batch_id, CAST(:payload AS JSONB))"
        ),
        linhas,
    )

    datas = [linha["reference_date"] for linha in linhas]
    session.execute(
        text(
            "INSERT INTO bronze.ingestion_log "
            "(batch_id, source, run_id, start_date, end_date, row_count) "
            "VALUES (:batch_id, :source, :run_id, :start_date, :end_date, "
            ":row_count)"
        ),
        {
            "batch_id": str(batch_id),
            "source": source,
            "run_id": run_id,
            "start_date": min(datas),
            "end_date": max(datas),
            "row_count": len(linhas),
        },
    )

    logger.info(
        "bronze.raw_ads: %d registros de %s (%s a %s).",
        len(linhas), source, min(datas), max(datas),
    )
    return len(linhas)


def _conferir_artefatos(
    selecionadas: list[str], run_id: str, start_date: str, end_date: str
) -> None:
    """Exige que todo arquivo bruto a carregar pertenca a esta execucao.

    A checagem acontece ANTES de qualquer insert, e para todas as fontes de uma
    vez: aceitar o Meta e so entao descobrir que o Google e de outro run
    deixaria a bronze com meia execucao dentro.

    Args:
        selecionadas: Fontes a carregar.
        run_id: Identificador da execucao atual.
        start_date: Primeiro dia da janela pedida.
        end_date: Ultimo dia da janela pedida.

    Raises:
        ManifestoInvalido: Se qualquer artefato nao provar origem nesta
            execucao.
    """
    for fonte in selecionadas:
        plataforma = por_fonte(fonte)
        registro = manifesto.validar(
            plataforma, run_id=run_id, start_date=start_date, end_date=end_date
        )
        if registro.registros == 0:
            logger.info(
                "%s: extracao desta execucao retornou 0 registros — resultado "
                "legitimo, nada a carregar.", fonte,
            )
        else:
            logger.info(
                "%s: artefato validado (run_id %s, janela %s a %s, %d registros).",
                fonte, run_id, registro.start_date, registro.end_date,
                registro.registros,
            )


def _conferir_replay(
    session: Session, selecionadas: list[str], run_id: str
) -> None:
    """Recusa carregar de novo o que esta execucao ja confirmou.

    O ``batch_id`` e sorteado a cada carga, entao ele nao serve de identidade:
    reexecutar o mesmo artefato produzia um lote novo e duplicava a bronze sem
    erro nenhum. A identidade operacional e ``(source, run_id)``.

    Consulta todas as fontes selecionadas antes de inserir qualquer linha, pelo
    mesmo motivo de :func:`_conferir_artefatos`: recusar o Google so depois de
    ja ter gravado o Meta e uma falha mais cara de entender.

    Nao substitui o indice unico do banco — duas cargas simultaneas podem
    consultar antes de qualquer uma confirmar, e ali as duas passariam por
    aqui. Esta checagem serve para falhar cedo e com mensagem util; a garantia
    e do banco.

    Args:
        session: Sessao SQLAlchemy ativa.
        selecionadas: Fontes que esta carga pretende gravar.
        run_id: Identificador da execucao atual.

    Raises:
        LoteJaCarregado: Se alguma das fontes ja tiver lote confirmado para
            este ``run_id``.
    """
    resultado = session.execute(
        text("SELECT source FROM bronze.ingestion_log WHERE run_id = :run_id"),
        {"run_id": run_id},
    )
    confirmadas = {linha[0] for linha in resultado} & set(selecionadas)
    if confirmadas:
        raise LoteJaCarregado(
            f"Execucao '{run_id}' ja tem lote confirmado para: "
            f"{', '.join(sorted(confirmadas))}. Carregar de novo duplicaria a "
            f"bronze. Consulte bronze.ingestion_log por (source, run_id) antes "
            f"de uma nova tentativa."
        )


def run(
    sources: list[str] | None = None,
    run_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    """Carrega os arquivos brutos disponiveis na camada bronze.

    Args:
        sources: Fontes a carregar (``meta_ads`` e/ou ``google_ads``). Quando
            ``None``, carrega todas. Restringir importa numa execucao de uma
            plataforma so: o arquivo bruto da outra pode ter sobrado de uma
            execucao anterior e seria reingerido como lote novo, inflando a
            bronze com uma copia de dado ja carregado.
        run_id: Identificador da execucao. Quando informado, cada artefato
            precisa provar, pelo manifesto, que veio dela — e a carga falha se
            nao provar. Exige ``start_date`` e ``end_date``.
        start_date: Primeiro dia da janela pedida a esta execucao.
        end_date: Ultimo dia da janela pedida a esta execucao.

    Returns:
        Total de registros inseridos.

    Raises:
        ValueError: Se alguma fonte informada for desconhecida ou se
            ``run_id`` vier sem a janela correspondente.
        manifesto.ManifestoInvalido: Se algum artefato nao pertencer a esta
            execucao.
        LoteJaCarregado: Se ``run_id`` ja tiver lote confirmado para alguma
            das fontes pedidas.
    """
    selecionadas = fontes() if sources is None else sources
    invalidas = set(selecionadas) - set(fontes())
    if invalidas:
        raise ValueError(
            f"Fonte desconhecida: {', '.join(sorted(invalidas))}. "
            f"Valores aceitos: {', '.join(fontes())}."
        )

    if run_id is not None:
        if not (start_date and end_date):
            raise ValueError(
                "--run-id exige --start-date e --end-date: sem a janela nao ha "
                "como conferir se o artefato e o desta execucao."
            )
        _conferir_artefatos(selecionadas, run_id, start_date, end_date)
    else:
        logger.warning(
            "Carga sem run_id: os arquivos brutos em disco serao aceitos como "
            "estao (modo local / --skip-extract), e sem protecao contra "
            "replay — a garantia de carga unica vale para execucao "
            "identificada por run_id."
        )

    engine = get_engine()
    ensure_schema(engine)

    total = 0
    with Session(engine) as session:
        try:
            # Depois do banco aberto e antes de qualquer insert: e o unico
            # ponto em que da para saber o que ja foi confirmado.
            if run_id is not None:
                _conferir_replay(session, selecionadas, run_id)

            for source in selecionadas:
                plataforma = por_fonte(source)
                # batch_id por fonte — cada arquivo e uma unidade de carga.
                batch_id = uuid.uuid4()
                total += load_source(
                    session,
                    source,
                    plataforma.arquivo_bruto,
                    plataforma.campo_data,
                    batch_id,
                    run_id,
                )
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.error(
                "Erro na carga da bronze. Rollback realizado. Tipo: %s",
                type(exc).__name__,
            )
            raise

    logger.info("Carga da bronze concluida. Total: %d registros.", total)
    return total


def _parse_args() -> argparse.Namespace:
    """Parseia os argumentos da carga.

    Returns:
        Namespace com ``sources``, ``run_id``, ``start_date`` e ``end_date``.
    """
    parser = argparse.ArgumentParser(description="Carga da camada bronze.")
    parser.add_argument(
        "--sources",
        default=None,
        help=(
            "Fontes a carregar, separadas por virgula "
            f"({', '.join(fontes())}). Default: todas."
        ),
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Identificador da execucao. Com ele, cada artefato precisa provar "
            "no manifesto que veio desta execucao. Exige --start-date e "
            "--end-date."
        ),
    )
    parser.add_argument("--start-date", default=None, help="Janela: primeiro dia.")
    parser.add_argument("--end-date", default=None, help="Janela: ultimo dia.")

    args = parser.parse_args()
    if args.sources:
        args.sources = [f.strip() for f in args.sources.split(",") if f.strip()]
    return args


def main() -> None:
    """Entry point para execucao standalone via CLI."""
    configurar_logging()
    args = _parse_args()
    run(
        sources=args.sources,
        run_id=args.run_id,
        start_date=args.start_date,
        end_date=args.end_date,
    )


if __name__ == "__main__":
    main()
