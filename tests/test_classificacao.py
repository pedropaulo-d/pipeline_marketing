"""Testes do motor de classificacao relativa de campanhas.

O que esta suite protege
------------------------
1. **A semantica antes da estatistica.** Recorte misto, mais de um tipo de
   Resultado e janela incompativel nunca viram quartil — viram
   `NAO_COMPARAVEL`. Um custo por resultado calculado sobre um periodo em que
   parte das linhas nao declarou contrato seria um numero errado que passaria
   em qualquer teste de schema.
2. **A ausencia de auto-influencia.** A campanha classificada jamais entra no
   proprio benchmark. Ha teste em que incluir a propria campanha mudaria o
   status.
3. **Os limites empiricos.** Os cortes de 3 pares, 3 dias, 3 resultados, 0,5x
   e 2x no gasto sem resultado e 15% na tendencia sao testados nas bordas
   exatas, porque e ali que uma mudanca silenciosa passaria despercebida.
4. **O que NAO pode decidir status.** Alcance, CTR, CPC e ROAS nao entram no
   motor. O teste nao le prosa: ele varre a arvore sintatica do modulo atras
   das chaves efetivamente lidas de cada linha.

Sem dependencia nova: `unittest`, stdlib e os modulos do proprio dashboard.

Rodar:
    python -m unittest tests.test_classificacao
"""

import ast
import random
import unittest
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from dashboard import classificacao as c
from dashboard import metricas as m

BASE_DIR = Path(__file__).resolve().parent.parent

# Identificadores ficticios no formato da superficie. Nao derivam de entidade
# real nem da chave HMAC: sao literais de teste.
CONTA_A = "Cliente-AAAA1111"
CONTA_B = "Cliente-BBBB2222"
CONTA_C = "Cliente-CCCC3333"

TIPO_MENSAGEM = "actions:onsite_conversion.messaging_conversation_started_7d"
TIPO_LEAD = "actions:offsite_conversion.fb_pixel_lead"
TIPO_THRUPLAY = "video_thruplay_watched_actions"
# Indicador estruturalmente valido que a fonte ainda nao devolveu: existe para
# provar que a comparacao nao depende de haver rotulo humano.
TIPO_SEM_ROTULO = "actions:onsite_conversion.indicator_ainda_nao_observado"

PRIMEIRO_DIA = date(2026, 8, 3)


def linha(
    *,
    dia: date,
    plataforma: str,
    conta: str,
    campanha: str,
    spend: str = "0",
    conversions: str = "0",
    result_type: str | None = None,
    result_count: str | None = None,
    result_attribution_window: str | None = None,
    cost_per_result: str | None = None,
) -> dict:
    """Monta uma linha do dataset no grao de anuncio x dia.

    As metricas que o motor nao pode consultar ficam com valores diferentes de
    zero de proposito: se alguma delas entrasse na conta, os numeros dos
    testes mudariam.
    """
    return {
        "data": dia,
        "plataforma": plataforma,
        "conta_id": conta,
        "conta_versao": 1,
        "campanha_id": campanha,
        "campanha_versao": 1,
        "adset_id": "AdSet-AAAA0001",
        "adset_versao": 1,
        "anuncio_id": "Anuncio-AAAA0001",
        "anuncio_versao": 1,
        "spend": Decimal(spend),
        "impressions": Decimal(9999),
        "link_clicks": Decimal(777),
        "conversions": Decimal(conversions),
        "conversion_value": Decimal(4242),
        "video_views": Decimal(555),
        "reach": Decimal(8888),
        "profile_views": Decimal(66),
        "purchases": Decimal(11),
        "purchase_value": Decimal(3333),
        "result_type": result_type,
        "result_count": None if result_count is None else Decimal(result_count),
        "result_attribution_window": result_attribution_window,
        "cost_per_result": None if cost_per_result is None else Decimal(cost_per_result),
    }


def campanha_result(
    conta: str,
    campanha: str,
    *,
    spend: str,
    resultados: str,
    tipo: str = TIPO_MENSAGEM,
    janela: str | None = "7d_click",
    dias: int = 5,
    primeiro_dia: date = PRIMEIRO_DIA,
) -> list[dict]:
    """Campanha Meta com Resultado tipado em todas as linhas.

    O primeiro dia carrega investimento e quantidade; os demais sao FORMA A
    (tipo declarado, quantidade zero, sem custo e sem janela), que e o caso
    neutro real do contrato. Assim a campanha tem varios dias ativos sem virar
    recorte misto.
    """
    linhas = [
        linha(
            dia=primeiro_dia,
            plataforma=m.META,
            conta=conta,
            campanha=campanha,
            spend=spend,
            result_type=tipo,
            result_count=resultados,
            result_attribution_window=janela,
            cost_per_result="1",
        )
    ]
    for passo in range(1, dias):
        linhas.append(
            linha(
                dia=primeiro_dia + timedelta(days=passo),
                plataforma=m.META,
                conta=conta,
                campanha=campanha,
                result_type=tipo,
                result_count="0",
            )
        )
    return linhas


def campanha_lead(
    conta: str,
    campanha: str,
    *,
    spend: str,
    leads: str,
    dias: int = 5,
    primeiro_dia: date = PRIMEIRO_DIA,
) -> list[dict]:
    """Campanha Meta sem Resultado algum, com Leads em `conversions`."""
    linhas = [
        linha(
            dia=primeiro_dia,
            plataforma=m.META,
            conta=conta,
            campanha=campanha,
            spend=spend,
            conversions=leads,
        )
    ]
    for passo in range(1, dias):
        linhas.append(
            linha(
                dia=primeiro_dia + timedelta(days=passo),
                plataforma=m.META,
                conta=conta,
                campanha=campanha,
            )
        )
    return linhas


def campanha_google(
    conta: str,
    campanha: str,
    *,
    spend: str,
    conversoes: str,
    dias: int = 5,
    primeiro_dia: date = PRIMEIRO_DIA,
) -> list[dict]:
    """Campanha Google. A superficie nunca traz Resultado para o Google."""
    linhas = [
        linha(
            dia=primeiro_dia,
            plataforma=m.GOOGLE,
            conta=conta,
            campanha=campanha,
            spend=spend,
            conversions=conversoes,
        )
    ]
    for passo in range(1, dias):
        linhas.append(
            linha(
                dia=primeiro_dia + timedelta(days=passo),
                plataforma=m.GOOGLE,
                conta=conta,
                campanha=campanha,
            )
        )
    return linhas


def pares_result(
    conta: str, custos: list[int], *, tipo: str = TIPO_MENSAGEM, prefixo: str = "P"
) -> list[dict]:
    """Cria uma campanha por custo desejado, com 10 resultados cada."""
    linhas: list[dict] = []
    for indice, custo in enumerate(custos):
        linhas += campanha_result(
            conta,
            f"Campanha-{prefixo}{indice:07d}",
            spend=str(custo * 10),
            resultados="10",
            tipo=tipo,
        )
    return linhas


def pares_google(conta: str, custos: list[int], *, prefixo: str = "G") -> list[dict]:
    linhas: list[dict] = []
    for indice, custo in enumerate(custos):
        linhas += campanha_google(
            conta,
            f"Campanha-{prefixo}{indice:07d}",
            spend=str(custo * 10),
            conversoes="10",
        )
    return linhas


def por_campanha(resultado: list[c.ClassificacaoCampanha]) -> dict:
    return {classificacao.campanha_id: classificacao for classificacao in resultado}


class TestPercentil(unittest.TestCase):
    """O calculo dos quartis nao pode depender da ordem nem do tipo."""

    def test_interpolacao_linear(self):
        valores = [Decimal(10), Decimal(20), Decimal(30), Decimal(40)]
        self.assertEqual(c.percentil(valores, 25), Decimal("17.5"))
        self.assertEqual(c.percentil(valores, 50), Decimal(25))
        self.assertEqual(c.percentil(valores, 75), Decimal("32.5"))

    def test_independe_da_ordem(self):
        valores = [Decimal(40), Decimal(10), Decimal(30), Decimal(20)]
        self.assertEqual(c.percentil(valores, 25), Decimal("17.5"))

    def test_lista_unitaria_e_vazia(self):
        self.assertEqual(c.percentil([Decimal(7)], 25), Decimal(7))
        self.assertIsNone(c.percentil([], 50))


class TestMetaResult(unittest.TestCase):
    """CPR: o KPI primario do Meta quando ha Resultado utilizavel."""

    def cenario(self, custo_alvo: int, *, conta_alvo: str = CONTA_A) -> dict:
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_result(
            conta_alvo, "Campanha-ALVO0001", spend=str(custo_alvo * 10), resultados="10"
        )
        return por_campanha(c.classificar_campanhas(linhas))

    def test_primeiro_quartil_e_excelente(self):
        alvo = self.cenario(10)["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.EXCELENTE)
        self.assertEqual(alvo.kpi_tipo, c.CPR)
        self.assertEqual(alvo.kpi_valor, Decimal(10))

    def test_entre_quartil_e_mediana_e_boa(self):
        self.assertEqual(self.cenario(20)["Campanha-ALVO0001"].status, c.BOA)

    def test_entre_mediana_e_terceiro_quartil_e_atencao(self):
        self.assertEqual(self.cenario(30)["Campanha-ALVO0001"].status, c.ATENCAO)

    def test_acima_do_terceiro_quartil_e_ruim(self):
        self.assertEqual(self.cenario(50)["Campanha-ALVO0001"].status, c.RUIM)

    def test_bordas_pertencem_ao_lado_melhor(self):
        # Pares em 10/20/30/40: P25 = 17,5 · P50 = 25 · P75 = 32,5. Uma borda
        # por cenario: duas campanhas alvo no mesmo grupo seriam pares uma da
        # outra e moveriam os quartis que o teste quer fixar.
        for custo, esperado in (
            ("17.5", c.EXCELENTE),
            ("25", c.BOA),
            ("32.5", c.ATENCAO),
        ):
            with self.subTest(custo=custo):
                linhas = pares_result(CONTA_A, [10, 20, 30, 40])
                linhas += campanha_result(
                    CONTA_A,
                    "Campanha-BORD0001",
                    spend=str(Decimal(custo) * 10),
                    resultados="10",
                )
                alvo = por_campanha(c.classificar_campanhas(linhas))[
                    "Campanha-BORD0001"
                ]
                self.assertEqual(alvo.status, esperado)

    def test_leave_one_out_muda_o_status(self):
        # Pares 10/20/30 sem a alvo: P25 = 15, e a alvo de 12 fica EXCELENTE.
        # Incluindo a alvo, P25 cairia para 11,5 e ela viraria BOA.
        linhas = pares_result(CONTA_A, [10, 20, 30])
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="120", resultados="10"
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.EXCELENTE)
        self.assertEqual(alvo.benchmark_n, 3)
        self.assertEqual(alvo.benchmark_p25, Decimal(15))

    def test_nivel_1_usa_o_mesmo_cliente(self):
        alvo = self.cenario(10)["Campanha-ALVO0001"]
        self.assertEqual(alvo.benchmark_origem, c.MESMO_CLIENTE)
        self.assertEqual(alvo.benchmark_n, 4)

    def test_nivel_2_usa_o_portfolio_do_mesmo_tipo(self):
        # A conta do alvo tem 2 pares (abaixo de 3); o portfolio tem 6.
        linhas = pares_result(CONTA_A, [10, 20], prefixo="A")
        linhas += pares_result(CONTA_B, [30, 40, 50, 60], prefixo="B")
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.benchmark_origem, c.MESMO_TIPO_PORTFOLIO)
        self.assertEqual(alvo.benchmark_n, 6)
        self.assertEqual(alvo.status, c.EXCELENTE)

    def test_portfolio_com_menos_de_cinco_pares_e_insuficiente(self):
        linhas = pares_result(CONTA_A, [10, 20], prefixo="A")
        linhas += pares_result(CONTA_B, [30, 40], prefixo="B")
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.benchmark_origem, c.INDISPONIVEL)
        self.assertEqual(alvo.benchmark_n, 0)
        self.assertIn("comparáveis suficientes", alvo.motivo)

    def test_tipos_diferentes_nao_se_comparam(self):
        # Seis pares de ThruPlay nao servem de referencia para uma campanha de
        # mensagem, mesmo com o N necessario.
        linhas = pares_result(
            CONTA_B, [30, 40, 50, 60, 70, 80], tipo=TIPO_THRUPLAY, prefixo="T"
        )
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.eixo_comparacao[1], TIPO_MENSAGEM)

    def test_multiplos_tipos_nao_e_comparavel(self):
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        linhas.append(
            linha(
                dia=PRIMEIRO_DIA + timedelta(days=1),
                plataforma=m.META,
                conta=CONTA_A,
                campanha="Campanha-ALVO0001",
                spend="50",
                result_type=TIPO_THRUPLAY,
                result_count="5",
                result_attribution_window="7d_click",
                cost_per_result="10",
            )
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.NAO_COMPARAVEL)
        self.assertIn("Múltiplos tipos", alvo.motivo)
        self.assertIsNone(alvo.kpi_valor)

    def test_janela_incompativel_nao_e_comparavel(self):
        linhas = campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        linhas.append(
            linha(
                dia=PRIMEIRO_DIA + timedelta(days=1),
                plataforma=m.META,
                conta=CONTA_A,
                campanha="Campanha-ALVO0001",
                spend="50",
                result_type=TIPO_MENSAGEM,
                result_count="5",
                result_attribution_window="1d_view",
                cost_per_result="10",
            )
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.NAO_COMPARAVEL)
        self.assertIn("Janelas de atribuição incompatíveis", alvo.motivo)

    def test_typed_mais_absence_e_fail_closed(self):
        # A regra que a analise exploratoria sugeriu — "agregar so as linhas
        # tipadas" — somaria o investimento de um dia sem contrato ao
        # denominador de outro. Aqui isso tem de virar NAO_COMPARAVEL.
        linhas = campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        linhas.append(
            linha(
                dia=PRIMEIRO_DIA + timedelta(days=9),
                plataforma=m.META,
                conta=CONTA_A,
                campanha="Campanha-ALVO0001",
                spend="500",
            )
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.NAO_COMPARAVEL)
        self.assertIn("Result incompletos", alvo.motivo)
        self.assertIsNone(alvo.kpi_valor)

    def test_forma_a_neutra_nao_gera_incompatibilidade(self):
        # `campanha_result` ja produz quatro dias de FORMA A. Se o NULL neutro
        # contasse como segunda janela, a campanha nunca seria classificada.
        alvo = self.cenario(10)["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.EXCELENTE)
        self.assertEqual(alvo.eixo_comparacao[2], "7d_click")

    def test_tipo_sem_rotulo_amigavel_continua_comparavel(self):
        # Indicador que a fonte ainda nao devolveu, portanto sem nome de
        # exibicao. A comparacao de custo entre campanhas do mesmo tipo
        # tecnico continua valida: o motor compara pelo tipo, nao pelo rotulo.
        self.assertNotIn(TIPO_SEM_ROTULO, m.ROTULOS_RESULTADO)
        linhas = pares_result(CONTA_A, [10, 20, 30, 40], tipo=TIPO_SEM_ROTULO)
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10",
            tipo=TIPO_SEM_ROTULO,
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.EXCELENTE)
        self.assertEqual(alvo.eixo_comparacao[1], TIPO_SEM_ROTULO)

    def test_diferenca_para_a_mediana_mantem_o_sinal(self):
        alvo = self.cenario(10)["Campanha-ALVO0001"]
        # Mediana dos pares = 25; custo 10 fica 60% abaixo.
        self.assertEqual(alvo.benchmark_mediana, Decimal(25))
        self.assertEqual(alvo.diferenca_mediana_pct, Decimal("-0.6"))


class TestMetaCPL(unittest.TestCase):
    """Fallback para custo por Lead quando nao ha Resultado utilizavel."""

    def test_sem_result_com_leads_usa_cpl(self):
        linhas = [
            *campanha_lead(CONTA_A, "Campanha-L0000001", spend="100", leads="10"),
            *campanha_lead(CONTA_A, "Campanha-L0000002", spend="200", leads="10"),
            *campanha_lead(CONTA_A, "Campanha-L0000003", spend="300", leads="10"),
            *campanha_lead(CONTA_A, "Campanha-ALVO0001", spend="120", leads="10"),
        ]
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.kpi_tipo, c.CPL)
        self.assertEqual(alvo.eixo_comparacao, (c.EIXO_META_LEAD,))
        self.assertEqual(alvo.status, c.EXCELENTE)
        self.assertIn("Result indisponível", alvo.motivo)

    def test_sem_result_e_sem_leads_nao_e_comparavel(self):
        linhas = campanha_lead(CONTA_A, "Campanha-ALVO0001", spend="500", leads="0")
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.NAO_COMPARAVEL)
        self.assertIn("Sem Result e sem Leads", alvo.motivo)
        self.assertNotEqual(alvo.status, c.RUIM)

    def test_cpl_nao_se_compara_com_cpr_de_tipo_lead(self):
        # Seis campanhas com Resultado do tipo Lead nao formam referencia para
        # uma campanha avaliada por CPL: sao contratos derivados diferentes.
        linhas = pares_result(
            CONTA_B, [10, 20, 30, 40, 50, 60], tipo=TIPO_LEAD, prefixo="R"
        )
        linhas += campanha_lead(CONTA_A, "Campanha-ALVO0001", spend="100", leads="10")
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.benchmark_origem, c.INDISPONIVEL)

    def test_cpl_aceita_portfolio_no_mesmo_eixo(self):
        linhas = [
            *campanha_lead(CONTA_B, "Campanha-L0000001", spend="100", leads="10"),
            *campanha_lead(CONTA_B, "Campanha-L0000002", spend="200", leads="10"),
            *campanha_lead(CONTA_B, "Campanha-L0000003", spend="300", leads="10"),
            *campanha_lead(CONTA_C, "Campanha-L0000004", spend="400", leads="10"),
            *campanha_lead(CONTA_C, "Campanha-L0000005", spend="500", leads="10"),
            *campanha_lead(CONTA_A, "Campanha-ALVO0001", spend="120", leads="10"),
        ]
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.benchmark_origem, c.MESMO_TIPO_PORTFOLIO)
        self.assertEqual(alvo.benchmark_n, 5)


class TestGoogle(unittest.TestCase):
    """Google: CPA, e nada de benchmark entre clientes."""

    def test_cpa_classificado_com_pares_da_propria_conta(self):
        linhas = pares_google(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="500", conversoes="10"
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.kpi_tipo, c.CPA)
        self.assertEqual(alvo.status, c.RUIM)
        self.assertEqual(alvo.benchmark_origem, c.MESMO_CLIENTE)

    def test_sem_pares_na_conta_nao_cai_para_o_portfolio(self):
        # Oito pares em outras contas nao viram referencia: sem eixo semantico
        # o Google nao tem grupo comparavel entre clientes.
        linhas = pares_google(CONTA_B, [10, 20, 30, 40, 50, 60, 70, 80], prefixo="B")
        linhas += campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="100", conversoes="10"
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.benchmark_origem, c.INDISPONIVEL)

    def test_google_nunca_usa_origem_de_portfolio(self):
        linhas = pares_google(CONTA_B, [10, 20, 30, 40, 50, 60], prefixo="B")
        linhas += pares_google(CONTA_A, [15, 25], prefixo="A")
        linhas += campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="100", conversoes="10"
        )
        origens = {
            classificacao.benchmark_origem
            for classificacao in c.classificar_campanhas(linhas)
        }
        self.assertNotIn(c.MESMO_TIPO_PORTFOLIO, origens)

    def test_valor_de_conversao_nao_altera_status(self):
        # `conversion_value` e `purchase_value` sao diferentes de zero no
        # fixture. Se ROAS participasse, estes dois cenarios divergiriam.
        linhas = pares_google(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="100", conversoes="10"
        )
        com_valor = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]

        sem_valor = []
        for registro in linhas:
            copia = dict(registro)
            copia["conversion_value"] = Decimal(0)
            copia["purchase_value"] = Decimal(0)
            copia["purchases"] = Decimal(0)
            sem_valor.append(copia)
        zerado = por_campanha(c.classificar_campanhas(sem_valor))["Campanha-ALVO0001"]
        self.assertEqual(com_valor.status, zerado.status)
        self.assertEqual(com_valor.kpi_valor, zerado.kpi_valor)


class TestGastoSemResultado(unittest.TestCase):
    """Denominador zero com investimento: a regra que separa cedo de caro."""

    def cenario(self, spend: str) -> c.ClassificacaoCampanha:
        # Pares 10/20/30/40 com 10 conversoes cada: mediana do CPA = 25.
        linhas = pares_google(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend=spend, conversoes="0"
        )
        return por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]

    def test_abaixo_de_meia_referencia_e_insuficiente(self):
        alvo = self.cenario("10")  # 0,4x a mediana de 25
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertIn("ainda baixo", alvo.motivo)

    def test_exatamente_meia_referencia_e_atencao(self):
        alvo = self.cenario("12.5")
        self.assertEqual(alvo.status, c.ATENCAO)
        self.assertIn("Investimento relevante sem resultado", alvo.motivo)

    def test_logo_abaixo_do_dobro_ainda_e_atencao(self):
        self.assertEqual(self.cenario("49.75").status, c.ATENCAO)

    def test_exatamente_o_dobro_e_ruim(self):
        alvo = self.cenario("50")
        self.assertEqual(alvo.status, c.RUIM)
        self.assertIn("sem gerar resultado", alvo.motivo)

    def test_tres_vezes_a_referencia_e_ruim(self):
        self.assertEqual(self.cenario("75").status, c.RUIM)

    def test_sem_referencia_nao_vira_ruim(self):
        linhas = campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="10000", conversoes="0"
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertIn("sem referência de custo", alvo.motivo)

    def test_regra_precede_o_gate_de_poucos_dias(self):
        # Um unico dia, mas gasto de 3x a referencia sem conversao: o veredito
        # nao pode virar "poucos dias".
        linhas = pares_google(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="75", conversoes="0", dias=1
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.RUIM)

    def test_meta_sem_result_e_sem_lead_nao_entra_na_regra(self):
        # Ausencia total no Meta e limite semantico, nao gasto sem resultado:
        # nao existe tipo de Resultado a partir do qual buscar referencia.
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_lead(CONTA_A, "Campanha-ALVO0001", spend="9999", leads="0")
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.NAO_COMPARAVEL)


class TestSuficiencia(unittest.TestCase):
    """Gates de evidencia da propria campanha."""

    def base(self) -> list[dict]:
        return pares_google(CONTA_A, [10, 20, 30, 40])

    def test_sem_investimento(self):
        linhas = self.base() + campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="0", conversoes="5"
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertIn("Sem investimento", alvo.motivo)

    def test_dois_dias_e_insuficiente(self):
        linhas = self.base() + campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="100", conversoes="10", dias=2
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertIn("dia(s)", alvo.motivo)

    def test_tres_dias_ja_classifica(self):
        linhas = self.base() + campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="100", conversoes="10", dias=3
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertIn(alvo.status, c.STATUS_DE_DESEMPENHO)

    def test_dois_resultados_e_insuficiente(self):
        linhas = self.base() + campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="20", conversoes="2"
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertIn("resultado(s)", alvo.motivo)

    def test_tres_resultados_ja_classifica(self):
        linhas = self.base() + campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="30", conversoes="3"
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertIn(alvo.status, c.STATUS_DE_DESEMPENHO)

    def test_campanha_fraca_nao_serve_de_par(self):
        # Tres campanhas com uma conversao cada nao formam referencia: elas nao
        # passam no mesmo gate de evidencia exigido de quem seria classificado.
        linhas = []
        for indice in range(3):
            linhas += campanha_google(
                CONTA_A, f"Campanha-W{indice:07d}", spend="10", conversoes="1"
            )
        linhas += campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="100", conversoes="10"
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.benchmark_origem, c.INDISPONIVEL)


class TestTendencia(unittest.TestCase):
    """Tendencia so aparece com volume, e nunca decide o status."""

    def cenario(
        self, spend_atual: str, *, denominador_anterior: str = "10", anterior=True
    ):
        atual = pares_google(CONTA_A, [10, 20, 30, 40])
        atual += campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend=spend_atual, conversoes="10"
        )
        passado = None
        if anterior:
            passado = campanha_google(
                CONTA_A,
                "Campanha-ALVO0001",
                spend="1000",
                conversoes=denominador_anterior,
                primeiro_dia=PRIMEIRO_DIA - timedelta(days=10),
            )
        resultado = c.classificar_campanhas(atual, linhas_periodo_anterior=passado)
        return por_campanha(resultado)["Campanha-ALVO0001"]

    def test_queda_maior_que_quinze_por_cento_e_melhora(self):
        # CPA anterior = 100; atual = 80.
        self.assertEqual(self.cenario("800").tendencia, c.MELHORANDO)

    def test_dentro_da_zona_neutra_e_estavel(self):
        # CPA atual = 90: variacao de -10%.
        self.assertEqual(self.cenario("900").tendencia, c.ESTAVEL)

    def test_alta_maior_que_quinze_por_cento_e_piora(self):
        self.assertEqual(self.cenario("1200").tendencia, c.PIORANDO)

    def test_borda_de_quinze_por_cento_ja_e_movimento(self):
        self.assertEqual(self.cenario("850").tendencia, c.MELHORANDO)
        self.assertEqual(self.cenario("1150").tendencia, c.PIORANDO)

    def test_denominador_anterior_baixo_desliga_a_tendencia(self):
        self.assertIsNone(self.cenario("800", denominador_anterior="9").tendencia)

    def test_sem_periodo_anterior_nao_ha_tendencia(self):
        self.assertIsNone(self.cenario("800", anterior=False).tendencia)

    def test_tendencia_nao_altera_status(self):
        com = self.cenario("1200")
        sem = self.cenario("1200", anterior=False)
        self.assertEqual(com.status, sem.status)
        self.assertEqual(com.tendencia, c.PIORANDO)
        self.assertIsNone(sem.tendencia)

    def test_eixo_diferente_no_periodo_anterior_desliga(self):
        atual = pares_result(CONTA_A, [10, 20, 30, 40])
        atual += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        passado = campanha_result(
            CONTA_A,
            "Campanha-ALVO0001",
            spend="1000",
            resultados="10",
            tipo=TIPO_THRUPLAY,
            primeiro_dia=PRIMEIRO_DIA - timedelta(days=10),
        )
        alvo = por_campanha(
            c.classificar_campanhas(atual, linhas_periodo_anterior=passado)
        )["Campanha-ALVO0001"]
        self.assertIsNone(alvo.tendencia)


class TestRecorteEOrdem(unittest.TestCase):
    """Alvo, referencia, ordenacao e determinismo."""

    def universo(self) -> list[dict]:
        linhas = pares_result(CONTA_A, [10, 20, 30, 40], prefixo="A")
        linhas += pares_google(CONTA_B, [10, 20, 30, 40], prefixo="B")
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        return linhas

    def test_recorte_por_conta_e_plataforma(self):
        resultado = c.classificar_campanhas(
            self.universo(), conta_id=CONTA_A, plataforma=m.META
        )
        self.assertTrue(all(item.conta_id == CONTA_A for item in resultado))
        self.assertTrue(all(item.plataforma == m.META for item in resultado))

    def test_recorte_nao_destroi_o_benchmark(self):
        # O universo continua sendo o periodo inteiro: recortar a saida por
        # conta nao pode mudar o status de quem foi classificado.
        completo = por_campanha(c.classificar_campanhas(self.universo()))
        recortado = por_campanha(
            c.classificar_campanhas(self.universo(), conta_id=CONTA_A)
        )
        self.assertEqual(
            completo["Campanha-ALVO0001"], recortado["Campanha-ALVO0001"]
        )

    def test_ordem_de_entrada_nao_muda_o_resultado(self):
        linhas = self.universo()
        embaralhadas = list(linhas)
        random.Random(20260901).shuffle(embaralhadas)
        self.assertEqual(
            c.classificar_campanhas(linhas), c.classificar_campanhas(embaralhadas)
        )

    def test_saida_ordenada_de_forma_estavel(self):
        resultado = c.classificar_campanhas(self.universo())
        chaves = [(i.plataforma, i.conta_id, i.campanha_id) for i in resultado]
        self.assertEqual(chaves, sorted(chaves))

    def test_periodo_curto_e_metadado(self):
        curto = c.classificar_campanhas(
            campanha_google(CONTA_A, "Campanha-ALVO0001", spend="100",
                            conversoes="10", dias=3)
        )
        longo = c.classificar_campanhas(
            campanha_google(CONTA_A, "Campanha-ALVO0001", spend="100",
                            conversoes="10", dias=10)
        )
        self.assertTrue(curto[0].periodo_curto)
        self.assertFalse(longo[0].periodo_curto)

    def test_dataset_vazio(self):
        self.assertEqual(c.classificar_campanhas([]), [])


class TestContratoDoMotor(unittest.TestCase):
    """O que o motor nao pode ler, importar nem vazar."""

    def arvore(self) -> ast.Module:
        fonte = (BASE_DIR / "dashboard" / "classificacao.py").read_text(
            encoding="utf-8"
        )
        return ast.parse(fonte)

    def test_nao_le_metrica_proibida(self):
        # Varre as chaves efetivamente lidas no codigo, nao a prosa: alcance,
        # impressoes, cliques e valores nao podem entrar em KPI, benchmark,
        # suficiencia nem tendencia.
        lidas = {
            no.slice.value
            for no in ast.walk(self.arvore())
            if isinstance(no, ast.Subscript)
            and isinstance(no.slice, ast.Constant)
            and isinstance(no.slice.value, str)
        }
        proibidas = {
            "reach",
            "impressions",
            "link_clicks",
            "video_views",
            "profile_views",
            "purchases",
            "purchase_value",
            "conversion_value",
        }
        self.assertEqual(lidas & proibidas, set())

    def test_nao_importa_streamlit_nem_banco(self):
        modulos = set()
        for no in ast.walk(self.arvore()):
            if isinstance(no, ast.Import):
                modulos.update(alias.name.split(".")[0] for alias in no.names)
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos.add(no.module.split(".")[0])
        self.assertEqual(
            modulos & {"streamlit", "plotly", "psycopg2", "sqlalchemy", "requests"},
            set(),
        )
        self.assertEqual(modulos, {"dataclasses", "decimal", "dashboard"})

    def test_status_sao_exatamente_seis(self):
        self.assertEqual(len(c.STATUS), 6)
        self.assertEqual(
            set(c.STATUS),
            {
                c.EXCELENTE,
                c.BOA,
                c.ATENCAO,
                c.RUIM,
                c.DADOS_INSUFICIENTES,
                c.NAO_COMPARAVEL,
            },
        )

    def test_origens_de_benchmark(self):
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        origens = {
            item.benchmark_origem for item in c.classificar_campanhas(linhas)
        }
        self.assertLessEqual(
            origens, {c.MESMO_CLIENTE, c.MESMO_TIPO_PORTFOLIO, c.INDISPONIVEL}
        )

    def test_classificacao_nao_carrega_campo_privado(self):
        campos = set(c.ClassificacaoCampanha.__dataclass_fields__)
        self.assertEqual(
            campos
            & {
                "objective",
                "optimization_goal",
                "conta_nome",
                "campanha_nome",
                "conta_external_id",
                "campanha_external_id",
            },
            set(),
        )

    def test_motivo_nao_cita_identificador(self):
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        for item in c.classificar_campanhas(linhas):
            self.assertNotIn(item.conta_id, item.motivo)
            self.assertNotIn(item.campanha_id, item.motivo)

    def test_motor_nao_le_arquivo(self):
        chamadas = {
            no.func.id
            for no in ast.walk(self.arvore())
            if isinstance(no, ast.Call) and isinstance(no.func, ast.Name)
        }
        self.assertEqual(chamadas & {"open", "eval", "exec"}, set())


class TestMotivoEstruturado(unittest.TestCase):
    """Cada ramo da regra tem codigo proprio, e a UI nunca precisa ler texto."""

    def test_result_incompleto_tem_codigo_proprio(self):
        linhas = campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        linhas.append(
            linha(
                dia=PRIMEIRO_DIA + timedelta(days=9),
                plataforma=m.META,
                conta=CONTA_A,
                campanha="Campanha-ALVO0001",
                spend="500",
            )
        )
        alvo = por_campanha(c.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_RESULT_INCOMPLETO)
        self.assertEqual(alvo.status, c.NAO_COMPARAVEL)

    def test_codigos_dos_demais_bloqueios_semanticos(self):
        multiplos = campanha_result(
            CONTA_A, "Campanha-MULT0001", spend="100", resultados="10"
        )
        multiplos.append(
            linha(
                dia=PRIMEIRO_DIA + timedelta(days=1),
                plataforma=m.META,
                conta=CONTA_A,
                campanha="Campanha-MULT0001",
                spend="50",
                result_type=TIPO_THRUPLAY,
                result_count="5",
                result_attribution_window="7d_click",
                cost_per_result="10",
            )
        )
        janela = campanha_result(
            CONTA_A, "Campanha-JANE0001", spend="100", resultados="10"
        )
        janela.append(
            linha(
                dia=PRIMEIRO_DIA + timedelta(days=1),
                plataforma=m.META,
                conta=CONTA_A,
                campanha="Campanha-JANE0001",
                spend="50",
                result_type=TIPO_MENSAGEM,
                result_count="5",
                result_attribution_window="1d_view",
                cost_per_result="10",
            )
        )
        sem_kpi = campanha_lead(CONTA_A, "Campanha-SKPI0001", spend="500", leads="0")

        for linhas, campanha, esperado in (
            (multiplos, "Campanha-MULT0001", c.MOTIVO_MULTIPLOS_RESULT_TYPES),
            (janela, "Campanha-JANE0001", c.MOTIVO_JANELA_INCOMPATIVEL),
            (sem_kpi, "Campanha-SKPI0001", c.MOTIVO_SEM_KPI_META),
        ):
            with self.subTest(codigo=esperado):
                alvo = por_campanha(c.classificar_campanhas(linhas))[campanha]
                self.assertEqual(alvo.motivo_codigo, esperado)

    def test_codigos_de_suficiencia_e_benchmark(self):
        base = pares_google(CONTA_A, [10, 20, 30, 40])
        casos = (
            (
                campanha_google(CONTA_A, "Campanha-SPEN0001", spend="0",
                                conversoes="5"),
                "Campanha-SPEN0001",
                c.MOTIVO_SPEND_ZERO,
            ),
            (
                campanha_google(CONTA_A, "Campanha-DIAS0001", spend="100",
                                conversoes="10", dias=2),
                "Campanha-DIAS0001",
                c.MOTIVO_POUCOS_DIAS,
            ),
            (
                campanha_google(CONTA_A, "Campanha-DENO0001", spend="20",
                                conversoes="2"),
                "Campanha-DENO0001",
                c.MOTIVO_DENOMINADOR_BAIXO,
            ),
            (
                campanha_google(CONTA_A, "Campanha-QUAR0001", spend="100",
                                conversoes="10"),
                "Campanha-QUAR0001",
                c.MOTIVO_QUARTIL,
            ),
        )
        for extra, campanha, esperado in casos:
            with self.subTest(codigo=esperado):
                alvo = por_campanha(c.classificar_campanhas(base + extra))[campanha]
                self.assertEqual(alvo.motivo_codigo, esperado)

        sozinha = campanha_google(
            CONTA_B, "Campanha-PEER0001", spend="100", conversoes="10"
        )
        alvo = por_campanha(c.classificar_campanhas(sozinha))["Campanha-PEER0001"]
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_SEM_PEERS)

    def test_codigos_do_gasto_sem_resultado(self):
        base = pares_google(CONTA_A, [10, 20, 30, 40])  # mediana 25
        for spend, esperado in (
            ("10", c.MOTIVO_ZERO_RESULT_GASTO_BAIXO),
            ("30", c.MOTIVO_ZERO_RESULT_GASTO_RELEVANTE),
            ("75", c.MOTIVO_ZERO_RESULT_GASTO_ALTO),
        ):
            with self.subTest(codigo=esperado):
                linhas = base + campanha_google(
                    CONTA_A, "Campanha-ZERO0001", spend=spend, conversoes="0"
                )
                alvo = por_campanha(c.classificar_campanhas(linhas))[
                    "Campanha-ZERO0001"
                ]
                self.assertEqual(alvo.motivo_codigo, esperado)

        sem_referencia = campanha_google(
            CONTA_B, "Campanha-ZERO0002", spend="9999", conversoes="0"
        )
        alvo = por_campanha(c.classificar_campanhas(sem_referencia))[
            "Campanha-ZERO0002"
        ]
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_ZERO_RESULT_SEM_REFERENCIA)

    def test_todo_codigo_emitido_esta_declarado(self):
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        linhas += pares_google(CONTA_B, [10, 20, 30, 40], prefixo="G")
        linhas += campanha_lead(CONTA_C, "Campanha-SKPI0001", spend="10", leads="0")
        for item in c.classificar_campanhas(linhas):
            self.assertIn(item.motivo_codigo, c.MOTIVOS)


class TestResumo(unittest.TestCase):
    """Resumo e contagem pura: nao reclassifica e nao esconde categoria."""

    def universo(self) -> list[dict]:
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        linhas += campanha_lead(CONTA_B, "Campanha-SKPI0001", spend="50", leads="0")
        return linhas

    def test_todas_as_categorias_aparecem(self):
        resumo = c.resumir_classificacoes(c.classificar_campanhas(self.universo()))
        self.assertEqual(set(resumo["por_status"]), set(c.STATUS))
        self.assertEqual(set(resumo["por_motivo"]), set(c.MOTIVOS))
        self.assertEqual(
            set(resumo["por_origem"]),
            {c.MESMO_CLIENTE, c.MESMO_TIPO_PORTFOLIO, c.INDISPONIVEL},
        )
        self.assertIn(None, resumo["por_tendencia"])

    def test_contagens_fecham(self):
        classificacoes = c.classificar_campanhas(self.universo())
        resumo = c.resumir_classificacoes(classificacoes)
        self.assertEqual(resumo["total"], len(classificacoes))
        self.assertEqual(sum(resumo["por_status"].values()), resumo["total"])
        self.assertEqual(sum(resumo["por_motivo"].values()), resumo["total"])
        self.assertEqual(sum(resumo["por_origem"].values()), resumo["total"])
        self.assertEqual(
            resumo["com_desempenho"],
            sum(1 for i in classificacoes if i.status in c.STATUS_DE_DESEMPENHO),
        )
        self.assertEqual(resumo["por_status"][c.NAO_COMPARAVEL], 1)
        self.assertEqual(resumo["por_motivo"][c.MOTIVO_SEM_KPI_META], 1)

    def test_resumo_de_lista_vazia(self):
        resumo = c.resumir_classificacoes([])
        self.assertEqual(resumo["total"], 0)
        self.assertEqual(resumo["com_desempenho"], 0)
        self.assertEqual(set(resumo["por_status"]), set(c.STATUS))


class TestDemoClassificavel(unittest.TestCase):
    """O dataset sintetico versionado precisa DEMONSTRAR a classificacao.

    A versao anterior da demo tinha 15 campanhas e nenhum grupo de comparacao
    com pares suficientes: as 15 saiam como "Dados insuficientes" e a tela
    ficaria inteira cinza. Estes testes existem para que isso nao volte em
    silencio numa regeracao futura.
    """

    @classmethod
    def setUpClass(cls):
        from dashboard import dados

        cls.dados = dados
        cls.conjunto = dados.carregar(dados.escolher_fonte(modo="demonstracao"))
        cls.resultado = c.classificar_campanhas(cls.conjunto.linhas)
        cls.resumo = c.resumir_classificacoes(cls.resultado)

    def test_contrato_da_demo_intacto(self):
        self.assertEqual(self.conjunto.manifesto["versao_contrato"], 3)
        self.assertEqual(len(self.conjunto.manifesto["colunas"]), 24)
        self.assertEqual(self.conjunto.modo, "demonstracao")

    def test_demo_continua_sintetica(self):
        # Sem chave de pseudonimizacao e com a natureza declarada em texto: a
        # demo nao pode passar a derivar de dado real por descuido.
        self.assertIsNone(self.conjunto.manifesto["fingerprint_chave"])
        self.assertIn("SINTETICOS", self.conjunto.manifesto["natureza"])
        self.assertNotIn("objective", self.conjunto.manifesto["colunas"])
        self.assertNotIn("optimization_goal", self.conjunto.manifesto["colunas"])

    def test_todos_os_seis_estados_aparecem(self):
        for status in c.STATUS:
            with self.subTest(status=status):
                self.assertGreater(
                    self.resumo["por_status"][status],
                    0,
                    f"a demo nao exercita o status {status}",
                )

    def test_ha_exemplo_de_ruim_por_quartil_e_por_gasto_sem_resultado(self):
        ruins = [item for item in self.resultado if item.status == c.RUIM]
        codigos = {item.motivo_codigo for item in ruins}
        self.assertIn(c.MOTIVO_QUARTIL, codigos)
        self.assertIn(c.MOTIVO_ZERO_RESULT_GASTO_ALTO, codigos)

    def test_ha_exemplo_de_result_incompleto(self):
        self.assertGreater(self.resumo["por_motivo"][c.MOTIVO_RESULT_INCOMPLETO], 0)

    def test_dados_insuficientes_nao_vem_so_de_grupo_pequeno(self):
        codigos = {
            item.motivo_codigo
            for item in self.resultado
            if item.status == c.DADOS_INSUFICIENTES
        }
        self.assertTrue(
            codigos - {c.MOTIVO_SEM_PEERS},
            "todos os insuficientes vem de grupo pequeno",
        )

    def test_origens_de_benchmark_exercitadas(self):
        meta = [item for item in self.resultado if item.plataforma == m.META]
        google = [item for item in self.resultado if item.plataforma == m.GOOGLE]
        origens_meta = Counter(item.benchmark_origem for item in meta)
        origens_google = Counter(item.benchmark_origem for item in google)
        self.assertGreater(origens_meta[c.MESMO_CLIENTE], 0)
        self.assertGreater(origens_meta[c.MESMO_TIPO_PORTFOLIO], 0)
        self.assertGreater(origens_google[c.MESMO_CLIENTE], 0)
        self.assertEqual(origens_google[c.MESMO_TIPO_PORTFOLIO], 0)

    def test_os_tres_kpis_aparecem(self):
        kpis = {item.kpi_tipo for item in self.resultado}
        self.assertLessEqual({c.CPR, c.CPL, c.CPA}, kpis)

    def test_alcance_e_valor_nao_mudam_status_na_demo(self):
        # Prova de comportamento, e nao de codigo: zerar alcance, valor de
        # conversao e compras nao pode mover nenhuma campanha de status.
        neutras = []
        for registro in self.conjunto.linhas:
            copia = dict(registro)
            copia["reach"] = Decimal(0)
            copia["conversion_value"] = Decimal(0)
            copia["purchases"] = Decimal(0)
            copia["purchase_value"] = Decimal(0)
            neutras.append(copia)
        antes = {(i.plataforma, i.campanha_id): i.status for i in self.resultado}
        depois = {
            (i.plataforma, i.campanha_id): i.status
            for i in c.classificar_campanhas(neutras)
        }
        self.assertEqual(antes, depois)

    def test_tendencia_demonstravel_na_demo(self):
        datas = sorted({linha["data"] for linha in self.conjunto.linhas})
        fim = datas[-1]
        inicio_atual = fim - timedelta(days=6)
        fim_anterior = inicio_atual - timedelta(days=1)
        inicio_anterior = fim_anterior - timedelta(days=6)
        atual = [
            linha
            for linha in self.conjunto.linhas
            if inicio_atual <= linha["data"] <= fim
        ]
        anterior = [
            linha
            for linha in self.conjunto.linhas
            if inicio_anterior <= linha["data"] <= fim_anterior
        ]
        tendencias = {
            item.tendencia
            for item in c.classificar_campanhas(
                atual, linhas_periodo_anterior=anterior
            )
        }
        self.assertGreaterEqual(len(tendencias - {None}), 2)


if __name__ == "__main__":
    unittest.main()
