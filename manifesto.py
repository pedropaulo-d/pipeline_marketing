"""Manifesto de extracao — prova de que um JSON bruto pertence a esta execucao.

O problema que isto fecha
-------------------------
``bronze_loader`` carregava todo ``temp_*_raw.json`` que existisse em disco, sem
nenhuma forma de saber quem o escreveu nem quando. Os arquivos nao carregam
metadado: sao a lista crua de registros da API. Consequencias medidas na
auditoria de 17/08/2026:

- extracao do Meta falha, alguem marca a task como sucesso na UI, e o
  ``temp_meta_raw.json`` de uma execucao ANTERIOR entra na bronze como lote
  novo, com ``extracted_at`` mais recente — e a silver adota o mais recente;
- ``--platforms google`` deixava o arquivo do Meta sobrando (armadilha nº 9),
  hoje contornada pelo ``main.py`` passando as fontes, mas nao pela DAG;
- nao havia como distinguir "a extracao rodou e nao trouxe nada" de "o arquivo
  sumiu" ou "o arquivo e de ontem".

Cada extracao passa a gravar, ao lado do JSON bruto, um manifesto com a fonte,
o ``run_id``, a janela consultada, o instante, a contagem de registros e o
``sha256`` do arquivo. O loader so aceita o arquivo se o manifesto casar com o
que a execucao atual espera — inclusive o hash, que amarra manifesto e conteudo.

Nao e formato novo nem servico novo: e um JSON ao lado do outro, escrito e lido
pelos mesmos processos que ja escrevem e leem o bruto.

Uso:
    from manifesto import gravar, ler, validar

    gravar(plataforma, run_id="manual__...", start_date=..., end_date=...,
           registros=527)
    problemas = validar(plataforma, run_id=..., start_date=..., end_date=...)
"""

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plataformas import Plataforma

# Sufixo do arquivo intermediario da escrita atomica. Ignorado pelo git via
# `*.parcial`, para que um resto de execucao interrompida nunca seja versionado.
SUFIXO_PARCIAL: str = ".parcial"

# Versao do formato. Existe para que um manifesto gravado por uma versao
# anterior do codigo seja rejeitado explicitamente, e nao lido pela metade.
VERSAO: int = 1


class ManifestoInvalido(RuntimeError):
    """Manifesto ausente, ilegivel ou incompativel com a execucao atual."""


@dataclass(frozen=True)
class Manifesto:
    """Metadados de uma extracao concluida.

    Attributes:
        versao: Versao do formato do manifesto.
        fonte: Valor de ``source`` na bronze (``meta_ads`` / ``google_ads``).
        run_id: Identificador da execucao que produziu o arquivo. ``None`` em
            execucao local sem orquestrador.
        start_date: Primeiro dia da janela consultada (``YYYY-MM-DD``).
        end_date: Ultimo dia da janela consultada (``YYYY-MM-DD``).
        extraido_em: Instante da gravacao, em UTC e ISO 8601.
        registros: Quantidade de registros no arquivo bruto. Zero e um
            resultado legitimo e distinguivel de arquivo ausente.
        sha256: Hash do arquivo bruto, que amarra manifesto e conteudo.
    """

    versao: int
    fonte: str
    run_id: str | None
    start_date: str
    end_date: str
    extraido_em: str
    registros: int
    sha256: str


def escrever_json_atomico(caminho: Path, conteudo: Any, **kwargs) -> None:
    """Escreve um JSON de forma que o caminho final nunca fique pela metade.

    Grava num arquivo vizinho e so entao renomeia. ``os.replace`` e atomico
    dentro do mesmo sistema de arquivos, entao o caminho final so passa a
    existir com o conteudo inteiro — quem le encontra a versao anterior ou a
    nova, nunca um JSON truncado.

    Importa porque os brutos sao a entrada do ``--skip-extract``: uma extracao
    interrompida no meio da escrita deixaria, no modo local (que nao valida
    manifesto), um arquivo que so falha ao ser desserializado.

    Args:
        caminho: Destino final.
        conteudo: Estrutura serializavel.
        **kwargs: Repassados a ``json.dump``.

    Raises:
        BaseException: O que a serializacao levantar, sem alteracao. O arquivo
            parcial e removido antes de propagar e o destino final fica
            intocado.
    """
    parcial = caminho.with_name(caminho.name + SUFIXO_PARCIAL)
    try:
        with open(parcial, "w", encoding="utf-8") as arquivo:
            json.dump(conteudo, arquivo, **kwargs)
    # `BaseException`, e nao `Exception`: `KeyboardInterrupt` e `SystemExit`
    # tambem interrompem a escrita e tambem devem limpar o arquivo parcial. O
    # `raise` seco logo abaixo garante que nada e mascarado. Contra `SIGKILL`
    # nao ha o que fazer — sobra um `.parcial`, que e inofensivo e ignorado
    # pelo git; o destino final continua sendo a versao anterior, integra.
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise

    os.replace(parcial, caminho)


def _hash_arquivo(caminho: Path) -> str:
    """Calcula o sha256 de um arquivo.

    Args:
        caminho: Arquivo a ler.

    Returns:
        Hash hexadecimal.
    """
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def gravar(
    plataforma: Plataforma,
    run_id: str | None,
    start_date: str,
    end_date: str,
    registros: int,
) -> Manifesto:
    """Grava o manifesto ao lado do arquivo bruto ja escrito.

    Args:
        plataforma: Entrada do registro de plataformas.
        run_id: Identificador da execucao, ou ``None`` em execucao local.
        start_date: Primeiro dia da janela consultada.
        end_date: Ultimo dia da janela consultada.
        registros: Quantidade de registros gravados no arquivo bruto.

    Returns:
        O manifesto gravado.

    Raises:
        FileNotFoundError: Se o arquivo bruto nao existir. O manifesto descreve
            um arquivo — grava-lo sem ele produziria uma prova sem objeto.
    """
    bruto = plataforma.arquivo_bruto
    if not bruto.exists():
        raise FileNotFoundError(
            f"Arquivo bruto ausente ao gravar o manifesto: {bruto}"
        )

    manifesto = Manifesto(
        versao=VERSAO,
        fonte=plataforma.fonte_bronze,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
        extraido_em=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        registros=registros,
        sha256=_hash_arquivo(bruto),
    )

    escrever_json_atomico(
        plataforma.arquivo_manifesto, asdict(manifesto), indent=2, ensure_ascii=False
    )
    return manifesto


def ler(plataforma: Plataforma) -> Manifesto:
    """Le o manifesto de uma plataforma.

    Args:
        plataforma: Entrada do registro de plataformas.

    Returns:
        O manifesto lido.

    Raises:
        ManifestoInvalido: Se o arquivo nao existir, nao for JSON valido ou nao
            tiver os campos do formato.
    """
    caminho = plataforma.arquivo_manifesto
    if not caminho.exists():
        raise ManifestoInvalido(
            f"Manifesto ausente: {caminho.name}. O arquivo bruto de "
            f"{plataforma.fonte_bronze} nao tem prova de origem — nao da para "
            "saber se veio desta execucao."
        )

    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ManifestoInvalido(f"Manifesto ilegivel: {caminho.name}.") from exc

    try:
        return Manifesto(**dados)
    except TypeError as exc:
        raise ManifestoInvalido(
            f"Manifesto fora do formato esperado: {caminho.name}."
        ) from exc


def validar(
    plataforma: Plataforma,
    run_id: str,
    start_date: str,
    end_date: str,
) -> Manifesto:
    """Confere se o arquivo bruto em disco pertence a esta execucao.

    Cada checagem corresponde a um modo de falha observado ou previsto:
    manifesto ausente (arquivo legado ou extracao que nao rodou), fonte trocada,
    ``run_id`` de outra execucao (Meta novo + Google velho, por exemplo), janela
    diferente da pedida, e conteudo alterado depois da extracao.

    Args:
        plataforma: Entrada do registro de plataformas.
        run_id: Identificador da execucao atual.
        start_date: Primeiro dia da janela pedida a esta execucao.
        end_date: Ultimo dia da janela pedida a esta execucao.

    Returns:
        O manifesto validado.

    Raises:
        ManifestoInvalido: Se qualquer checagem falhar. A mensagem lista todos
            os problemas encontrados, e nao apenas o primeiro.
    """
    manifesto = ler(plataforma)
    bruto = plataforma.arquivo_bruto

    problemas: list[str] = []

    if manifesto.versao != VERSAO:
        problemas.append(
            f"versao do manifesto {manifesto.versao}, esperada {VERSAO}"
        )
    if manifesto.fonte != plataforma.fonte_bronze:
        problemas.append(
            f"fonte '{manifesto.fonte}', esperada '{plataforma.fonte_bronze}'"
        )
    if manifesto.run_id != run_id:
        problemas.append(
            f"run_id '{manifesto.run_id}', esperado '{run_id}' — o arquivo e de "
            "outra execucao"
        )
    if (manifesto.start_date, manifesto.end_date) != (start_date, end_date):
        problemas.append(
            f"janela {manifesto.start_date}..{manifesto.end_date}, esperada "
            f"{start_date}..{end_date}"
        )
    if not bruto.exists():
        problemas.append(f"arquivo bruto ausente: {bruto.name}")
    elif _hash_arquivo(bruto) != manifesto.sha256:
        problemas.append(
            f"sha256 de {bruto.name} nao confere com o manifesto — o arquivo "
            "mudou depois da extracao"
        )

    if problemas:
        raise ManifestoInvalido(
            f"Artefato de {plataforma.fonte_bronze} rejeitado: "
            + "; ".join(problemas)
        )

    return manifesto
