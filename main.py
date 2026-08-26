"""Orquestrador do pipeline ELT (Extração → Bronze → Transformação com dbt).

O dado bruto vai integro para a camada bronze e todas as transformações
acontecem no banco, materializadas e testadas pelo dbt. Nenhuma etapa
transforma dado em Python.

Uso:
    docker compose run --rm etl_app python main.py --start-date 2026-03-30 --end-date 2026-03-31

Sem argumentos, extrai apenas o dia anterior.
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from config import configurar_logging, dbt_env, ontem, validate_env
from plataformas import PLATAFORMAS, chaves

logger = logging.getLogger("pipeline")

BASE_DIR: Path = Path(__file__).resolve().parent

SEPARATOR: str = "=" * 60

T = TypeVar("T")

# Etapas do pipeline, na ordem de execucao. A numeracao dos logs ("ETAPA 2/3")
# e derivada desta tupla: acrescentar uma etapa deixa de exigir renumerar os
# rotulos a mao em cada funcao.
ETAPAS: tuple[str, ...] = (
    "EXTRAÇÃO",
    "CARGA BRONZE (dado bruto imutável)",
    "TRANSFORMAÇÃO dbt (silver → gold) + TESTES",
)
ETAPA_EXTRACAO, ETAPA_BRONZE, ETAPA_DBT = ETAPAS


# ── Validação de argumentos ──────────────────────────────────


def _valid_date(value: str) -> str:
    """Valida que o valor está no formato YYYY-MM-DD.

    Args:
        value: String de data fornecida pelo usuário.

    Returns:
        A mesma string se válida.

    Raises:
        argparse.ArgumentTypeError: Se o formato for inválido.
    """
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Data inválida: '{value}'. Use o formato YYYY-MM-DD."
        )
    return value


def parse_args() -> argparse.Namespace:
    """Parseia e valida os argumentos de linha de comando.

    Returns:
        Namespace com ``start_date`` e ``end_date`` validados.

    Raises:
        SystemExit: Se start_date > end_date.
    """
    padrao = ontem()

    parser = argparse.ArgumentParser(
        description="Pipeline ELT: Meta/Google Ads → bronze → silver → gold",
    )
    parser.add_argument(
        "--start-date",
        type=_valid_date,
        default=padrao,
        help="Data inicial (YYYY-MM-DD). Default: ontem.",
    )
    parser.add_argument(
        "--end-date",
        type=_valid_date,
        default=padrao,
        help="Data final (YYYY-MM-DD). Default: ontem.",
    )
    # Os nomes de arquivo e a lista de plataformas saem do registro: a ajuda
    # da CLI nunca fica dessincronizada do que o pipeline realmente aceita.
    brutos = " / ".join(p.arquivo_bruto.name for p in PLATAFORMAS.values())
    aceitas = ", ".join(chaves())

    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help=(
            "Pula a extração e reprocessa os arquivos brutos já existentes "
            f"({brutos}). Útil para "
            "demonstrar transformação e carga sem consumir a API."
        ),
    )
    parser.add_argument(
        "--platforms",
        default=",".join(chaves()),
        help=(
            f"Plataformas a extrair, separadas por vírgula: {aceitas}. "
            f"Default: {','.join(chaves())}. Permite rodar o pipeline quando as "
            "credenciais de uma das plataformas estão indisponíveis."
        ),
    )

    parser.add_argument(
        "--permitir-contas-meta-indisponiveis",
        action="store_true",
        help=(
            "DESVIO EXCEPCIONAL. Por padrão a descoberta do Meta ABORTA se "
            "alguma conta estiver temporariamente indisponível, para não "
            "produzir snapshot parcial. Com esta flag, essas contas são "
            "excluídas com registro em log e a extração prossegue. Status de "
            "conta desconhecido continua abortando em qualquer caso. Use "
            "apenas em recuperação autorizada, execução a execução — a DAG "
            "nunca liga esta flag."
        ),
    )

    args = parser.parse_args()

    args.platforms = [p.strip().lower() for p in args.platforms.split(",") if p.strip()]
    invalid = set(args.platforms) - set(chaves())
    if invalid:
        parser.error(
            f"--platforms inválido: {', '.join(sorted(invalid))}. "
            f"Valores aceitos: {aceitas}."
        )
    if not args.platforms:
        parser.error("--platforms exige ao menos uma plataforma.")

    if args.start_date > args.end_date:
        parser.error(
            f"--start-date ({args.start_date}) não pode ser maior que "
            f"--end-date ({args.end_date})."
        )

    # Desvio pedido sem a plataforma que o consome, ou sem extração nenhuma, é
    # engano do operador — e engano silencioso aqui vira falsa sensação de que
    # o desvio está valendo.
    if args.permitir_contas_meta_indisponiveis:
        if args.skip_extract:
            parser.error(
                "--permitir-contas-meta-indisponiveis não faz sentido com "
                "--skip-extract: não há descoberta de contas."
            )
        if "meta" not in args.platforms:
            parser.error(
                "--permitir-contas-meta-indisponiveis exige 'meta' em "
                "--platforms."
            )

    return args


# ── Execução das etapas ──────────────────────────────────────


def _cabecalho(etapa: str, detalhe: str = "") -> None:
    """Registra o cabeçalho numerado de uma etapa.

    Args:
        etapa: Um dos valores de :data:`ETAPAS`.
        detalhe: Texto opcional acrescentado ao rótulo.
    """
    posicao = ETAPAS.index(etapa) + 1
    rotulo = f"ETAPA {posicao}/{len(ETAPAS)}: {etapa}"
    if detalhe:
        rotulo = f"{rotulo}  {detalhe}"

    logger.info(SEPARATOR)
    logger.info(rotulo)
    logger.info(SEPARATOR)


def executar_etapa(
    etapa: str,
    funcao: Callable[[], T],
    detalhe: str = "",
    detalhar_erro: bool = False,
) -> T:
    """Executa uma etapa do pipeline, abortando o processo se ela falhar.

    Os três blocos ``try/except`` da orquestração eram idênticos em forma:
    chamar, registrar a falha, sair com código 1.

    Args:
        etapa: Um dos valores de :data:`ETAPAS`.
        funcao: Chamada sem argumentos que executa a etapa.
        detalhe: Texto opcional para o cabeçalho.
        detalhar_erro: Se ``True``, registra a mensagem da exceção; se
            ``False`` (default), apenas o tipo. O default é conservador de
            propósito — mensagens de erro de SDK de API podem carregar token
            ou payload, e log não é lugar de segredo (ver ``config.mask``).
            Só a etapa do dbt detalha, porque a mensagem dela é nossa e
            informativa.

    Returns:
        O que ``funcao`` retornar.

    Raises:
        SystemExit: Código 1 se a etapa levantar qualquer exceção.
    """
    _cabecalho(etapa, detalhe)

    try:
        return funcao()
    except Exception as exc:
        motivo = exc if detalhar_erro else type(exc).__name__
        logger.error("FALHA NA ETAPA %s. Pipeline interrompido. Erro: %s", etapa, motivo)
        sys.exit(1)


def run_extraction(
    start_date: str,
    end_date: str,
    platforms: list[str],
    run_id: str | None = None,
    opcoes: dict[str, dict[str, bool]] | None = None,
) -> dict[str, int]:
    """Executa a extração das plataformas selecionadas.

    Args:
        start_date: Data inicial no formato ``YYYY-MM-DD``.
        end_date: Data final no formato ``YYYY-MM-DD``.
        platforms: Plataformas a extrair (``"meta"`` e/ou ``"google"``).
        run_id: Identificador desta execução, gravado no manifesto de cada
            artefato para que a carga possa exigir a prova de origem.
        opcoes: Desvios específicos por plataforma, no formato
            ``{chave: {nome_da_opcao: valor}}``. Só chega ao extrator daquela
            plataforma; ``None`` (o default) mantém o comportamento padrão.

    Returns:
        Mapa ``{plataforma: registros_extraidos}``.
    """
    counts: dict[str, int] = {}
    opcoes = opcoes or {}

    # O despacho percorre o registro em vez de um `if` por plataforma. O import
    # do SDK continua tardio — acontece dentro de `Plataforma.extrair`.
    for chave in platforms:
        plataforma = PLATAFORMAS[chave]
        logger.info("Extraindo %s...", plataforma.nome)
        counts[chave] = plataforma.extrair(
            start_date, end_date, run_id, **opcoes.get(chave, {})
        )

    return counts


def run_bronze(
    sources: list[str] | None = None,
    run_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> int:
    """Carrega os arquivos brutos na camada bronze, sem transformar.

    Args:
        sources: Fontes da bronze a carregar. ``None`` carrega todas — o caso
            de ``--skip-extract``, em que os arquivos em disco são a entrada.
        run_id: Identificador desta execução. Quando informado, cada artefato
            precisa provar no manifesto que veio dela.
        start_date: Primeiro dia da janela extraída.
        end_date: Último dia da janela extraída.

    Returns:
        Quantidade de registros inseridos.
    """
    from loaders import bronze_loader

    return bronze_loader.run(sources, run_id, start_date, end_date)


def run_dbt() -> None:
    """Executa ``dbt build`` — materializa silver e gold e roda os testes.

    Raises:
        RuntimeError: Se o dbt terminar com código de saída diferente de zero.
    """
    dbt_dir = BASE_DIR / "dbt"
    env = {**os.environ, **dbt_env()}

    resultado = subprocess.run(
        [
            "dbt", "build",
            "--project-dir", str(dbt_dir),
            "--profiles-dir", str(dbt_dir),
        ],
        env=env,
        check=False,
    )

    if resultado.returncode != 0:
        raise RuntimeError(
            f"dbt build falhou (exit {resultado.returncode}). "
            "Verifique os modelos e testes acima."
        )


# ── Main ─────────────────────────────────────────────────────


def main() -> None:
    """Orquestra o pipeline ELT completo com interrupção em caso de falha."""
    configurar_logging()
    args = parse_args()
    t0 = time.time()

    logger.info(SEPARATOR)
    logger.info("PIPELINE INICIADO — bronze → silver → gold")
    logger.info("Período: %s a %s", args.start_date, args.end_date)
    logger.info(SEPARATOR)

    # ── Validação de credenciais ──
    # Só são exigidas as credenciais das plataformas efetivamente extraídas;
    # a URL do Data Warehouse é sempre obrigatória.
    groups = (
        [] if args.skip_extract
        else [PLATAFORMAS[p].nome for p in args.platforms]
    )
    validate_env(groups=groups)

    # ── Extração ──
    # Identificador desta execução: vai para o manifesto de cada artefato e é
    # o que permite à carga recusar um JSON sobrado de outra execução. Fora do
    # Airflow não existe `run_id`, então o pipeline gera o seu.
    run_id = f"local__{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}"

    counts: dict[str, int] = {}
    if args.skip_extract:
        _cabecalho(ETAPA_EXTRACAO, "IGNORADA (--skip-extract)")
        logger.info("Reprocessando os arquivos brutos já existentes.")
    else:
        # Desvio excepcional: só é montado quando o operador pediu, e só
        # alcança o extrator do Meta. Sem a flag, `opcoes` fica vazio e o
        # comportamento é exatamente o de antes — fail closed.
        opcoes: dict[str, dict[str, bool]] = {}
        if args.permitir_contas_meta_indisponiveis:
            logger.warning(
                "DESVIO EXCEPCIONAL HABILITADO NESTA EXECUÇÃO: contas Meta "
                "temporariamente indisponíveis serão excluídas da descoberta "
                "em vez de abortar. Status desconhecido continua abortando."
            )
            opcoes["meta"] = {"permitir_contas_indisponiveis": True}

        counts = executar_etapa(
            ETAPA_EXTRACAO,
            lambda: run_extraction(
                args.start_date, args.end_date, args.platforms, run_id, opcoes
            ),
            detalhe=f"(período: {args.start_date} a {args.end_date})",
        )

        if sum(counts.values()) == 0:
            logger.warning("Nenhum registro extraído. Pipeline interrompido.")
            sys.exit(0)

    # ── Carga bruta na bronze ──
    # Com --platforms restrito, só a fonte recém-extraída entra: o arquivo
    # bruto da outra plataforma pode ter sobrado de uma execução anterior.
    # Com --skip-extract não há execução de origem para exigir, e os arquivos
    # em disco são deliberadamente a entrada — por isso o `run_id` não vai.
    fontes = (
        None if args.skip_extract
        else [PLATAFORMAS[p].fonte_bronze for p in args.platforms]
    )
    bronze_count = executar_etapa(
        ETAPA_BRONZE,
        lambda: run_bronze(
            fontes,
            None if args.skip_extract else run_id,
            None if args.skip_extract else args.start_date,
            None if args.skip_extract else args.end_date,
        ),
    )

    # ── Transformação no banco + testes de dados ──
    # Única etapa com `detalhar_erro`: a mensagem do RuntimeError é nossa e
    # diz o código de saída do dbt, sem risco de vazar credencial.
    executar_etapa(ETAPA_DBT, run_dbt, detalhar_erro=True)

    # ── Resumo ──
    elapsed = time.time() - t0
    extraidos = (
        "extração ignorada"
        if args.skip_extract
        else " | ".join(f"{p}={n}" for p, n in counts.items())
    )
    logger.info(SEPARATOR)
    logger.info("PIPELINE CONCLUÍDO COM SUCESSO (%.1fs)", elapsed)
    logger.info("Resumo: %s | Bronze=%d", extraidos, bronze_count)
    logger.info(SEPARATOR)


if __name__ == "__main__":
    main()
