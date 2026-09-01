"""Gera o dataset SINTETICO de demonstracao do dashboard.

Por que existe
--------------
A superficie de exposicao (`data/exposicao/metricas.csv`) e gitignorada: ela
carrega metricas reais de clientes de uma agencia e nao sobrevive a um clone
limpo. Sem uma alternativa versionada, quem clonasse o repositorio veria uma
tela de erro em vez do artefato do TCC.

Este gerador produz um arquivo **inteiramente ficticio**, no contrato v3 de
24 colunas, que permite exercitar filtros, comparacao de periodo, rankings,
graficos e Resultado sem nenhum dado de cliente.

O que NAO e
-----------
Nao e anonimizacao. Nada aqui deriva de nome, external ID, chave natural ou
metrica real: os identificadores saem de `sha256("demo|<nivel>|<indice>")` e
os numeros, de um gerador pseudoaleatorio com semente fixa. Nao existe
correspondencia com nenhuma entidade real, e a chave HMAC da fronteira de
exposicao **nao** e usada — pseudonimo real e rotulo de demonstracao sao
coisas diferentes e nao devem compartilhar primitivo.

Fidelidade ao contrato
----------------------
As ausencias reais sao reproduzidas de proposito, porque o dashboard precisa
demonstrar como lida com elas:

- `reach`, `profile_views`, `purchases` e `purchase_value` ficam zerados no
  Google Ads, que nao
  os fornece nesse nivel de GAQL;
- `profile_views` fica zerado tambem no Meta, como no artefato real;
- `conversion_value` fica zerado no Meta e positivo no Google, reproduzindo o
  que a superficie real apresenta;
- `conversions` sai fracionaria no Google e inteira no Meta;
- ha entidades com duas versoes SCD2, para a coluna de versao nao ficar
  constante.

Uso
---
    python dashboard/gerar_dados_demo.py
    python dashboard/gerar_dados_demo.py --destino dashboard/dados_demo

O resultado e deterministico: mesma semente, mesmo arquivo, byte a byte.
"""

import argparse
import csv
import hashlib
import io
import json
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

BASE_DIR: Path = Path(__file__).resolve().parent.parent

DESTINO_PADRAO: Path = BASE_DIR / "dashboard" / "dados_demo"

NOME_CSV: str = "metricas.csv"
NOME_MANIFESTO: str = "manifesto.json"

SEMENTE: int = 20260825
VERSAO_CONTRATO: int = 3

# Periodo deliberadamente distinto do periodo real do artefato, para que
# ninguem confunda um screenshot de demonstracao com um de dado real.
PRIMEIRO_DIA: date = date(2026, 6, 1)
DIAS: int = 28

PREFIXO: dict[str, str] = {
    "conta": "Cliente",
    "campanha": "Campanha",
    "adset": "AdSet",
    "anuncio": "Anuncio",
}

META: str = "Meta Ads"
GOOGLE: str = "Google Ads"
PLATAFORMAS: tuple[str, ...] = (META, GOOGLE)

RESULTADO_LEAD: str = "actions:offsite_conversion.fb_pixel_lead"
RESULTADO_THRUPLAY: str = "video_thruplay_watched_actions"

# ── Papeis de campanha ───────────────────────────────────────
# A demo existe para DEMONSTRAR o painel, e desde a classificacao relativa de
# campanhas isso inclui demonstrar os estados dela. Uma carteira sorteada nao
# produz esses estados: a versao anterior tinha 15 campanhas espalhadas por 6
# contas, nenhum grupo de comparacao alcancava o minimo de pares e as 15
# apareciam como "Dados insuficientes". Por isso a carteira passou a ser
# declarada, e nao sorteada — o acaso continua governando o RUIDO diario, nunca
# a estrutura.
PAPEL_PADRAO: str = "padrao"
PAPEL_ZERO_RESULT: str = "zero_result"
PAPEL_SEM_KPI: str = "sem_kpi"
PAPEL_RESULT_TARDIO: str = "result_tardio"
PAPEL_POUCOS_DIAS: str = "poucos_dias"
PAPEL_DENOMINADOR_BAIXO: str = "denominador_baixo"
PAPEL_SEM_INVESTIMENTO: str = "sem_investimento"


def _anuncio(
    *,
    cpc: float | None = None,
    papel: str | None = None,
    taxa: float | None = None,
    escala: float | None = None,
    cliques_fixos: int | None = None,
    dias_maximos: int | None = None,
) -> dict:
    """Declara somente as diferencas de um anuncio dentro da campanha.

    O perfil da campanha continua sendo a fonte dos valores omitidos. A
    estrutura permite construir peers com custos distintos e papeis especiais
    sem duplicar a definicao inteira da campanha nem gravar status no dado.
    """
    valores = {
        "cpc": cpc,
        "papel": papel,
        "taxa": taxa,
        "escala": escala,
        "cliques_fixos": cliques_fixos,
        "dias_maximos": dias_maximos,
    }
    return {chave: valor for chave, valor in valores.items() if valor is not None}


def _grupo(*anuncios: dict) -> tuple[dict, ...]:
    """Declara os anuncios que compartilham um ad set/grupo sintetico."""
    return tuple(anuncios)


def _campanha(
    *,
    tipo: str | None = None,
    cpc: float = 1.0,
    papel: str = PAPEL_PADRAO,
    taxa: float = 0.05,
    ctr: float = 0.02,
    escala: float = 2.5,
    ticket: float = 120.0,
    cliques_fixos: int | None = None,
    dias_maximos: int | None = None,
    grupos: tuple[tuple[dict, ...], ...] | None = None,
) -> dict:
    """Descreve uma campanha sintetica da carteira de demonstracao.

    O custo por resultado emerge da razao `cpc / taxa`, entao variar `cpc` com
    `taxa` constante distribui as campanhas do grupo ao longo dos quartis de
    forma previsivel — sem escrever o status desejado em lugar nenhum.

    Args:
        tipo: `result_type` da campanha, ou ``None`` para ausencia total.
        cpc: Custo por clique sintetico.
        papel: Comportamento especial. Ver as constantes `PAPEL_*`.
        taxa: Fracao dos cliques que vira conversao.
        ctr: Fracao das impressoes que vira clique.
        escala: Multiplicador de volume diario.
        ticket: Valor sintetico por compra ou conversao.
        cliques_fixos: Cliques por dia, quando o volume precisa ser controlado
            (usado no gasto sem resultado, em que o total investido decide o
            status).
        dias_maximos: Dias ativos, quando a campanha precisa ser curta.
        grupos: Estrutura opcional de anuncios por ad set. Quando ausente, a
            campanha preserva o padrao historico de dois grupos com um
            anuncio em cada. Cada anuncio declara apenas overrides do perfil.

    Returns:
        Perfil da campanha.
    """
    return {
        "tipo": tipo,
        "cpc": cpc,
        "papel": papel,
        "taxa": taxa,
        "ctr": ctr,
        "escala": escala,
        "ticket": ticket,
        "cliques_fixos": cliques_fixos,
        "dias_maximos": dias_maximos,
        "grupos": grupos,
    }


# A carteira e declarada. Cada conta existe por um motivo de demonstracao, e o
# comentario diz qual — quem for mexer aqui precisa saber o que quebra.
CARTEIRA: tuple[dict, ...] = (
    # Conta madura de Lead: seis campanhas no mesmo eixo dao a cada uma cinco
    # pares e exercitam o benchmark MESMO_CLIENTE em toda a faixa de quartis.
    # As duas ultimas cobrem os dois gates de evidencia.
    {
        "plataforma": META,
        "scd2_conta": True,
        "campanhas": (
            # Um grupo com quatro anuncios Lead comparaveis demonstra N1 e
            # produz os quatro quartis por dados, nunca por status gravado.
            _campanha(
                tipo=RESULTADO_LEAD,
                cpc=0.50,
                grupos=(
                    _grupo(
                        _anuncio(cpc=0.20),
                        _anuncio(cpc=0.50),
                        _anuncio(cpc=0.60),
                        _anuncio(cpc=0.90),
                    ),
                ),
            ),
            _campanha(tipo=RESULTADO_LEAD, cpc=1.00),
            _campanha(tipo=RESULTADO_LEAD, cpc=1.50),
            _campanha(tipo=RESULTADO_LEAD, cpc=1.65),
            _campanha(tipo=RESULTADO_LEAD, cpc=2.00),
            _campanha(tipo=RESULTADO_LEAD, cpc=2.50),
            _campanha(
                tipo=RESULTADO_LEAD,
                cpc=1.20,
                papel=PAPEL_DENOMINADOR_BAIXO,
                escala=0.4,
            ),
            _campanha(
                tipo=RESULTADO_LEAD,
                cpc=1.20,
                papel=PAPEL_POUCOS_DIAS,
                dias_maximos=2,
            ),
        ),
    },
    # Conta pequena de ThruPlay: dois pares proprios, abaixo do minimo de tres.
    # Ela so e classificavel pelo portfolio do mesmo tipo — e e o unico caso da
    # demo que exercita MESMO_TIPO_PORTFOLIO.
    {
        "plataforma": META,
        "campanhas": (
            _campanha(tipo=RESULTADO_THRUPLAY, cpc=1.00),
            _campanha(tipo=RESULTADO_THRUPLAY, cpc=2.20),
        ),
    },
    # Conta grande de ThruPlay: fornece os pares de portfolio para a conta
    # anterior e tem benchmark proprio.
    {
        "plataforma": META,
        "campanhas": (
            # Grupo local mais denso para o segundo tipo de Result. A media
            # dos CPCs permanece 0,60, preservando o papel da campanha.
            _campanha(
                tipo=RESULTADO_THRUPLAY,
                cpc=0.60,
                grupos=(
                    _grupo(
                        _anuncio(cpc=0.25),
                        _anuncio(cpc=0.45),
                        _anuncio(cpc=0.60),
                        _anuncio(cpc=0.75),
                        _anuncio(cpc=0.95),
                    ),
                ),
            ),
            _campanha(tipo=RESULTADO_THRUPLAY, cpc=1.20),
            _campanha(tipo=RESULTADO_THRUPLAY, cpc=1.80),
            _campanha(tipo=RESULTADO_THRUPLAY, cpc=2.40),
        ),
    },
    # Conta sem Resultado declarado: o painel cai para custo por Lead, que e o
    # fallback do contrato v3 quando a fonte nao devolveu `results`.
    {
        "plataforma": META,
        "campanhas": (
            # Result inteiramente ausente, mas Leads presentes: o grupo
            # exercita o fallback CPL no nivel de anuncio.
            _campanha(
                cpc=0.80,
                grupos=(
                    _grupo(
                        _anuncio(cpc=0.40),
                        _anuncio(cpc=0.70),
                        _anuncio(cpc=0.90),
                        _anuncio(cpc=1.20),
                    ),
                ),
            ),
            _campanha(cpc=1.40),
            _campanha(cpc=2.00),
            _campanha(cpc=2.60),
        ),
    },
    # Conta dos limites semanticos do Meta: uma campanha sem Resultado e sem
    # Lead, e uma que so passa a declarar Resultado no meio do periodo — o
    # mesmo formato da fronteira real de cobertura, que precisa aparecer como
    # "Dados de Result incompletos" e nao como desempenho ruim.
    {
        "plataforma": META,
        "scd2_campanha": True,
        "campanhas": (
            _campanha(papel=PAPEL_SEM_KPI, cpc=1.10),
            _campanha(tipo=RESULTADO_LEAD, papel=PAPEL_RESULT_TARDIO, cpc=1.30),
        ),
    },
    # Conta principal do Google: cinco campanhas com CPA distribuido e as tres
    # faixas do gasto sem resultado.
    {
        "plataforma": GOOGLE,
        "scd2_campanha": True,
        "campanhas": (
            # Dois grupos com dois anuncios: N1 falha e cada anuncio encontra
            # exatamente tres peers no N2 da mesma campanha.
            _campanha(
                cpc=0.50,
                grupos=(
                    _grupo(_anuncio(cpc=0.20), _anuncio(cpc=0.40)),
                    _grupo(_anuncio(cpc=0.60), _anuncio(cpc=0.80)),
                ),
            ),
            # N1 Google com cinco anuncios e custo medio igual ao perfil
            # anterior da campanha; aumenta a demonstrabilidade sem mover o
            # eixo economico agregado que sustenta o motor de campanhas.
            _campanha(
                cpc=1.00,
                grupos=(
                    _grupo(
                        _anuncio(cpc=0.40),
                        _anuncio(cpc=0.70),
                        _anuncio(cpc=1.00),
                        _anuncio(cpc=1.30),
                        _anuncio(cpc=1.60),
                    ),
                ),
            ),
            # N1 Google com tres peers elegiveis e um anuncio sem conversao.
            # O gasto do quarto anuncio e comparado ao CPA mediano dos outros,
            # demonstrando a regra de zero-result sem inventar status no CSV.
            _campanha(
                cpc=1.50,
                grupos=(
                    _grupo(
                        _anuncio(cpc=1.00),
                        _anuncio(cpc=1.50),
                        _anuncio(cpc=2.00),
                        _anuncio(
                            cpc=1.50,
                            papel=PAPEL_ZERO_RESULT,
                            cliques_fixos=8,
                            dias_maximos=3,
                        ),
                    ),
                ),
            ),
            _campanha(cpc=2.00),
            _campanha(cpc=2.50),
            _campanha(
                papel=PAPEL_ZERO_RESULT, cpc=1.00, cliques_fixos=2, dias_maximos=3
            ),
            _campanha(
                papel=PAPEL_ZERO_RESULT, cpc=1.00, cliques_fixos=8, dias_maximos=3
            ),
            _campanha(
                papel=PAPEL_ZERO_RESULT, cpc=2.00, cliques_fixos=30, dias_maximos=5
            ),
        ),
    },
    # Conta pequena do Google: duas campanhas validas nao formam grupo, e o
    # Google nao atravessa clientes. E o caso que mostra a decisao conservadora
    # da plataforma sem eixo semantico. A terceira campanha nao investe.
    {
        "plataforma": GOOGLE,
        "campanhas": (
            _campanha(cpc=1.10),
            _campanha(cpc=1.90),
            _campanha(papel=PAPEL_SEM_INVESTIMENTO, cpc=0.0),
        ),
    },
)

COLUNAS_V2: tuple[str, ...] = (
    "data", "plataforma",
    "conta_id", "conta_versao",
    "campanha_id", "campanha_versao",
    "adset_id", "adset_versao",
    "anuncio_id", "anuncio_versao",
    "spend", "impressions", "link_clicks", "conversions",
    "conversion_value", "video_views", "reach", "profile_views", "purchases",
    "purchase_value",
)

COLUNAS_RESULTADO: tuple[str, ...] = (
    "result_type", "result_count", "result_attribution_window",
    "cost_per_result",
)

COLUNAS: tuple[str, ...] = COLUNAS_V2 + COLUNAS_RESULTADO


def identificador(nivel: str, indice: int) -> str:
    """Constroi um identificador ficticio no formato da exposicao.

    A entrada e o indice sequencial da entidade sintetica. Nao ha nome real,
    external ID nem chave natural em lugar nenhum deste caminho.

    Args:
        nivel: `conta`, `campanha`, `adset` ou `anuncio`.
        indice: Numero sequencial da entidade.

    Returns:
        Rotulo como ``Cliente-1A2B3C4D``.
    """
    material = f"demo|{nivel}|{indice}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest().upper()
    return f"{PREFIXO[nivel]}-{digest[:8]}"


def montar_hierarquia(sorteio: random.Random) -> list[dict]:
    """Materializa a carteira declarada em `CARTEIRA` como anuncios.

    A estrutura — quantas contas, quantas campanhas por conta, qual eixo e
    qual papel — vem da carteira e nao do sorteio. O gerador pseudoaleatorio
    entra so no ruido de cada anuncio (presenca, jitter de volume), para a
    serie diaria nao ficar artificialmente lisa.

    Args:
        sorteio: Gerador pseudoaleatorio ja semeado.

    Returns:
        Lista de anuncios, cada um com a cadeia hierarquica completa, a
        plataforma, o perfil economico e o papel da campanha.
    """
    anuncios: list[dict] = []
    seq = {"conta": 0, "campanha": 0, "adset": 0, "anuncio": 0}

    for conta_spec in CARTEIRA:
        seq["conta"] += 1
        conta = identificador("conta", seq["conta"])
        plataforma = conta_spec["plataforma"]
        conta_versao_2 = conta_spec.get("scd2_conta", False)

        for indice, perfil in enumerate(conta_spec["campanhas"]):
            seq["campanha"] += 1
            campanha = identificador("campanha", seq["campanha"])
            # Uma campanha renomeada por conta marcada: a coluna de versao
            # SCD2 precisa variar em algum lugar do artefato.
            campanha_versao_2 = conta_spec.get("scd2_campanha", False) and indice == 0

            grupos = perfil["grupos"] or ((_anuncio(),), (_anuncio(),))
            for grupo_spec in grupos:
                seq["adset"] += 1
                adset = identificador("adset", seq["adset"])
                for anuncio_spec in grupo_spec:
                    perfil_anuncio = {**perfil, **anuncio_spec}
                    seq["anuncio"] += 1
                    anuncios.append({
                        "plataforma": plataforma,
                        "conta_id": conta,
                        "conta_versao_2": conta_versao_2,
                        "campanha_id": campanha,
                        "campanha_versao_2": campanha_versao_2,
                        "adset_id": adset,
                        "anuncio_id": identificador("anuncio", seq["anuncio"]),
                        "anuncio_versao_2": seq["anuncio"] % 17 == 0,
                        "perfil": perfil_anuncio,
                        # Papel especial nao sorteia estreia nem presenca: o
                        # caso demonstrado depende de dias e investimento
                        # controlados no nivel em que o override foi declarado.
                        "estreia": (
                            0
                            if perfil_anuncio["papel"] != PAPEL_PADRAO
                            else sorteio.choice([0, 0, 0, 5, 11])
                        ),
                        "presenca": (
                            1.0
                            if perfil_anuncio["papel"] != PAPEL_PADRAO
                            else sorteio.uniform(0.65, 1.0)
                        ),
                        "escala": (
                            perfil_anuncio["escala"]
                            * sorteio.uniform(0.85, 1.15)
                        ),
                    })
    return anuncios


def _versao(marcado: bool, dia: int) -> int:
    """Resolve o numero de versao SCD2 de uma entidade num dia.

    Args:
        marcado: Se a entidade tem duas versoes no periodo.
        dia: Indice do dia dentro do periodo.

    Returns:
        ``2`` a partir da metade do periodo para entidades marcadas, senao
        ``1``.
    """
    return 2 if marcado and dia >= DIAS // 2 else 1


def gerar_linhas() -> list[dict]:
    """Produz todas as linhas do dataset sintetico.

    Returns:
        Linhas no contrato de exposicao, ordenadas por
        ``(data, plataforma, conta, campanha, adset, anuncio)``.
    """
    sorteio = random.Random(SEMENTE)
    anuncios = montar_hierarquia(sorteio)

    linhas: list[dict] = []
    for dia in range(DIAS):
        data = PRIMEIRO_DIA + timedelta(days=dia)
        # Fim de semana rende menos: da a serie temporal um formato
        # reconhecivel em vez de ruido puro.
        fator_semana = 0.65 if data.weekday() >= 5 else 1.0

        for anuncio in anuncios:
            perfil = anuncio["perfil"]
            papel = perfil["papel"]
            if dia < anuncio["estreia"]:
                continue
            if perfil["dias_maximos"] is not None:
                if dia >= anuncio["estreia"] + perfil["dias_maximos"]:
                    continue
            if sorteio.random() > anuncio["presenca"]:
                continue

            meta = anuncio["plataforma"] == META
            if perfil["cliques_fixos"] is not None:
                # Volume controlado: no gasto sem resultado o que decide o
                # status e o total investido contra a referencia, entao ele nao
                # pode depender de sorteio.
                link_clicks = perfil["cliques_fixos"]
                impressions = int(link_clicks / perfil["ctr"])
            else:
                base = sorteio.uniform(400, 9000) * anuncio["escala"] * fator_semana
                impressions = int(base)
                if impressions <= 0:
                    continue
                link_clicks = int(impressions * perfil["ctr"])

            spend = Decimal(str(round(link_clicks * perfil["cpc"], 2)))
            if papel == PAPEL_ZERO_RESULT or papel == PAPEL_SEM_KPI:
                # Investimento sem nenhum resultado observado. Nao e erro de
                # geracao: e o caso que separa "gastou pouco e ainda nao
                # produziu" de "gastou muito e nao produziu".
                conversoes_brutas = 0.0
            elif papel == PAPEL_DENOMINADOR_BAIXO:
                # Evidencia insuficiente da propria campanha: um unico
                # resultado no periodo inteiro.
                conversoes_brutas = 1.0 if dia == anuncio["estreia"] else 0.0
            else:
                conversoes_brutas = link_clicks * perfil["taxa"]

            if meta:
                conversions = Decimal(int(round(conversoes_brutas)))
                # O Meta nao traz valor de conversao neste grao no artefato
                # real; reproduzir isso mantem o caso de ROAS indisponivel
                # visivel na demonstracao.
                conversion_value = Decimal("0")
                purchases = int(conversions * Decimal("0.35"))
                # O valor monetario do Meta mora em `purchase_value`, nao em
                # `conversion_value`: sao conceitos distintos, e o segundo e
                # estruturalmente zero na fonte.
                purchase_value = Decimal(
                    str(round(purchases * perfil["ticket"], 2))
                )
                reach = int(impressions * sorteio.uniform(0.55, 0.9))
                video_views = int(impressions * sorteio.uniform(0.08, 0.45))
            else:
                conversions = Decimal(str(round(conversoes_brutas, 6)))
                conversion_value = Decimal(
                    str(round(float(conversions) * perfil["ticket"], 2))
                )
                purchases = 0
                # Google nao reporta compra neste grao: zero e ausencia de
                # suporte, e `conversion_value` nao escorrega para ca.
                purchase_value = Decimal("0")
                reach = 0
                video_views = int(impressions * sorteio.uniform(0.0, 0.06))

            result_type = perfil["tipo"]
            if papel == PAPEL_SEM_KPI:
                result_type = None
            elif papel == PAPEL_RESULT_TARDIO and dia < DIAS // 2:
                # Ausencia total na primeira metade e Resultado declarado na
                # segunda: reproduz a fronteira de cobertura do artefato real,
                # em que a reextracao de Result cobre so parte do periodo.
                result_type = None
            if result_type is None:
                result_count = None
                result_attribution_window = None
                cost_per_result = None
            else:
                # Lead acompanha a conversao sintetica. ThruPlay usa uma
                # fracao deterministica das visualizacoes Meta: continua
                # ficticio, nao reutiliza numero da superficie operacional.
                if result_type == RESULTADO_LEAD:
                    result_count = conversions
                else:
                    result_count = Decimal(
                        int(Decimal(video_views) * Decimal("0.60"))
                    )

                # Zero aqui e factual: o tipo foi declarado, mas nao houve
                # resultado. Sem denominador, custo e janela ficam NULL — a
                # mesma semantica da Forma A aceita pelo contrato real.
                if result_count > 0:
                    result_attribution_window = "default"
                    cost_per_result = (spend / result_count).quantize(
                        Decimal("0.00000001")
                    )
                else:
                    result_attribution_window = None
                    cost_per_result = None

            linhas.append({
                "data": data.isoformat(),
                "plataforma": anuncio["plataforma"],
                "conta_id": anuncio["conta_id"],
                "conta_versao": _versao(anuncio["conta_versao_2"], dia),
                "campanha_id": anuncio["campanha_id"],
                "campanha_versao": _versao(anuncio["campanha_versao_2"], dia),
                "adset_id": anuncio["adset_id"],
                "adset_versao": 1,
                "anuncio_id": anuncio["anuncio_id"],
                "anuncio_versao": _versao(anuncio["anuncio_versao_2"], dia),
                "spend": spend,
                "impressions": impressions,
                "link_clicks": link_clicks,
                "conversions": conversions,
                "conversion_value": conversion_value,
                "video_views": video_views,
                "reach": reach,
                # Zerado nas duas plataformas, como no artefato real.
                "profile_views": 0,
                "purchases": purchases,
                "purchase_value": purchase_value,
                "result_type": result_type,
                "result_count": result_count,
                "result_attribution_window": result_attribution_window,
                "cost_per_result": cost_per_result,
            })

    linhas.sort(key=lambda l: (
        l["data"], l["plataforma"], l["conta_id"], l["campanha_id"],
        l["adset_id"], l["anuncio_id"],
    ))
    return linhas


def _texto(valor) -> str:
    """Serializa ausencia como campo vazio, nunca como texto inventado.

    Args:
        valor: Valor de uma celula.

    Returns:
        Texto do valor, ou vazio quando ele for ``None``.
    """
    return "" if valor is None else str(valor)


def serializar_csv(linhas: list[dict]) -> str:
    """Serializa as linhas no formato do artefato de exposicao.

    Args:
        linhas: Linhas geradas.

    Returns:
        Conteudo do CSV.
    """
    buffer = io.StringIO(newline="")
    escritor = csv.writer(buffer, lineterminator="\n")
    escritor.writerow(COLUNAS)
    for linha in linhas:
        escritor.writerow([_texto(linha[coluna]) for coluna in COLUNAS])
    return buffer.getvalue()


TIPOS: dict[str, str] = {
    "data": "date (YYYY-MM-DD)",
    "plataforma": "text",
    "conta_id": "text (Cliente-XXXXXXXX)",
    "conta_versao": "integer >= 1",
    "campanha_id": "text (Campanha-XXXXXXXX)",
    "campanha_versao": "integer >= 1",
    "adset_id": "text (AdSet-XXXXXXXX)",
    "adset_versao": "integer >= 1",
    "anuncio_id": "text (Anuncio-XXXXXXXX)",
    "anuncio_versao": "integer >= 1",
    "spend": "decimal",
    "impressions": "integer",
    "link_clicks": "integer",
    "conversions": "decimal (fracionario no Google, nunca inteiro)",
    "conversion_value": "decimal",
    "video_views": "integer",
    "reach": "integer",
    "profile_views": "integer",
    "purchases": "integer",
    "purchase_value": "decimal",
    "result_type": "text nullable (indicador oficial da Meta)",
    "result_count": "decimal nullable (NULL = ausencia, nao zero)",
    "result_attribution_window": "text nullable (NULL = janela nao aplicavel)",
    "cost_per_result": "decimal nullable (NULL = sem denominador)",
}

AVISO_VIDEO_VIEWS: str = (
    "video_views tem definicao diferente em cada plataforma: TrueView de 30s, "
    "video completo ou interacao no Google; a partir de 3s no Meta. A metrica "
    "e valida dentro de cada plataforma e o total cross-platform NAO tem "
    "interpretacao analitica comum — nao somar entre plataformas."
)

AVISO_METRICAS_AUSENTES: str = (
    "reach, profile_views, purchases e purchase_value sao zero no Google por "
    "ausencia de "
    "suporte da GAQL neste grao — ausencia de suporte, nao ausencia de dado."
)


def montar_manifesto(linhas: list[dict], conteudo: str) -> dict:
    """Monta o manifesto do dataset sintetico.

    Ele declara em texto que os dados sao ficticios: o arquivo pode ser
    copiado para fora do repositorio e precisa continuar dizendo o que e.

    O manifesto segue os campos que `scripts/auditar_dataset_exposicao.py`
    exige, de proposito — assim o dataset de demonstracao pode ser submetido ao
    MESMO auditor independente da superficie real, e o contrato fica provado
    em vez de afirmado. A unica diferenca deliberada e `fingerprint_chave`,
    que sai nulo: nenhuma chave de pseudonimizacao participou desta geracao, e
    preencher o campo sugeriria uma procedencia que nao existe.

    Args:
        linhas: Linhas geradas.
        conteudo: Conteudo exato do CSV.

    Returns:
        Dicionario serializavel do manifesto.
    """
    datas = sorted(linha["data"] for linha in linhas)
    return {
        "versao_contrato": VERSAO_CONTRATO,
        "modo": "demonstracao",
        "natureza": (
            "DADOS SINTETICOS E FICTICIOS. Nao derivam de nome, identificador "
            "ou metrica de cliente real, e nao usam a chave de "
            "pseudonimizacao da fronteira de exposicao."
        ),
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gerador": "dashboard/gerar_dados_demo.py",
        "semente": SEMENTE,
        "artefato": NOME_CSV,
        "sha256": hashlib.sha256(conteudo.encode("utf-8")).hexdigest(),
        "linhas": len(linhas),
        "data_min": datas[0] if datas else None,
        "data_max": datas[-1] if datas else None,
        "grao": "1 anuncio x 1 dia — chave (anuncio_id, data)",
        "colunas": list(COLUNAS),
        "tipos": dict(TIPOS),
        "cardinalidades": {
            nivel: len({linha[f"{nivel}_id"] for linha in linhas})
            for nivel in ("conta", "campanha", "adset", "anuncio")
        },
        # Nulo de proposito: nao houve chave de pseudonimizacao envolvida.
        "fingerprint_chave": None,
        "origem": "dashboard/gerar_dados_demo.py (gerador sintetico)",
        "avisos": {
            "video_views": AVISO_VIDEO_VIEWS,
            "metricas_ausentes_no_google": AVISO_METRICAS_AUSENTES,
        },
        "uso": (
            "Demonstracao do dashboard sem dado de cliente. Nao representa "
            "desempenho real de nenhuma conta."
        ),
    }


def gerar(destino: Path) -> int:
    """Gera CSV e manifesto no diretorio informado.

    Args:
        destino: Diretorio de saida.

    Returns:
        Quantidade de linhas gravadas.
    """
    linhas = gerar_linhas()
    conteudo = serializar_csv(linhas)
    manifesto = montar_manifesto(linhas, conteudo)

    destino.mkdir(parents=True, exist_ok=True)
    (destino / NOME_CSV).write_text(conteudo, encoding="utf-8")
    (destino / NOME_MANIFESTO).write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return len(linhas)


def main() -> None:
    """Entry point da CLI."""
    parser = argparse.ArgumentParser(
        description="Gera o dataset sintetico de demonstracao do dashboard.",
    )
    parser.add_argument(
        "--destino",
        default=str(DESTINO_PADRAO),
        help=f"Diretorio de saida. Default: {DESTINO_PADRAO}",
    )
    args = parser.parse_args()

    total = gerar(Path(args.destino))
    print(f"{total} linhas sinteticas gravadas em {args.destino}")


if __name__ == "__main__":
    main()
