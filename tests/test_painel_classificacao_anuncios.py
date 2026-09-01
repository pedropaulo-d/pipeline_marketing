"""Testes da apresentacao e integracao da classificacao de anuncios.

O motor possui sua propria suite. Aqui a fronteira protegida e outra: filtros
granulares limitam apenas a saida, a tabela nao recalcula KPI/benchmark e a
pagina apresenta os seis estados sem transformar ausencia de evidencia em
desempenho ruim.

Rodar:
    python -m unittest tests.test_painel_classificacao_anuncios
"""

import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from unittest import mock

from dashboard import classificacao as cl
from dashboard import dados, filtros
from dashboard import metricas as m
from dashboard import painel_classificacao as pc
from dashboard import painel_classificacao_anuncios as pca

from tests.test_classificacao_anuncios import (
    CAMPANHA_A,
    CAMPANHA_B,
    CONTA_A,
    GRUPO_A,
    GRUPO_B,
    TIPO_LEAD,
    anuncio_google,
    grupo_google,
    grupo_result,
    por_anuncio,
)

BASE_DIR = Path(__file__).resolve().parent.parent


def selecao_do_periodo(linhas: list[dict], **extra) -> filtros.Selecao:
    """Monta selecao que cobre integralmente a fixture."""
    datas = sorted({linha["data"] for linha in linhas})
    return filtros.Selecao(datas[0], datas[-1], **extra)


def campanha_n2() -> list[dict]:
    """Quatro anuncios na campanha, divididos em dois grupos de dois."""
    linhas = grupo_google(["10", "20"], prefixo="N2A", grupo=GRUPO_A)
    linhas += grupo_google(["30", "40"], prefixo="N2B", grupo=GRUPO_B)
    return linhas


class TestUniversoDaInterface(unittest.TestCase):
    """Campanha, grupo e anuncio nao podem destruir N1/N2."""

    def test_universo_da_conta_remove_filtros_granulares(self):
        linhas = grupo_google(["10", "20", "30", "40"])
        linhas += grupo_google(
            ["50", "60", "70", "80"],
            prefixo="OUT",
            campanha=CAMPANHA_B,
            grupo=GRUPO_B,
        )
        selecao = selecao_do_periodo(
            linhas,
            contas=(CONTA_A,),
            campanhas=(CAMPANHA_A,),
            adsets=(GRUPO_A,),
        )
        universo = filtros.universo_da_conta_no_periodo(
            linhas, selecao, CONTA_A
        )
        self.assertEqual(
            {linha["campanha_id"] for linha in universo},
            {CAMPANHA_A, CAMPANHA_B},
        )
        self.assertEqual(
            {linha["adset_id"] for linha in universo}, {GRUPO_A, GRUPO_B}
        )

    def test_filtro_visual_de_anuncio_preserva_n1(self):
        universo = grupo_google(["10", "20", "30", "40"])
        completo = por_anuncio(cl.classificar_anuncios(universo))
        anuncio = "Anuncio-PAR0000"
        alvo = pca.filtrar_alvos(
            list(completo.values()), anuncios=(anuncio,)
        )[0]
        self.assertEqual(alvo, completo[anuncio])
        self.assertEqual(alvo.benchmark_origem, cl.MESMO_GRUPO)
        self.assertEqual(alvo.benchmark_n, 3)

    def test_filtro_visual_de_adset_preserva_n2(self):
        universo = campanha_n2()
        completo = cl.classificar_anuncios(universo)
        alvo_original = por_anuncio(completo)["Anuncio-N2A0000"]
        filtrados = pca.filtrar_alvos(completo, adsets=(GRUPO_A,))
        alvo_filtrado = por_anuncio(filtrados)["Anuncio-N2A0000"]
        self.assertEqual(alvo_filtrado, alvo_original)
        self.assertEqual(alvo_filtrado.benchmark_origem, cl.MESMA_CAMPANHA)
        self.assertEqual(alvo_filtrado.benchmark_n, 3)

    def test_filtro_visual_de_campanha_nao_muda_benchmark(self):
        universo = grupo_google(["10", "20", "30", "40"])
        universo += grupo_google(
            ["50", "60", "70", "80"],
            prefixo="OUT",
            campanha=CAMPANHA_B,
            grupo=GRUPO_B,
        )
        completo = cl.classificar_anuncios(universo)
        filtrado = pca.filtrar_alvos(completo, campanhas=(CAMPANHA_A,))
        self.assertEqual(
            por_anuncio(filtrado)["Anuncio-PAR0000"],
            por_anuncio(completo)["Anuncio-PAR0000"],
        )

    def test_interface_nao_exibe_origem_cross_campaign(self):
        linhas = grupo_google(["10", "20", "30", "40"])
        registros = pca.linhas_tabela(cl.classificar_anuncios(linhas))
        referencias = " ".join(registro["Referência"] for registro in registros)
        self.assertNotIn("Mesmo cliente", referencias)
        self.assertNotIn("portfólio", referencias)


class TestResumoEFormatacao(unittest.TestCase):
    """A camada visual reaproveita os contratos aprovados das campanhas."""

    def test_resumo_existente_aceita_anuncios(self):
        classificacoes = cl.classificar_anuncios(
            grupo_google(["10", "20", "30", "40"])
        )
        resumo = cl.resumir_classificacoes(classificacoes)
        self.assertEqual(resumo["total"], 4)
        self.assertEqual(sum(resumo["por_status"].values()), 4)
        self.assertEqual(
            set(resumo["por_origem"]),
            {cl.MESMO_GRUPO, cl.MESMA_CAMPANHA, cl.INDISPONIVEL},
        )
        self.assertEqual(resumo["por_tendencia"][None], 4)

    def test_rotulos_e_icones_sao_os_mesmos_das_campanhas(self):
        classificacoes = cl.classificar_anuncios(
            grupo_google(["10", "20", "30", "40"])
        )
        resumo = cl.resumir_classificacoes(classificacoes)
        desempenho, contexto = pc.cartoes_resumo(resumo)
        rotulos = {cartao["rotulo"] for cartao in desempenho + contexto}
        for status in cl.STATUS:
            self.assertIn(
                f"{pc.ICONE_STATUS[status]} {pc.ROTULO_STATUS[status]}",
                rotulos,
            )

    def test_cartoes_sao_contagens_sem_score(self):
        resumo = cl.resumir_classificacoes(
            cl.classificar_anuncios(grupo_google(["10", "20", "30", "40"]))
        )
        grupos = pc.cartoes_resumo(resumo)
        for cartao in grupos[0] + grupos[1]:
            self.assertNotIn("%", cartao["valor"])
            self.assertNotIn("/100", cartao["valor"])

    def test_referencia_n1(self):
        item = cl.classificar_anuncios(
            grupo_google(["10", "20", "30", "40"])
        )[0]
        referencia = pca.formatar_referencia(item)
        self.assertIn("Grupo · N=3", referencia)
        self.assertNotIn("Mesmo grupo", referencia)
        self.assertIn("N=3", referencia)
        self.assertIn("R$", referencia)

    def test_referencia_n2(self):
        item = cl.classificar_anuncios(campanha_n2())[0]
        referencia = pca.formatar_referencia(item)
        self.assertIn("Campanha · N=3", referencia)
        self.assertNotIn("Mesma campanha", referencia)
        self.assertIn("N=3", referencia)

    def test_rotulo_compacto_nao_altera_origem_interna(self):
        n1 = cl.classificar_anuncios(
            grupo_google(["10", "20", "30", "40"])
        )[0]
        n2 = cl.classificar_anuncios(campanha_n2())[0]
        pca.formatar_referencia(n1)
        pca.formatar_referencia(n2)
        self.assertEqual(n1.benchmark_origem, cl.MESMO_GRUPO)
        self.assertEqual(n2.benchmark_origem, cl.MESMA_CAMPANHA)

    def test_kpi_tem_rotulo_humano(self):
        classificacoes = cl.classificar_anuncios(
            grupo_google(["10", "20", "30", "40"])
        )
        for registro in pca.linhas_tabela(classificacoes):
            self.assertEqual(registro["KPI"], "Custo por conversão")

    def test_result_type_reutiliza_mapa_canonico(self):
        item = cl.classificar_anuncios(
            grupo_result(["10", "20", "30", "40"], tipo=TIPO_LEAD)
        )[0]
        self.assertEqual(
            pca.tipo_de_resultado(item), pc.rotulo_tipo_resultado(TIPO_LEAD)
        )

    def test_tipo_desconhecido_nao_quebra(self):
        item = cl.classificar_anuncios(
            grupo_result(["10", "20", "30", "40"])
        )[0]
        futuro = replace(item, result_type="indicator_futuro")
        self.assertEqual(
            pca.tipo_de_resultado(futuro),
            pc.rotulo_tipo_resultado("indicator_futuro"),
        )

    def test_diferenca_preserva_sinal_do_motor(self):
        item = cl.classificar_anuncios(
            grupo_google(["10", "20", "30", "40"])
        )[0]
        registro = pca.linhas_tabela([item])[0]
        self.assertEqual(
            registro["Δ mediana"],
            pc.formatar_diferenca(item.diferenca_mediana_pct),
        )


class TestTabela(unittest.TestCase):
    """Colunas e ordenacao favorecem acao sem esconder explicabilidade."""

    @classmethod
    def setUpClass(cls):
        cls.demo = dados.carregar(
            dados.Fonte(dados.CAMINHO_DEMONSTRACAO, dados.MODO_DEMONSTRACAO)
        )
        cls.classificacoes = cl.classificar_anuncios(cls.demo.linhas)

    def test_todos_os_seis_estados_sao_formatados(self):
        estados = Counter(item.status for item in self.classificacoes)
        self.assertEqual(set(estados), set(cl.STATUS))
        registros = pca.linhas_tabela(self.classificacoes)
        self.assertEqual(len(registros), len(self.classificacoes))

    def test_problemas_aparecem_primeiro(self):
        ordenadas = pca.ordenar(self.classificacoes)
        posicao = {status: indice for indice, status in enumerate(pc.ORDEM_STATUS)}
        observadas = [posicao[item.status] for item in ordenadas]
        self.assertEqual(observadas, sorted(observadas))

    def test_tendencia_e_benchmark_nao_sao_colunas(self):
        colunas = pca.colunas_da_tabela(self.classificacoes)
        self.assertNotIn("Tendência", colunas)
        self.assertNotIn("Benchmark", colunas)
        self.assertIn("Referência", colunas)

    def test_motivo_e_sempre_a_ultima_coluna(self):
        colunas = pca.colunas_da_tabela(self.classificacoes)
        self.assertEqual(colunas[-1], "Motivo")
        self.assertTrue(
            all(registro["Motivo"] for registro in pca.linhas_tabela(
                self.classificacoes
            ))
        )

    def test_google_only_oculta_tipo_de_resultado(self):
        google = cl.classificar_anuncios(
            grupo_google(["10", "20", "30", "40"])
        )
        self.assertNotIn("Resultado", pca.colunas_da_tabela(google))

    def test_meta_result_exibe_tipo(self):
        meta = cl.classificar_anuncios(
            grupo_result(["10", "20", "30", "40"])
        )
        self.assertIn("Resultado", pca.colunas_da_tabela(meta))

    def test_uma_campanha_e_um_grupo_ocultam_contexto_repetido(self):
        grupo = cl.classificar_anuncios(
            grupo_google(["10", "20", "30", "40"])
        )
        colunas = pca.colunas_da_tabela(grupo)
        self.assertNotIn("Campanha", colunas)
        self.assertNotIn("Grupo", colunas)

    def test_multiplas_campanhas_e_grupos_exibem_contexto(self):
        colunas = pca.colunas_da_tabela(self.classificacoes)
        self.assertIn("Campanha", colunas)
        self.assertIn("Grupo", colunas)

    def test_cabecalhos_compactos_substituem_os_longos(self):
        colunas = pca.colunas_da_tabela(self.classificacoes)
        self.assertIn("Grupo", colunas)
        self.assertIn("Resultado", colunas)
        self.assertIn("Δ mediana", colunas)
        self.assertNotIn("Ad set/grupo", colunas)
        self.assertNotIn("Tipo de resultado", colunas)
        self.assertNotIn("Diferença vs. mediana", colunas)

    def test_motivo_recebe_a_maior_largura(self):
        self.assertEqual(pca.LARGURA_COLUNA["Motivo"], "large")
        for coluna in (
            "Anúncio", "Campanha", "Grupo", "Status", "KPI", "Valor",
            "Referência", "Δ mediana",
        ):
            with self.subTest(coluna=coluna):
                self.assertNotEqual(pca.LARGURA_COLUNA[coluna], "large")

    def test_classificacao_abre_a_pagina_antes_do_ranking(self):
        fonte = (BASE_DIR / "dashboard" / "app.py").read_text(encoding="utf-8")
        corpo = fonte.split("def pagina_anuncios", 1)[1].split(
            "# ── Composicao", 1
        )[0]
        self.assertLess(
            corpo.index("secao_classificacao_anuncios(dataset, selecao)"),
            corpo.index("pagina_ranking("),
        )


class TestAvisos(unittest.TestCase):
    """Avisos usam motivo_codigo, nunca parsing da mensagem."""

    def item(self):
        return cl.classificar_anuncios(
            grupo_google(["10", "20", "30", "40"])
        )[0]

    def test_result_incompleto_detectado_pelo_codigo(self):
        item = replace(
            self.item(),
            motivo_codigo=cl.MOTIVO_RESULT_INCOMPLETO,
            motivo="texto sem palavras reconheciveis",
        )
        self.assertTrue(
            pca.tem_motivo([item], cl.MOTIVO_RESULT_INCOMPLETO)
        )

    def test_texto_sem_codigo_nao_dispara_aviso(self):
        item = replace(
            self.item(),
            motivo_codigo=cl.MOTIVO_QUARTIL,
            motivo="result incompleto escrito apenas na frase",
        )
        self.assertFalse(
            pca.tem_motivo([item], cl.MOTIVO_RESULT_INCOMPLETO)
        )

    def test_sem_peers_e_neutro(self):
        self.assertIn("sem classificação", pca.NOTA_SEM_PEERS)
        self.assertIn("não compara anúncios entre campanhas", pca.NOTA_SEM_PEERS)
        self.assertNotIn("erro", pca.NOTA_SEM_PEERS.lower())

    def test_nao_comparavel_nao_e_desempenho_ruim(self):
        self.assertIn("não representa desempenho ruim", pca.AVISO_RESULT_INCOMPLETO)
        self.assertNotEqual(
            pc.ICONE_STATUS[cl.NAO_COMPARAVEL], pc.ICONE_STATUS[cl.RUIM]
        )

    def test_ajuda_explica_a_hierarquia_sem_ambiguidade(self):
        self.assertIn("primeiro tenta anúncios do mesmo grupo", pca.AJUDA)
        self.assertIn("tenta anúncios da mesma campanha", pca.AJUDA)
        self.assertIn("nunca compara anúncios entre campanhas", pca.AJUDA)


class TestDemoNaApresentacao(unittest.TestCase):
    """A demo aprovada sustenta cards, N1, N2 e tabela sem regeneracao."""

    @classmethod
    def setUpClass(cls):
        cls.dataset = dados.carregar(
            dados.Fonte(dados.CAMINHO_DEMONSTRACAO, dados.MODO_DEMONSTRACAO)
        )
        cls.classificacoes = cl.classificar_anuncios(cls.dataset.linhas)

    def test_contagens_aprovadas(self):
        resumo = cl.resumir_classificacoes(self.classificacoes)
        self.assertEqual(resumo["total"], 76)
        self.assertEqual(resumo["com_desempenho"], 23)
        self.assertEqual(
            resumo["por_status"],
            {
                cl.EXCELENTE: 8,
                cl.BOA: 3,
                cl.ATENCAO: 6,
                cl.RUIM: 6,
                cl.DADOS_INSUFICIENTES: 49,
                cl.NAO_COMPARAVEL: 4,
            },
        )

    def test_n1_e_n2_aparecem_na_referencia(self):
        referencias = {
            registro["Referência"]
            for registro in pca.linhas_tabela(self.classificacoes)
        }
        self.assertTrue(any("· Grupo · N=" in texto for texto in referencias))
        self.assertTrue(any("· Campanha · N=" in texto for texto in referencias))

    def test_todas_as_contas_sao_apresentaveis(self):
        contas = sorted({linha["conta_id"] for linha in self.dataset.linhas})
        self.assertEqual(len(contas), 7)
        for conta in contas:
            with self.subTest(conta=conta):
                universo = [
                    linha for linha in self.dataset.linhas
                    if linha["conta_id"] == conta
                ]
                itens = cl.classificar_anuncios(universo, conta_id=conta)
                self.assertTrue(itens)
                self.assertEqual(len(pca.linhas_tabela(itens)), len(itens))


class TestTelaStreamlit(unittest.TestCase):
    """Fumaca real da pagina Anuncios com todas as contas sinteticas."""

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
        self.patch_modo = mock.patch.dict(
            "os.environ", {dados.VARIAVEL_MODO: "demo"}, clear=False
        )
        self.patch_modo.start()
        self.addCleanup(self.patch_modo.stop)

    def _anuncios(self):
        app = self.AppTest.from_file(self.app, default_timeout=180).run()
        app.radio[0].set_value("Anuncios").run()
        return app

    @staticmethod
    def _texto(app) -> str:
        partes = [bloco.value for bloco in app.markdown]
        partes += [bloco.value for bloco in app.info]
        return " ".join(str(parte) for parte in partes)

    def test_sem_conta_exibe_estado_vazio(self):
        app = self._anuncios()
        self.assertEqual([erro.value for erro in app.exception], [])
        texto = self._texto(app)
        self.assertIn("Desempenho dos anúncios", texto)
        self.assertIn("Selecione um cliente", texto)

    def test_multiplas_contas_exibem_o_mesmo_estado_vazio(self):
        app = self._anuncios()
        contas = app.multiselect(key="filtro_contas").options[:2]
        app.multiselect(key="filtro_contas").set_value(contas).run()
        self.assertEqual([erro.value for erro in app.exception], [])
        self.assertIn("Selecione um cliente", self._texto(app))

    def test_uma_conta_exibe_cards_e_tabela(self):
        app = self._anuncios()
        conta = app.multiselect(key="filtro_contas").options[0]
        app.multiselect(key="filtro_contas").set_value([conta]).run()
        self.assertEqual([erro.value for erro in app.exception], [])
        self.assertNotIn("Selecione um cliente", self._texto(app))
        self.assertGreaterEqual(len(app.metric), 6)
        # Classificacao + detalhamento do ranking. O grafico e Plotly, nao
        # DataFrame, e o detalhe individual e composto por cards/serie.
        self.assertGreaterEqual(len(app.dataframe), 2)

    def test_todas_as_contas_da_demo_renderizam(self):
        app = self._anuncios()
        contas = app.multiselect(key="filtro_contas").options
        self.assertEqual(len(contas), 7)
        for conta in contas:
            with self.subTest(conta=conta):
                app.multiselect(key="filtro_contas").set_value([conta]).run()
                self.assertEqual([erro.value for erro in app.exception], [])


if __name__ == "__main__":
    unittest.main()
