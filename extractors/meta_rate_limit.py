"""Telemetria passiva de rate limit da Graph API do Meta.

Por que este modulo existe
--------------------------
Em 28/08/2026 uma reextracao segmentada bateu no limite de carga do app
(`OAuthException`, HTTP 403, code 4, subcode 1504022) depois de dois blocos de
sete dias completos e um terco do terceiro. O erro e `is_transient`: a conduta
correta e esperar. Mas *quanto* esperar era invisivel — a decisao virava
tentativa e erro, e cada tentativa consome a mesma quota que esta faltando.

A Meta ja responde essa pergunta em cada resposta HTTP, nos headers de uso.
Eles chegam junto com o dado que o extrator ja pede. Este modulo apenas lê o
que ja chegou.

O que este modulo NAO faz
-------------------------
- **Nao emite request nenhum.** Nada de endpoint de quota, health check ou
  pagina repetida. Toda a informacao vem de respostas que a extracao ja fez.
- **Nao decide nada.** Sem sleep, backoff, retry, troca de token ou de conta,
  sem circuit breaker e sem threshold. Rate limit continua sendo falha
  terminal, exatamente como antes. Primeiro medir; pacing, se for o caso, vira
  decisao com evidencia na mao.
- **Nao registra identificador.** Ver a secao abaixo — e a razao de a leitura
  ser por allowlist, e nao por copia.

Privacidade: por que allowlist e nao copia
------------------------------------------
`X-Business-Use-Case-Usage` e um objeto **indexado por identificador** — a
chave e o ID do business ou da conta de anuncios. Logar o header bruto
publicaria esses IDs em qualquer lugar que o log alcance, incluindo
documentacao tecnica e material de defesa.

Por isso a leitura desse header **itera somente sobre os valores** e nunca
sobre as chaves, e cada metrica sai por nome declarado em
:data:`METRICAS_NUMERICAS`. O valor bruto nao e guardado, nao entra no `repr`
e nao entra no resumo. E o mesmo espirito de `assert_campos_extraidos_sao_consumidos`
e do exportador da superficie de exposicao: o que sai e o que foi declarado,
nunca o que sobrou de uma copia.

Robustez: telemetria nunca invalida uma resposta valida
-------------------------------------------------------
Header ausente, JSON malformado, campo novo, campo faltando, tipo inesperado —
tudo devolve ausencia de metrica, nunca excecao. Um header quebrado nao pode
derrubar uma extracao que a API respondeu corretamente.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Uso global do app. Percentuais 0-100 de consumo da janela corrente.
HEADER_APP_USAGE: str = "x-app-usage"

# Uso por conta de anuncios.
HEADER_ACCOUNT_USAGE: str = "x-ad-account-usage"

# Uso por caso de uso de negocio. INDEXADO POR IDENTIFICADOR — ver o cabecalho.
HEADER_BUSINESS_USE_CASE: str = "x-business-use-case-usage"

# Throttle especifico de Ads Insights, que e o endpoint desta extracao.
HEADER_INSIGHTS_THROTTLE: str = "x-fb-ads-insights-throttle"

# Presente em algumas respostas de limite. Segundos ate a liberacao.
HEADER_RETRY_AFTER: str = "retry-after"

# Allowlist de metricas numericas. Nome fora desta lista nao e lido, mesmo que
# apareca no header — campo novo da Meta e ignorado ate ser avaliado, nunca
# capturado por padrao.
METRICAS_NUMERICAS: frozenset[str] = frozenset({
    "call_count",
    "total_cputime",
    "total_time",
    "app_id_util_pct",
    "acc_id_util_pct",
    "estimated_time_to_regain_access",
})


def _numero(valor: Any) -> float | None:
    """Converte para float o que for numerico, sem levantar excecao.

    `bool` e recusado de proposito: em Python ele passa em ``isinstance(x, int)``
    e viraria 0.0/1.0 silenciosamente, poluindo um percentual com um flag.

    Args:
        valor: Qualquer valor vindo do header.

    Returns:
        O numero, ou ``None`` quando o valor nao for numerico.
    """
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        try:
            return float(valor.strip())
        except ValueError:
            return None
    return None


def _json_de_header(bruto: Any) -> Any:
    """Desserializa o valor de um header, tolerando qualquer defeito.

    Args:
        bruto: Valor cru do header.

    Returns:
        A estrutura desserializada, ou ``None`` se ausente ou malformada.
    """
    if bruto is None:
        return None
    if isinstance(bruto, (dict, list)):
        return bruto
    if not isinstance(bruto, str):
        return None
    try:
        return json.loads(bruto)
    except (ValueError, TypeError):
        return None


def _metricas_de_objeto(objeto: Any) -> dict[str, float]:
    """Extrai as metricas da allowlist de um objeto JSON.

    Le apenas os nomes declarados em :data:`METRICAS_NUMERICAS`. Chave fora da
    lista e descartada sem ser inspecionada — e o que garante que um
    identificador nunca escape por um campo novo.

    Args:
        objeto: Estrutura desserializada do header.

    Returns:
        Mapa nome -> valor, somente com o que era numerico e permitido.
    """
    if not isinstance(objeto, dict):
        return {}
    saida: dict[str, float] = {}
    for nome in METRICAS_NUMERICAS:
        numero = _numero(objeto.get(nome))
        if numero is not None:
            saida[nome] = numero
    return saida


def _metricas_de_use_case(objeto: Any) -> dict[str, float]:
    """Agrega as metricas de `X-Business-Use-Case-Usage` descartando as chaves.

    O header e ``{"<id>": [{...}, ...]}``. As chaves sao identificadores de
    business ou de conta, entao a iteracao usa ``.values()`` e nunca
    ``.items()`` nem ``.keys()``: o identificador nao chega a ser lido. De cada
    entrada saem apenas as metricas da allowlist, consolidadas pelo maximo — o
    pior caso e o que importa para decidir quando tentar de novo.

    Args:
        objeto: Estrutura desserializada do header.

    Returns:
        Mapa nome -> maior valor observado entre todas as entradas.
    """
    if not isinstance(objeto, dict):
        return {}
    agregado: dict[str, float] = {}
    for entradas in objeto.values():
        lista = entradas if isinstance(entradas, list) else [entradas]
        for entrada in lista:
            for nome, valor in _metricas_de_objeto(entrada).items():
                anterior = agregado.get(nome)
                agregado[nome] = valor if anterior is None else max(anterior, valor)
    return agregado


def _buscar(headers: Any, nome: str) -> Any:
    """Le um header sem depender da capitalizacao nem do tipo do container.

    `requests` devolve um mapa case-insensitive, mas um dict comum pode chegar
    aqui vindo de teste ou de outra camada. A busca cai para varredura
    normalizada quando o acesso direto falha.

    Args:
        headers: Mapa de headers da resposta.
        nome: Nome do header em minusculas.

    Returns:
        O valor bruto, ou ``None``.
    """
    if headers is None:
        return None
    try:
        valor = headers.get(nome)
    except AttributeError:
        return None
    if valor is not None:
        return valor
    try:
        itens = headers.items()
    except AttributeError:
        return None
    for chave, valor in itens:
        if isinstance(chave, str) and chave.lower() == nome:
            return valor
    return None


@dataclass(frozen=True)
class Observacao:
    """Uma leitura sanitizada dos headers de uso de uma resposta.

    Todos os campos sao opcionais: a Meta nao envia todos os headers em todas
    as respostas, e ausencia e ausencia — nunca zero.

    Attributes:
        app_call_count_pct: Percentual da cota de chamadas do app.
        app_total_cputime_pct: Percentual da cota de CPU do app.
        app_total_time_pct: Percentual da cota de tempo do app.
        insights_app_util_pct: Utilizacao de Ads Insights no nivel do app.
        insights_account_util_pct: Utilizacao de Ads Insights na conta.
        conta_util_pct: Utilizacao reportada para a conta de anuncios.
        caso_de_uso_call_count_pct: Maior percentual de chamadas entre os casos
            de uso de negocio.
        caso_de_uso_cputime_pct: Maior percentual de CPU entre os casos de uso.
        caso_de_uso_time_pct: Maior percentual de tempo entre os casos de uso.
        minutos_para_liberar: Maior `estimated_time_to_regain_access` visto.
        retry_after_segundos: Valor numerico de `Retry-After`, quando numerico.
    """

    app_call_count_pct: float | None = None
    app_total_cputime_pct: float | None = None
    app_total_time_pct: float | None = None
    insights_app_util_pct: float | None = None
    insights_account_util_pct: float | None = None
    conta_util_pct: float | None = None
    caso_de_uso_call_count_pct: float | None = None
    caso_de_uso_cputime_pct: float | None = None
    caso_de_uso_time_pct: float | None = None
    minutos_para_liberar: float | None = None
    retry_after_segundos: float | None = None

    def vazia(self) -> bool:
        """Diz se nenhuma metrica foi observada.

        Returns:
            ``True`` quando a resposta nao trouxe header de uso algum.
        """
        return all(getattr(self, campo) is None for campo in _CAMPOS)


_CAMPOS: tuple[str, ...] = (
    "app_call_count_pct",
    "app_total_cputime_pct",
    "app_total_time_pct",
    "insights_app_util_pct",
    "insights_account_util_pct",
    "conta_util_pct",
    "caso_de_uso_call_count_pct",
    "caso_de_uso_cputime_pct",
    "caso_de_uso_time_pct",
    "minutos_para_liberar",
    "retry_after_segundos",
)

# Rotulos do resumo. So aparece o que foi realmente observado — um resumo com
# dez `None` nao informa nada e ainda esconde o que importa.
_ROTULOS: dict[str, str] = {
    "app_call_count_pct": "app_chamadas_pct",
    "app_total_cputime_pct": "app_cpu_pct",
    "app_total_time_pct": "app_tempo_pct",
    "insights_app_util_pct": "insights_app_pct",
    "insights_account_util_pct": "insights_conta_pct",
    "conta_util_pct": "conta_pct",
    "caso_de_uso_call_count_pct": "caso_uso_chamadas_pct",
    "caso_de_uso_cputime_pct": "caso_uso_cpu_pct",
    "caso_de_uso_time_pct": "caso_uso_tempo_pct",
    "minutos_para_liberar": "minutos_para_liberar",
    "retry_after_segundos": "retry_after_s",
}


def ler_headers(headers: Any) -> Observacao:
    """Transforma os headers de uma resposta numa observacao sanitizada.

    Nunca levanta excecao: qualquer defeito no header vira ausencia de metrica.

    Args:
        headers: Mapa de headers da resposta HTTP.

    Returns:
        A observacao. Pode vir vazia.
    """
    app = _metricas_de_objeto(_json_de_header(_buscar(headers, HEADER_APP_USAGE)))
    conta = _metricas_de_objeto(
        _json_de_header(_buscar(headers, HEADER_ACCOUNT_USAGE))
    )
    insights = _metricas_de_objeto(
        _json_de_header(_buscar(headers, HEADER_INSIGHTS_THROTTLE))
    )
    caso_de_uso = _metricas_de_use_case(
        _json_de_header(_buscar(headers, HEADER_BUSINESS_USE_CASE))
    )

    return Observacao(
        app_call_count_pct=app.get("call_count"),
        app_total_cputime_pct=app.get("total_cputime"),
        app_total_time_pct=app.get("total_time"),
        insights_app_util_pct=insights.get("app_id_util_pct"),
        insights_account_util_pct=insights.get("acc_id_util_pct"),
        conta_util_pct=conta.get("acc_id_util_pct"),
        caso_de_uso_call_count_pct=caso_de_uso.get("call_count"),
        caso_de_uso_cputime_pct=caso_de_uso.get("total_cputime"),
        caso_de_uso_time_pct=caso_de_uso.get("total_time"),
        minutos_para_liberar=caso_de_uso.get("estimated_time_to_regain_access"),
        retry_after_segundos=_numero(_buscar(headers, HEADER_RETRY_AFTER)),
    )


@dataclass
class Coletor:
    """Acumula as observacoes de uma execucao inteira.

    Guarda o maximo de cada metrica e a ultima leitura — nao a serie completa.
    Uma execucao percorre dezenas de contas com varias paginas cada; a serie
    inteira seria ruido, e o que responde "quando posso tentar de novo" e o
    pior caso mais o estado final.

    Attributes:
        observacoes: Quantas leituras nao vazias entraram.
        maximos: Maior valor visto de cada metrica.
        ultima: Ultima observacao nao vazia.
    """

    observacoes: int = 0
    maximos: dict[str, float] = field(default_factory=dict)
    ultima: Observacao | None = None
    _assinatura_anterior: Any = field(default=None, repr=False)

    def observar_headers(self, headers: Any) -> Observacao:
        """Le e acumula os headers de uma resposta.

        Leituras consecutivas identicas sao descartadas: iterar um cursor toca
        os mesmos headers uma vez por item, e so ha resposta nova quando a
        pagina vira.

        Args:
            headers: Mapa de headers da resposta HTTP.

        Returns:
            A observacao lida, mesmo quando ja contabilizada ou vazia.
        """
        assinatura = tuple(
            _buscar(headers, nome) for nome in (
                HEADER_APP_USAGE, HEADER_ACCOUNT_USAGE,
                HEADER_BUSINESS_USE_CASE, HEADER_INSIGHTS_THROTTLE,
                HEADER_RETRY_AFTER,
            )
        )
        if assinatura == self._assinatura_anterior:
            return self.ultima or Observacao()
        self._assinatura_anterior = assinatura

        observacao = ler_headers(headers)
        if observacao.vazia():
            return observacao

        self.observacoes += 1
        self.ultima = observacao
        for campo in _CAMPOS:
            valor = getattr(observacao, campo)
            if valor is None:
                continue
            anterior = self.maximos.get(campo)
            self.maximos[campo] = valor if anterior is None else max(anterior, valor)

        logger.debug(
            "Uso da API Meta: %s", self._formatar(self.maximos, observacao)
        )
        return observacao

    @staticmethod
    def _formatar(valores: dict[str, float], atual: Observacao) -> str:
        """Formata as metricas presentes, omitindo as ausentes.

        Args:
            valores: Maximos acumulados.
            atual: Observacao mais recente.

        Returns:
            Texto compacto ``chave=valor``.
        """
        partes = [
            f"{_ROTULOS[campo]}={valores[campo]:g}"
            for campo in _CAMPOS
            if campo in valores
        ]
        return " ".join(partes) or "(sem metrica)"

    def resumo(self) -> str | None:
        """Monta o resumo seguro da execucao.

        Returns:
            Uma linha com as metricas observadas, ou ``None`` se a API nao
            enviou header de uso algum — caso em que nao ha o que reportar.
        """
        if not self.observacoes:
            return None
        return (
            f"Telemetria de rate limit Meta: observacoes={self.observacoes} "
            f"{self._formatar(self.maximos, self.ultima or Observacao())}"
        )

    def registrar_resumo(self) -> None:
        """Registra o resumo no log, no nivel adequado ao que foi observado.

        `WARNING` somente quando a propria fonte declara tempo de recuperacao
        ou pede espera — nao ha threshold inventado aqui.
        """
        resumo = self.resumo()
        if resumo is None:
            logger.debug(
                "A API Meta nao devolveu headers de uso nesta execucao."
            )
            return
        alerta = (
            self.maximos.get("minutos_para_liberar")
            or self.maximos.get("retry_after_segundos")
        )
        logger.warning(resumo) if alerta else logger.info(resumo)


def observar_cursor(cursor: Any, coletor: Coletor):
    """Itera um cursor do SDK observando os headers de cada pagina.

    O SDK expoe `Cursor.headers()` como acessor publico, atualizado a cada
    `load_next_page()`. A leitura acontece sobre a resposta que a iteracao ja
    provocou: **nenhum request adicional e emitido**, e a sequencia de paginas
    e exatamente a mesma sem a telemetria.

    Args:
        cursor: Cursor devolvido pelo SDK.
        coletor: Acumulador da execucao.

    Yields:
        Cada item do cursor, sem alteracao.
    """
    ler = getattr(cursor, "headers", None)
    if not callable(ler):
        yield from cursor
        return

    # A primeira pagina ja foi carregada por `FacebookRequest.execute`.
    coletor.observar_headers(_headers_de(ler))
    for item in cursor:
        yield item
        coletor.observar_headers(_headers_de(ler))


def _headers_de(ler: Any) -> Any:
    """Chama o acessor de headers sem deixar defeito do SDK vazar.

    Args:
        ler: O metodo ``headers`` do cursor.

    Returns:
        O mapa de headers, ou ``None``.
    """
    try:
        return ler()
    except Exception:  # noqa: BLE001 - telemetria nunca quebra a extracao
        return None


def observar_excecao(erro: BaseException, coletor: Coletor) -> None:
    """Aproveita os headers da resposta que originou um erro da API.

    O 403 de limite carrega os mesmos headers de uso da resposta bem sucedida,
    e e a leitura mais informativa que existe: e o estado no exato momento em
    que a quota acabou. `FacebookRequestError.http_headers()` e acessor
    publico do SDK, entao nao ha monkeypatch envolvido.

    O erro **nao** e tratado aqui: quem chama continua propagando. Rate limit
    segue sendo falha terminal.

    Args:
        erro: Excecao levantada pelo SDK.
        coletor: Acumulador da execucao.
    """
    ler = getattr(erro, "http_headers", None)
    if not callable(ler):
        return
    coletor.observar_headers(_headers_de(ler))
