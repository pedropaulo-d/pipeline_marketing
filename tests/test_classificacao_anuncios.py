"""Testes do motor de classificacao relativa no nivel de anuncio.

A suite caracteriza as conclusoes empiricas da 4V.3A: benchmark primeiro no
mesmo grupo, depois na mesma campanha, sempre leave-one-out e nunca entre
campanhas. Tambem congela a semantica compartilhada de CPR/CPL/CPA sem fazer
o motor de anuncios depender da classificacao da campanha ou da UI.

Rodar:
    python -m unittest tests.test_classificacao_anuncios
"""

import inspect
import random
import unittest
from collections import Counter, defaultdict
from dataclasses import fields
from datetime import date, timedelta
from decimal import Decimal

from dashboard import classificacao as c
from dashboard import metricas as m


CONTA_A = "Cliente-ANUN0001"
CONTA_B = "Cliente-ANUN0002"
CAMPANHA_A = "Campanha-ANUN0001"
CAMPANHA_B = "Campanha-ANUN0002"
CAMPANHA_C = "Campanha-ANUN0003"
GRUPO_A = "AdSet-ANUN0001"
GRUPO_B = "AdSet-ANUN0002"
GRUPO_C = "AdSet-ANUN0003"
TIPO_LEAD = "actions:offsite_conversion.fb_pixel_lead"
TIPO_THRUPLAY = "video_thruplay_watched_actions"
PRIMEIRO_DIA = date(2026, 8, 3)


def linha(
    *,
    dia: date,
    plataforma: str,
    conta: str,
    campanha: str,
    grupo: str,
    anuncio: str,
    spend: Decimal | str = "0",
    conversions: Decimal | str = "0",
    result_type: str | None = None,
    result_count: Decimal | str | None = None,
    result_attribution_window: str | None = None,
    cost_per_result: Decimal | str | None = None,
    impressions: Decimal | str = "1000",
    link_clicks: Decimal | str = "50",
    reach: Decimal | str = "700",
    purchase_value: Decimal | str = "123",
    conversion_value: Decimal | str = "456",
) -> dict:
    """Monta linha integral do contrato v3 com identificadores sinteticos."""
    return {
        "data": dia,
        "plataforma": plataforma,
        "conta_id": conta,
        "conta_versao": 1,
        "campanha_id": campanha,
        "campanha_versao": 1,
        "adset_id": grupo,
        "adset_versao": 1,
        "anuncio_id": anuncio,
        "anuncio_versao": 1,
        "spend": Decimal(spend),
        "impressions": Decimal(impressions),
        "link_clicks": Decimal(link_clicks),
        "conversions": Decimal(conversions),
        "conversion_value": Decimal(conversion_value),
        "video_views": Decimal(321),
        "reach": Decimal(reach),
        "profile_views": Decimal(17),
        "purchases": Decimal(9),
        "purchase_value": Decimal(purchase_value),
        "result_type": result_type,
        "result_count": (
            None if result_count is None else Decimal(result_count)
        ),
        "result_attribution_window": result_attribution_window,
        "cost_per_result": (
            None if cost_per_result is None else Decimal(cost_per_result)
        ),
    }


def anuncio_google(
    anuncio: str,
    *,
    custo: Decimal | str = "10",
    conversoes: Decimal | str = "10",
    spend: Decimal | str | None = None,
    dias: int = 3,
    conta: str = CONTA_A,
    campanha: str = CAMPANHA_A,
    grupo: str = GRUPO_A,
) -> list[dict]:
    """Anuncio Google com CPA controlado e Result inteiramente ausente."""
    quantidade = Decimal(conversoes)
    total = Decimal(spend) if spend is not None else Decimal(custo) * quantidade
    linhas = [
        linha(
            dia=PRIMEIRO_DIA,
            plataforma=m.GOOGLE,
            conta=conta,
            campanha=campanha,
            grupo=grupo,
            anuncio=anuncio,
            spend=total,
            conversions=quantidade,
        )
    ]
    for passo in range(1, dias):
        linhas.append(
            linha(
                dia=PRIMEIRO_DIA + timedelta(days=passo),
                plataforma=m.GOOGLE,
                conta=conta,
                campanha=campanha,
                grupo=grupo,
                anuncio=anuncio,
            )
        )
    return linhas


def anuncio_result(
    anuncio: str,
    *,
    custo: Decimal | str = "10",
    resultados: Decimal | str = "10",
    spend: Decimal | str | None = None,
    dias: int = 3,
    conta: str = CONTA_A,
    campanha: str = CAMPANHA_A,
    grupo: str = GRUPO_A,
    tipo: str = TIPO_LEAD,
    janela: str | None = "7d_click",
) -> list[dict]:
    """Anuncio Meta tipado; dias posteriores usam a Forma A neutra."""
    quantidade = Decimal(resultados)
    total = Decimal(spend) if spend is not None else Decimal(custo) * quantidade
    custo_factual = None if quantidade <= 0 else total / quantidade
    linhas = [
        linha(
            dia=PRIMEIRO_DIA,
            plataforma=m.META,
            conta=conta,
            campanha=campanha,
            grupo=grupo,
            anuncio=anuncio,
            spend=total,
            result_type=tipo,
            result_count=quantidade,
            result_attribution_window=janela,
            cost_per_result=custo_factual,
        )
    ]
    for passo in range(1, dias):
        linhas.append(
            linha(
                dia=PRIMEIRO_DIA + timedelta(days=passo),
                plataforma=m.META,
                conta=conta,
                campanha=campanha,
                grupo=grupo,
                anuncio=anuncio,
                result_type=tipo,
                result_count="0",
            )
        )
    return linhas


def anuncio_lead(
    anuncio: str,
    *,
    custo: Decimal | str = "10",
    leads: Decimal | str = "10",
    spend: Decimal | str | None = None,
    dias: int = 3,
    conta: str = CONTA_A,
    campanha: str = CAMPANHA_A,
    grupo: str = GRUPO_A,
) -> list[dict]:
    """Anuncio Meta sem Result, com CPL calculavel por `conversions`."""
    quantidade = Decimal(leads)
    total = Decimal(spend) if spend is not None else Decimal(custo) * quantidade
    linhas = [
        linha(
            dia=PRIMEIRO_DIA,
            plataforma=m.META,
            conta=conta,
            campanha=campanha,
            grupo=grupo,
            anuncio=anuncio,
            spend=total,
            conversions=quantidade,
        )
    ]
    for passo in range(1, dias):
        linhas.append(
            linha(
                dia=PRIMEIRO_DIA + timedelta(days=passo),
                plataforma=m.META,
                conta=conta,
                campanha=campanha,
                grupo=grupo,
                anuncio=anuncio,
            )
        )
    return linhas


def grupo_google(
    custos: list[Decimal | str],
    *,
    prefixo: str = "PAR",
    conta: str = CONTA_A,
    campanha: str = CAMPANHA_A,
    grupo: str = GRUPO_A,
) -> list[dict]:
    linhas: list[dict] = []
    for indice, custo in enumerate(custos):
        linhas += anuncio_google(
            f"Anuncio-{prefixo}{indice:04d}",
            custo=custo,
            conta=conta,
            campanha=campanha,
            grupo=grupo,
        )
    return linhas


def grupo_result(
    custos: list[Decimal | str],
    *,
    prefixo: str = "MTA",
    tipo: str = TIPO_LEAD,
    conta: str = CONTA_A,
    campanha: str = CAMPANHA_A,
    grupo: str = GRUPO_A,
) -> list[dict]:
    linhas: list[dict] = []
    for indice, custo in enumerate(custos):
        linhas += anuncio_result(
            f"Anuncio-{prefixo}{indice:04d}",
            custo=custo,
            tipo=tipo,
            conta=conta,
            campanha=campanha,
            grupo=grupo,
        )
    return linhas


def grupo_lead(
    custos: list[Decimal | str],
    *,
    prefixo: str = "LED",
    conta: str = CONTA_A,
    campanha: str = CAMPANHA_A,
    grupo: str = GRUPO_A,
) -> list[dict]:
    linhas: list[dict] = []
    for indice, custo in enumerate(custos):
        linhas += anuncio_lead(
            f"Anuncio-{prefixo}{indice:04d}",
            custo=custo,
            conta=conta,
            campanha=campanha,
            grupo=grupo,
        )
    return linhas


def por_anuncio(
    resultado: list[c.ClassificacaoAnuncio],
) -> dict[str, c.ClassificacaoAnuncio]:
    return {item.anuncio_id: item for item in resultado}


class TestContratoPublico(unittest.TestCase):
    """API, dataclass e taxonomia ficam independentes de Streamlit."""

    def test_dataclass_tem_campos_exigidos_e_nao_tem_tendencia(self):
        nomes = {campo.name for campo in fields(c.ClassificacaoAnuncio)}
        self.assertTrue(
            {
                "anuncio_id",
                "campanha_id",
                "adset_id",
                "plataforma",
                "status",
                "kpi_tipo",
                "kpi_valor",
                "result_type",
                "benchmark_p25",
                "benchmark_mediana",
                "benchmark_p75",
                "benchmark_origem",
                "benchmark_n",
                "diferenca_mediana_pct",
                "motivo",
                "motivo_codigo",
                "eixo_comparacao",
                "dias_ativos",
                "denominador",
                "spend",
            }.issubset(nomes)
        )
        self.assertNotIn("tendencia", nomes)
        self.assertNotIn("periodo_anterior", nomes)

    def test_funcao_nao_recebe_periodo_anterior_nem_nivel(self):
        parametros = inspect.signature(c.classificar_anuncios).parameters
        self.assertNotIn("linhas_periodo_anterior", parametros)
        self.assertNotIn("periodo_anterior", parametros)
        self.assertNotIn("nivel", parametros)

    def test_reutiliza_exatamente_a_taxonomia_de_seis_status(self):
        self.assertEqual(
            c.STATUS,
            (
                c.EXCELENTE,
                c.BOA,
                c.ATENCAO,
                c.RUIM,
                c.DADOS_INSUFICIENTES,
                c.NAO_COMPARAVEL,
            ),
        )

    def test_origens_de_anuncio_sao_proprias(self):
        universo = grupo_google(["10", "20", "30", "40"])
        origens = {
            item.benchmark_origem for item in c.classificar_anuncios(universo)
        }
        self.assertLessEqual(
            origens, {c.MESMO_GRUPO, c.MESMA_CAMPANHA, c.INDISPONIVEL}
        )
        self.assertFalse(origens & {c.MESMO_CLIENTE, c.MESMO_TIPO_PORTFOLIO})

    def test_dataset_vazio(self):
        self.assertEqual(c.classificar_anuncios([]), [])


class TestPeerGroupN1(unittest.TestCase):
    """N1 compara no mesmo ad set/grupo, com tres outros anuncios."""

    def test_quatro_anuncios_tem_tres_peers_leave_one_out(self):
        resultado = c.classificar_anuncios(grupo_google(["10", "20", "30", "40"]))
        self.assertEqual(len(resultado), 4)
        self.assertTrue(
            all(item.benchmark_origem == c.MESMO_GRUPO for item in resultado)
        )
        self.assertTrue(all(item.benchmark_n == 3 for item in resultado))
        self.assertTrue(all(item.status in c.STATUS_DE_DESEMPENHO for item in resultado))

    def test_bordas_dos_quartis_pertencem_ao_lado_melhor(self):
        # Os tres peers fixos em 10/20/30 produzem P25=15, P50=20 e P75=25.
        for custo, esperado in (
            ("15", c.EXCELENTE),
            ("20", c.BOA),
            ("25", c.ATENCAO),
            ("25.01", c.RUIM),
        ):
            with self.subTest(custo=custo):
                linhas = grupo_google(["10", "20", "30"])
                linhas += anuncio_google("Anuncio-ALVO0001", custo=custo)
                alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
                self.assertEqual(alvo.status, esperado)

    def test_leave_one_out_muda_rotulo_na_fixture(self):
        linhas = grupo_google(["10", "20", "30"])
        linhas += anuncio_google("Anuncio-ALVO0001", custo="30")
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.benchmark_p75, Decimal(25))
        self.assertEqual(alvo.status, c.RUIM)

        com_auto_influencia = [Decimal(10), Decimal(20), Decimal(30), Decimal(30)]
        status_incorreto = c._quartil(
            Decimal(30),
            c.percentil(com_auto_influencia, 25),
            c.percentil(com_auto_influencia, 50),
            c.percentil(com_auto_influencia, 75),
        )
        self.assertEqual(status_incorreto, c.ATENCAO)

    def test_diferenca_para_mediana_preserva_sinal(self):
        linhas = grupo_google(["10", "20", "30"])
        linhas += anuncio_google("Anuncio-ALVO0001", custo="10")
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.benchmark_mediana, Decimal(20))
        self.assertEqual(alvo.diferenca_mediana_pct, Decimal("-0.5"))

    def test_peer_precisa_de_spend_positivo(self):
        linhas = grupo_google(["10", "20"])
        linhas += anuncio_google(
            "Anuncio-SEM-SPEND", conversoes="10", spend="0"
        )
        linhas += anuncio_google("Anuncio-ALVO0001", custo="15")
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.benchmark_origem, c.INDISPONIVEL)
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_SEM_PEERS)

    def test_peer_precisa_de_tres_dias_e_tres_resultados(self):
        linhas = grupo_google(["10", "20"])
        linhas += anuncio_google("Anuncio-DOIS-DIAS", custo="30", dias=2)
        linhas += anuncio_google(
            "Anuncio-DOIS-RESULT", custo="30", conversoes="2"
        )
        linhas += anuncio_google("Anuncio-ALVO0001", custo="15")
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.benchmark_n, 0)


class TestPeerGroupN2(unittest.TestCase):
    """N2 amplia somente do grupo para a campanha."""

    def test_grupo_pequeno_usa_mesma_campanha(self):
        linhas = anuncio_google("Anuncio-ALVO0001", custo="15", grupo=GRUPO_A)
        for indice, custo in enumerate(("10", "20", "30")):
            linhas += anuncio_google(
                f"Anuncio-PAR{indice:04d}", custo=custo, grupo=GRUPO_B
            )
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.benchmark_origem, c.MESMA_CAMPANHA)
        self.assertEqual(alvo.benchmark_n, 3)
        self.assertEqual(alvo.status, c.EXCELENTE)

    def test_n1_tem_precedencia_sobre_n2(self):
        linhas = grupo_google(["10", "20", "30"], grupo=GRUPO_A)
        linhas += anuncio_google("Anuncio-ALVO0001", custo="15", grupo=GRUPO_A)
        linhas += grupo_google(
            ["100", "200", "300"], prefixo="OUT", grupo=GRUPO_B
        )
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.benchmark_origem, c.MESMO_GRUPO)
        self.assertEqual(alvo.benchmark_n, 3)
        self.assertEqual(alvo.benchmark_mediana, Decimal(20))

    def test_nao_atravessa_campanha(self):
        linhas = anuncio_google("Anuncio-ALVO0001", custo="15", campanha=CAMPANHA_A)
        linhas += grupo_google(
            ["10", "20", "30", "40"], prefixo="CB", campanha=CAMPANHA_B
        )
        linhas += grupo_google(
            ["10", "20", "30", "40"], prefixo="CC", campanha=CAMPANHA_C
        )
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.benchmark_origem, c.INDISPONIVEL)
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_SEM_PEERS)

    def test_nao_atravessa_conta_mesmo_com_ids_hierarquicos_iguais(self):
        linhas = anuncio_google("Anuncio-ALVO0001", custo="15", conta=CONTA_A)
        linhas += grupo_google(
            ["10", "20", "30", "40"], prefixo="OU", conta=CONTA_B
        )
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.benchmark_origem, c.INDISPONIVEL)


class TestSemanticaMeta(unittest.TestCase):
    """CPR, CPL e os bloqueios fail-closed do contrato Result."""

    def test_cpr_meta_result_homogeneo(self):
        linhas = grupo_result(["10", "20", "30"])
        linhas += anuncio_result("Anuncio-ALVO0001", custo="15")
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.kpi_tipo, c.CPR)
        self.assertEqual(alvo.kpi_valor, Decimal(15))
        self.assertEqual(alvo.result_type, TIPO_LEAD)
        self.assertEqual(alvo.status, c.EXCELENTE)

    def test_cpl_e_fallback_quando_result_esta_ausente(self):
        linhas = grupo_lead(["10", "20", "30"])
        linhas += anuncio_lead("Anuncio-ALVO0001", custo="15")
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.kpi_tipo, c.CPL)
        self.assertEqual(alvo.kpi_valor, Decimal(15))
        self.assertIsNone(alvo.result_type)
        self.assertIn("CPL", alvo.motivo)

    def test_sem_result_e_sem_lead_nao_e_comparavel(self):
        linhas = anuncio_lead("Anuncio-ALVO0001", leads="0", spend="100")
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.status, c.NAO_COMPARAVEL)
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_SEM_KPI_META)

    def test_typed_mais_absence_nao_e_comparavel(self):
        linhas = anuncio_result("Anuncio-ALVO0001", custo="10")
        linhas.append(
            linha(
                dia=PRIMEIRO_DIA + timedelta(days=4),
                plataforma=m.META,
                conta=CONTA_A,
                campanha=CAMPANHA_A,
                grupo=GRUPO_A,
                anuncio="Anuncio-ALVO0001",
                spend="50",
            )
        )
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.status, c.NAO_COMPARAVEL)
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_RESULT_INCOMPLETO)

    def test_multiplos_result_types_nao_sao_comparaveis(self):
        linhas = anuncio_result("Anuncio-ALVO0001", custo="10")
        linhas.append(
            linha(
                dia=PRIMEIRO_DIA + timedelta(days=4),
                plataforma=m.META,
                conta=CONTA_A,
                campanha=CAMPANHA_A,
                grupo=GRUPO_A,
                anuncio="Anuncio-ALVO0001",
                spend="50",
                result_type=TIPO_THRUPLAY,
                result_count="5",
                result_attribution_window="7d_click",
                cost_per_result="10",
            )
        )
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.status, c.NAO_COMPARAVEL)
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_MULTIPLOS_RESULT_TYPES)

    def test_janela_incompativel_nao_e_comparavel(self):
        linhas = anuncio_result("Anuncio-ALVO0001", custo="10")
        linhas.append(
            linha(
                dia=PRIMEIRO_DIA + timedelta(days=4),
                plataforma=m.META,
                conta=CONTA_A,
                campanha=CAMPANHA_A,
                grupo=GRUPO_A,
                anuncio="Anuncio-ALVO0001",
                spend="50",
                result_type=TIPO_LEAD,
                result_count="5",
                result_attribution_window="1d_view",
                cost_per_result="10",
            )
        )
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.status, c.NAO_COMPARAVEL)
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_JANELA_INCOMPATIVEL)

    def test_forma_a_neutra_nao_cria_segunda_janela(self):
        # `anuncio_result` acrescenta duas linhas Forma A neutras.
        linhas = grupo_result(["10", "20", "30"])
        linhas += anuncio_result("Anuncio-ALVO0001", custo="15")
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.eixo_comparacao[2], "7d_click")
        self.assertIn(alvo.status, c.STATUS_DE_DESEMPENHO)

    def test_tipos_de_resultado_distintos_nao_formam_peers(self):
        linhas = grupo_result(
            ["10", "20", "30", "40"], tipo=TIPO_THRUPLAY
        )
        linhas += anuncio_result(
            "Anuncio-ALVO0001", custo="15", tipo=TIPO_LEAD
        )
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.benchmark_origem, c.INDISPONIVEL)

    def test_janelas_distintas_nao_formam_peers(self):
        linhas = grupo_result(["10", "20", "30", "40"])
        linhas += anuncio_result(
            "Anuncio-ALVO0001", custo="15", janela="1d_view"
        )
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.benchmark_origem, c.INDISPONIVEL)

    def test_cpr_e_cpl_nao_formam_peers(self):
        linhas = grupo_result(["10", "20", "30", "40"])
        linhas += anuncio_lead("Anuncio-ALVO0001", custo="15")
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.kpi_tipo, c.CPL)
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.benchmark_origem, c.INDISPONIVEL)

    def test_result_zero_com_referencia_e_avaliado_antes_do_gate(self):
        linhas = grupo_result(["10", "20", "30"])
        # Janela explicita mantem o mesmo eixo dos peers apesar do count zero.
        linhas += anuncio_result(
            "Anuncio-ALVO0001",
            resultados="0",
            spend="40",
            dias=1,
            janela="7d_click",
        )
        alvo = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        self.assertEqual(alvo.kpi_tipo, c.CPR)
        self.assertEqual(alvo.denominador, Decimal(0))
        self.assertEqual(alvo.status, c.RUIM)
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_ZERO_RESULT_GASTO_ALTO)


class TestGoogleESuficiencia(unittest.TestCase):
    """CPA e gates de tres dias/tres conversoes, sem threshold monetario."""

    def base(self) -> list[dict]:
        return grupo_google(["10", "20", "30"])

    def alvo(self, **kwargs) -> c.ClassificacaoAnuncio:
        linhas = self.base() + anuncio_google("Anuncio-ALVO0001", **kwargs)
        return por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]

    def test_google_usa_cpa(self):
        alvo = self.alvo(custo="15")
        self.assertEqual(alvo.kpi_tipo, c.CPA)
        self.assertEqual(alvo.kpi_valor, Decimal(15))
        self.assertIsNone(alvo.result_type)

    def test_spend_zero_e_insuficiente(self):
        alvo = self.alvo(spend="0", conversoes="10")
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_SPEND_ZERO)

    def test_denominadores_um_e_dois_sao_insuficientes(self):
        for quantidade in ("1", "2"):
            with self.subTest(quantidade=quantidade):
                alvo = self.alvo(custo="10", conversoes=quantidade)
                self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
                self.assertEqual(alvo.motivo_codigo, c.MOTIVO_DENOMINADOR_BAIXO)

    def test_denominador_tres_ja_classifica(self):
        alvo = self.alvo(custo="15", conversoes="3")
        self.assertIn(alvo.status, c.STATUS_DE_DESEMPENHO)

    def test_dois_dias_sao_insuficientes(self):
        alvo = self.alvo(custo="15", dias=2)
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_POUCOS_DIAS)

    def test_tres_dias_ja_classificam(self):
        alvo = self.alvo(custo="15", dias=3)
        self.assertIn(alvo.status, c.STATUS_DE_DESEMPENHO)

    def test_sem_peers_e_insuficiente(self):
        alvo = por_anuncio(
            c.classificar_anuncios(anuncio_google("Anuncio-ALVO0001", custo="15"))
        )["Anuncio-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_SEM_PEERS)


class TestZeroResultado(unittest.TestCase):
    """A sensibilidade de 0,5x/2x vale antes do gate do denominador."""

    def classificar(self, multiplo: str) -> c.ClassificacaoAnuncio:
        # Os peers 10/20/30 fixam a mediana em 20.
        linhas = grupo_google(["10", "20", "30"])
        linhas += anuncio_google(
            "Anuncio-ALVO0001",
            conversoes="0",
            spend=Decimal(multiplo) * Decimal(20),
            dias=1,
        )
        return por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]

    def test_multiplicadores_nas_bordas(self):
        for multiplo, status, motivo in (
            ("0.4", c.DADOS_INSUFICIENTES, c.MOTIVO_ZERO_RESULT_GASTO_BAIXO),
            ("0.5", c.ATENCAO, c.MOTIVO_ZERO_RESULT_GASTO_RELEVANTE),
            ("1.99", c.ATENCAO, c.MOTIVO_ZERO_RESULT_GASTO_RELEVANTE),
            ("2", c.RUIM, c.MOTIVO_ZERO_RESULT_GASTO_ALTO),
            ("3", c.RUIM, c.MOTIVO_ZERO_RESULT_GASTO_ALTO),
        ):
            with self.subTest(multiplo=multiplo):
                alvo = self.classificar(multiplo)
                self.assertEqual(alvo.status, status)
                self.assertEqual(alvo.motivo_codigo, motivo)
                self.assertEqual(alvo.benchmark_origem, c.MESMO_GRUPO)

    def test_zero_sem_referencia_e_insuficiente(self):
        alvo = por_anuncio(
            c.classificar_anuncios(
                anuncio_google(
                    "Anuncio-ALVO0001", conversoes="0", spend="999", dias=1
                )
            )
        )["Anuncio-ALVO0001"]
        self.assertEqual(alvo.status, c.DADOS_INSUFICIENTES)
        self.assertEqual(alvo.motivo_codigo, c.MOTIVO_ZERO_RESULT_SEM_REFERENCIA)


class TestFiltrosEDeterminismo(unittest.TestCase):
    """Filtros limitam alvos, nunca o universo do benchmark."""

    def universo(self) -> list[dict]:
        linhas = grupo_google(["10", "20", "30"], grupo=GRUPO_A)
        linhas += anuncio_google("Anuncio-ALVO0001", custo="15", grupo=GRUPO_A)
        linhas += grupo_google(
            ["40", "50", "60"], prefixo="G2", grupo=GRUPO_B
        )
        linhas += grupo_google(
            ["70", "80", "90"],
            prefixo="C2",
            campanha=CAMPANHA_B,
            grupo=GRUPO_C,
        )
        return linhas

    def test_filtro_campanha_restringe_saida_sem_remover_peers(self):
        completo = por_anuncio(c.classificar_anuncios(self.universo()))
        filtrado = por_anuncio(
            c.classificar_anuncios(self.universo(), campanha_id=CAMPANHA_A)
        )
        self.assertEqual(completo["Anuncio-ALVO0001"], filtrado["Anuncio-ALVO0001"])
        self.assertTrue(all(item.campanha_id == CAMPANHA_A for item in filtrado.values()))

    def test_filtro_adset_restringe_saida_sem_remover_peers(self):
        completo = por_anuncio(c.classificar_anuncios(self.universo()))
        filtrado = por_anuncio(
            c.classificar_anuncios(self.universo(), adset_id=GRUPO_A)
        )
        self.assertEqual(completo["Anuncio-ALVO0001"], filtrado["Anuncio-ALVO0001"])
        self.assertTrue(all(item.adset_id == GRUPO_A for item in filtrado.values()))

    def test_filtros_conta_e_plataforma(self):
        linhas = self.universo() + grupo_result(
            ["10", "20", "30", "40"], conta=CONTA_B, campanha=CAMPANHA_C
        )
        resultado = c.classificar_anuncios(
            linhas, conta_id=CONTA_A, plataforma=m.GOOGLE
        )
        self.assertTrue(resultado)
        self.assertTrue(all(item.conta_id == CONTA_A for item in resultado))
        self.assertTrue(all(item.plataforma == m.GOOGLE for item in resultado))

    def test_ordem_de_entrada_nao_muda_resultado(self):
        linhas = self.universo()
        embaralhadas = list(linhas)
        random.Random(20260901).shuffle(embaralhadas)
        self.assertEqual(
            c.classificar_anuncios(linhas), c.classificar_anuncios(embaralhadas)
        )

    def test_saida_e_ordenada_pela_hierarquia(self):
        resultado = c.classificar_anuncios(self.universo())
        chaves = [
            (
                item.plataforma,
                item.conta_id,
                item.campanha_id,
                item.adset_id,
                item.anuncio_id,
            )
            for item in resultado
        ]
        self.assertEqual(chaves, sorted(chaves))

    def test_metricas_auxiliares_nao_mudam_status(self):
        linhas = self.universo()
        original = por_anuncio(c.classificar_anuncios(linhas))["Anuncio-ALVO0001"]
        alteradas = [dict(item) for item in linhas]
        for item in alteradas:
            if item["anuncio_id"] == "Anuncio-ALVO0001":
                item["impressions"] = Decimal("999999999")
                item["link_clicks"] = Decimal("1")
                item["reach"] = Decimal("987654")
                item["purchase_value"] = Decimal("999999")
                item["conversion_value"] = Decimal("888888")
        alterado = por_anuncio(c.classificar_anuncios(alteradas))["Anuncio-ALVO0001"]
        self.assertEqual(original, alterado)

    def test_motivo_nao_expoe_identificadores(self):
        for item in c.classificar_anuncios(self.universo()):
            self.assertNotIn(item.conta_id, item.motivo)
            self.assertNotIn(item.campanha_id, item.motivo)
            self.assertNotIn(item.adset_id, item.motivo)
            self.assertNotIn(item.anuncio_id, item.motivo)


class TestDemoClassificavelPorAnuncio(unittest.TestCase):
    """A demo versionada exercita hierarquia, estados e KPIs de anuncio."""

    @classmethod
    def setUpClass(cls):
        from dashboard import dados

        cls.conjunto = dados.carregar(
            dados.Fonte(
                dados.CAMINHO_DEMONSTRACAO,
                dados.MODO_DEMONSTRACAO,
            )
        )
        cls.anuncios = c.classificar_anuncios(cls.conjunto.linhas)
        cls.campanhas = c.classificar_campanhas(cls.conjunto.linhas)

    def test_hierarquia_tem_cenario_n1_e_n2(self):
        grupos: dict[tuple, set[str]] = defaultdict(set)
        campanhas: dict[tuple, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for linha_dataset in self.conjunto.linhas:
            chave_campanha = (
                linha_dataset["plataforma"],
                linha_dataset["conta_id"],
                linha_dataset["campanha_id"],
            )
            chave_grupo = chave_campanha + (linha_dataset["adset_id"],)
            grupos[chave_grupo].add(linha_dataset["anuncio_id"])
            campanhas[chave_campanha][linha_dataset["adset_id"]].add(
                linha_dataset["anuncio_id"]
            )

        self.assertGreaterEqual(max(map(len, grupos.values())), 4)
        self.assertTrue(
            any(
                sum(map(len, por_grupo.values())) >= 4
                and max(map(len, por_grupo.values())) < 4
                for por_grupo in campanhas.values()
            ),
            "falta campanha com quatro anuncios e grupos pequenos para N2",
        )

    def test_origens_n1_n2_e_indisponivel_aparecem(self):
        origens = Counter(item.benchmark_origem for item in self.anuncios)
        self.assertGreater(origens[c.MESMO_GRUPO], 0)
        self.assertGreater(origens[c.MESMA_CAMPANHA], 0)
        self.assertGreater(origens[c.INDISPONIVEL], 0)

    def test_todos_os_seis_estados_aparecem(self):
        estados = Counter(item.status for item in self.anuncios)
        for status in c.STATUS:
            with self.subTest(status=status):
                self.assertGreater(estados[status], 0)

    def test_meta_google_e_os_tres_kpis_sao_demonstrados(self):
        medidos = [
            item for item in self.anuncios if item.status in c.STATUS_DE_DESEMPENHO
        ]
        plataformas = Counter(item.plataforma for item in medidos)
        kpis = Counter(item.kpi_tipo for item in medidos)
        self.assertGreater(plataformas[m.META], 0)
        self.assertGreater(plataformas[m.GOOGLE], 0)
        self.assertGreater(kpis[c.CPR], 0)
        self.assertGreater(kpis[c.CPL], 0)
        self.assertGreater(kpis[c.CPA], 0)

    def test_zero_result_com_benchmark_emite_status(self):
        zeros = [
            item
            for item in self.anuncios
            if item.denominador == 0
            and item.benchmark_origem != c.INDISPONIVEL
        ]
        self.assertTrue(zeros)
        self.assertTrue(
            all(item.status in {c.ATENCAO, c.RUIM} for item in zeros)
        )

    def test_dados_insuficientes_tem_mais_de_um_motivo(self):
        motivos = {
            item.motivo_codigo
            for item in self.anuncios
            if item.status == c.DADOS_INSUFICIENTES
        }
        demonstraveis = {
            c.MOTIVO_DENOMINADOR_BAIXO,
            c.MOTIVO_POUCOS_DIAS,
            c.MOTIVO_SPEND_ZERO,
            c.MOTIVO_SEM_PEERS,
        }
        self.assertGreaterEqual(len(motivos & demonstraveis), 2)
        self.assertTrue(
            any(
                item.motivo_codigo == c.MOTIVO_SEM_PEERS
                and item.spend > 0
                and item.dias_ativos >= c.MIN_DIAS_ATIVOS
                and item.denominador is not None
                and item.denominador >= c.MIN_DENOMINADOR
                for item in self.anuncios
            ),
            "falta anuncio elegivel que falha N1 e N2 por ausencia de peers",
        )

    def test_nao_comparavel_preserva_limite_semantico(self):
        nao_comparaveis = [
            item for item in self.anuncios if item.status == c.NAO_COMPARAVEL
        ]
        self.assertTrue(nao_comparaveis)
        self.assertLessEqual(
            {item.motivo_codigo for item in nao_comparaveis},
            {
                c.MOTIVO_RESULT_INCOMPLETO,
                c.MOTIVO_MULTIPLOS_RESULT_TYPES,
                c.MOTIVO_JANELA_INCOMPATIVEL,
                c.MOTIVO_SEM_KPI_META,
            },
        )
        self.assertTrue(all(item.status != c.RUIM for item in nao_comparaveis))

    def test_motor_de_campanhas_continua_demonstravel(self):
        estados = Counter(item.status for item in self.campanhas)
        for status in c.STATUS:
            with self.subTest(status=status):
                self.assertGreater(estados[status], 0)

        meta = [item for item in self.campanhas if item.plataforma == m.META]
        google = [item for item in self.campanhas if item.plataforma == m.GOOGLE]
        origens_meta = Counter(item.benchmark_origem for item in meta)
        origens_google = Counter(item.benchmark_origem for item in google)
        self.assertGreater(origens_meta[c.MESMO_CLIENTE], 0)
        self.assertGreater(origens_meta[c.MESMO_TIPO_PORTFOLIO], 0)
        self.assertGreater(origens_google[c.MESMO_CLIENTE], 0)
        self.assertEqual(origens_google[c.MESMO_TIPO_PORTFOLIO], 0)


if __name__ == "__main__":
    unittest.main()
