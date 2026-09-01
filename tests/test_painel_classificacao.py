"""Testes da apresentacao da classificacao de campanhas.

O que esta suite protege
------------------------
1. **O universo do benchmark.** A secao exibe as campanhas de UMA conta, mas
   compara contra um universo maior. Ha teste que falha se alguem passar ao
   motor apenas as linhas ja filtradas pela conta — o erro seria invisivel na
   tela: a campanha simplesmente apareceria como "sem pares suficientes".
2. **Os rotulos de Resultado.** Cada `result_type` e um eixo de comparacao
   diferente; dois eixos com o mesmo nome levariam o leitor a comparar valores
   medidos contra referencias distintas.
3. **A deteccao por codigo, nunca por texto.** O aviso de cobertura parcial de
   Resultado sai de `motivo_codigo`. Ha teste que troca o texto do motivo e
   exige que o aviso continue; e outro que troca o codigo e exige que ele suma.
4. **Nenhuma regra na camada visual.** A apresentacao nao recalcula quartil,
   nao inverte sinal e nao fabrica mediana.

Sem dependencia nova: `unittest`, stdlib e os modulos do dashboard. Os testes
de tela usam `streamlit.testing` e sao pulados onde o Streamlit nao existe.

Rodar:
    python -m unittest tests.test_painel_classificacao
"""

import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from dashboard import classificacao as cl
from dashboard import dados, filtros
from dashboard import metricas as m
from dashboard import painel_classificacao as pc

from tests.test_classificacao import (
    CONTA_A,
    CONTA_B,
    CONTA_C,
    PRIMEIRO_DIA,
    TIPO_LEAD,
    TIPO_MENSAGEM,
    TIPO_THRUPLAY,
    campanha_google,
    campanha_lead,
    campanha_result,
    linha,
    pares_google,
    pares_result,
    por_campanha,
)

BASE_DIR = Path(__file__).resolve().parent.parent


def selecao_do_periodo(linhas: list[dict], **extra) -> filtros.Selecao:
    """Monta uma selecao cobrindo todas as datas das linhas informadas."""
    datas = sorted({registro["data"] for registro in linhas})
    return filtros.Selecao(data_inicio=datas[0], data_fim=datas[-1], **extra)


class TestRotulosDeResultado(unittest.TestCase):
    """Os dez indicadores reais, e o que acontece com o decimo primeiro."""

    REAIS = {
        "actions:offsite_conversion.fb_pixel_lead": "Lead (Pixel)",
        "actions:onsite_conversion.lead_grouped": "Lead (formulário)",
        "actions:onsite_conversion.messaging_conversation_started_7d":
            "Conversas iniciadas (7 dias)",
        "video_thruplay_watched_actions": "ThruPlay",
        "profile_visit_view": "Visitas ao perfil",
        "actions:post_engagement": "Engajamento com a publicação",
        "actions:omni_landing_page_view": "Visualizações da página de destino",
        "estimated_ad_recallers": "Lembrança do anúncio (estimada)",
        "reach": "Alcance (resultado Meta)",
        "actions:offsite_conversion.fb_pixel_purchase": "Compra (resultado Pixel)",
    }

    def test_os_dez_indicadores_reais_tem_rotulo(self):
        for tipo, esperado in self.REAIS.items():
            with self.subTest(tipo=tipo):
                self.assertEqual(pc.rotulo_tipo_resultado(tipo), esperado)

    def test_os_dois_leads_nao_colapsam(self):
        pixel = pc.rotulo_tipo_resultado(
            "actions:offsite_conversion.fb_pixel_lead"
        )
        formulario = pc.rotulo_tipo_resultado(
            "actions:onsite_conversion.lead_grouped"
        )
        self.assertNotEqual(pixel, formulario)

    def test_alcance_resultado_nao_se_confunde_com_a_metrica(self):
        rotulo = pc.rotulo_tipo_resultado("reach")
        self.assertIn("resultado Meta", rotulo)
        self.assertNotEqual(rotulo, m.CATALOGO["reach"].rotulo)

    def test_compra_resultado_nao_se_confunde_com_a_metrica(self):
        rotulo = pc.rotulo_tipo_resultado(
            "actions:offsite_conversion.fb_pixel_purchase"
        )
        self.assertIn("resultado Pixel", rotulo)
        self.assertNotEqual(rotulo, m.CATALOGO["purchases"].rotulo)

    def test_tipo_novo_nao_derruba_a_tela(self):
        rotulo = pc.rotulo_tipo_resultado("indicator_que_ainda_nao_existe")
        self.assertIn("não rotulado", rotulo)
        self.assertIn("indicator_que_ainda_nao_existe", rotulo)
        self.assertNotEqual(rotulo, m.INDISPONIVEL)

    def test_sem_tipo_devolve_vazio(self):
        self.assertEqual(pc.rotulo_tipo_resultado(None), "")
        self.assertEqual(pc.rotulo_tipo_resultado(""), "")

    def test_tipo_aparece_na_linha_quando_o_kpi_e_cpr(self):
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        tabela = {
            registro["Campanha"]: registro
            for registro in pc.linhas_tabela(cl.classificar_campanhas(linhas))
        }
        self.assertEqual(
            tabela["Campanha-ALVO0001"]["Tipo de resultado"],
            "Conversas iniciadas (7 dias)",
        )

    def test_conta_so_do_google_nao_exibe_a_coluna_de_tipo(self):
        # A fonte nao declara Resultado no Google: a coluna ficaria inteira em
        # `--` e so gastaria largura.
        classificacoes = cl.classificar_campanhas(
            pares_google(CONTA_A, [10, 20, 30, 40])
        )
        self.assertNotIn("Tipo de resultado", pc.colunas_da_tabela(classificacoes))
        for registro in pc.linhas_tabela(classificacoes):
            self.assertNotIn("Tipo de resultado", registro)

    def test_conta_meta_com_result_exibe_a_coluna(self):
        classificacoes = cl.classificar_campanhas(
            pares_result(CONTA_A, [10, 20, 30, 40])
        )
        self.assertIn("Tipo de resultado", pc.colunas_da_tabela(classificacoes))
        for registro in pc.linhas_tabela(classificacoes):
            self.assertEqual(
                registro["Tipo de resultado"], "Conversas iniciadas (7 dias)"
            )

    def test_conjunto_misto_mantem_a_coluna_com_traco_onde_falta(self):
        # Uma campanha com tipo basta: a coluna explica contra qual referencia
        # aquela linha foi medida, e quem nao tem tipo mostra `--`.
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        linhas += [
            *campanha_lead(CONTA_A, "Campanha-CPL00001", spend="100", leads="10"),
            *campanha_lead(CONTA_A, "Campanha-CPL00002", spend="200", leads="10"),
            *campanha_lead(CONTA_A, "Campanha-CPL00003", spend="300", leads="10"),
            *campanha_lead(CONTA_A, "Campanha-CPL00004", spend="400", leads="10"),
        ]
        classificacoes = cl.classificar_campanhas(linhas)
        self.assertIn("Tipo de resultado", pc.colunas_da_tabela(classificacoes))
        registros = {
            registro["Campanha"]: registro
            for registro in pc.linhas_tabela(classificacoes)
        }
        self.assertEqual(
            registros["Campanha-P0000000"]["Tipo de resultado"],
            "Conversas iniciadas (7 dias)",
        )
        self.assertEqual(
            registros["Campanha-CPL00001"]["Tipo de resultado"], m.INDISPONIVEL
        )

    def test_ocultar_a_coluna_nao_muda_a_classificacao(self):
        linhas = pares_google(CONTA_A, [10, 20, 30, 40])
        classificacoes = cl.classificar_campanhas(linhas)
        self.assertEqual(
            {(i.campanha_id, i.status, i.benchmark_origem, i.benchmark_n)
             for i in classificacoes},
            {(i.campanha_id, i.status, i.benchmark_origem, i.benchmark_n)
             for i in cl.classificar_campanhas(linhas)},
        )
        self.assertTrue(
            all(i.status in cl.STATUS_DE_DESEMPENHO for i in classificacoes)
        )


class TestFormatacao(unittest.TestCase):
    """Helpers puros de apresentacao."""

    def classificar(self, linhas, campanha="Campanha-ALVO0001"):
        return por_campanha(cl.classificar_campanhas(linhas))[campanha]

    def test_status_sempre_tem_texto(self):
        for status in cl.STATUS:
            with self.subTest(status=status):
                texto = pc.formatar_status(status)
                self.assertIn(pc.ROTULO_STATUS[status], texto)

    def test_nao_comparavel_nao_usa_vermelho(self):
        self.assertNotEqual(
            pc.ICONE_STATUS[cl.NAO_COMPARAVEL], pc.ICONE_STATUS[cl.RUIM]
        )
        self.assertNotEqual(
            pc.ICONE_STATUS[cl.DADOS_INSUFICIENTES], pc.ICONE_STATUS[cl.RUIM]
        )

    def test_diferenca_preserva_o_sinal(self):
        self.assertEqual(pc.formatar_diferenca(Decimal("-0.18")), "-18%")
        self.assertEqual(pc.formatar_diferenca(Decimal("0.32")), "+32%")
        self.assertEqual(pc.formatar_diferenca(Decimal(0)), "0%")
        self.assertEqual(pc.formatar_diferenca(None), m.INDISPONIVEL)

    def test_referencia_descreve_mediana_origem_e_n(self):
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        texto = pc.formatar_referencia(self.classificar(linhas))
        self.assertIn("R$", texto)
        self.assertIn("Mesmo cliente", texto)
        self.assertIn("N=4", texto)

    def test_referencia_indisponivel_nao_fabrica_mediana(self):
        linhas = campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="100", conversoes="10"
        )
        item = self.classificar(linhas)
        self.assertEqual(item.benchmark_origem, cl.INDISPONIVEL)
        self.assertEqual(pc.formatar_referencia(item), m.INDISPONIVEL)

    def test_ordem_coloca_problema_no_topo(self):
        self.assertEqual(pc.ORDEM_STATUS[0], cl.RUIM)
        self.assertEqual(pc.ORDEM_STATUS[1], cl.ATENCAO)
        self.assertEqual(pc.ORDEM_STATUS[-1], cl.NAO_COMPARAVEL)

    def test_ordenacao_e_deterministica(self):
        linhas = pares_result(CONTA_A, [10, 20, 30, 40, 50, 60])
        linhas += campanha_lead(CONTA_A, "Campanha-SKPI0001", spend="10", leads="0")
        classificacoes = cl.classificar_campanhas(linhas)
        primeira = pc.ordenar(classificacoes)
        segunda = pc.ordenar(list(reversed(classificacoes)))
        self.assertEqual(primeira, segunda)
        posicoes = [pc.ORDEM_STATUS.index(item.status) for item in primeira]
        self.assertEqual(posicoes, sorted(posicoes))

    def test_colunas_de_uma_plataforma_sem_tendencia(self):
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        registro = pc.linhas_tabela(cl.classificar_campanhas(linhas))[0]
        self.assertEqual(
            list(registro),
            [
                "Campanha", "Status", "KPI", "Tipo de resultado",
                "Valor", "Referência", "Diferença vs. mediana", "Motivo",
            ],
        )

    def test_tabela_nao_expoe_campo_interno(self):
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        for registro in pc.linhas_tabela(cl.classificar_campanhas(linhas)):
            texto = " ".join(str(valor) for valor in registro.values())
            for interno in ("motivo_codigo", "eixo_comparacao", "conta_id",
                            "benchmark_p25", "objective", "optimization_goal"):
                self.assertNotIn(interno, texto)

    def test_kpi_recebe_nome_legivel(self):
        self.assertEqual(pc.ROTULO_KPI[cl.CPR], "Custo por resultado")
        self.assertEqual(pc.ROTULO_KPI[cl.CPL], "Custo por lead")
        self.assertEqual(pc.ROTULO_KPI[cl.CPA], "Custo por conversão")

    def test_cartoes_separam_desempenho_de_contexto(self):
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        resumo = cl.resumir_classificacoes(cl.classificar_campanhas(linhas))
        desempenho, contexto = pc.cartoes_resumo(resumo)
        self.assertEqual(len(desempenho), 4)
        self.assertEqual(len(contexto), 2)
        rotulos = [cartao["rotulo"] for cartao in desempenho + contexto]
        for status in cl.STATUS:
            self.assertTrue(
                any(pc.ROTULO_STATUS[status] in rotulo for rotulo in rotulos)
            )

    def test_resumo_nao_produz_nota_media(self):
        # Contagem por status, e so. Score de conta esconderia a diferenca
        # entre carteira com problema e carteira sem evidencia.
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        resumo = cl.resumir_classificacoes(cl.classificar_campanhas(linhas))
        desempenho, contexto = pc.cartoes_resumo(resumo)
        for cartao in desempenho + contexto:
            self.assertNotIn("%", cartao["valor"])
            self.assertNotIn("/100", cartao["valor"])


class TestUniversoDoBenchmark(unittest.TestCase):
    """O recorte da tela nao pode encolher o grupo de comparacao."""

    def universo(self) -> list[dict]:
        # A conta alvo tem dois pares proprios (abaixo de tres) e depende do
        # portfolio do mesmo tipo em outras contas.
        linhas = pares_result(CONTA_A, [10, 20], prefixo="A")
        linhas += pares_result(CONTA_B, [30, 40, 50, 60], prefixo="B")
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        return linhas

    def test_universo_do_periodo_preserva_as_outras_contas(self):
        linhas = self.universo()
        selecao = selecao_do_periodo(linhas, contas=(CONTA_A,))
        universo = filtros.universo_do_periodo(linhas, selecao)
        self.assertEqual(
            {registro["conta_id"] for registro in universo}, {CONTA_A, CONTA_B}
        )
        # O recorte exibido continua sendo o da conta escolhida.
        self.assertEqual(
            {registro["conta_id"] for registro in filtros.aplicar(linhas, selecao)},
            {CONTA_A},
        )

    def test_portfolio_sobrevive_com_uma_conta_selecionada(self):
        linhas = self.universo()
        selecao = selecao_do_periodo(linhas, contas=(CONTA_A,))
        universo = filtros.universo_do_periodo(linhas, selecao)
        alvo = por_campanha(
            cl.classificar_campanhas(universo, conta_id=CONTA_A)
        )["Campanha-ALVO0001"]
        self.assertEqual(alvo.benchmark_origem, cl.MESMO_TIPO_PORTFOLIO)
        # Dois pares na propria conta e quatro na outra: o portfolio existe
        # exatamente porque o nivel do cliente ficou abaixo de tres.
        self.assertEqual(alvo.benchmark_n, 6)

    def test_passar_apenas_a_conta_destruiria_o_portfolio(self):
        # Este e o erro que o teste anterior existe para impedir. Se algum dia
        # a UI passar `filtros.aplicar(...)` em vez do universo, o resultado
        # vira este — e a campanha some da classificacao sem qualquer erro.
        linhas = self.universo()
        selecao = selecao_do_periodo(linhas, contas=(CONTA_A,))
        recortado = filtros.aplicar(linhas, selecao)
        alvo = por_campanha(
            cl.classificar_campanhas(recortado, conta_id=CONTA_A)
        )["Campanha-ALVO0001"]
        self.assertEqual(alvo.benchmark_origem, cl.INDISPONIVEL)
        self.assertEqual(alvo.status, cl.DADOS_INSUFICIENTES)

    def test_filtro_de_campanha_nao_encolhe_a_referencia(self):
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        selecao = selecao_do_periodo(
            linhas, contas=(CONTA_A,), campanhas=("Campanha-ALVO0001",)
        )
        universo = filtros.universo_do_periodo(linhas, selecao)
        alvo = por_campanha(
            cl.classificar_campanhas(universo, conta_id=CONTA_A)
        )["Campanha-ALVO0001"]
        self.assertEqual(alvo.benchmark_n, 4)
        self.assertEqual(alvo.benchmark_origem, cl.MESMO_CLIENTE)

    def test_filtro_de_adset_nao_altera_o_benchmark(self):
        linhas = pares_result(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_result(
            CONTA_A, "Campanha-ALVO0001", spend="100", resultados="10"
        )
        sem_adset = selecao_do_periodo(linhas, contas=(CONTA_A,))
        com_adset = replace(sem_adset, adsets=("AdSet-AAAA0001",))
        antes = cl.classificar_campanhas(
            filtros.universo_do_periodo(linhas, sem_adset), conta_id=CONTA_A
        )
        depois = cl.classificar_campanhas(
            filtros.universo_do_periodo(linhas, com_adset), conta_id=CONTA_A
        )
        self.assertEqual(antes, depois)

    def test_periodo_anterior_tem_a_mesma_duracao(self):
        inicio, fim = date(2026, 8, 19), date(2026, 8, 25)
        anterior_inicio, anterior_fim = m.periodo_anterior(inicio, fim)
        self.assertEqual(anterior_inicio, date(2026, 8, 12))
        self.assertEqual(anterior_fim, date(2026, 8, 18))
        self.assertEqual(
            (fim - inicio).days, (anterior_fim - anterior_inicio).days
        )


class TestGoogleNaTela(unittest.TestCase):
    """A decisao conservadora do Google precisa continuar visivel."""

    def test_conta_com_pares_classifica(self):
        linhas = pares_google(CONTA_A, [10, 20, 30, 40])
        linhas += campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="500", conversoes="10"
        )
        alvo = por_campanha(cl.classificar_campanhas(linhas))["Campanha-ALVO0001"]
        self.assertIn(alvo.status, cl.STATUS_DE_DESEMPENHO)
        self.assertEqual(
            pc.ROTULO_ORIGEM[alvo.benchmark_origem], "Mesmo cliente"
        )

    def test_conta_sem_pares_fica_sem_classificacao_e_gera_aviso(self):
        linhas = pares_google(CONTA_B, [10, 20, 30, 40, 50, 60], prefixo="B")
        linhas += campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="100", conversoes="10"
        )
        classificacoes = cl.classificar_campanhas(linhas, conta_id=CONTA_A)
        alvo = por_campanha(classificacoes)["Campanha-ALVO0001"]
        self.assertEqual(alvo.status, cl.DADOS_INSUFICIENTES)
        self.assertTrue(pc.tem_google_sem_pares(classificacoes))

    def test_nenhuma_linha_google_exibe_portfolio(self):
        linhas = pares_google(CONTA_A, [10, 20, 30, 40])
        linhas += pares_google(CONTA_B, [15, 25, 35, 45], prefixo="B")
        for item in cl.classificar_campanhas(linhas):
            self.assertNotEqual(item.benchmark_origem, cl.MESMO_TIPO_PORTFOLIO)
        # A origem agora e lida dentro da referencia, que e onde ela aparece.
        for registro in pc.linhas_tabela(cl.classificar_campanhas(linhas)):
            self.assertNotIn("Mesmo tipo no portfólio", registro["Referência"])


class TestAvisoDeCoberturaDeResultado(unittest.TestCase):
    """O aviso sai do codigo do motivo, nunca da frase."""

    def mista(self) -> list[dict]:
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
        return linhas

    def test_campanha_com_cobertura_parcial_nao_recebe_kpi(self):
        alvo = por_campanha(cl.classificar_campanhas(self.mista()))[
            "Campanha-ALVO0001"
        ]
        self.assertEqual(alvo.status, cl.NAO_COMPARAVEL)
        self.assertEqual(alvo.motivo_codigo, cl.MOTIVO_RESULT_INCOMPLETO)
        self.assertIsNone(alvo.kpi_valor)

    def test_aviso_aparece(self):
        self.assertTrue(
            pc.tem_result_incompleto(cl.classificar_campanhas(self.mista()))
        )

    def test_aviso_nao_depende_do_texto_do_motivo(self):
        classificacoes = [
            replace(item, motivo="frase completamente diferente")
            for item in cl.classificar_campanhas(self.mista())
        ]
        self.assertTrue(pc.tem_result_incompleto(classificacoes))

    def test_aviso_some_quando_o_codigo_muda(self):
        classificacoes = [
            replace(item, motivo_codigo=cl.MOTIVO_QUARTIL)
            for item in cl.classificar_campanhas(self.mista())
        ]
        self.assertFalse(pc.tem_result_incompleto(classificacoes))

    def test_texto_do_aviso_e_neutro(self):
        self.assertIn("não representa desempenho ruim", pc.AVISO_RESULT_INCOMPLETO)
        self.assertNotIn("erro", pc.AVISO_RESULT_INCOMPLETO.lower())
        # Nenhuma data de corte escrita na regra: a deteccao e por codigo.
        self.assertNotIn("2026", pc.AVISO_RESULT_INCOMPLETO)

    def test_modulo_nao_tem_data_de_corte_no_codigo(self):
        fonte = (BASE_DIR / "dashboard" / "painel_classificacao.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("2026-08-01", fonte)
        self.assertNotIn("date(", fonte)


class TestDemoNaTela(unittest.TestCase):
    """A demo versionada precisa produzir uma tela util."""

    @classmethod
    def setUpClass(cls):
        cls.conjunto = dados.carregar(dados.escolher_fonte(modo="demonstracao"))

    def test_ha_conta_com_classificacao_util(self):
        uteis = 0
        for conta in sorted({l["conta_id"] for l in self.conjunto.linhas}):
            classificacoes = cl.classificar_campanhas(
                self.conjunto.linhas, conta_id=conta
            )
            if any(
                item.status in cl.STATUS_DE_DESEMPENHO for item in classificacoes
            ):
                uteis += 1
        self.assertGreaterEqual(uteis, 3)

    def test_tabela_da_demo_nao_explode_em_nenhum_estado(self):
        classificacoes = cl.classificar_campanhas(self.conjunto.linhas)
        estados = {item.status for item in classificacoes}
        self.assertEqual(estados, set(cl.STATUS))
        registros = pc.linhas_tabela(classificacoes)
        self.assertEqual(len(registros), len(classificacoes))
        for registro in registros:
            self.assertTrue(registro["Status"])
            self.assertTrue(registro["Motivo"])

    def test_os_tres_cenarios_de_benchmark_aparecem_na_demo(self):
        classificacoes = cl.classificar_campanhas(self.conjunto.linhas)
        meta = [i for i in classificacoes if i.plataforma == m.META]
        google = [i for i in classificacoes if i.plataforma == m.GOOGLE]
        self.assertTrue(
            any(i.benchmark_origem == cl.MESMO_CLIENTE for i in meta)
        )
        self.assertTrue(
            any(i.benchmark_origem == cl.MESMO_TIPO_PORTFOLIO for i in meta)
        )
        self.assertTrue(
            any(i.benchmark_origem == cl.MESMO_CLIENTE for i in google)
        )
        self.assertFalse(
            any(i.benchmark_origem == cl.MESMO_TIPO_PORTFOLIO for i in google)
        )


class TestTelaDeClassificacao(unittest.TestCase):
    """Fumaca da secao no Streamlit, com o dataset de demonstracao."""

    @classmethod
    def setUpClass(cls):
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            raise unittest.SkipTest("streamlit nao instalado neste ambiente")
        if not dados.CAMINHO_DEMONSTRACAO.is_file():
            raise unittest.SkipTest("dataset de demonstracao nao gerado")
        cls.AppTest = AppTest
        cls.app = str(BASE_DIR / "dashboard" / "app.py")

    def setUp(self):
        # O modo precisa valer em TODAS as reexecucoes, nao so na primeira:
        # cada `.run()` reavalia o script, e sem a variavel ativa o painel
        # voltaria a escolher a superficie operacional no meio do teste.
        self.patch_modo = mock.patch.dict(
            "os.environ", {dados.VARIAVEL_MODO: "demo"}, clear=False
        )
        self.patch_modo.start()
        self.addCleanup(self.patch_modo.stop)

    def _campanhas(self):
        app = self.AppTest.from_file(self.app, default_timeout=180).run()
        app.radio[0].set_value("Campanhas").run()
        return app

    def _texto(self, app) -> str:
        partes = [bloco.value for bloco in app.markdown]
        partes += [bloco.value for bloco in app.info]
        return " ".join(str(parte) for parte in partes)

    def test_sem_conta_selecionada_pede_um_cliente(self):
        app = self._campanhas()
        self.assertEqual([erro.value for erro in app.exception], [])
        texto = self._texto(app)
        self.assertIn("Desempenho das campanhas", texto)
        self.assertIn("Selecione um cliente", texto)

    def test_com_uma_conta_a_secao_aparece(self):
        app = self._campanhas()
        contas = app.multiselect(key="filtro_contas").options
        app.multiselect(key="filtro_contas").set_value([contas[0]]).run()
        self.assertEqual([erro.value for erro in app.exception], [])
        texto = self._texto(app)
        self.assertNotIn("Selecione um cliente", texto)
        self.assertGreaterEqual(len(app.dataframe), 1)

    def test_todas_as_contas_da_demo_renderizam(self):
        app = self._campanhas()
        contas = app.multiselect(key="filtro_contas").options
        for conta in contas:
            with self.subTest(conta=conta):
                app.multiselect(key="filtro_contas").set_value([conta]).run()
                self.assertEqual([erro.value for erro in app.exception], [])


class TestColunasCondicionais(unittest.TestCase):
    """A tabela mostra o que este recorte precisa, e nada alem disso."""

    def meta(self) -> list[dict]:
        return pares_result(CONTA_A, [10, 20, 30, 40])

    def com_google(self) -> list[dict]:
        return self.meta() + pares_google(CONTA_A, [10, 20, 30, 40], prefixo="G")

    def com_tendencia(self):
        atual = pares_google(CONTA_A, [10, 20, 30, 40])
        atual += campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="800", conversoes="10"
        )
        anterior = campanha_google(
            CONTA_A,
            "Campanha-ALVO0001",
            spend="1000",
            conversoes="10",
            primeiro_dia=PRIMEIRO_DIA - timedelta(days=10),
        )
        return cl.classificar_campanhas(atual, linhas_periodo_anterior=anterior)

    def test_benchmark_nao_e_coluna_redundante(self):
        classificacoes = cl.classificar_campanhas(self.meta())
        colunas = pc.colunas_da_tabela(classificacoes)
        self.assertNotIn("Benchmark", colunas)
        # A origem continua visivel — dentro da referencia — e continua no
        # modelo, que e o que a UI e os testes consultam.
        registro = pc.linhas_tabela(classificacoes)[0]
        self.assertIn("Mesmo cliente", registro["Referência"])
        self.assertTrue(
            all(item.benchmark_origem for item in classificacoes)
        )

    def test_plataforma_some_quando_ha_so_uma(self):
        colunas = pc.colunas_da_tabela(cl.classificar_campanhas(self.meta()))
        self.assertNotIn("Plataforma", colunas)

    def test_plataforma_aparece_quando_ha_duas(self):
        classificacoes = cl.classificar_campanhas(self.com_google())
        colunas = pc.colunas_da_tabela(classificacoes)
        self.assertIn("Plataforma", colunas)
        # Logo depois da campanha: e o contexto de leitura da linha.
        self.assertEqual(colunas[1], "Plataforma")
        plataformas = {
            registro["Plataforma"] for registro in pc.linhas_tabela(classificacoes)
        }
        self.assertEqual(plataformas, {m.META, m.GOOGLE})

    def test_tendencia_some_quando_todas_sao_nulas(self):
        classificacoes = cl.classificar_campanhas(self.meta())
        self.assertTrue(all(item.tendencia is None for item in classificacoes))
        self.assertNotIn("Tendência", pc.colunas_da_tabela(classificacoes))

    def test_tendencia_aparece_quando_existe_alguma(self):
        classificacoes = self.com_tendencia()
        self.assertTrue(any(item.tendencia for item in classificacoes))
        colunas = pc.colunas_da_tabela(classificacoes)
        self.assertIn("Tendência", colunas)
        registros = {
            registro["Campanha"]: registro
            for registro in pc.linhas_tabela(classificacoes)
        }
        self.assertEqual(
            registros["Campanha-ALVO0001"]["Tendência"], "Melhorando"
        )

    def test_ocultar_coluna_nao_afrouxa_o_gate_de_tendencia(self):
        # A coluna some por estar vazia, nao porque o criterio mudou.
        atual = pares_google(CONTA_A, [10, 20, 30, 40])
        atual += campanha_google(
            CONTA_A, "Campanha-ALVO0001", spend="800", conversoes="10"
        )
        anterior = campanha_google(
            CONTA_A,
            "Campanha-ALVO0001",
            spend="1000",
            conversoes="9",
            primeiro_dia=PRIMEIRO_DIA - timedelta(days=10),
        )
        classificacoes = cl.classificar_campanhas(
            atual, linhas_periodo_anterior=anterior
        )
        self.assertTrue(all(item.tendencia is None for item in classificacoes))
        self.assertNotIn("Tendência", pc.colunas_da_tabela(classificacoes))

    def test_motivo_e_sempre_a_ultima_coluna(self):
        for classificacoes in (
            cl.classificar_campanhas(self.meta()),
            cl.classificar_campanhas(self.com_google()),
            self.com_tendencia(),
        ):
            with self.subTest(colunas=len(pc.colunas_da_tabela(classificacoes))):
                colunas = pc.colunas_da_tabela(classificacoes)
                self.assertEqual(colunas[-1], "Motivo")
                for registro in pc.linhas_tabela(classificacoes):
                    self.assertTrue(registro["Motivo"])

    def test_tabela_encolheu_em_relacao_ao_maximo(self):
        # Uma conta Meta com Resultado: oito colunas. Uma conta so do Google,
        # sem tipo e sem tendencia: sete.
        self.assertEqual(
            len(pc.colunas_da_tabela(cl.classificar_campanhas(self.meta()))), 8
        )
        self.assertEqual(
            len(
                pc.colunas_da_tabela(
                    cl.classificar_campanhas(
                        pares_google(CONTA_B, [10, 20, 30, 40], prefixo="S")
                    )
                )
            ),
            7,
        )
        self.assertLessEqual(
            len(pc.colunas_da_tabela(self.com_tendencia())), 10
        )


class TestAjudaEIcones(unittest.TestCase):
    """Explicabilidade do texto de ajuda e neutralidade dos icones."""

    def test_ajuda_explica_o_leave_one_out(self):
        self.assertIn("excluída do próprio grupo de referência", pc.AJUDA)
        self.assertIn("medianas ligeiramente", pc.AJUDA)

    def test_ajuda_mantem_os_demais_pontos(self):
        self.assertIn("semanticamente equivalente", pc.AJUDA)
        self.assertIn("quartis", pc.AJUDA)
        self.assertIn("Dados insuficientes", pc.AJUDA)
        self.assertIn("Não comparável", pc.AJUDA)
        self.assertIn("não significam desempenho", pc.AJUDA)
        # Ajuda curta: o expander nao pode virar capitulo de metodologia.
        self.assertLess(len(pc.AJUDA), 600)

    def test_icone_de_nao_comparavel_e_neutro_e_claro(self):
        icone = pc.ICONE_STATUS[cl.NAO_COMPARAVEL]
        self.assertNotEqual(icone, pc.ICONE_STATUS[cl.RUIM])
        self.assertNotEqual(icone, pc.ICONE_STATUS[cl.DADOS_INSUFICIENTES])
        # O icone escuro sumia no tema dark do painel.
        self.assertNotIn(icone, {"⚫", "🔴", "🟥"})

    def test_texto_do_status_continua_obrigatorio(self):
        texto = pc.formatar_status(cl.NAO_COMPARAVEL)
        self.assertIn("Não comparável", texto)


if __name__ == "__main__":
    unittest.main()
