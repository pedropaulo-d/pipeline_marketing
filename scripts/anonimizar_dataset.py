"""Desidentifica os JSONs brutos com contrato explicito e fail closed.

Esta e uma ferramenta secundaria para reproducao a partir dos brutos. A
superficie oficial de material da Defesa continua sendo Gold ->
``data/exposicao/``. Gerar estes JSONs nao autoriza publica-los.

Seguranca
---------
- toda chave top-level e classificada por plataforma;
- campo, tipo, estrutura aninhada ou ``action_type`` novo aborta;
- IDs e nomes usam o HMAC de :mod:`pseudonimos`, com chave local;
- metricas e datas sao copiadas sem conversao;
- a saida e construida campo a campo, nunca por copia do registro;
- JSON e manifesto so substituem os anteriores depois dos pos-checks.

Uso::

    python scripts/anonimizar_dataset.py
    python scripts/anonimizar_dataset.py --entrada temp_meta_raw.json \
        --plataforma meta --saida data/anonimizado/meta.json

O destino padrao e ``data/anonimizado/``. Escrever sob ``data/publico/``
exige ``--permitir-publicacao``, que apenas libera o caminho: a autorizacao
escrita da agencia continua obrigatoria.
"""

import argparse
import hashlib
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import config  # noqa: F401  — carrega o .env pela fonte unica do projeto
import pseudonimos
from config import configurar_logging
from plataformas import PLATAFORMAS

BASE_DIR: Path = Path(__file__).resolve().parent.parent
SAIDA_PADRAO: Path = BASE_DIR / "data" / "anonimizado"
DIRETORIO_PUBLICACAO: Path = BASE_DIR / "data" / "publico"
SUFIXO_PARCIAL: str = ".parcial"
VERSAO_CONTRATO: int = 1

PSEUDONIMIZAR_ID: str = "PSEUDONIMIZAR_ID"
PSEUDONIMIZAR_NOME: str = "PSEUDONIMIZAR_NOME"
PRESERVAR_METRICA: str = "PRESERVAR_METRICA"
PRESERVAR_DATA: str = "PRESERVAR_DATA"
ESTRUTURA_ANINHADA: str = "ESTRUTURA_ANINHADA"
PROIBIDO: str = "PROIBIDO"
IGNORADO_SEGURO: str = "IGNORADO_SEGURO"


class ContratoAnonimizacaoQuebrado(Exception):
    """O bruto nao satisfaz o contrato seguro da plataforma."""


@dataclass(frozen=True)
class Campo:
    """Classificacao estrutural de um campo bruto.

    Attributes:
        categoria: Tratamento aplicado ao campo.
        tipos: Tipos Python aceitos depois do parse do JSON.
        obrigatorio: Se a ausencia quebra o contrato.
        nivel: Dominio de entidade usado pelo HMAC, quando aplicavel.
        campo_id: ID que define a identidade de um campo de nome.
    """

    categoria: str
    tipos: tuple[type, ...]
    obrigatorio: bool = True
    nivel: str | None = None
    campo_id: str | None = None


@dataclass(frozen=True)
class Resultado:
    """Resumo nao identificavel de uma geracao concluida."""

    registros: int
    nomes: int
    ids: int
    manifesto: Path
    sha256: str


# Allowlist observada nos brutos reais de 18/08/2026. Um tipo novo pode ser
# metrica legitima ou conversao customizada com nome/ID de cliente; nos dois
# casos exige revisao explicita antes de entrar aqui.
ACTION_TYPES_META_PERMITIDOS: frozenset[str] = frozenset({
    "comment",
    "landing_page_view",
    "lead",
    "like",
    "link_click",
    "offsite_complete_registration_add_meta_leads",
    "offsite_content_view_add_20_s_calls",
    "offsite_content_view_add_meta_leads",
    "offsite_conversion.fb_pixel_custom",
    "offsite_conversion.fb_pixel_lead",
    "offsite_conversion.fb_pixel_view_content",
    "offsite_lead_add_20_s_calls",
    "offsite_search_add_meta_leads",
    "omni_landing_page_view",
    "omni_view_content",
    "onsite_conversion.lead",
    "onsite_conversion.lead_grouped",
    "onsite_conversion.messaging_block",
    "onsite_conversion.messaging_conversation_replied_7d",
    "onsite_conversion.messaging_conversation_started_7d",
    "onsite_conversion.messaging_first_reply",
    "onsite_conversion.messaging_user_depth_2_message_send",
    "onsite_conversion.messaging_user_depth_3_message_send",
    "onsite_conversion.messaging_user_depth_5_message_send",
    "onsite_conversion.post_net_comment",
    "onsite_conversion.post_net_like",
    "onsite_conversion.post_net_save",
    "onsite_conversion.post_save",
    "onsite_conversion.post_unlike",
    "onsite_conversion.post_unsave",
    "onsite_conversion.total_messaging_connection",
    "onsite_web_app_view_content",
    "onsite_web_lead",
    "onsite_web_view_content",
    "page_engagement",
    "photo_view",
    "post",
    "post_engagement",
    "post_interaction_gross",
    "post_interaction_net",
    "post_reaction",
    "video_view",
    "view_content",
})

CONTRATOS: dict[str, dict[str, Campo]] = {
    "meta": {
        "account_id": Campo(PSEUDONIMIZAR_ID, (str,), nivel="conta"),
        "account_name": Campo(
            PSEUDONIMIZAR_NOME, (str,), nivel="conta", campo_id="account_id"
        ),
        "campaign_id": Campo(PSEUDONIMIZAR_ID, (str,), nivel="campanha"),
        "campaign_name": Campo(
            PSEUDONIMIZAR_NOME,
            (str,),
            nivel="campanha",
            campo_id="campaign_id",
        ),
        "adset_id": Campo(PSEUDONIMIZAR_ID, (str,), nivel="adset"),
        "adset_name": Campo(
            PSEUDONIMIZAR_NOME, (str,), nivel="adset", campo_id="adset_id"
        ),
        "ad_id": Campo(PSEUDONIMIZAR_ID, (str,), nivel="anuncio"),
        "ad_name": Campo(
            PSEUDONIMIZAR_NOME, (str,), nivel="anuncio", campo_id="ad_id"
        ),
        "spend": Campo(PRESERVAR_METRICA, (str,)),
        "impressions": Campo(PRESERVAR_METRICA, (str,)),
        "inline_link_clicks": Campo(PRESERVAR_METRICA, (str,)),
        "reach": Campo(PRESERVAR_METRICA, (str,)),
        "actions": Campo(ESTRUTURA_ANINHADA, (list,), obrigatorio=False),
        "action_values": Campo(ESTRUTURA_ANINHADA, (list,), obrigatorio=False),
        "date_start": Campo(PRESERVAR_DATA, (str,)),
        "date_stop": Campo(PRESERVAR_DATA, (str,)),
    },
    "google": {
        "date": Campo(PRESERVAR_DATA, (str,)),
        "account_id": Campo(PSEUDONIMIZAR_ID, (str,), nivel="conta"),
        "account_name": Campo(
            PSEUDONIMIZAR_NOME, (str,), nivel="conta", campo_id="account_id"
        ),
        "campaign_id": Campo(PSEUDONIMIZAR_ID, (str,), nivel="campanha"),
        "campaign_name": Campo(
            PSEUDONIMIZAR_NOME,
            (str,),
            nivel="campanha",
            campo_id="campaign_id",
        ),
        "ad_group_id": Campo(PSEUDONIMIZAR_ID, (str,), nivel="adset"),
        "ad_group_name": Campo(
            PSEUDONIMIZAR_NOME,
            (str,),
            nivel="adset",
            campo_id="ad_group_id",
        ),
        "ad_id": Campo(PSEUDONIMIZAR_ID, (str,), nivel="anuncio"),
        "ad_name": Campo(
            PSEUDONIMIZAR_NOME, (str,), nivel="anuncio", campo_id="ad_id"
        ),
        "impressions": Campo(PRESERVAR_METRICA, (int,)),
        "clicks": Campo(PRESERVAR_METRICA, (int,)),
        "cost": Campo(PRESERVAR_METRICA, (float,)),
        "conversions": Campo(PRESERVAR_METRICA, (float,)),
        "conversions_value": Campo(PRESERVAR_METRICA, (float,)),
        "video_trueview_views": Campo(PRESERVAR_METRICA, (int,)),
    },
}

RELACOES: dict[str, tuple[tuple[str, str], ...]] = {
    "meta": (
        ("campaign_id", "account_id"),
        ("adset_id", "campaign_id"),
        ("ad_id", "adset_id"),
    ),
    "google": (
        ("campaign_id", "account_id"),
        ("ad_group_id", "campaign_id"),
        ("ad_id", "ad_group_id"),
    ),
}


def _tipo_aceito(valor: Any, tipos: tuple[type, ...]) -> bool:
    """Confere tipos exatamente, sem aceitar ``bool`` como ``int``."""
    return type(valor) in tipos


def _validar_decimal_textual(valor: str, campo: str, indice: int) -> None:
    """Valida metrica textual sem converter o valor de saida."""
    try:
        numero = Decimal(valor)
    except InvalidOperation as erro:
        raise ContratoAnonimizacaoQuebrado(
            f"Metrica invalida em {campo}, registro {indice}."
        ) from erro
    if not numero.is_finite() or numero < 0:
        raise ContratoAnonimizacaoQuebrado(
            f"Metrica invalida em {campo}, registro {indice}."
        )


def _validar_data(valor: str, campo: str, indice: int) -> None:
    """Valida uma data ISO sem altera-la."""
    try:
        date.fromisoformat(valor)
    except ValueError as erro:
        raise ContratoAnonimizacaoQuebrado(
            f"Data invalida em {campo}, registro {indice}."
        ) from erro


def _validar_estrutura_aninhada(
    itens: list[Any], campo: str, indice: int
) -> None:
    """Valida ``actions``/``action_values`` com allowlists em dois niveis."""
    for posicao, item in enumerate(itens):
        if type(item) is not dict:
            raise ContratoAnonimizacaoQuebrado(
                f"Item nao objeto em {campo}, registro {indice}, item {posicao}."
            )
        if set(item) != {"action_type", "value"}:
            raise ContratoAnonimizacaoQuebrado(
                f"Estrutura desconhecida em {campo}, registro {indice}, "
                f"item {posicao}."
            )
        if type(item["action_type"]) is not str or type(item["value"]) is not str:
            raise ContratoAnonimizacaoQuebrado(
                f"Tipo invalido em {campo}, registro {indice}, item {posicao}."
            )
        if item["action_type"] not in ACTION_TYPES_META_PERMITIDOS:
            # Nao incluir o valor: um tipo customizado pode carregar identidade.
            raise ContratoAnonimizacaoQuebrado(
                f"action_type nao aprovado em {campo}, registro {indice}, "
                f"item {posicao}. Revise a allowlist explicitamente."
            )
        _validar_decimal_textual(item["value"], f"{campo}.value", indice)


def validar_registro(registro: Any, plataforma: str, indice: int) -> None:
    """Valida schema, obrigatoriedade e tipos de um registro bruto."""
    if type(registro) is not dict:
        raise ContratoAnonimizacaoQuebrado(
            f"Registro {indice} de {plataforma} nao e objeto JSON."
        )

    contrato = CONTRATOS[plataforma]
    desconhecidos = set(registro) - set(contrato)
    if desconhecidos:
        raise ContratoAnonimizacaoQuebrado(
            f"{len(desconhecidos)} campo(s) top-level desconhecido(s) em "
            f"{plataforma}, registro {indice}."
        )

    ausentes = {
        nome for nome, campo in contrato.items()
        if campo.obrigatorio and nome not in registro
    }
    if ausentes:
        raise ContratoAnonimizacaoQuebrado(
            f"{len(ausentes)} campo(s) obrigatorio(s) ausente(s) em "
            f"{plataforma}, registro {indice}."
        )

    for nome, valor in registro.items():
        campo = contrato[nome]
        if not _tipo_aceito(valor, campo.tipos):
            raise ContratoAnonimizacaoQuebrado(
                f"Tipo invalido em {nome}, registro {indice} de {plataforma}."
            )
        if campo.categoria == PSEUDONIMIZAR_ID and not valor:
            raise ContratoAnonimizacaoQuebrado(
                f"ID vazio em {nome}, registro {indice} de {plataforma}."
            )
        if campo.categoria == PRESERVAR_DATA:
            _validar_data(valor, nome, indice)
        elif campo.categoria == PRESERVAR_METRICA:
            if type(valor) is str:
                _validar_decimal_textual(valor, nome, indice)
            elif not math.isfinite(valor) or valor < 0:
                raise ContratoAnonimizacaoQuebrado(
                    f"Metrica invalida em {nome}, registro {indice}."
                )
        elif campo.categoria == ESTRUTURA_ANINHADA:
            _validar_estrutura_aninhada(valor, nome, indice)

    if plataforma == "meta" and registro["date_start"] != registro["date_stop"]:
        raise ContratoAnonimizacaoQuebrado(
            f"Registro Meta {indice} nao representa um unico dia."
        )


def validar_hierarquia(registros: list[dict], plataforma: str) -> None:
    """Garante que cada filho tem um unico pai no arquivo."""
    for filho, pai in RELACOES[plataforma]:
        pais: dict[str, str] = {}
        for registro in registros:
            anterior = pais.setdefault(registro[filho], registro[pai])
            if anterior != registro[pai]:
                raise ContratoAnonimizacaoQuebrado(
                    f"Hierarquia inconsistente em {plataforma}: uma entidade "
                    "filha possui mais de um pai."
                )


def _identidade_assinada(plataforma: str, external_id: str) -> str:
    """Compoe a entrada estavel e separada por fonte para o HMAC oficial."""
    return f"bruto:v{VERSAO_CONTRATO}|{plataforma}|{external_id}"


def _pseudonimos_do_registro(
    registro: dict,
    plataforma: str,
    colisoes: dict[tuple[str, str, str], str],
) -> dict[str, str]:
    """Gera um rotulo por entidade e detecta colisao do digest truncado."""
    rotulos: dict[str, str] = {}
    for nome, campo in CONTRATOS[plataforma].items():
        if campo.categoria != PSEUDONIMIZAR_ID:
            continue
        original = registro[nome]
        rotulo = pseudonimos.gerar_id_publico(
            campo.nivel or "", _identidade_assinada(plataforma, original)
        )
        chave = (plataforma, campo.nivel or "", rotulo)
        anterior = colisoes.setdefault(chave, original)
        if anterior != original:
            raise ContratoAnonimizacaoQuebrado(
                f"Colisao de pseudonimo no nivel {campo.nivel} de {plataforma}."
            )
        rotulos[nome] = rotulo
    return rotulos


def anonimizar_registro(
    registro: dict,
    plataforma: str,
    colisoes: dict[tuple[str, str, str], str] | None = None,
) -> dict:
    """Constroi a saida permitida campo a campo.

    Args:
        registro: Registro bruto ja parseado.
        plataforma: ``meta`` ou ``google``.
        colisoes: Registro efemero para detectar colisao entre entidades.

    Returns:
        Novo objeto apenas com campos declarados no contrato.
    """
    validar_registro(registro, plataforma, 0)
    controle = colisoes if colisoes is not None else {}
    rotulos = _pseudonimos_do_registro(registro, plataforma, controle)
    saida: dict[str, Any] = {}

    for nome, campo in CONTRATOS[plataforma].items():
        if nome not in registro:
            continue
        if campo.categoria == PSEUDONIMIZAR_ID:
            saida[nome] = rotulos[nome]
        elif campo.categoria == PSEUDONIMIZAR_NOME:
            saida[nome] = rotulos[campo.campo_id or ""]
        elif campo.categoria in (PRESERVAR_METRICA, PRESERVAR_DATA):
            saida[nome] = registro[nome]
        elif campo.categoria == ESTRUTURA_ANINHADA:
            saida[nome] = [
                {"action_type": item["action_type"], "value": item["value"]}
                for item in registro[nome]
            ]
        elif campo.categoria in (PROIBIDO, IGNORADO_SEGURO):
            continue
        else:
            raise ContratoAnonimizacaoQuebrado(
                f"Categoria desconhecida no contrato de {plataforma}."
            )
    return saida


def _conferir_preservacao(origem: list[dict], saida: list[dict], plataforma: str) -> None:
    """Compara cada valor analitico antes de ordenar a saida."""
    if len(origem) != len(saida):
        raise ContratoAnonimizacaoQuebrado("A quantidade de registros mudou.")

    contrato = CONTRATOS[plataforma]
    for indice, (antes, depois) in enumerate(zip(origem, saida, strict=True)):
        if set(depois) != set(antes):
            raise ContratoAnonimizacaoQuebrado(
                f"O conjunto de campos mudou no registro {indice}."
            )
        for nome, campo in contrato.items():
            if nome not in antes:
                continue
            if campo.categoria in (
                PRESERVAR_METRICA, PRESERVAR_DATA, ESTRUTURA_ANINHADA
            ) and depois[nome] != antes[nome]:
                raise ContratoAnonimizacaoQuebrado(
                    f"O valor analitico de {nome} mudou no registro {indice}."
                )
            if campo.categoria == PSEUDONIMIZAR_ID:
                if depois[nome] == antes[nome]:
                    raise ContratoAnonimizacaoQuebrado(
                        f"Um external ID sobreviveu no registro {indice}."
                    )
            if campo.categoria == PSEUDONIMIZAR_NOME:
                if antes[nome] and depois[nome] == antes[nome]:
                    raise ContratoAnonimizacaoQuebrado(
                        f"Um nome real sobreviveu no registro {indice}."
                    )
                if depois[nome] != depois[campo.campo_id or ""]:
                    raise ContratoAnonimizacaoQuebrado(
                        f"Nome e ID perderam identidade no registro {indice}."
                    )


def _serializar(registros: list[dict]) -> str:
    """Serializa deterministicamente, inclusive sob reordenacao da entrada."""
    ordenados = sorted(
        registros,
        key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
    )
    return json.dumps(
        ordenados, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"


def _caminho_manifesto(saida: Path) -> Path:
    """Deriva o manifesto sem a armadilha de ``with_suffix``."""
    return saida.with_name(f"{saida.stem}.manifesto.json")


def montar_manifesto(
    plataforma: str, saida: Path, registros: list[dict], conteudo: str
) -> dict:
    """Monta o pequeno contrato de reproducao do JSON desidentificado."""
    campo_data = PLATAFORMAS[plataforma].campo_data
    datas = sorted(registro[campo_data] for registro in registros)
    return {
        "versao": VERSAO_CONTRATO,
        "fonte": plataforma,
        "arquivo": saida.name,
        "linhas": len(registros),
        "data_min": datas[0] if datas else None,
        "data_max": datas[-1] if datas else None,
        "sha256": hashlib.sha256(conteudo.encode("utf-8")).hexdigest(),
        "campos_esperados": list(CONTRATOS[plataforma]),
        "classificacao": {
            nome: campo.categoria for nome, campo in CONTRATOS[plataforma].items()
        },
        "fingerprint_chave": pseudonimos.fingerprint_chave(),
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uso": (
            "Artefato bruto local desidentificado. Nao e a superficie oficial "
            "da Defesa e sua geracao nao autoriza publicacao."
        ),
    }


def _esta_sob(caminho: Path, diretorio: Path) -> bool:
    """Diz se um caminho resolvido esta dentro de um diretorio."""
    resolvido = caminho.resolve()
    raiz = diretorio.resolve()
    return resolvido == raiz or raiz in resolvido.parents


def _gravar_atomico(saida: Path, conteudo: str, manifesto: dict) -> Path:
    """Valida dois parciais antes de substituir os artefatos anteriores."""
    caminho_manifesto = _caminho_manifesto(saida)
    parcial_json = saida.with_name(saida.name + SUFIXO_PARCIAL)
    parcial_manifesto = caminho_manifesto.with_name(
        caminho_manifesto.name + SUFIXO_PARCIAL
    )
    texto_manifesto = json.dumps(
        manifesto, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"

    saida.parent.mkdir(parents=True, exist_ok=True)
    try:
        parcial_json.write_text(conteudo, encoding="utf-8")
        parcial_manifesto.write_text(texto_manifesto, encoding="utf-8")

        relido = parcial_json.read_text(encoding="utf-8")
        json.loads(relido)
        manifesto_relido = json.loads(parcial_manifesto.read_text(encoding="utf-8"))
        if hashlib.sha256(relido.encode("utf-8")).hexdigest() != manifesto_relido["sha256"]:
            raise ContratoAnonimizacaoQuebrado(
                "Checksum do JSON parcial diverge do manifesto."
            )
        if manifesto_relido != manifesto:
            raise ContratoAnonimizacaoQuebrado(
                "Manifesto parcial diverge do conteudo validado."
            )

        os.replace(parcial_json, saida)
        os.replace(parcial_manifesto, caminho_manifesto)
    finally:
        parcial_json.unlink(missing_ok=True)
        parcial_manifesto.unlink(missing_ok=True)
    return caminho_manifesto


def anonimizar_arquivo(
    entrada: Path,
    saida: Path,
    plataforma: str,
    permitir_publicacao: bool = False,
) -> Resultado:
    """Valida, desidentifica, confere e grava um JSON bruto.

    Raises:
        ContratoAnonimizacaoQuebrado: Em qualquer violacao estrutural,
            analitica ou de destino.
        pseudonimos.ChaveInvalida: Se o segredo local nao for utilizavel.
    """
    if plataforma not in CONTRATOS:
        raise ContratoAnonimizacaoQuebrado("Plataforma desconhecida.")
    if _esta_sob(saida, DIRETORIO_PUBLICACAO) and not permitir_publicacao:
        raise ContratoAnonimizacaoQuebrado(
            "data/publico/ exige --permitir-publicacao e autorizacao da agencia."
        )

    # Falhar por chave antes de ler o bruto ou tocar no destino.
    pseudonimos.fingerprint_chave()
    try:
        registros = json.loads(entrada.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as erro:
        raise ContratoAnonimizacaoQuebrado("Arquivo de entrada JSON invalido.") from erro
    if type(registros) is not list:
        raise ContratoAnonimizacaoQuebrado("A raiz do JSON precisa ser uma lista.")

    for indice, registro in enumerate(registros):
        validar_registro(registro, plataforma, indice)
    validar_hierarquia(registros, plataforma)

    colisoes: dict[tuple[str, str, str], str] = {}
    anonimizados = [
        anonimizar_registro(registro, plataforma, colisoes)
        for registro in registros
    ]
    _conferir_preservacao(registros, anonimizados, plataforma)
    validar_hierarquia(anonimizados, plataforma)

    conteudo = _serializar(anonimizados)
    manifesto = montar_manifesto(plataforma, saida, anonimizados, conteudo)
    caminho_manifesto = _gravar_atomico(saida, conteudo, manifesto)

    nomes = {
        registro[nome]
        for registro in registros
        for nome, campo in CONTRATOS[plataforma].items()
        if campo.categoria == PSEUDONIMIZAR_NOME and registro[nome]
    }
    ids = {
        registro[nome]
        for registro in registros
        for nome, campo in CONTRATOS[plataforma].items()
        if campo.categoria == PSEUDONIMIZAR_ID
    }
    return Resultado(
        registros=len(anonimizados),
        nomes=len(nomes),
        ids=len(ids),
        manifesto=caminho_manifesto,
        sha256=manifesto["sha256"],
    )


def _plataforma_da_entrada(entrada: Path, explicita: str | None) -> str:
    """Resolve a plataforma sem adivinhar pelo conteudo sensivel."""
    if explicita:
        return explicita
    resolvido = entrada.resolve()
    candidatas = [
        chave for chave, item in PLATAFORMAS.items()
        if item.arquivo_bruto.resolve() == resolvido
    ]
    if len(candidatas) == 1:
        return candidatas[0]
    raise ContratoAnonimizacaoQuebrado(
        "Use --plataforma meta|google com um arquivo de entrada customizado."
    )


def executar(args: argparse.Namespace) -> int:
    """Executa a CLI e converte falhas de contrato em exit 1."""
    try:
        if args.entrada:
            entrada = Path(args.entrada)
            plataforma = _plataforma_da_entrada(entrada, args.plataforma)
            saida = (
                Path(args.saida)
                if args.saida
                else Path(args.diretorio_saida) / entrada.name
            )
            arquivos = [(plataforma, entrada, saida)]
        else:
            destino = Path(args.diretorio_saida)
            arquivos = [
                (chave, item.arquivo_bruto, destino / item.arquivo_bruto.name)
                for chave, item in PLATAFORMAS.items()
            ]

        processados: list[Resultado] = []
        for plataforma, entrada, saida in arquivos:
            if not entrada.exists():
                raise ContratoAnonimizacaoQuebrado(
                    f"Arquivo bruto de {plataforma} ausente."
                )
            resultado = anonimizar_arquivo(
                entrada, saida, plataforma, args.permitir_publicacao
            )
            processados.append(resultado)
            print(
                f"{plataforma}: {resultado.registros} registros | "
                f"{resultado.nomes} nomes | {resultado.ids} IDs | "
                f"sha256 {resultado.sha256}"
            )

    except (ContratoAnonimizacaoQuebrado, pseudonimos.ChaveInvalida) as erro:
        print(f"Anonimizacao abortada: {erro}", file=sys.stderr)
        return 1

    print(f"{sum(item.registros for item in processados)} registros anonimizados.")
    print("Metricas e datas preservadas; nomes e IDs substituidos por HMAC.")
    print("Gerar estes arquivos nao autoriza publica-los.")
    return 0


def _parser() -> argparse.ArgumentParser:
    """Cria o parser da CLI."""
    parser = argparse.ArgumentParser(
        description="Desidentifica JSON bruto com contrato fail closed."
    )
    parser.add_argument("--entrada", help="Arquivo JSON especifico.")
    parser.add_argument("--saida", help="Arquivo de saida (com --entrada).")
    parser.add_argument(
        "--plataforma",
        choices=sorted(CONTRATOS),
        help="Obrigatoria para entrada customizada; inferida nos brutos padrao.",
    )
    parser.add_argument(
        "--diretorio-saida",
        default=str(SAIDA_PADRAO),
        help=f"Destino no modo lote. Default: {SAIDA_PADRAO}",
    )
    parser.add_argument(
        "--permitir-publicacao",
        action="store_true",
        help=(
            "Libera escrever em data/publico/. Nao substitui a autorizacao "
            "escrita da agencia."
        ),
    )
    return parser


def main() -> None:
    """Entry point da CLI."""
    configurar_logging()
    sys.exit(executar(_parser().parse_args()))


if __name__ == "__main__":
    main()
