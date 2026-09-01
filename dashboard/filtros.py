"""Filtros globais do dashboard, com dependencia hierarquica.

A hierarquia do modelo dimensional — Conta -> Campanha -> AdSet -> Anuncio —
tambem vale para os filtros: escolher uma conta nao pode deixar campanhas de
outras contas na lista de opcoes. O caminho e sempre o mesmo:

1. recorta o periodo;
2. recorta a plataforma;
3. recorta cada nivel, de cima para baixo, sempre sobre o que sobrou.

Selecao invalida e descartada, nao ignorada
-------------------------------------------
Quando o usuario troca a conta, campanhas de outra conta continuam no estado
do widget. `sanear` remove o que deixou de ser opcao valida, entao o resultado
de `aplicar` nunca depende de resto de selecao anterior. Selecao vazia num
nivel significa "todos", que e diferente de "nenhum": e o comportamento
esperado de filtro de BI, e evita a tela em branco por engano.
"""

from dataclasses import dataclass, replace
from datetime import date, timedelta

from dashboard.contratos import LinhaDataset

NIVEIS: tuple[str, ...] = ("conta", "campanha", "adset")

# Janela aberta por padrao: os sete ultimos dias de calendario **do dataset**.
# A referencia e a maior data do arquivo, nunca `date.today()` — o artefato e
# um recorte historico, e ancorar no relogio abriria o painel vazio no dia
# seguinte e produziria screenshot diferente a cada execucao. Com a data do
# dataset, a mesma superficie sempre abre na mesma tela.
JANELA_PADRAO_DIAS: int = 7


@dataclass(frozen=True)
class Selecao:
    """Estado dos filtros globais.

    Attributes:
        data_inicio: Primeiro dia do periodo, inclusivo.
        data_fim: Ultimo dia do periodo, inclusivo.
        plataformas: Plataformas escolhidas. Vazio significa todas.
        contas: Contas pseudonimizadas escolhidas. Vazio significa todas.
        campanhas: Campanhas escolhidas. Vazio significa todas.
        adsets: Ad sets escolhidos. Vazio significa todos.
    """

    data_inicio: date
    data_fim: date
    plataformas: tuple[str, ...] = ()
    contas: tuple[str, ...] = ()
    campanhas: tuple[str, ...] = ()
    adsets: tuple[str, ...] = ()


def intervalo_disponivel(
    linhas: list[LinhaDataset],
) -> tuple[date | None, date | None]:
    """Descobre o intervalo de datas coberto pelo dataset.

    Args:
        linhas: Linhas do dataset.

    Returns:
        Tupla ``(primeira_data, ultima_data)``; ``(None, None)`` se vazio.
    """
    if not linhas:
        return None, None
    datas = [linha["data"] for linha in linhas]
    return min(datas), max(datas)


def periodo_padrao(
    linhas: list[LinhaDataset],
) -> tuple[date | None, date | None]:
    """Calcula o periodo aberto por padrao: os ultimos sete dias do dataset.

    A janela e de **calendario**, e nao de dias com dado: vai de
    ``max(data) - 6`` ate ``max(data)``, recortada pelo inicio do dataset. Um
    artefato com lacunas — o caso real deste projeto — abre nos mesmos sete
    dias de calendario, com os dias vazios simplesmente ausentes das series.

    Dataset com menos de sete dias de calendario abre inteiro.

    Args:
        linhas: Linhas do dataset.

    Returns:
        Tupla ``(inicio, fim)``; ``(None, None)`` se o dataset estiver vazio.
    """
    inicio, fim = intervalo_disponivel(linhas)
    if inicio is None or fim is None:
        return None, None
    candidato = fim - timedelta(days=JANELA_PADRAO_DIAS - 1)
    return max(inicio, candidato), fim


def selecao_inicial(linhas: list[LinhaDataset]) -> Selecao:
    """Monta a selecao padrao: ultimos sete dias, sem recorte de entidade.

    Args:
        linhas: Linhas do dataset.

    Returns:
        A selecao inicial. Com dataset vazio, usa a data de hoje nos dois
        extremos — nao ha periodo a inferir, e a tela informara a ausencia.
    """
    inicio, fim = periodo_padrao(linhas)
    if inicio is None or fim is None:
        hoje = date.today()
        return Selecao(hoje, hoje)
    return Selecao(inicio, fim)


def _no_periodo(
    linhas: list[LinhaDataset], selecao: Selecao
) -> list[LinhaDataset]:
    """Recorta as linhas pelo periodo da selecao.

    Args:
        linhas: Linhas do dataset.
        selecao: Selecao vigente.

    Returns:
        Linhas dentro de ``[data_inicio, data_fim]``.
    """
    return [
        linha
        for linha in linhas
        if selecao.data_inicio <= linha["data"] <= selecao.data_fim
    ]


def opcoes(linhas: list[LinhaDataset], selecao: Selecao) -> dict:
    """Calcula as opcoes validas de cada filtro, respeitando a hierarquia.

    Cada nivel enxerga apenas o que sobrou dos filtros acima dele. E o que faz
    campanhas de outra conta desaparecerem da lista assim que a conta e
    escolhida.

    Args:
        linhas: Linhas do dataset completo.
        selecao: Selecao vigente.

    Returns:
        Dicionario com as listas ordenadas de `plataformas`, `contas`,
        `campanhas` e `adsets`.
    """
    no_periodo = _no_periodo(linhas, selecao)

    plataformas = sorted({linha["plataforma"] for linha in no_periodo})

    escopo = no_periodo
    if selecao.plataformas:
        escopo = [
            linha for linha in escopo if linha["plataforma"] in selecao.plataformas
        ]

    resultado = {"plataformas": plataformas}
    for nivel in NIVEIS:
        coluna = f"{nivel}_id"
        resultado[f"{nivel}s"] = sorted({linha[coluna] for linha in escopo})
        escolhidos = getattr(selecao, f"{nivel}s")
        if escolhidos:
            escopo = [linha for linha in escopo if linha[coluna] in escolhidos]
    return resultado


def sanear(linhas: list[LinhaDataset], selecao: Selecao) -> Selecao:
    """Remove da selecao o que deixou de ser opcao valida.

    Args:
        linhas: Linhas do dataset completo.
        selecao: Selecao vigente, possivelmente com residuo de escolha antiga.

    Returns:
        Selecao equivalente, contendo apenas valores ainda validos.
    """
    disponiveis = opcoes(linhas, selecao)
    limpa = replace(
        selecao,
        plataformas=tuple(
            p for p in selecao.plataformas if p in disponiveis["plataformas"]
        ),
    )
    # As opcoes dos niveis dependem da plataforma ja saneada, por isso o
    # recalculo em vez de reaproveitar `disponiveis`.
    disponiveis = opcoes(linhas, limpa)
    for nivel in NIVEIS:
        campo = f"{nivel}s"
        validos = tuple(
            v for v in getattr(limpa, campo) if v in disponiveis[campo]
        )
        limpa = replace(limpa, **{campo: validos})
        disponiveis = opcoes(linhas, limpa)
    return limpa


def aplicar(
    linhas: list[LinhaDataset], selecao: Selecao
) -> list[LinhaDataset]:
    """Aplica todos os filtros simultaneamente.

    Args:
        linhas: Linhas do dataset completo.
        selecao: Selecao vigente.

    Returns:
        Linhas que satisfazem periodo, plataforma e os tres niveis.
    """
    resultado = _no_periodo(linhas, selecao)
    if selecao.plataformas:
        resultado = [
            linha
            for linha in resultado
            if linha["plataforma"] in selecao.plataformas
        ]
    for nivel in NIVEIS:
        escolhidos = getattr(selecao, f"{nivel}s")
        if escolhidos:
            coluna = f"{nivel}_id"
            resultado = [
                linha for linha in resultado if linha[coluna] in escolhidos
            ]
    return resultado


def aplicar_em_periodo(
    linhas: list[LinhaDataset], selecao: Selecao, inicio: date, fim: date
) -> list[LinhaDataset]:
    """Aplica os filtros de entidade em outro periodo.

    Serve a comparacao com o periodo anterior: os recortes de plataforma,
    conta, campanha e ad set continuam valendo; so a janela de datas muda.

    Args:
        linhas: Linhas do dataset completo.
        selecao: Selecao vigente.
        inicio: Primeiro dia do periodo alternativo.
        fim: Ultimo dia do periodo alternativo.

    Returns:
        Linhas do periodo alternativo sob os mesmos filtros de entidade.
    """
    return aplicar(linhas, replace(selecao, data_inicio=inicio, data_fim=fim))


def universo_do_periodo(
    linhas: list[LinhaDataset],
    selecao: Selecao,
    inicio: date | None = None,
    fim: date | None = None,
) -> list[LinhaDataset]:
    """Recorta periodo e plataforma, mas **preserva as demais entidades**.

    Existe para a classificacao de campanhas, que precisa de um grupo de
    comparacao maior do que a tela mostra. O benchmark de nivel 2 do Meta
    compara campanhas do mesmo tipo de Resultado em OUTRAS contas: passar ao
    motor apenas as linhas da conta selecionada eliminaria esse nivel em
    silencio, e a campanha apareceria como "sem pares suficientes" por um
    defeito de recorte, nao por falta de dado.

    Filtros de conta, campanha e ad set continuam valendo para tudo o que e
    exibido — eles apenas nao encolhem a referencia estatistica.

    Args:
        linhas: Linhas do dataset completo.
        selecao: Selecao vigente.
        inicio: Primeiro dia alternativo. ``None`` mantem o da selecao.
        fim: Ultimo dia alternativo. ``None`` mantem o da selecao.

    Returns:
        Linhas do periodo, filtradas apenas por plataforma.
    """
    janela = replace(
        selecao,
        data_inicio=inicio or selecao.data_inicio,
        data_fim=fim or selecao.data_fim,
        contas=(),
        campanhas=(),
        adsets=(),
    )
    return aplicar(linhas, janela)


def universo_da_conta_no_periodo(
    linhas: list[LinhaDataset],
    selecao: Selecao,
    conta_id: str,
) -> list[LinhaDataset]:
    """Preserva todos os peers de anuncio da conta no periodo selecionado.

    A classificacao de anuncios nunca atravessa campanha nem conta, mas um
    filtro visual de campanha ou ad set nao pode remover os pares usados em
    N1/N2. Este recorte aplica periodo, plataforma e a conta obrigatoria;
    campanha e ad set ficam exclusivamente para o filtro de saida.

    Args:
        linhas: Linhas do dataset completo.
        selecao: Selecao vigente.
        conta_id: Unica conta escolhida para a classificacao.

    Returns:
        Linhas da conta e do periodo, sem recorte de campanha ou ad set.
    """
    janela = replace(
        selecao,
        contas=(conta_id,),
        campanhas=(),
        adsets=(),
    )
    return aplicar(linhas, janela)
