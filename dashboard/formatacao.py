"""Formatacao pt-BR dos numeros do painel.

Por que isto e um modulo separado
---------------------------------
`metricas.py` existe para proteger o SIGNIFICADO das metricas: o que pode ser
somado, o que nao pode, o que o zero de cada plataforma quer dizer. Transformar
`Decimal("38741.181825")` em `R$ 38.741,18` e outra coisa — e apresentacao, e
nao tem opiniao alguma sobre o que o numero mede.

As funcoes daqui **nao conhecem o catalogo de metricas**: nao sabem o que e
`spend`, `reach` ou ROAS, e nao consultam plataforma. Recebem um valor e um
formato declarado, e devolvem texto. Por isso este modulo fica na camada mais
baixa do dashboard, ao lado de `contratos`, e `metricas` importa dele — nunca
o contrario.

Os adaptadores que ligam formato e catalogo (`formatar_metrica`,
`formatar_derivada`, `formatar_painel`, `formatar_quantidade_resultado`)
continuam em `metricas.py`, porque precisam do catalogo para escolher o
formato. A fronteira e essa: **escolher** o formato e decisao de metrica;
**aplicar** o formato e apresentacao.

Regras que a formatacao preserva
--------------------------------
- **`None` nunca vira zero.** Valor indisponivel sai como `--`. Zero medido e
  uma afirmacao; ausencia de valor nao e.
- **Nunca `NaN` nem `inf`.** A divisao segura mora em `metricas.dividir`; aqui
  so chega valor ja resolvido.
- **`Decimal` ate a ultima linha.** A conversao para texto acontece depois do
  arredondamento explicito com `ROUND_HALF_UP`; `float` nao participa.
- **Multiplicador pequeno nao vira zero.** `0,0005x` sai como `< 0,001x`, nao
  como `0,000x`, que seria lido como ausencia de retorno.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP


INDISPONIVEL: str = "--"

MOEDA: str = "moeda"
INTEIRO: str = "inteiro"
DECIMAL: str = "decimal"
PERCENTUAL: str = "percentual"
MULTIPLICADOR: str = "multiplicador"

# Abaixo deste valor um multiplicador arredondado viraria `0,000x` e seria
# lido como zero. Zero e resultado legitimo; "muito pequeno" nao e zero.
PISO_MULTIPLICADOR: Decimal = Decimal("0.001")


def _separar_milhar(inteiro: str) -> str:
    """Insere ponto a cada tres digitos.

    Args:
        inteiro: Parte inteira, so digitos.

    Returns:
        Texto com separador de milhar.
    """
    partes = []
    while len(inteiro) > 3:
        partes.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    partes.insert(0, inteiro)
    return ".".join(partes)


def _numero(valor: Decimal, casas: int) -> str:
    """Formata um `Decimal` no padrao brasileiro.

    Args:
        valor: Valor a formatar.
        casas: Casas decimais.

    Returns:
        Texto formatado, com sinal quando negativo.
    """
    quantizado = Decimal(str(valor)).quantize(
        Decimal(1) if casas == 0 else Decimal("1." + "0" * casas),
        rounding=ROUND_HALF_UP,
    )
    sinal = "-" if quantizado < 0 else ""
    texto = str(abs(quantizado))
    inteiro, _, decimal = texto.partition(".")
    inteiro = _separar_milhar(inteiro)
    return f"{sinal}{inteiro},{decimal}" if casas else f"{sinal}{inteiro}"


def _casas_multiplicador(valor: Decimal) -> int:
    """Escolhe as casas decimais de um multiplicador pela ordem de grandeza.

    Duas casas fixas achatariam `0,028x` em `0,03x` — uma diferenca de
    interpretacao, nao de arredondamento. A regra tem duas faixas:

    ===============  ======  ==========
    Faixa            Casas   Exemplo
    ===============  ======  ==========
    ``< 0,1``        3       ``0,028x``
    ``>= 0,1``       2       ``12,54x``
    ===============  ======  ==========

    Args:
        valor: Multiplicador ja calculado.

    Returns:
        Quantidade de casas decimais.
    """
    absoluto = abs(valor)
    if absoluto == 0:
        # Zero e resultado legitimo, nao valor minusculo: exibi-lo com tres
        # casas (`0,000x`) sugeriria uma precisao que nao esta em jogo.
        return 2
    if absoluto < Decimal("0.1"):
        return 3
    return 2


def _multiplicador(valor: Decimal, casas: int | None) -> str:
    """Formata um multiplicador com o sufixo `x`.

    Args:
        valor: Multiplicador ja calculado.
        casas: Sobrescreve a regra de magnitude quando informado.

    Returns:
        Texto como ``2,00x`` ou ``0,028x``. Valor nao nulo pequeno demais
        para as tres casas sai como ``< 0,001x``, nunca como ``0,000x``.
    """
    valor = Decimal(str(valor))
    if casas is not None:
        return f"{_numero(valor, casas)}x"
    if valor != 0 and abs(valor) < PISO_MULTIPLICADOR:
        return "< 0,001x" if valor > 0 else "> -0,001x"
    return f"{_numero(valor, _casas_multiplicador(valor))}x"


def formatar(valor, formato: str, casas: int | None = None) -> str:
    """Formata um valor conforme o formato declarado no catalogo.

    Args:
        valor: Valor a formatar, ou ``None``.
        formato: Um de `moeda`, `inteiro`, `decimal`, `percentual`,
            `multiplicador`.
        casas: Sobrescreve as casas decimais padrao do formato.

    Returns:
        Texto pronto para exibicao. ``None`` vira `--`, nunca `NaN`, `inf`
        ou `0`.
    """
    if valor is None:
        return INDISPONIVEL
    if formato == MOEDA:
        return f"R$ {_numero(valor, 2 if casas is None else casas)}"
    if formato == INTEIRO:
        return _numero(valor, 0 if casas is None else casas)
    if formato == PERCENTUAL:
        return f"{_numero(valor, 2 if casas is None else casas)}%"
    if formato == MULTIPLICADOR:
        return _multiplicador(valor, casas)
    return _numero(valor, 2 if casas is None else casas)


def formatar_variacao(valor) -> str:
    """Formata a variacao percentual com seta neutra.

    Args:
        valor: Variacao em pontos percentuais, ou ``None``.

    Returns:
        Texto como ``^ 12,34%`` ou ``v 3,10%``; `--` quando nao calculavel.
        A seta indica direcao, nao julgamento.
    """
    if valor is None:
        return INDISPONIVEL
    valor = Decimal(str(valor))
    seta = "▲" if valor > 0 else ("▼" if valor < 0 else "▬")
    return f"{seta} {_numero(abs(valor), 2)}%"


MESES: tuple[str, ...] = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)


def _dia_mes(dia: date) -> str:
    """Formata uma data como ``12 ago``.

    Args:
        dia: Data a formatar.

    Returns:
        Dia e mes abreviado, sem depender de locale do sistema.
    """
    return f"{dia.day:02d} {MESES[dia.month - 1]}"


def formatar_periodo(inicio: date, fim: date) -> str:
    """Formata um intervalo de datas para o cabecalho.

    Args:
        inicio: Primeiro dia.
        fim: Ultimo dia.

    Returns:
        Texto como ``12 ago — 18 ago 2026``.
    """
    if inicio == fim:
        return f"{_dia_mes(inicio)} {inicio.year}"
    if inicio.year == fim.year:
        return f"{_dia_mes(inicio)} — {_dia_mes(fim)} {fim.year}"
    return f"{_dia_mes(inicio)} {inicio.year} — {_dia_mes(fim)} {fim.year}"
