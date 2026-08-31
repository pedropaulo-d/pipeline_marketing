"""Testes da camada de visualizacao.

O que esta suite protege
------------------------
1. **A fronteira de exposicao.** O dashboard so pode consumir a superficie
   pseudonimizada. Ha teste de codigo-fonte procurando driver de banco, SDK de
   plataforma e referencia a schema do DW nos modulos do painel, e teste de
   comportamento provando que arquivo com coluna de identidade real e
   recusado inteiro em vez de renderizado em parte.
2. **O contrato de dados.** Coluna faltando, fora de ordem, com sufixo
   proibido, com identificador fora do formato de pseudonimo ou com valor nao
   numerico aborta com mensagem legivel — nunca com stack trace, nunca em
   silencio.
3. **A aritmetica.** Divisao por zero devolve indisponivel, jamais `NaN`,
   `Infinity` ou `0`. Agregacao acontece em `Decimal`, e nao em `float`.
4. **Os filtros.** Hierarquia entre conta, campanha e ad set; todos ativos ao
   mesmo tempo; selecao residual descartada.

Sem dependencia nova: `unittest`, stdlib e os modulos do proprio dashboard,
que sao stdlib puro. Os testes de Plotly e Streamlit sao pulados onde as
bibliotecas nao existem — e o caso do container do ETL.

Rodar:
    python -m unittest discover -s tests -t .
"""

import csv
import importlib
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

from dashboard import contratos, dados, filtros, gerar_dados_demo
from dashboard import metricas as m

BASE_DIR = Path(__file__).resolve().parent.parent

CABECALHO = list(dados.COLUNAS_OBRIGATORIAS)
CABECALHO_RESULTADO = CABECALHO + list(dados.COLUNAS_RESULTADO_OPCIONAIS)

# Identificadores ficticios, no formato da superficie de exposicao. Nao saem
# de nenhuma entidade real nem da chave HMAC: sao literais de teste.
CONTA_A = "Cliente-AAAA1111"
CONTA_B = "Cliente-BBBB2222"
CAMPANHA_A1 = "Campanha-AAAA0001"
CAMPANHA_A2 = "Campanha-AAAA0002"
CAMPANHA_B1 = "Campanha-BBBB0001"
ADSET_A1 = "AdSet-AAAA0001"
ADSET_A2 = "AdSet-AAAA0002"
ADSET_B1 = "AdSet-BBBB0001"


def linha_csv(
    data_iso: str,
    plataforma: str,
    conta: str = CONTA_A,
    campanha: str = CAMPANHA_A1,
    adset: str = ADSET_A1,
    anuncio: str = "Anuncio-AAAA0001",
    spend: str = "100.00",
    impressions: str = "1000",
    link_clicks: str = "50",
    conversions: str = "5.5",
    conversion_value: str = "500.00",
    video_views: str = "10",
    reach: str = "0",
    profile_views: str = "0",
    purchases: str = "0",
    purchase_value: str = "0.00",
    versoes: tuple[int, int, int, int] = (1, 1, 1, 1),
) -> list[str]:
    """Monta uma linha do CSV de exposicao.

    Args:
        data_iso: Data em ISO.
        plataforma: Nome da plataforma.
        conta: Identificador pseudonimizado da conta.
        campanha: Identificador da campanha.
        adset: Identificador do ad set.
        anuncio: Identificador do anuncio.
        spend: Investimento.
        impressions: Impressoes.
        link_clicks: Cliques.
        conversions: Conversoes.
        conversion_value: Valor de conversao.
        video_views: Visualizacoes de video.
        reach: Alcance.
        profile_views: Visitas ao perfil.
        purchases: Compras.
        purchase_value: Valor monetario das compras (so Meta).
        versoes: Versoes SCD2 de conta, campanha, adset e anuncio.

    Returns:
        A linha, na ordem do contrato.
    """
    return [
        data_iso, plataforma,
        conta, str(versoes[0]),
        campanha, str(versoes[1]),
        adset, str(versoes[2]),
        anuncio, str(versoes[3]),
        spend, impressions, link_clicks, conversions, conversion_value,
        video_views, reach, profile_views, purchases, purchase_value,
    ]


def linha_csv_resultado(
    *args,
    result_type: str = "",
    result_count: str = "",
    result_attribution_window: str = "",
    cost_per_result: str = "",
    **kwargs,
) -> list[str]:
    """Monta a futura linha v3 sem mudar o fixture real da superficie v2."""
    return linha_csv(*args, **kwargs) + [
        result_type,
        result_count,
        result_attribution_window,
        cost_per_result,
    ]


def escrever_csv(diretorio: Path, linhas: list[list[str]],
                 cabecalho: list[str] | None = None) -> Path:
    """Grava um CSV de teste.

    Args:
        diretorio: Diretorio de destino.
        linhas: Linhas de dados.
        cabecalho: Cabecalho alternativo; o do contrato quando omitido.

    Returns:
        Caminho do arquivo gravado.
    """
    buffer = io.StringIO(newline="")
    escritor = csv.writer(buffer, lineterminator="\n")
    escritor.writerow(cabecalho if cabecalho is not None else CABECALHO)
    for linha in linhas:
        escritor.writerow(linha)
    caminho = diretorio / "metricas.csv"
    caminho.write_text(buffer.getvalue(), encoding="utf-8")
    return caminho


def carregar(linhas: list[list[str]], cabecalho: list[str] | None = None,
             modo: str = dados.MODO_DEMONSTRACAO) -> dados.Dataset:
    """Grava e carrega um CSV temporario.

    Args:
        linhas: Linhas de dados.
        cabecalho: Cabecalho alternativo.
        modo: Modo atribuido a fonte.

    Returns:
        O dataset carregado.
    """
    with tempfile.TemporaryDirectory() as pasta:
        caminho = escrever_csv(Path(pasta), linhas, cabecalho)
        return dados.carregar(dados.Fonte(caminho, modo))


class TestCarregamento(unittest.TestCase):
    """O dataset e lido, tipado e resumido corretamente."""

    def test_carrega_e_tipa_as_colunas(self):
        dataset = carregar([linha_csv("2026-06-01", "Meta Ads")])
        (linha,) = dataset.linhas
        self.assertEqual(linha["data"], date(2026, 6, 1))
        self.assertEqual(linha["plataforma"], "Meta Ads")
        self.assertEqual(linha["conta_versao"], 1)
        self.assertIsInstance(linha["spend"], Decimal)
        self.assertEqual(linha["spend"], Decimal("100.00"))

    def test_conversao_fracionaria_preserva_a_escala(self):
        # Truncar `conversions` ja custou ~1% das conversoes no ETL legado.
        dataset = carregar(
            [linha_csv("2026-06-01", "Google Ads", conversions="8.228458")]
        )
        self.assertEqual(dataset.linhas[0]["conversions"], Decimal("8.228458"))

    def test_celula_vazia_de_metrica_vira_zero(self):
        linha = linha_csv("2026-06-01", "Meta Ads")
        linha[CABECALHO.index("reach")] = ""
        dataset = carregar([linha])
        self.assertEqual(dataset.linhas[0]["reach"], Decimal(0))

    def test_resumo_conta_entidades_e_intervalo(self):
        dataset = carregar([
            linha_csv("2026-06-01", "Meta Ads"),
            linha_csv("2026-06-03", "Google Ads", conta=CONTA_B,
                      campanha=CAMPANHA_B1, adset=ADSET_B1,
                      anuncio="Anuncio-BBBB0001"),
        ])
        resumo = dados.resumo(dataset)
        self.assertEqual(resumo["linhas"], 2)
        self.assertEqual(resumo["dias"], 2)
        self.assertEqual(resumo["contas"], 2)
        self.assertEqual(resumo["data_min"], date(2026, 6, 1))
        self.assertEqual(resumo["data_max"], date(2026, 6, 3))
        self.assertEqual(resumo["plataformas"], ["Google Ads", "Meta Ads"])

    def test_manifesto_vizinho_e_lido_quando_existe(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = escrever_csv(
                Path(pasta), [linha_csv("2026-06-01", "Meta Ads")]
            )
            (Path(pasta) / "manifesto.json").write_text(
                '{"linhas": 1, "gerado_em": "2026-06-02T00:00:00+00:00"}',
                encoding="utf-8",
            )
            dataset = dados.carregar(
                dados.Fonte(caminho, dados.MODO_DEMONSTRACAO)
            )
        self.assertEqual(dataset.manifesto["linhas"], 1)

    def test_manifesto_ausente_nao_impede_o_carregamento(self):
        dataset = carregar([linha_csv("2026-06-01", "Meta Ads")])
        self.assertEqual(dataset.manifesto, {})


class TestContratoDeSchema(unittest.TestCase):
    """Schema incompativel aborta com mensagem, nunca em silencio."""

    def test_coluna_obrigatoria_ausente_e_nomeada_no_erro(self):
        cabecalho = [c for c in CABECALHO if c != "conversions"]
        linha = linha_csv("2026-06-01", "Meta Ads")
        del linha[CABECALHO.index("conversions")]
        with self.assertRaises(dados.ContratoInvalido) as erro:
            carregar([linha], cabecalho=cabecalho)
        self.assertIn("conversions", str(erro.exception))

    def test_ordem_diferente_do_contrato_e_recusada(self):
        cabecalho = list(CABECALHO)
        cabecalho[1], cabecalho[2] = cabecalho[2], cabecalho[1]
        linha = linha_csv("2026-06-01", "Meta Ads")
        linha[1], linha[2] = linha[2], linha[1]
        with self.assertRaises(dados.ContratoInvalido) as erro:
            carregar([linha], cabecalho=cabecalho)
        self.assertIn("ordem", str(erro.exception).lower())

    def test_coluna_extra_e_ignorada_e_reportada(self):
        # Coluna nova na origem nao vira coluna nova no dashboard.
        cabecalho = CABECALHO + ["landing_page_id"]
        linha = linha_csv("2026-06-01", "Meta Ads") + ["abc"]
        dataset = carregar([linha], cabecalho=cabecalho)
        self.assertEqual(dataset.colunas_ignoradas, ("landing_page_id",))
        self.assertNotIn("landing_page_id", dataset.linhas[0])

    def test_arquivo_sem_cabecalho_e_recusado(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "metricas.csv"
            caminho.write_text("", encoding="utf-8")
            with self.assertRaises(dados.ContratoInvalido):
                dados.carregar(
                    dados.Fonte(caminho, dados.MODO_DEMONSTRACAO)
                )

    def test_data_invalida_aponta_a_linha(self):
        with self.assertRaises(dados.ContratoInvalido) as erro:
            carregar([linha_csv("01/06/2026", "Meta Ads")])
        self.assertIn("linha 2", str(erro.exception))

    def test_metrica_nao_numerica_e_recusada(self):
        with self.assertRaises(dados.ContratoInvalido) as erro:
            carregar([linha_csv("2026-06-01", "Meta Ads", spend="mil reais")])
        self.assertIn("spend", str(erro.exception))

    def test_versao_scd2_invalida_e_recusada(self):
        with self.assertRaises(dados.ContratoInvalido):
            carregar([linha_csv("2026-06-01", "Meta Ads", versoes=(0, 1, 1, 1))])

    def test_linha_com_numero_errado_de_campos_e_recusada(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "metricas.csv"
            caminho.write_text(
                ",".join(CABECALHO) + "\n2026-06-01,Meta Ads\n",
                encoding="utf-8",
            )
            with self.assertRaises(dados.ContratoInvalido):
                dados.carregar(
                    dados.Fonte(caminho, dados.MODO_DEMONSTRACAO)
                )


class TestFronteiraDeExposicao(unittest.TestCase):
    """Nenhum campo identificavel conhecido pode entrar no dashboard."""

    def test_contrato_nao_declara_campo_identificavel(self):
        for coluna in dados.COLUNAS_OBRIGATORIAS:
            for sufixo in dados.SUFIXOS_PROIBIDOS:
                self.assertFalse(
                    coluna.endswith(sufixo),
                    f"{coluna} termina em sufixo proibido {sufixo}",
                )

    def test_coluna_de_nome_real_recusa_o_arquivo_inteiro(self):
        for proibida in ("conta_nome", "campanha_nome", "adset_nome",
                         "anuncio_nome"):
            with self.subTest(coluna=proibida):
                cabecalho = CABECALHO + [proibida]
                linha = linha_csv("2026-06-01", "Meta Ads") + ["Empresa X"]
                with self.assertRaises(dados.ContratoInvalido) as erro:
                    carregar([linha], cabecalho=cabecalho)
                self.assertIn(proibida, str(erro.exception))

    def test_coluna_de_external_id_recusa_o_arquivo_inteiro(self):
        cabecalho = CABECALHO + ["conta_external_id"]
        linha = linha_csv("2026-06-01", "Meta Ads") + ["act_123"]
        with self.assertRaises(dados.ContratoInvalido):
            carregar([linha], cabecalho=cabecalho)

    def test_chave_natural_e_substituta_recusam_o_arquivo(self):
        for proibida in ("campanha_nk", "campanha_sk"):
            with self.subTest(coluna=proibida):
                cabecalho = CABECALHO + [proibida]
                linha = linha_csv("2026-06-01", "Meta Ads") + ["deadbeef"]
                with self.assertRaises(dados.ContratoInvalido):
                    carregar([linha], cabecalho=cabecalho)

    def test_identificador_fora_do_formato_de_pseudonimo_e_recusado(self):
        # Um nome real escondido numa celula de identificador nao passa.
        with self.assertRaises(dados.ContratoInvalido) as erro:
            carregar([linha_csv("2026-06-01", "Meta Ads",
                                conta="Clinica Exemplo Ltda")])
        self.assertIn("conta_id", str(erro.exception))

    def test_plataforma_com_texto_livre_longo_e_recusada(self):
        with self.assertRaises(dados.ContratoInvalido):
            carregar([linha_csv(
                "2026-06-01",
                "Meta Ads - conta da Clinica Exemplo de Sao Paulo",
            )])

    def test_mensagem_de_erro_nao_reproduz_o_valor_recusado(self):
        with self.assertRaises(dados.ContratoInvalido) as erro:
            carregar([linha_csv("2026-06-01", "Meta Ads",
                                conta="Clinica Exemplo Ltda")])
        self.assertNotIn("Clinica", str(erro.exception))

    def test_modulos_do_dashboard_nao_importam_banco_nem_sdk(self):
        # A fronteira e estrutural: nao ha como o painel falar com o DW ou com
        # as APIs porque o codigo nao carrega nenhuma biblioteca capaz disso.
        proibidos = (
            "psycopg2", "sqlalchemy", "google.ads", "google_ads",
            "facebook_business", "requests", "httpx", "dbt",
        )
        for arquivo in sorted(Path(BASE_DIR / "dashboard").glob("*.py")):
            fonte = arquivo.read_text(encoding="utf-8")
            importados = re.findall(
                r"^\s*(?:import|from)\s+([\w.]+)", fonte, re.MULTILINE
            )
            for modulo in importados:
                for proibido in proibidos:
                    self.assertFalse(
                        modulo == proibido or modulo.startswith(proibido + "."),
                        f"{arquivo.name} importa {modulo}",
                    )

    def test_dashboard_nao_executa_sql(self):
        # A docstring de `app.py` desenha a arquitetura e cita a view oficial;
        # o que nao pode existir e consulta contra ela.
        padrao = re.compile(
            r"\bselect\b[\s\S]{0,300}?\bfrom\b\s+\w+\s*\.", re.IGNORECASE
        )
        for arquivo in sorted(Path(BASE_DIR / "dashboard").glob("*.py")):
            with self.subTest(arquivo=arquivo.name):
                self.assertIsNone(
                    padrao.search(arquivo.read_text(encoding="utf-8"))
                )

    def test_entrada_de_dados_nao_menciona_schema_do_data_warehouse(self):
        # `dados.py` e a unica porta de entrada de dado do painel.
        fonte = (BASE_DIR / "dashboard" / "dados.py").read_text(
            encoding="utf-8"
        )
        for schema in ("bronze.", "silver.", "gold.", "raw_ads"):
            with self.subTest(schema=schema):
                self.assertNotIn(schema, fonte)

    def test_gerador_de_demo_nao_usa_a_chave_de_pseudonimizacao(self):
        fonte = (BASE_DIR / "dashboard" / "gerar_dados_demo.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("import pseudonimos", fonte)
        self.assertNotIn("PSEUDONIMIZACAO_CHAVE", fonte)


class TestEscolhaDeFonte(unittest.TestCase):
    """A origem do dado e escolhida sem nunca cair no banco."""

    def test_prefere_a_superficie_de_exposicao_quando_existe(self):
        with tempfile.TemporaryDirectory() as pasta:
            real = Path(pasta) / "real.csv"
            real.write_text("x", encoding="utf-8")
            demo = Path(pasta) / "demo.csv"
            demo.write_text("x", encoding="utf-8")
            with mock.patch.object(dados, "CAMINHO_PSEUDONIMIZADO", real), \
                 mock.patch.object(dados, "CAMINHO_DEMONSTRACAO", demo), \
                 mock.patch.dict("os.environ", {}, clear=True):
                fonte = dados.escolher_fonte()
        self.assertEqual(fonte.modo, dados.MODO_PSEUDONIMIZADO)

    def test_cai_na_demonstracao_quando_nao_ha_superficie(self):
        with tempfile.TemporaryDirectory() as pasta:
            real = Path(pasta) / "nao_existe.csv"
            demo = Path(pasta) / "demo.csv"
            demo.write_text("x", encoding="utf-8")
            with mock.patch.object(dados, "CAMINHO_PSEUDONIMIZADO", real), \
                 mock.patch.object(dados, "CAMINHO_DEMONSTRACAO", demo), \
                 mock.patch.dict("os.environ", {}, clear=True):
                fonte = dados.escolher_fonte()
        self.assertEqual(fonte.modo, dados.MODO_DEMONSTRACAO)

    def test_modo_demo_forca_o_dataset_sintetico(self):
        with tempfile.TemporaryDirectory() as pasta:
            real = Path(pasta) / "real.csv"
            real.write_text("x", encoding="utf-8")
            demo = Path(pasta) / "demo.csv"
            demo.write_text("x", encoding="utf-8")
            with mock.patch.object(dados, "CAMINHO_PSEUDONIMIZADO", real), \
                 mock.patch.object(dados, "CAMINHO_DEMONSTRACAO", demo):
                fonte = dados.escolher_fonte(modo="demo")
        self.assertEqual(fonte.modo, dados.MODO_DEMONSTRACAO)

    def test_sem_nenhuma_fonte_levanta_contrato_invalido(self):
        with tempfile.TemporaryDirectory() as pasta:
            with mock.patch.object(
                dados, "CAMINHO_PSEUDONIMIZADO", Path(pasta) / "a.csv"
            ), mock.patch.object(
                dados, "CAMINHO_DEMONSTRACAO", Path(pasta) / "b.csv"
            ), mock.patch.dict("os.environ", {}, clear=True):
                with self.assertRaises(dados.ContratoInvalido):
                    dados.escolher_fonte()

    def test_rotulo_do_modo_e_explicito_na_interface(self):
        self.assertEqual(
            dados.ROTULO_MODO[dados.MODO_DEMONSTRACAO],
            "DADOS DE DEMONSTRACAO",
        )
        self.assertEqual(
            dados.ROTULO_MODO[dados.MODO_PSEUDONIMIZADO],
            "DADOS PSEUDONIMIZADOS",
        )


class TestFiltros(unittest.TestCase):
    """Periodo, plataforma e hierarquia, todos ativos ao mesmo tempo."""

    def setUp(self):
        self.dataset = carregar([
            linha_csv("2026-06-01", "Meta Ads", conta=CONTA_A,
                      campanha=CAMPANHA_A1, adset=ADSET_A1,
                      anuncio="Anuncio-AAAA0001"),
            linha_csv("2026-06-02", "Meta Ads", conta=CONTA_A,
                      campanha=CAMPANHA_A2, adset=ADSET_A2,
                      anuncio="Anuncio-AAAA0002"),
            linha_csv("2026-06-03", "Google Ads", conta=CONTA_B,
                      campanha=CAMPANHA_B1, adset=ADSET_B1,
                      anuncio="Anuncio-BBBB0001"),
        ])
        self.linhas = self.dataset.linhas

    def test_periodo_recorta_pelos_extremos_inclusive(self):
        selecao = filtros.Selecao(date(2026, 6, 2), date(2026, 6, 3))
        resultado = filtros.aplicar(self.linhas, selecao)
        self.assertEqual(
            [l["data"] for l in resultado],
            [date(2026, 6, 2), date(2026, 6, 3)],
        )

    def test_selecao_inicial_de_dataset_curto_cobre_tudo(self):
        # Tres dias de calendario: menos que a janela padrao de sete, entao a
        # selecao inicial abre o dataset inteiro.
        selecao = filtros.selecao_inicial(self.linhas)
        self.assertEqual(selecao.data_inicio, date(2026, 6, 1))
        self.assertEqual(selecao.data_fim, date(2026, 6, 3))
        self.assertEqual(filtros.aplicar(self.linhas, selecao), self.linhas)

    def test_filtro_de_plataforma(self):
        selecao = filtros.Selecao(
            date(2026, 6, 1), date(2026, 6, 3), plataformas=("Meta Ads",)
        )
        resultado = filtros.aplicar(self.linhas, selecao)
        self.assertEqual(len(resultado), 2)
        self.assertEqual({l["plataforma"] for l in resultado}, {"Meta Ads"})

    def test_filtros_atuam_simultaneamente(self):
        selecao = filtros.Selecao(
            date(2026, 6, 1), date(2026, 6, 3),
            plataformas=("Meta Ads",),
            contas=(CONTA_A,),
            campanhas=(CAMPANHA_A2,),
            adsets=(ADSET_A2,),
        )
        resultado = filtros.aplicar(self.linhas, selecao)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["anuncio_id"], "Anuncio-AAAA0002")

    def test_selecao_vazia_num_nivel_significa_todos(self):
        selecao = filtros.Selecao(date(2026, 6, 1), date(2026, 6, 3))
        self.assertEqual(len(filtros.aplicar(self.linhas, selecao)), 3)

    def test_opcoes_de_campanha_respeitam_a_conta(self):
        selecao = filtros.Selecao(
            date(2026, 6, 1), date(2026, 6, 3), contas=(CONTA_A,)
        )
        opcoes = filtros.opcoes(self.linhas, selecao)
        self.assertEqual(opcoes["campanhas"], [CAMPANHA_A1, CAMPANHA_A2])
        self.assertNotIn(CAMPANHA_B1, opcoes["campanhas"])

    def test_opcoes_de_adset_respeitam_a_campanha(self):
        selecao = filtros.Selecao(
            date(2026, 6, 1), date(2026, 6, 3),
            contas=(CONTA_A,), campanhas=(CAMPANHA_A1,),
        )
        opcoes = filtros.opcoes(self.linhas, selecao)
        self.assertEqual(opcoes["adsets"], [ADSET_A1])

    def test_opcoes_de_conta_respeitam_a_plataforma(self):
        selecao = filtros.Selecao(
            date(2026, 6, 1), date(2026, 6, 3), plataformas=("Google Ads",)
        )
        opcoes = filtros.opcoes(self.linhas, selecao)
        self.assertEqual(opcoes["contas"], [CONTA_B])

    def test_opcoes_respeitam_o_periodo(self):
        selecao = filtros.Selecao(date(2026, 6, 1), date(2026, 6, 1))
        opcoes = filtros.opcoes(self.linhas, selecao)
        self.assertEqual(opcoes["plataformas"], ["Meta Ads"])
        self.assertEqual(opcoes["contas"], [CONTA_A])

    def test_sanear_descarta_selecao_que_deixou_de_ser_valida(self):
        # Campanha da conta B com a conta A selecionada: residuo de escolha
        # anterior, que produziria recorte vazio sem explicacao.
        selecao = filtros.Selecao(
            date(2026, 6, 1), date(2026, 6, 3),
            contas=(CONTA_A,), campanhas=(CAMPANHA_B1,),
        )
        limpa = filtros.sanear(self.linhas, selecao)
        self.assertEqual(limpa.campanhas, ())
        self.assertEqual(limpa.contas, (CONTA_A,))
        self.assertEqual(len(filtros.aplicar(self.linhas, limpa)), 2)

    def test_sanear_descarta_plataforma_fora_do_periodo(self):
        selecao = filtros.Selecao(
            date(2026, 6, 1), date(2026, 6, 1), plataformas=("Google Ads",)
        )
        limpa = filtros.sanear(self.linhas, selecao)
        self.assertEqual(limpa.plataformas, ())

    def test_aplicar_em_periodo_preserva_os_filtros_de_entidade(self):
        selecao = filtros.Selecao(
            date(2026, 6, 3), date(2026, 6, 3), plataformas=("Meta Ads",)
        )
        resultado = filtros.aplicar_em_periodo(
            self.linhas, selecao, date(2026, 6, 1), date(2026, 6, 2)
        )
        self.assertEqual(len(resultado), 2)
        self.assertEqual({l["plataforma"] for l in resultado}, {"Meta Ads"})


class TestPeriodoPadrao(unittest.TestCase):
    """A janela aberta por padrao sao os ultimos sete dias DO DATASET.

    A ancora e `max(data)` do arquivo, nunca o relogio: o artefato e um
    recorte historico, e ancorar em `date.today()` abriria o painel vazio no
    dia seguinte e produziria screenshot diferente a cada execucao.
    """

    def test_dataset_longo_abre_nos_ultimos_sete_dias(self):
        linhas = carregar([
            linha_csv(f"2026-06-{dia:02d}", "Meta Ads",
                      anuncio=f"Anuncio-AAAA{dia:04d}")
            for dia in range(1, 29)
        ]).linhas
        self.assertEqual(
            filtros.periodo_padrao(linhas),
            (date(2026, 6, 22), date(2026, 6, 28)),
        )

    def test_janela_tem_exatamente_sete_dias_de_calendario(self):
        linhas = carregar([
            linha_csv(f"2026-06-{dia:02d}", "Meta Ads",
                      anuncio=f"Anuncio-AAAA{dia:04d}")
            for dia in range(1, 29)
        ]).linhas
        inicio, fim = filtros.periodo_padrao(linhas)
        self.assertEqual((fim - inicio).days + 1, filtros.JANELA_PADRAO_DIAS)

    def test_dataset_com_menos_de_sete_dias_abre_inteiro(self):
        linhas = carregar([
            linha_csv("2026-06-01", "Meta Ads"),
            linha_csv("2026-06-02", "Meta Ads", anuncio="Anuncio-AAAA0002"),
            linha_csv("2026-06-03", "Meta Ads", anuncio="Anuncio-AAAA0003"),
        ]).linhas
        self.assertEqual(
            filtros.periodo_padrao(linhas),
            (date(2026, 6, 1), date(2026, 6, 3)),
        )

    def test_lacuna_no_calendario_nao_estica_a_janela(self):
        # Caso real do artefato: um dia isolado meses antes do bloco recente.
        # A janela continua sendo de sete dias de calendario a partir do
        # ultimo dia, e o dia isolado fica de fora.
        linhas = carregar(
            [linha_csv("2026-04-07", "Meta Ads", anuncio="Anuncio-AAAA9999")]
            + [
                linha_csv(f"2026-08-{dia:02d}", "Meta Ads",
                          anuncio=f"Anuncio-AAAA{dia:04d}")
                for dia in range(10, 19)
            ]
        ).linhas
        inicio, fim = filtros.periodo_padrao(linhas)
        self.assertEqual((inicio, fim), (date(2026, 8, 12), date(2026, 8, 18)))
        recorte = filtros.aplicar(linhas, filtros.selecao_inicial(linhas))
        self.assertNotIn(date(2026, 4, 7), {l["data"] for l in recorte})

    def test_ancora_e_o_dataset_e_nao_o_relogio(self):
        # Duas datas maximas diferentes produzem duas janelas diferentes, e
        # nenhuma delas depende de quando o teste roda.
        antigo = carregar([
            linha_csv(f"2020-01-{dia:02d}", "Meta Ads",
                      anuncio=f"Anuncio-AAAA{dia:04d}")
            for dia in range(1, 21)
        ]).linhas
        self.assertEqual(
            filtros.periodo_padrao(antigo),
            (date(2020, 1, 14), date(2020, 1, 20)),
        )
        self.assertNotEqual(filtros.periodo_padrao(antigo)[1], date.today())

    def test_dataset_vazio_devolve_intervalo_nulo(self):
        self.assertEqual(filtros.periodo_padrao([]), (None, None))

    def test_selecao_manual_continua_valendo(self):
        linhas = carregar([
            linha_csv(f"2026-06-{dia:02d}", "Meta Ads",
                      anuncio=f"Anuncio-AAAA{dia:04d}")
            for dia in range(1, 29)
        ]).linhas
        manual = filtros.Selecao(date(2026, 6, 3), date(2026, 6, 5))
        recorte = filtros.aplicar(linhas, manual)
        self.assertEqual(
            sorted({l["data"] for l in recorte}),
            [date(2026, 6, 3), date(2026, 6, 4), date(2026, 6, 5)],
        )

    def test_periodo_anterior_do_padrao_tem_a_mesma_duracao(self):
        linhas = carregar([
            linha_csv(f"2026-06-{dia:02d}", "Meta Ads",
                      anuncio=f"Anuncio-AAAA{dia:04d}")
            for dia in range(1, 29)
        ]).linhas
        inicio, fim = filtros.periodo_padrao(linhas)
        anterior = m.periodo_anterior(inicio, fim)
        self.assertEqual(anterior, (date(2026, 6, 15), date(2026, 6, 21)))
        self.assertEqual(
            (anterior[1] - anterior[0]).days, (fim - inicio).days
        )

    def test_dataset_de_demonstracao_abre_nos_seus_ultimos_sete_dias(self):
        if not dados.CAMINHO_DEMONSTRACAO.is_file():
            self.skipTest("dataset de demonstracao nao gerado")
        conjunto = dados.carregar(
            dados.Fonte(dados.CAMINHO_DEMONSTRACAO, dados.MODO_DEMONSTRACAO)
        )
        maior = max(linha["data"] for linha in conjunto.linhas)
        inicio, fim = filtros.periodo_padrao(conjunto.linhas)
        self.assertEqual(fim, maior)
        self.assertEqual((fim - inicio).days + 1, filtros.JANELA_PADRAO_DIAS)

    def test_superficie_pseudonimizada_abre_nos_seus_ultimos_sete_dias(self):
        if not dados.CAMINHO_PSEUDONIMIZADO.is_file():
            self.skipTest("superficie de exposicao ausente neste ambiente")
        conjunto = dados.carregar(
            dados.Fonte(
                dados.CAMINHO_PSEUDONIMIZADO, dados.MODO_PSEUDONIMIZADO
            )
        )
        maior = max(linha["data"] for linha in conjunto.linhas)
        inicio, fim = filtros.periodo_padrao(conjunto.linhas)
        self.assertEqual(fim, maior)
        self.assertEqual((fim - inicio).days + 1, filtros.JANELA_PADRAO_DIAS)


class TestDatasetVazio(unittest.TestCase):
    """Dataset sem linhas nao pode quebrar nenhum calculo."""

    def setUp(self):
        self.dataset = carregar([])

    def test_carrega_sem_linhas(self):
        self.assertEqual(self.dataset.linhas, [])

    def test_resumo_devolve_intervalo_nulo(self):
        resumo = dados.resumo(self.dataset)
        self.assertEqual(resumo["linhas"], 0)
        self.assertIsNone(resumo["data_min"])
        self.assertEqual(resumo["plataformas"], [])

    def test_intervalo_disponivel_e_nulo(self):
        self.assertEqual(filtros.intervalo_disponivel([]), (None, None))

    def test_selecao_inicial_nao_levanta(self):
        selecao = filtros.selecao_inicial([])
        self.assertEqual(selecao.data_inicio, selecao.data_fim)

    def test_agregado_vazio_zera_metricas(self):
        totais = m.agregar([])
        self.assertEqual(totais["linhas"], 0)
        self.assertEqual(totais["spend"], Decimal(0))

    def test_derivadas_de_agregado_vazio_sao_indisponiveis(self):
        derivadas = m.calcular_derivadas(m.agregar([]))
        self.assertTrue(all(valor is None for valor in derivadas.values()))

    def test_ranking_vazio(self):
        self.assertEqual(m.ranking([], "campanha", "spend"), [])

    def test_serie_vazia(self):
        self.assertEqual(m.serie_diaria([], "spend"), {})


class TestPlataformaUnica(unittest.TestCase):
    """Um dataset de uma unica origem continua totalmente utilizavel."""

    def setUp(self):
        self.linhas = carregar([
            linha_csv("2026-06-01", "Google Ads", reach="0",
                      profile_views="0", purchases="0"),
            linha_csv("2026-06-02", "Google Ads", reach="0",
                      profile_views="0", purchases="0",
                      anuncio="Anuncio-AAAA0002"),
        ]).linhas

    def test_uma_serie_por_plataforma(self):
        series = m.serie_diaria(self.linhas, "spend")
        self.assertEqual(list(series), ["Google Ads"])

    def test_agregacao_e_derivadas_funcionam(self):
        totais = m.agregar(self.linhas)
        self.assertEqual(totais["spend"], Decimal("200.00"))
        self.assertIsNotNone(m.calcular_derivada("ctr", totais))

    def test_metrica_sem_suporte_na_unica_origem_nao_vira_desempenho(self):
        self.assertFalse(m.suportada("reach", "Google Ads"))
        self.assertFalse(m.suportada("purchases", "Google Ads"))
        self.assertFalse(m.suportada("profile_views", "Google Ads"))
        self.assertTrue(m.suportada("spend", "Google Ads"))

    def test_opcoes_trazem_uma_unica_plataforma(self):
        selecao = filtros.selecao_inicial(self.linhas)
        self.assertEqual(
            filtros.opcoes(self.linhas, selecao)["plataformas"],
            ["Google Ads"],
        )


class TestAgregacao(unittest.TestCase):
    """Somas exatas, agrupamento e ranking."""

    def setUp(self):
        self.linhas = carregar([
            linha_csv("2026-06-01", "Meta Ads", spend="100.10",
                      impressions="1000", link_clicks="50",
                      conversions="5.5"),
            linha_csv("2026-06-01", "Google Ads", conta=CONTA_B,
                      campanha=CAMPANHA_B1, adset=ADSET_B1,
                      anuncio="Anuncio-BBBB0001", spend="200.20",
                      impressions="3000", link_clicks="30",
                      conversions="2.25"),
            linha_csv("2026-06-02", "Meta Ads", spend="0.00",
                      impressions="0", link_clicks="0", conversions="0"),
        ]).linhas

    def test_soma_em_decimal_sem_erro_de_ponto_flutuante(self):
        totais = m.agregar(self.linhas)
        self.assertEqual(totais["spend"], Decimal("300.30"))
        self.assertEqual(totais["conversions"], Decimal("7.75"))
        self.assertIsInstance(totais["spend"], Decimal)

    def test_soma_por_plataforma_fecha_com_o_total(self):
        # Mesma verificacao que o pipeline faz contra inflacao de join.
        total = m.agregar(self.linhas)["spend"]
        por_plataforma = m.agregar_por(
            self.linhas, lambda linha: linha["plataforma"]
        )
        self.assertEqual(
            sum(v["spend"] for v in por_plataforma.values()), total
        )

    def test_serie_diaria_ordena_e_agrupa_por_dia(self):
        series = m.serie_diaria(self.linhas, "spend", por_plataforma=False)
        self.assertEqual(
            series["Total"],
            [(date(2026, 6, 1), Decimal("300.30")),
             (date(2026, 6, 2), Decimal("0.00"))],
        )

    def test_ranking_ordena_pela_metrica_escolhida(self):
        itens = m.ranking(self.linhas, "campanha", "spend")
        self.assertEqual(itens[0]["id"], CAMPANHA_B1)
        self.assertEqual(itens[0]["spend"], Decimal("200.20"))

    def test_ranking_respeita_o_topo(self):
        self.assertEqual(len(m.ranking(self.linhas, "campanha", "spend", 1)), 1)

    def test_ranking_de_anuncio_traz_os_pais_pseudonimizados(self):
        itens = m.ranking(self.linhas, "anuncio", "spend")
        self.assertIn("conta", itens[0])
        self.assertIn("campanha", itens[0])
        self.assertTrue(itens[0]["conta"].startswith("Cliente-"))

    def test_ranking_conta_versoes_scd2(self):
        linhas = carregar([
            linha_csv("2026-06-01", "Meta Ads", versoes=(1, 1, 1, 1)),
            linha_csv("2026-06-02", "Meta Ads", versoes=(1, 2, 1, 1)),
        ]).linhas
        itens = m.ranking(linhas, "campanha", "spend")
        self.assertEqual(itens[0]["versoes"], 2)


class TestPeriodoAnterior(unittest.TestCase):
    """A janela de comparacao tem a mesma duracao e termina na vespera."""

    def test_sete_dias(self):
        self.assertEqual(
            m.periodo_anterior(date(2026, 8, 10), date(2026, 8, 16)),
            (date(2026, 8, 3), date(2026, 8, 9)),
        )

    def test_um_unico_dia(self):
        self.assertEqual(
            m.periodo_anterior(date(2026, 8, 10), date(2026, 8, 10)),
            (date(2026, 8, 9), date(2026, 8, 9)),
        )

    def test_atravessa_o_mes(self):
        self.assertEqual(
            m.periodo_anterior(date(2026, 7, 1), date(2026, 7, 3)),
            (date(2026, 6, 28), date(2026, 6, 30)),
        )

    def test_periodo_invertido_e_erro(self):
        with self.assertRaises(ValueError):
            m.periodo_anterior(date(2026, 8, 10), date(2026, 8, 1))

    def test_comparacao_respeita_todos_os_filtros(self):
        linhas = carregar([
            linha_csv("2026-06-01", "Meta Ads", spend="10.00"),
            linha_csv("2026-06-01", "Google Ads", conta=CONTA_B,
                      campanha=CAMPANHA_B1, adset=ADSET_B1,
                      anuncio="Anuncio-BBBB0001", spend="99.00"),
            linha_csv("2026-06-02", "Meta Ads", spend="20.00",
                      anuncio="Anuncio-AAAA0002"),
        ]).linhas
        selecao = filtros.Selecao(
            date(2026, 6, 2), date(2026, 6, 2), plataformas=("Meta Ads",)
        )
        inicio, fim = m.periodo_anterior(
            selecao.data_inicio, selecao.data_fim
        )
        anteriores = filtros.aplicar_em_periodo(linhas, selecao, inicio, fim)
        self.assertEqual(m.agregar(anteriores)["spend"], Decimal("10.00"))

    def test_sem_dados_anteriores_a_lista_e_vazia(self):
        linhas = carregar([linha_csv("2026-06-01", "Meta Ads")]).linhas
        selecao = filtros.Selecao(date(2026, 6, 1), date(2026, 6, 1))
        inicio, fim = m.periodo_anterior(
            selecao.data_inicio, selecao.data_fim
        )
        self.assertEqual(
            filtros.aplicar_em_periodo(linhas, selecao, inicio, fim), []
        )


class TestVariacao(unittest.TestCase):
    """Variacao percentual: neutra, e indisponivel quando nao ha base."""

    def test_alta(self):
        self.assertEqual(
            m.variacao(Decimal(150), Decimal(100)), Decimal(50)
        )

    def test_queda(self):
        self.assertEqual(
            m.variacao(Decimal(80), Decimal(100)), Decimal(-20)
        )

    def test_base_zero_nao_inventa_percentual(self):
        self.assertIsNone(m.variacao(Decimal(10), Decimal(0)))

    def test_base_ausente_e_indisponivel(self):
        self.assertIsNone(m.variacao(Decimal(10), None))
        self.assertIsNone(m.variacao(None, Decimal(10)))

    def test_formatacao_usa_seta_sem_julgamento(self):
        # Alta de investimento e alta de CPA nao tem a mesma leitura: o
        # dashboard indica direcao, nao qualidade.
        self.assertIn("▲", m.formatar_variacao(Decimal(12)))
        self.assertIn("▼", m.formatar_variacao(Decimal(-12)))
        self.assertEqual(m.formatar_variacao(None), m.INDISPONIVEL)


class TestDerivadas(unittest.TestCase):
    """Indicadores derivados e divisao segura."""

    def setUp(self):
        self.totais = m.agregar(carregar([
            linha_csv("2026-06-01", "Meta Ads", spend="100.00",
                      impressions="10000", link_clicks="200",
                      conversions="10", conversion_value="500.00"),
        ]).linhas)

    def test_ctr(self):
        self.assertEqual(
            m.calcular_derivada("ctr", self.totais), Decimal(2)
        )

    def test_cpc(self):
        self.assertEqual(
            m.calcular_derivada("cpc", self.totais), Decimal("0.5")
        )

    def test_cpm(self):
        self.assertEqual(
            m.calcular_derivada("cpm", self.totais), Decimal(10)
        )

    def test_cpa(self):
        self.assertEqual(
            m.calcular_derivada("cpa", self.totais), Decimal(10)
        )

    def test_roas(self):
        self.assertEqual(
            m.calcular_derivada("roas", self.totais), Decimal(5)
        )

    def test_todos_os_operandos_sao_metricas_consolidaveis(self):
        # Um derivado cujo operando nao some entre plataformas produziria
        # indicador sem leitura no total consolidado.
        for definicao in m.DERIVADAS.values():
            self.assertIn(definicao.numerador, m.METRICAS_CONSOLIDAVEIS)
            self.assertIn(definicao.denominador, m.METRICAS_CONSOLIDAVEIS)


class TestDivisaoSegura(unittest.TestCase):
    """Nenhum caminho produz NaN, Infinity ou zero enganoso."""

    def test_denominador_zero_devolve_none(self):
        self.assertIsNone(m.dividir(Decimal(10), Decimal(0)))

    def test_denominador_negativo_devolve_none(self):
        self.assertIsNone(m.dividir(Decimal(10), Decimal(-1)))

    def test_numerador_zero_e_resultado_legitimo(self):
        self.assertEqual(m.dividir(Decimal(0), Decimal(10)), Decimal(0))

    def test_operando_ausente_devolve_none(self):
        self.assertIsNone(m.dividir(None, Decimal(10)))
        self.assertIsNone(m.dividir(Decimal(10), None))

    def test_derivadas_com_denominador_zerado_ficam_indisponiveis(self):
        totais = m.agregar(carregar([
            linha_csv("2026-06-01", "Meta Ads", spend="0.00",
                      impressions="0", link_clicks="0", conversions="0",
                      conversion_value="0"),
        ]).linhas)
        derivadas = m.calcular_derivadas(totais)
        for chave, valor in derivadas.items():
            with self.subTest(indicador=chave):
                self.assertIsNone(valor)
                self.assertEqual(
                    m.formatar_derivada(chave, valor), m.INDISPONIVEL
                )

    def test_roas_indisponivel_quando_a_origem_nao_reporta_valor(self):
        # Caso real do artefato: o Meta nao traz valor de conversao neste
        # grao. O ROAS resultante e indisponivel, nao zero.
        totais = m.agregar(carregar([
            linha_csv("2026-06-01", "Meta Ads", conversion_value="0"),
        ]).linhas)
        self.assertEqual(m.calcular_derivada("roas", totais), Decimal(0))
        totais_sem_gasto = m.agregar(carregar([
            linha_csv("2026-06-01", "Meta Ads", spend="0",
                      conversion_value="0"),
        ]).linhas)
        self.assertIsNone(m.calcular_derivada("roas", totais_sem_gasto))

    def test_nenhuma_formatacao_produz_nan_ou_infinity(self):
        for formato in (m.MOEDA, m.INTEIRO, m.DECIMAL, m.PERCENTUAL,
                        m.MULTIPLICADOR):
            texto = m.formatar(None, formato)
            self.assertEqual(texto, m.INDISPONIVEL)
            self.assertNotIn("nan", texto.lower())
            self.assertNotIn("inf", texto.lower())


class TestFormatacao(unittest.TestCase):
    """Formatacao em pt-BR, so na apresentacao."""

    def test_moeda(self):
        self.assertEqual(
            m.formatar(Decimal("38741.181825"), m.MOEDA), "R$ 38.741,18"
        )

    def test_inteiro_com_separador_de_milhar(self):
        self.assertEqual(m.formatar(Decimal(1875349), m.INTEIRO), "1.875.349")

    def test_percentual(self):
        self.assertEqual(m.formatar(Decimal("2.5"), m.PERCENTUAL), "2,50%")

    def test_negativo(self):
        self.assertEqual(m.formatar(Decimal("-1234.5"), m.MOEDA),
                         "R$ -1.234,50")

    def test_zero(self):
        self.assertEqual(m.formatar(Decimal(0), m.INTEIRO), "0")

    def test_formatar_metrica_segue_o_catalogo(self):
        self.assertTrue(
            m.formatar_metrica("spend", Decimal(10)).startswith("R$")
        )
        self.assertEqual(
            m.formatar_metrica("impressions", Decimal(1000)), "1.000"
        )


class TestFormatacaoDeMultiplicador(unittest.TestCase):
    """O ROAS e um multiplicador, e a apresentacao precisa dizer isso.

    A formula nao muda — `conversion_value / spend`, fator 1. O que muda e a
    leitura: `0,03` sugere um numero arredondado sem unidade, `0,028x` diz
    que sao 2,8 centavos de valor de conversao por real investido.
    """

    def test_sufixo_de_multiplicador(self):
        self.assertEqual(m.formatar(Decimal(2), m.MULTIPLICADOR), "2,00x")

    def test_valor_pequeno_nao_e_achatado_em_duas_casas(self):
        # Caso real da validacao contra o Google Ads: R$ 4,00 de valor de
        # conversao sobre R$ 142,46 de investimento. Duas casas exibiriam
        # `0,03x` e perderiam a ordem de grandeza.
        roas = m.dividir(Decimal("4.00"), Decimal("142.46"))
        self.assertEqual(m.formatar(roas, m.MULTIPLICADOR), "0,028x")

    def test_casas_seguem_a_ordem_de_grandeza(self):
        for valor, esperado in (
            ("0", "0,00x"),
            ("0.028078", "0,028x"),
            ("0.45", "0,45x"),
            ("1", "1,00x"),
            ("9.5", "9,50x"),
            ("12.543", "12,54x"),
            ("1234.5", "1.234,50x"),
        ):
            with self.subTest(valor=valor):
                self.assertEqual(
                    m.formatar(Decimal(valor), m.MULTIPLICADOR), esperado
                )

    def test_valor_minusculo_nao_vira_zero(self):
        # `0,000x` seria lido como ausencia de retorno; o piso diz que ha
        # valor, so abaixo da resolucao exibida.
        self.assertEqual(
            m.formatar(Decimal("0.0005"), m.MULTIPLICADOR), "< 0,001x"
        )

    def test_indisponivel_continua_indisponivel(self):
        self.assertEqual(
            m.formatar(None, m.MULTIPLICADOR), m.INDISPONIVEL
        )

    def test_roas_do_catalogo_usa_o_formato_de_multiplicador(self):
        self.assertEqual(m.DERIVADAS["roas"].formato, m.MULTIPLICADOR)
        self.assertEqual(
            m.formatar_derivada("roas", Decimal(5)), "5,00x"
        )

    def test_formula_do_roas_permanece_intacta(self):
        definicao = m.DERIVADAS["roas"]
        self.assertEqual(definicao.numerador, "conversion_value")
        self.assertEqual(definicao.denominador, "spend")
        self.assertEqual(definicao.fator, Decimal(1))


class TestAjudaContextual(unittest.TestCase):
    """Toda metrica exibida em cartao tem definicao para a ajuda."""

    # Metricas do catalogo que ainda viram cartao — hoje so as de ENTREGA,
    # porque resultado e valor passaram a sair do painel por plataforma.
    METRICAS_EM_CARTAO = tuple(
        chave[1:]
        for grupo in m.ENTREGA.values()
        for chave in grupo
        if chave.startswith("@")
    )

    def test_metricas_dos_cartoes_tem_ajuda(self):
        for metrica in self.METRICAS_EM_CARTAO:
            with self.subTest(metrica=metrica):
                self.assertTrue(m.CATALOGO[metrica].ajuda)

    def test_compras_mantem_a_ressalva_de_disponibilidade(self):
        # A definicao nova nao substitui o aviso de que a GAQL nao entrega a
        # metrica neste grao.
        self.assertTrue(m.CATALOGO["purchases"].observacao)

    def test_todos_os_derivados_tem_ajuda(self):
        for chave, definicao in m.DERIVADAS.items():
            with self.subTest(indicador=chave):
                self.assertTrue(definicao.ajuda)

    def test_ajuda_do_cpa_cita_a_metrica_equivalente_do_google(self):
        # Validacao manual contra a interface: "Custo / conv." e o mesmo
        # numero que o cartao de CPA.
        self.assertIn("Custo / conv.", m.DERIVADAS["cpa"].ajuda)

    def test_ajuda_do_roas_explica_o_multiplicador(self):
        self.assertIn("2,00x", m.DERIVADAS["roas"].ajuda)


def linhas_painel() -> list[dict]:
    """Recorte minimo com as duas plataformas, em valores redondos.

    Meta: R$ 100, 10 leads, 2 compras, R$ 40 de valor de compra e nenhum
    valor de conversao — que e o que a fonte realmente reporta.
    Google: R$ 200, 5 conversoes, R$ 300 de valor de conversao, sem compra.
    """
    return carregar([
        linha_csv("2026-08-01", "Meta Ads", spend="100.00",
                  impressions="1000", link_clicks="50",
                  conversions="10", conversion_value="0.00",
                  video_views="0", reach="0", profile_views="0",
                  purchases="2", purchase_value="40.00"),
        linha_csv("2026-08-01", "Google Ads", spend="200.00",
                  impressions="2000", link_clicks="80",
                  conversions="5", conversion_value="300.00",
                  video_views="0", reach="0", profile_views="0",
                  purchases="0", purchase_value="0.00",
                  conta=CONTA_A, campanha=CAMPANHA_A1, adset=ADSET_A1,
                  anuncio="Anuncio-BBBB0001"),
    ]).linhas


class TestPainelMeta(unittest.TestCase):
    """`conversions` do Meta conta LEAD; o KPI e CPL, nao CPA."""

    def setUp(self):
        self.painel = m.painel(
            [l for l in linhas_painel() if l["plataforma"] == m.META]
        )

    def test_leads_usa_conversions_do_meta(self):
        self.assertEqual(self.painel["leads_meta"], Decimal(10))

    def test_cpl_e_investimento_meta_por_lead(self):
        self.assertEqual(self.painel["cpl_meta"], Decimal(10))
        # Sufixo no recorte misto, rotulo curto quando so o Meta esta em tela.
        self.assertEqual(m.PAINEL["cpl_meta"].rotulo, "CPL — Meta")
        self.assertEqual(m.PAINEL["cpl_meta"].rotulo_curto, "CPL")

    def test_compras_usa_purchases_do_meta(self):
        self.assertEqual(self.painel["compras_meta"], Decimal(2))

    def test_valor_de_compras_usa_purchase_value(self):
        self.assertEqual(self.painel["valor_compras_meta"], Decimal(40))

    def test_roas_meta_usa_purchase_value_sobre_investimento(self):
        # 40 / 100. Se usasse `conversion_value`, que e zero na fonte, o ROAS
        # do Meta seria eternamente 0,00x — o defeito que originou a correcao.
        self.assertEqual(self.painel["roas_meta"], Decimal("0.4"))

    def test_google_ausente_do_recorte_nao_vira_zero(self):
        self.assertIsNone(self.painel["conversoes_google"])
        self.assertIsNone(self.painel["valor_conversoes_google"])
        self.assertIsNone(self.painel["roas_google"])


class TestPainelGoogle(unittest.TestCase):
    """No Google o KPI e CPA, e o valor vem de `conversion_value`."""

    def setUp(self):
        self.painel = m.painel(
            [l for l in linhas_painel() if l["plataforma"] == m.GOOGLE]
        )

    def test_conversoes_usa_conversions_do_google(self):
        self.assertEqual(self.painel["conversoes_google"], Decimal(5))

    def test_cpa_e_investimento_google_por_conversao(self):
        self.assertEqual(self.painel["cpa_google"], Decimal(40))
        self.assertEqual(m.PAINEL["cpa_google"].rotulo, "CPA — Google")
        self.assertEqual(m.PAINEL["cpa_google"].rotulo_curto, "CPA")

    def test_valor_de_conversoes_usa_conversion_value(self):
        self.assertEqual(self.painel["valor_conversoes_google"], Decimal(300))

    def test_roas_google_usa_conversion_value(self):
        self.assertEqual(self.painel["roas_google"], Decimal("1.5"))

    def test_google_nao_inventa_compra(self):
        self.assertEqual(self.painel["compras_meta"], None)
        self.assertFalse(m.suportada("purchases", m.GOOGLE))
        self.assertFalse(m.suportada("purchase_value", m.GOOGLE))


class TestPainelConsolidado(unittest.TestCase):
    """Meta e Google convivem sem virar um numero unico sem significado."""

    def setUp(self):
        self.painel = m.painel(linhas_painel())

    def test_leads_meta_e_conversoes_google_nao_sao_somados(self):
        self.assertEqual(self.painel["leads_meta"], Decimal(10))
        self.assertEqual(self.painel["conversoes_google"], Decimal(5))
        # Nenhuma chave do painel carrega a soma 15.
        self.assertNotIn(Decimal(15), self.painel.values())

    def test_valor_meta_e_google_ficam_separados(self):
        self.assertEqual(self.painel["valor_compras_meta"], Decimal(40))
        self.assertEqual(self.painel["valor_conversoes_google"], Decimal(300))

    def test_valor_atribuido_total_soma_meta_e_google(self):
        self.assertEqual(self.painel["valor_atribuido_total"], Decimal(340))

    def test_roas_total_sai_das_somas_globais(self):
        # 340 / 300.
        self.assertEqual(
            self.painel["roas_total"], Decimal(340) / Decimal(300)
        )

    def test_roas_total_nao_e_media_dos_roas_por_plataforma(self):
        media = (self.painel["roas_meta"] + self.painel["roas_google"]) / 2
        self.assertNotEqual(self.painel["roas_total"], media)
        # A media daria 0,95x contra 1,13x reais: a plataforma com mais
        # investimento tem de pesar mais.
        self.assertEqual(media, Decimal("0.95"))

    def test_cliques_meta_e_google_tem_rotulos_distintos(self):
        self.assertEqual(self.painel["cliques_meta"], Decimal(50))
        self.assertEqual(self.painel["cliques_google"], Decimal(80))
        self.assertNotEqual(
            m.PAINEL["cliques_meta"].rotulo, m.PAINEL["cliques_google"].rotulo
        )
        self.assertIn("no link", m.PAINEL["cliques_meta"].rotulo)
        self.assertNotIn("no link", m.PAINEL["cliques_google"].rotulo)

    def test_valor_atribuido_nao_e_chamado_de_receita(self):
        definicao = m.PAINEL["valor_atribuido_total"]
        texto = (definicao.rotulo + " " + definicao.ajuda).lower()
        for proibido in ("receita", "faturamento", "vendas totais"):
            with self.subTest(termo=proibido):
                self.assertNotIn(proibido, texto)


class TestPainelZeroENulo(unittest.TestCase):
    """Denominador invalido continua vazio; zero medido continua zero."""

    def test_denominador_zero_mantem_indisponibilidade(self):
        painel = m.painel(carregar([
            linha_csv("2026-08-01", "Meta Ads", spend="0.00",
                      conversions="0", conversion_value="0.00",
                      purchases="0", purchase_value="0.00"),
        ]).linhas)

        self.assertIsNone(painel["cpl_meta"])
        self.assertIsNone(painel["roas_meta"])

    def test_valor_zero_com_investimento_positivo_da_roas_zero(self):
        """Zero medido nao e indisponibilidade: o cartao mostra 0,00x."""
        painel = m.painel(carregar([
            linha_csv("2026-08-01", "Meta Ads", spend="100.00",
                      conversions="4", conversion_value="0.00",
                      purchases="0", purchase_value="0.00"),
        ]).linhas)

        self.assertEqual(painel["roas_meta"], Decimal(0))
        self.assertEqual(m.formatar_painel("roas_meta", painel["roas_meta"]),
                         "0,00x")
        self.assertEqual(painel["cpl_meta"], Decimal(25))

    def test_google_sem_purchase_value_nao_cria_compra(self):
        painel = m.painel(carregar([
            linha_csv("2026-08-01", "Google Ads", spend="100.00",
                      conversions="4", conversion_value="80.00",
                      purchases="0", purchase_value="0.00"),
        ]).linhas)

        self.assertIsNone(painel["compras_meta"])
        self.assertIsNone(painel["valor_compras_meta"])
        self.assertEqual(painel["valor_atribuido_total"], Decimal(80))


class TestLayoutPorRecorte(unittest.TestCase):
    """A hierarquia dos cartoes acompanha a selecao de plataforma."""

    def test_recorte_reconhece_a_selecao(self):
        self.assertEqual(m.recorte([m.META]), "meta")
        self.assertEqual(m.recorte([m.GOOGLE]), "google")
        self.assertEqual(m.recorte([m.META, m.GOOGLE]), "ambas")

    def test_resultado_vem_antes_de_entrega(self):
        """O primeiro cartao do primeiro bloco e investimento, nao volume."""
        for recorte in ("meta", "google", "ambas"):
            with self.subTest(recorte=recorte):
                primeiro = m.PAINEL_RESULTADOS[recorte][0]
                self.assertTrue(primeiro.startswith("investimento"))

    def test_cliques_nunca_aparece_somado_sob_rotulo_unico(self):
        """No recorte misto os dois cliques entram separados, e a metrica
        generica do catalogo nao vira cartao de entrega."""
        entrega = m.ENTREGA["ambas"]
        self.assertIn("cliques_meta", entrega)
        self.assertIn("cliques_google", entrega)
        self.assertNotIn("@link_clicks", entrega)

    def test_cpl_e_cpa_nunca_convivem_no_mesmo_recorte_exclusivo(self):
        self.assertIn("cpl_meta", m.PAINEL_RESULTADOS["meta"])
        self.assertNotIn("cpa_google", m.PAINEL_RESULTADOS["meta"])
        self.assertIn("cpa_google", m.PAINEL_RESULTADOS["google"])
        self.assertNotIn("cpl_meta", m.PAINEL_RESULTADOS["google"])

    def test_consolidado_traz_os_tres_kpis_de_valor(self):
        valor = m.PAINEL_VALOR["ambas"]
        for chave in ("valor_atribuido_total", "valor_compras_meta",
                      "valor_conversoes_google"):
            with self.subTest(chave=chave):
                self.assertIn(chave, valor)
        # ROAS total abre a linha dos ROAS.
        self.assertEqual(valor[3], "roas_total")

    def test_eficiencia_perdeu_cpa_e_roas_genericos(self):
        """CPA e ROAS agora sao por plataforma; os genericos somariam
        definicoes diferentes sob um rotulo unico."""
        for grupo in m.EFICIENCIA.values():
            with self.subTest(grupo=grupo):
                self.assertNotIn("#cpa", grupo)
                self.assertNotIn("#roas", grupo)

    def test_toda_chave_de_layout_existe_no_catalogo(self):
        grupos = (
            list(m.PAINEL_RESULTADOS.values())
            + list(m.PAINEL_VALOR.values())
            + list(m.ENTREGA.values())
            + list(m.EFICIENCIA.values())
        )
        for grupo in grupos:
            for chave in grupo:
                with self.subTest(chave=chave):
                    if chave.startswith("@"):
                        self.assertIn(chave[1:], m.CATALOGO)
                    elif chave.startswith("#"):
                        self.assertIn(chave[1:], m.DERIVADAS)
                    else:
                        self.assertIn(chave, m.PAINEL)


class TestEficienciaPorPlataforma(unittest.TestCase):
    """CTR e CPC nunca consolidam; CPM continua consolidando.

    `link_clicks` guarda `inline_link_clicks` no Meta e `metrics.clicks` no
    Google. Somar as duas e dividir por impressoes produziria um CTR sem
    definicao — e o mesmo vale para o CPC. Investimento e impressao, ao
    contrario, tem semantica compativel entre as plataformas.
    """

    def setUp(self):
        self.painel = m.painel(linhas_painel())

    def test_ctr_meta_usa_somente_numeros_do_meta(self):
        # 50 cliques / 1000 impressoes x 100.
        self.assertEqual(self.painel["ctr_meta"], Decimal(5))

    def test_cpc_meta_usa_somente_numeros_do_meta(self):
        # R$ 100 / 50 cliques.
        self.assertEqual(self.painel["cpc_meta"], Decimal(2))

    def test_ctr_google_usa_somente_numeros_do_google(self):
        # 80 cliques / 2000 impressoes x 100.
        self.assertEqual(self.painel["ctr_google"], Decimal(4))

    def test_cpc_google_usa_somente_numeros_do_google(self):
        # R$ 200 / 80 cliques.
        self.assertEqual(self.painel["cpc_google"], Decimal("2.5"))

    def test_consolidado_nao_tem_ctr_generico(self):
        self.assertNotIn("#ctr", m.EFICIENCIA["ambas"])
        self.assertIn("ctr_meta", m.EFICIENCIA["ambas"])
        self.assertIn("ctr_google", m.EFICIENCIA["ambas"])

    def test_consolidado_nao_tem_cpc_generico(self):
        self.assertNotIn("#cpc", m.EFICIENCIA["ambas"])
        self.assertIn("cpc_meta", m.EFICIENCIA["ambas"])
        self.assertIn("cpc_google", m.EFICIENCIA["ambas"])

    def test_recorte_exclusivo_tambem_isola_a_plataforma(self):
        """Mesmo com uma plataforma so, a formula continua vindo do painel
        isolado — nao da soma do recorte."""
        self.assertEqual(m.EFICIENCIA["meta"], ("ctr_meta", "cpc_meta", "#cpm"))
        self.assertEqual(
            m.EFICIENCIA["google"], ("ctr_google", "cpc_google", "#cpm")
        )

    def test_rotulo_perde_o_sufixo_quando_a_plataforma_esta_isolada(self):
        for chave in ("ctr_meta", "cpc_meta", "ctr_google", "cpc_google"):
            with self.subTest(chave=chave):
                definicao = m.PAINEL[chave]
                self.assertIn("—", definicao.rotulo)
                self.assertIn(definicao.rotulo_curto, ("CTR", "CPC"))

    def test_mexer_no_google_nao_altera_ctr_e_cpc_do_meta(self):
        alteradas = [
            dict(linha, link_clicks=linha["link_clicks"] * 10)
            if linha["plataforma"] == m.GOOGLE else linha
            for linha in linhas_painel()
        ]
        depois = m.painel(alteradas)

        self.assertEqual(depois["ctr_meta"], self.painel["ctr_meta"])
        self.assertEqual(depois["cpc_meta"], self.painel["cpc_meta"])
        self.assertNotEqual(depois["ctr_google"], self.painel["ctr_google"])

    def test_mexer_no_meta_nao_altera_ctr_e_cpc_do_google(self):
        alteradas = [
            dict(linha, link_clicks=linha["link_clicks"] * 10)
            if linha["plataforma"] == m.META else linha
            for linha in linhas_painel()
        ]
        depois = m.painel(alteradas)

        self.assertEqual(depois["ctr_google"], self.painel["ctr_google"])
        self.assertEqual(depois["cpc_google"], self.painel["cpc_google"])
        self.assertNotEqual(depois["ctr_meta"], self.painel["ctr_meta"])

    def test_cpm_continua_consolidado(self):
        # (100 + 200) / (1000 + 2000) x 1000 = R$ 100,00.
        totais = m.agregar(linhas_painel())
        self.assertEqual(m.calcular_derivada("cpm", totais), Decimal(100))
        for grupo in m.EFICIENCIA.values():
            with self.subTest(grupo=grupo):
                self.assertIn("#cpm", grupo)


class TestReachNaoAditivo(unittest.TestCase):
    """Alcance conta pessoas unicas: nao soma entre linhas factuais.

    A regra nao e "so vale num dia". Dois anuncios no MESMO dia com alcance
    1.000 e 800 nao dao 1.800 — parte das pessoas viu os dois, e o dataset nao
    guarda a intersecao. Alcance so e exato na observacao original da API:
    um anuncio, um dia.
    """

    def _linhas(self, *linhas):
        return carregar(list(linhas)).linhas

    def test_uma_linha_meta_preserva_o_alcance(self):
        totais = m.agregar(self._linhas(
            linha_csv("2026-08-01", "Meta Ads", reach="1000"),
        ))

        self.assertEqual(totais["reach"], Decimal(1000))

    def test_mesmo_anuncio_em_dois_dias_fica_indisponivel(self):
        totais = m.agregar(self._linhas(
            linha_csv("2026-08-01", "Meta Ads", reach="1000"),
            linha_csv("2026-08-02", "Meta Ads", reach="800"),
        ))

        self.assertIsNone(totais["reach"])

    def test_dois_anuncios_no_mesmo_dia_ficam_indisponiveis(self):
        """O caso que a regra antiga deixava passar."""
        totais = m.agregar(self._linhas(
            linha_csv("2026-08-01", "Meta Ads", anuncio="Anuncio-AAAA0001",
                      reach="1000"),
            linha_csv("2026-08-01", "Meta Ads", anuncio="Anuncio-AAAA0002",
                      reach="800"),
        ))

        self.assertIsNone(totais["reach"])
        self.assertNotEqual(totais["reach"], Decimal(1800))

    def test_duas_campanhas_no_mesmo_dia_ficam_indisponiveis(self):
        totais = m.agregar(self._linhas(
            linha_csv("2026-08-01", "Meta Ads", campanha=CAMPANHA_A1,
                      anuncio="Anuncio-AAAA0001", reach="1000"),
            linha_csv("2026-08-01", "Meta Ads", campanha=CAMPANHA_A2,
                      anuncio="Anuncio-AAAA0002", reach="800"),
        ))

        self.assertIsNone(totais["reach"])

    def test_duas_contas_ficam_indisponiveis(self):
        totais = m.agregar(self._linhas(
            linha_csv("2026-08-01", "Meta Ads", conta=CONTA_A,
                      anuncio="Anuncio-AAAA0001", reach="1000"),
            linha_csv("2026-08-01", "Meta Ads", conta=CONTA_B,
                      anuncio="Anuncio-BBBB0001", reach="800"),
        ))

        self.assertIsNone(totais["reach"])

    def test_google_nao_reporta_alcance(self):
        """Zero do Google e ausencia de suporte; nem numa linha unica ele vira
        alcance."""
        linhas = self._linhas(
            linha_csv("2026-08-01", "Google Ads", reach="0"),
        )
        totais = m.agregar(linhas)
        por_plataforma = m.totais_por_plataforma(linhas)

        self.assertIsNone(totais["reach"])
        self.assertIsNone(por_plataforma[m.GOOGLE]["reach"])
        self.assertFalse(m.suportada("reach", m.GOOGLE))

    def test_recorte_meta_e_google_fica_indisponivel(self):
        totais = m.agregar(self._linhas(
            linha_csv("2026-08-01", "Meta Ads", reach="1000"),
            linha_csv("2026-08-01", "Google Ads", conta=CONTA_B,
                      campanha=CAMPANHA_B1, adset=ADSET_B1,
                      anuncio="Anuncio-BBBB0001", reach="0"),
        ))

        self.assertIsNone(totais["reach"])

    def test_indisponivel_nao_vira_zero_na_apresentacao(self):
        totais = m.agregar(self._linhas(
            linha_csv("2026-08-01", "Meta Ads", reach="1000"),
            linha_csv("2026-08-02", "Meta Ads", reach="800"),
        ))
        texto = m.formatar_metrica("reach", totais["reach"])

        self.assertEqual(texto, m.INDISPONIVEL)
        self.assertNotIn("0", texto)
        self.assertNotEqual(texto, "1.800")

    def test_agregar_por_aplica_a_regra_em_cada_grupo(self):
        linhas = self._linhas(
            linha_csv("2026-08-01", "Meta Ads", conta=CONTA_A,
                      anuncio="Anuncio-AAAA0001", reach="1000"),
            linha_csv("2026-08-02", "Meta Ads", conta=CONTA_A,
                      anuncio="Anuncio-AAAA0001", reach="900"),
            linha_csv("2026-08-01", "Meta Ads", conta=CONTA_B,
                      anuncio="Anuncio-BBBB0001", reach="700"),
        )
        por_conta = m.agregar_por(linhas, lambda linha: linha["conta_id"])

        # Conta A tem duas linhas factuais; conta B tem uma.
        self.assertIsNone(por_conta[CONTA_A]["reach"])
        self.assertEqual(por_conta[CONTA_B]["reach"], Decimal(700))

    def test_ranking_recusa_ordenar_por_metrica_nao_aditiva(self):
        linhas = self._linhas(
            linha_csv("2026-08-01", "Meta Ads", reach="1000"),
            linha_csv("2026-08-02", "Meta Ads", reach="800"),
        )

        with self.assertRaises(ValueError):
            m.ranking(linhas, "anuncio", "reach")

    def test_ranking_nao_publica_soma_de_alcance(self):
        """Mesmo ordenando por outra metrica, a coluna de alcance da entidade
        multi-linha nao pode trazer a soma."""
        linhas = self._linhas(
            linha_csv("2026-08-01", "Meta Ads", reach="1000"),
            linha_csv("2026-08-02", "Meta Ads", reach="800"),
        )
        itens = m.ranking(linhas, "anuncio", "spend")

        self.assertEqual(len(itens), 1)
        self.assertIsNone(itens[0]["reach"])

    def test_serie_nao_soma_alcance_de_varios_anuncios_no_mesmo_dia(self):
        linhas = self._linhas(
            linha_csv("2026-08-01", "Meta Ads", anuncio="Anuncio-AAAA0001",
                      reach="1000"),
            linha_csv("2026-08-01", "Meta Ads", anuncio="Anuncio-AAAA0002",
                      reach="800"),
            linha_csv("2026-08-02", "Meta Ads", anuncio="Anuncio-AAAA0001",
                      reach="600"),
        )
        serie = m.serie_diaria(linhas, "reach")
        pontos = dict(serie["Meta Ads"])

        # 01/08 reune dois anuncios; 02/08 tem so um.
        self.assertIsNone(pontos[date(2026, 8, 1)])
        self.assertEqual(pontos[date(2026, 8, 2)], Decimal(600))

    def test_serie_de_um_unico_anuncio_por_dia_continua_valida(self):
        """E o grafico do detalhe de anuncio: cada ponto e a observacao
        original da API."""
        linhas = self._linhas(
            linha_csv("2026-08-01", "Meta Ads", reach="1000"),
            linha_csv("2026-08-02", "Meta Ads", reach="800"),
        )
        pontos = dict(m.serie_diaria(linhas, "reach")["Meta Ads"])

        self.assertEqual(pontos[date(2026, 8, 1)], Decimal(1000))
        self.assertEqual(pontos[date(2026, 8, 2)], Decimal(800))

    def test_serie_google_mantem_alcance_indisponivel(self):
        pontos = dict(m.serie_diaria(self._linhas(
            linha_csv("2026-08-01", "Google Ads", reach="0"),
        ), "reach")["Google Ads"])

        self.assertIsNone(pontos[date(2026, 8, 1)])

    def test_zero_real_de_metrica_aditiva_continua_zero_na_serie(self):
        pontos = dict(m.serie_diaria(self._linhas(
            linha_csv("2026-08-01", "Meta Ads", spend="0"),
        ), "spend")["Meta Ads"])

        self.assertEqual(pontos[date(2026, 8, 1)], Decimal(0))

    def test_nenhuma_derivada_usa_alcance(self):
        """Frequencia (impressoes / alcance) nao existe — e nao pode nascer
        somando alcance."""
        operandos = set()
        for definicao in m.DERIVADAS.values():
            operandos.update({definicao.numerador, definicao.denominador})

        self.assertNotIn("reach", operandos)

    def test_demais_metricas_seguem_somando(self):
        totais = m.agregar(self._linhas(
            linha_csv("2026-08-01", "Meta Ads", spend="100.00",
                      impressions="1000", link_clicks="50", conversions="4",
                      conversion_value="0.00", video_views="7",
                      reach="1000", purchases="2", purchase_value="10.00"),
            linha_csv("2026-08-02", "Meta Ads", spend="50.00",
                      impressions="500", link_clicks="25", conversions="2",
                      conversion_value="0.00", video_views="3",
                      reach="800", purchases="1", purchase_value="5.00"),
        ))

        self.assertEqual(totais["spend"], Decimal("150.00"))
        self.assertEqual(totais["impressions"], Decimal(1500))
        self.assertEqual(totais["link_clicks"], Decimal(75))
        self.assertEqual(totais["conversions"], Decimal(6))
        self.assertEqual(totais["video_views"], Decimal(10))
        self.assertEqual(totais["purchases"], Decimal(3))
        self.assertEqual(totais["purchase_value"], Decimal("15.00"))
        self.assertIsNone(totais["reach"])

    def test_painel_por_plataforma_nao_quebra_com_alcance_ausente(self):
        """`painel` nao usa alcance, mas le o mesmo agregado: CPL, ROAS e os
        valores continuam saindo normalmente."""
        painel = m.painel(self._linhas(
            linha_csv("2026-08-01", "Meta Ads", spend="100.00",
                      conversions="10", purchases="2", purchase_value="40.00",
                      reach="1000"),
            linha_csv("2026-08-02", "Meta Ads", spend="100.00",
                      conversions="10", purchases="2", purchase_value="40.00",
                      reach="800"),
        ))

        self.assertEqual(painel["investimento_meta"], Decimal("200.00"))
        self.assertEqual(painel["cpl_meta"], Decimal(10))
        self.assertEqual(painel["valor_compras_meta"], Decimal(80))
        self.assertEqual(painel["roas_meta"], Decimal("0.4"))


class TestCatalogoDeMetricas(unittest.TestCase):
    """O catalogo espelha as limitacoes reais das duas APIs."""

    def test_cobre_as_metricas_do_pipeline(self):
        """Dez desde 26/08/2026: `purchase_value` entrou para carregar o valor
        monetario das compras do Meta, que `conversion_value` nunca carregou."""
        self.assertEqual(set(m.METRICAS), set(dados.METRICAS))
        self.assertEqual(len(m.METRICAS), 10)

    def test_metricas_sem_suporte_no_google(self):
        for metrica in ("reach", "profile_views", "purchases",
                        "purchase_value"):
            with self.subTest(metrica=metrica):
                self.assertFalse(m.suportada(metrica, "Google Ads"))
                self.assertTrue(m.suportada(metrica, "Meta Ads"))

    def test_video_views_nao_soma_entre_plataformas(self):
        # Definicoes diferentes: TrueView de 30s no Google, 3s no Meta.
        self.assertFalse(
            m.CATALOGO["video_views"].comparavel_entre_plataformas
        )
        self.assertNotIn("video_views", m.METRICAS_CONSOLIDAVEIS)

    def test_reach_e_declarada_nao_aditiva(self):
        self.assertEqual(m.CATALOGO["reach"].agregacao, m.NAO_ADITIVA)

    def test_reach_e_a_unica_nao_aditiva_hoje(self):
        nao_aditivas = {
            chave for chave, definicao in m.CATALOGO.items()
            if definicao.agregacao == m.NAO_ADITIVA
        }
        self.assertEqual(nao_aditivas, {"reach"})
        self.assertNotIn("reach", m.METRICAS_AGREGAVEIS)

    def test_metricas_consolidaveis_sao_as_cinco_comuns(self):
        self.assertEqual(
            set(m.METRICAS_CONSOLIDAVEIS),
            {"spend", "impressions", "link_clicks", "conversions",
             "conversion_value"},
        )

    def test_metrica_desconhecida_nao_e_suportada(self):
        self.assertFalse(m.suportada("clicks_totais", "Meta Ads"))


class TestGeradorDemoV3(unittest.TestCase):
    """O gerador puro produz v3 util sem tocar em dado operacional."""

    @classmethod
    def setUpClass(cls):
        cls.linhas = gerar_dados_demo.gerar_linhas()
        cls.texto = gerar_dados_demo.serializar_csv(cls.linhas)
        cls.manifesto = gerar_dados_demo.montar_manifesto(
            cls.linhas, cls.texto
        )

    def test_contrato_v3_tem_as_vinte_e_quatro_colunas(self):
        self.assertEqual(gerar_dados_demo.VERSAO_CONTRATO, 3)
        self.assertEqual(len(gerar_dados_demo.COLUNAS), 24)
        self.assertEqual(
            gerar_dados_demo.COLUNAS,
            tuple(CABECALHO_RESULTADO),
        )
        self.assertEqual(self.manifesto["versao_contrato"], 3)
        self.assertEqual(
            self.manifesto["colunas"], list(gerar_dados_demo.COLUNAS)
        )

    def test_contexto_interno_nao_entra_na_demo(self):
        for coluna in ("objective", "optimization_goal"):
            with self.subTest(coluna=coluna):
                self.assertNotIn(coluna, gerar_dados_demo.COLUNAS)
                self.assertTrue(all(coluna not in linha for linha in self.linhas))

    def test_meta_tem_typed_positivo_custo_janela_e_ausencia(self):
        meta = [l for l in self.linhas if l["plataforma"] == "Meta Ads"]
        tipadas = [l for l in meta if l["result_type"] is not None]
        ausentes = [l for l in meta if l["result_type"] is None]

        self.assertTrue(tipadas)
        self.assertTrue(ausentes)
        self.assertTrue(any(l["result_count"] > 0 for l in tipadas))
        self.assertTrue(any(l["cost_per_result"] is not None for l in tipadas))
        self.assertTrue(
            any(l["result_attribution_window"] == "default" for l in tipadas)
        )
        for linha in ausentes:
            for coluna in gerar_dados_demo.COLUNAS_RESULTADO:
                self.assertIsNone(linha[coluna])

    def test_google_tem_resultado_inteiramente_null(self):
        google = [l for l in self.linhas if l["plataforma"] == "Google Ads"]
        self.assertTrue(google)
        for linha in google:
            for coluna in gerar_dados_demo.COLUNAS_RESULTADO:
                with self.subTest(coluna=coluna):
                    self.assertIsNone(linha[coluna])

    def test_zero_typed_nao_vira_ausencia_nem_ganha_custo(self):
        zeros = [
            linha for linha in self.linhas
            if linha["result_type"] is not None and linha["result_count"] == 0
        ]
        self.assertTrue(zeros)
        for linha in zeros:
            self.assertIsNone(linha["cost_per_result"])
            self.assertIsNone(linha["result_attribution_window"])

    def test_custo_factual_e_spend_dividido_por_result_count(self):
        positivas = [
            linha for linha in self.linhas
            if linha["result_count"] is not None and linha["result_count"] > 0
        ]
        self.assertTrue(positivas)
        for linha in positivas:
            esperado = (linha["spend"] / linha["result_count"]).quantize(
                Decimal("0.00000001")
            )
            self.assertEqual(linha["cost_per_result"], esperado)

    def test_tipos_sinteticos_sao_os_do_contrato_real(self):
        tipos = {l["result_type"] for l in self.linhas if l["result_type"]}
        self.assertEqual(tipos, {
            gerar_dados_demo.RESULTADO_LEAD,
            gerar_dados_demo.RESULTADO_THRUPLAY,
        })
        self.assertTrue(tipos <= set(m.ROTULOS_RESULTADO))

    def test_campanhas_exercitam_resultado_agregavel_e_ausencia(self):
        por_campanha: dict[str, list[dict]] = {}
        for linha in self.linhas:
            if linha["plataforma"] == "Meta Ads":
                por_campanha.setdefault(linha["campanha_id"], []).append(linha)

        agregaveis = []
        ausentes = []
        for linhas in por_campanha.values():
            resultado = m.resultado_campanha(linhas)
            if resultado["status_resultado"] == m.RESULTADO_DISPONIVEL:
                agregaveis.append((linhas, resultado))
            elif resultado["status_resultado"] == m.RESULTADO_AUSENTE:
                ausentes.append(resultado)

        self.assertTrue(agregaveis)
        self.assertTrue(ausentes)
        linhas, resultado = next(
            par for par in agregaveis if par[1]["result_count"] > 0
        )
        gasto = sum((l["spend"] for l in linhas), Decimal(0))
        self.assertEqual(
            resultado["cost_per_result"],
            gasto / resultado["result_count"],
        )

    def test_null_serializa_como_campo_vazio(self):
        lidas = list(csv.DictReader(io.StringIO(self.texto)))
        google = next(l for l in lidas if l["plataforma"] == "Google Ads")
        for coluna in gerar_dados_demo.COLUNAS_RESULTADO:
            self.assertEqual(google[coluna], "")
        for inventado in (",None,", ",null,", ",N/A,"):
            self.assertNotIn(inventado, self.texto)

    def test_manifesto_cobre_schema_hash_e_natureza(self):
        self.assertEqual(
            set(self.manifesto["tipos"]), set(gerar_dados_demo.COLUNAS)
        )
        self.assertEqual(self.manifesto["linhas"], len(self.linhas))
        self.assertIn("FICTICIOS", self.manifesto["natureza"])

    def test_geracao_em_diretorio_temporario_carrega_v3(self):
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp)
            self.assertEqual(
                gerar_dados_demo.gerar(destino), len(self.linhas)
            )
            dataset = dados.carregar(
                dados.Fonte(destino / "metricas.csv", dados.MODO_DEMONSTRACAO)
            )

        self.assertEqual(len(dataset.linhas), len(self.linhas))
        self.assertFalse(dataset.colunas_ignoradas)
        self.assertTrue(any(l["result_type"] for l in dataset.linhas))

    def test_geracao_resultado_e_deterministica(self):
        novamente = gerar_dados_demo.serializar_csv(
            gerar_dados_demo.gerar_linhas()
        )
        self.assertEqual(self.texto, novamente)


class TestDatasetDeDemonstracao(unittest.TestCase):
    """O dataset sintetico versionado respeita o mesmo contrato."""

    @classmethod
    def setUpClass(cls):
        cls.caminho = dados.CAMINHO_DEMONSTRACAO
        if not cls.caminho.is_file():
            raise unittest.SkipTest("dataset de demonstracao nao gerado")
        cls.dataset = dados.carregar(
            dados.Fonte(cls.caminho, dados.MODO_DEMONSTRACAO)
        )

    def test_carrega_sob_o_contrato_de_exposicao(self):
        self.assertGreater(len(self.dataset.linhas), 0)
        self.assertEqual(self.dataset.colunas_ignoradas, ())

    def test_arquivo_versionado_declara_v3_com_resultado(self):
        self.assertEqual(self.dataset.manifesto.get("versao_contrato"), 3)
        self.assertEqual(
            self.dataset.manifesto.get("colunas"), CABECALHO_RESULTADO
        )
        self.assertTrue(any(l["result_type"] for l in self.dataset.linhas))

    def test_tem_as_duas_plataformas(self):
        resumo = dados.resumo(self.dataset)
        self.assertEqual(resumo["plataformas"], ["Google Ads", "Meta Ads"])

    def test_cobre_dias_suficientes_para_comparar_periodos(self):
        resumo = dados.resumo(self.dataset)
        self.assertGreaterEqual(resumo["dias"], 14)

    def test_tem_varias_entidades_em_cada_nivel(self):
        resumo = dados.resumo(self.dataset)
        for nivel in ("contas", "campanhas", "adsets", "anuncios"):
            with self.subTest(nivel=nivel):
                self.assertGreaterEqual(resumo[nivel], 2)

    def test_tem_entidade_com_duas_versoes_scd2(self):
        resumo = dados.resumo(self.dataset)
        self.assertTrue(
            any(resumo["entidades_multiversao"].values()),
            "o dataset de demonstracao precisa exercitar a coluna de versao",
        )

    def test_grao_de_anuncio_por_dia_e_unico(self):
        graos = {
            (linha["anuncio_id"], linha["data"])
            for linha in self.dataset.linhas
        }
        self.assertEqual(len(graos), len(self.dataset.linhas))

    def test_hierarquia_tem_um_unico_pai_por_filho(self):
        for pai, filho in (("conta", "campanha"), ("campanha", "adset"),
                           ("adset", "anuncio")):
            with self.subTest(nivel=filho):
                mapa: dict = {}
                for linha in self.dataset.linhas:
                    mapa.setdefault(linha[f"{filho}_id"], set()).add(
                        linha[f"{pai}_id"]
                    )
                self.assertFalse(
                    [v for v in mapa.values() if len(v) > 1]
                )

    def test_reproduz_a_ausencia_de_suporte_do_google(self):
        for linha in self.dataset.linhas:
            if linha["plataforma"] != "Google Ads":
                continue
            for metrica in ("reach", "profile_views", "purchases",
                        "purchase_value"):
                self.assertEqual(linha[metrica], Decimal(0))

    def test_manifesto_declara_natureza_ficticia(self):
        self.assertEqual(self.dataset.manifesto.get("modo"), "demonstracao")
        self.assertIn("FICTICIOS", self.dataset.manifesto.get("natureza", ""))

    def test_manifesto_nao_declara_fingerprint_de_chave(self):
        # Nenhuma chave de pseudonimizacao participou da geracao. O campo
        # existe (o auditor o exige) e sai nulo, para nao sugerir procedencia
        # que nao existe.
        self.assertIn("fingerprint_chave", self.dataset.manifesto)
        self.assertIsNone(self.dataset.manifesto["fingerprint_chave"])

    def test_passa_no_auditor_independente_da_superficie_real(self):
        # `scripts/auditar_dataset_exposicao.py` nao importa nada do
        # dashboard: submeter o dataset sintetico a ele prova o contrato em
        # vez de afirma-lo.
        try:
            import config  # noqa: F401
        except ImportError:
            self.skipTest("dependencias do auditor ausentes neste ambiente")

        ambiente = dict(os.environ, PYTHONPATH=str(BASE_DIR))
        resultado = subprocess.run(
            [
                sys.executable,
                "scripts/auditar_dataset_exposicao.py",
                "--sem-dw",
                "--diretorio", "dashboard/dados_demo",
            ],
            cwd=str(BASE_DIR), env=ambiente,
            capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(
            resultado.returncode, 0,
            resultado.stdout + resultado.stderr,
        )

    def test_geracao_e_deterministica(self):
        primeira = gerar_dados_demo.serializar_csv(
            gerar_dados_demo.gerar_linhas()
        )
        segunda = gerar_dados_demo.serializar_csv(
            gerar_dados_demo.gerar_linhas()
        )
        self.assertEqual(primeira, segunda)

    def test_arquivo_versionado_esta_em_dia_com_o_gerador(self):
        gerado = gerar_dados_demo.serializar_csv(
            gerar_dados_demo.gerar_linhas()
        )
        self.assertEqual(
            gerado, self.caminho.read_text(encoding="utf-8"),
            "regere com `python dashboard/gerar_dados_demo.py`",
        )

    def test_identificadores_nao_dependem_de_entrada_real(self):
        # A entrada do hash e o indice sequencial da entidade sintetica.
        self.assertEqual(
            gerar_dados_demo.identificador("conta", 1),
            gerar_dados_demo.identificador("conta", 1),
        )
        self.assertNotEqual(
            gerar_dados_demo.identificador("conta", 1),
            gerar_dados_demo.identificador("campanha", 1),
        )


class CSVComResultado:
    """Atalhos para as suites que leem o cabecalho com os campos de Resultado.

    Os dois metodos existiam copiados em sete classes, com corpo identico —
    conferido por AST, nao por semelhanca de nome. Sao encaminhamentos de uma
    linha para `carregar`/`linha_csv_resultado`, que ja sao a fabrica
    compartilhada do modulo: nao embutem cenario, nao escolhem valor e nao
    escondem expectativa. Por isso podem ser centralizados sem tornar os
    testes menos legiveis — o cenario continua escrito no proprio teste.

    E um mixin, e nao funcoes de modulo, para que as 49 chamadas existentes
    (`self._carregar(...)`, `self._linha(...)`) continuem identicas: a
    consolidacao nao deve aparecer no corpo de teste nenhum.
    """

    def _carregar(self, linhas: list[list[str]]) -> list[dict]:
        """Carrega linhas ja montadas sob o cabecalho com Resultado.

        Args:
            linhas: Linhas de CSV, cada uma como lista de campos.

        Returns:
            Linhas tipadas do dataset.
        """
        return carregar(linhas, CABECALHO_RESULTADO).linhas

    def _linha(self, **kwargs) -> dict:
        """Monta e carrega UMA linha Meta de 2026-08-01.

        Args:
            **kwargs: Campos repassados a `linha_csv_resultado`.

        Returns:
            A linha tipada.
        """
        return carregar(
            [linha_csv_resultado("2026-08-01", "Meta Ads", **kwargs)],
            CABECALHO_RESULTADO,
        ).linhas[0]


class TestResultadoPorCampanha(CSVComResultado, unittest.TestCase):
    """Resultado Meta e agregado somente para um tipo/janela validado."""

    def _lead(self, custo_um: str = "99", custo_dois: str = "1") -> list[dict]:
        return self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", spend="100.00", conversions="4",
                result_type="actions:offsite_conversion.fb_pixel_lead", result_count="4",
                result_attribution_window="default",
                cost_per_result=custo_um,
            ),
            linha_csv_resultado(
                "2026-08-02", "Meta Ads", spend="38.20", conversions="5",
                anuncio="Anuncio-AAAA0002", result_type="actions:offsite_conversion.fb_pixel_lead",
                result_count="5", result_attribution_window="default",
                cost_per_result=custo_dois,
            ),
        ])

    def test_campanha_lead_soma_resultado_e_recalcula_custo(self):
        resultado = m.resultado_campanha(self._lead())
        self.assertEqual(resultado["result_count"], Decimal(9))
        self.assertEqual(resultado["tipo_resultado"], "Lead")
        self.assertEqual(
            resultado["cost_per_result"], Decimal("138.20") / Decimal(9)
        )

    def test_campanha_thruplay_reproduz_fixture_validado(self):
        linhas = self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", spend="34.05",
                result_type="video_thruplay_watched_actions",
                result_count="81", result_attribution_window="default",
                cost_per_result="0.42037037",
            ),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["result_count"], Decimal(81))
        self.assertEqual(resultado["tipo_resultado"], "ThruPlay")
        self.assertEqual(
            resultado["cost_per_result"], Decimal("34.05") / Decimal(81)
        )
        self.assertEqual(m.formatar(resultado["cost_per_result"], m.MOEDA), "R$ 0,42")

    def test_custo_agregado_nunca_e_soma_dos_custos_diarios(self):
        resultado = m.resultado_campanha(self._lead("10", "20"))
        self.assertNotEqual(resultado["cost_per_result"], Decimal(30))

    def test_custo_agregado_nunca_e_media_dos_custos_diarios(self):
        resultado = m.resultado_campanha(self._lead("10", "20"))
        self.assertNotEqual(resultado["cost_per_result"], Decimal(15))

    def test_custos_diarios_nao_alteram_razao_agregada(self):
        antes = m.resultado_campanha(self._lead("10", "20"))
        depois = m.resultado_campanha(self._lead("999", "0.01"))
        self.assertEqual(antes["cost_per_result"], depois["cost_per_result"])

    def test_multiplos_tipos_ficam_indisponiveis(self):
        linhas = self._lead()
        linhas[1]["result_type"] = "video_thruplay_watched_actions"
        resultado = m.resultado_campanha(linhas)
        self.assertIsNone(resultado["result_count"])
        self.assertIsNone(resultado["cost_per_result"])
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_MULTIPLOS)

    def test_multiplas_janelas_ficam_indisponiveis(self):
        linhas = self._lead()
        linhas[1]["result_attribution_window"] = "7d_click"
        resultado = m.resultado_campanha(linhas)
        self.assertIsNone(resultado["result_count"])
        self.assertIsNone(resultado["cost_per_result"])
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_MULTIPLOS)

    def test_sem_resultado_fica_indisponivel(self):
        linhas = self._carregar([
            linha_csv_resultado("2026-08-01", "Meta Ads", spend="10"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertIsNone(resultado["result_type"])
        self.assertIsNone(resultado["result_count"])
        self.assertIsNone(resultado["cost_per_result"])

    def test_indicator_desconhecido_nao_inventa_rotulo(self):
        linhas = self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", spend="10",
                result_type="indicator.nao_validado", result_count="2",
                result_attribution_window="default", cost_per_result="5",
            ),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(
            resultado["tipo_resultado"], m.RESULTADO_NAO_MAPEADO
        )
        self.assertIsNone(resultado["result_count"])
        self.assertIsNone(resultado["cost_per_result"])

    def test_google_nao_ganha_resultado_meta(self):
        linhas = self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Google Ads", spend="100", conversions="5",
                result_type="actions:offsite_conversion.fb_pixel_lead", result_count="5",
                result_attribution_window="default", cost_per_result="20",
            ),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["status_resultado"], m.RESULTADO_SEM_SUPORTE)
        self.assertIsNone(resultado["result_count"])
        self.assertIsNone(resultado["cost_per_result"])

    def test_cpl_lead_continua_igual_ao_custo_por_resultado(self):
        linhas = self._lead()
        custo_resultado = m.resultado_campanha(linhas)["cost_per_result"]
        cpl = m.painel(linhas)["cpl_meta"]
        self.assertEqual(custo_resultado, cpl)

    def test_reach_continua_nao_aditivo(self):
        linhas = self._lead()
        linhas[0]["reach"] = Decimal(100)
        linhas[1]["reach"] = Decimal(80)
        self.assertIsNone(m.agregar(linhas)["reach"])

    def test_tabela_de_campanhas_declara_as_tres_novas_colunas(self):
        fonte = (BASE_DIR / "dashboard" / "app.py").read_text(encoding="utf-8")
        for coluna in ("Resultado", "Tipo de resultado", "Custo por resultado"):
            with self.subTest(coluna=coluna):
                self.assertIn(f'"{coluna}"', fonte)


class TestFormasReaisDeResultado(CSVComResultado, unittest.TestCase):
    """Formas que a Meta realmente devolve, medidas no bloco 2026-08-01..07.

    Cobrem os rotulos dos indicators observados, a quantidade zero legitima e
    os dois estados da janela de atribuicao. Nenhuma delas pode virar
    interpretacao de negocio inventada na camada de apresentacao.
    """

    def test_indicators_de_lead_observados_recebem_rotulo_lead(self):
        for indicator in ("actions:offsite_conversion.fb_pixel_lead",
                          "actions:onsite_conversion.lead_grouped"):
            with self.subTest(indicator=indicator):
                self.assertEqual(m.ROTULOS_RESULTADO[indicator], "Lead")

    def test_conversa_iniciada_nao_e_lead(self):
        indicator = "actions:onsite_conversion.messaging_conversation_started_7d"
        self.assertNotIn(indicator, m.ROTULOS_RESULTADO)
        linhas = self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", spend="10",
                result_type=indicator, result_count="3",
                result_attribution_window="default", cost_per_result="3.33",
            ),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_NAO_MAPEADO)
        self.assertIsNone(resultado["result_count"])

    def test_thruplay_mantem_rotulo(self):
        self.assertEqual(
            m.ROTULOS_RESULTADO["video_thruplay_watched_actions"], "ThruPlay"
        )

    def test_indicator_desconhecido_estruturalmente_valido_e_nao_mapeado(self):
        linhas = self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", spend="10",
                result_type="profile_visit_view", result_count="78",
                cost_per_result="0.09551282",
            ),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_NAO_MAPEADO)
        self.assertEqual(resultado["status_resultado"], m.RESULTADO_DESCONHECIDO)
        self.assertEqual(resultado["result_type"], "profile_visit_view")

    def test_dia_com_zero_resultado_ainda_contribui_com_investimento(self):
        linhas = self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", spend="10",
                result_type="actions:offsite_conversion.fb_pixel_lead",
                result_count="0", result_attribution_window="default",
            ),
            linha_csv_resultado(
                "2026-08-02", "Meta Ads", spend="10",
                anuncio="Anuncio-AAAA0002",
                result_type="actions:offsite_conversion.fb_pixel_lead",
                result_count="2", result_attribution_window="default",
                cost_per_result="5",
            ),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["result_count"], Decimal(2))
        # 20 / 2, nao 10 / 2: o dia sem resultado gastou e continua no
        # numerador.
        self.assertEqual(resultado["cost_per_result"], Decimal(10))
        self.assertNotEqual(resultado["cost_per_result"], Decimal(5))

    def test_janela_null_em_todas_as_linhas_continua_agregavel(self):
        linhas = self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", spend="10",
                result_type="video_thruplay_watched_actions",
                result_count="40", cost_per_result="0.25",
            ),
            linha_csv_resultado(
                "2026-08-02", "Meta Ads", spend="30",
                anuncio="Anuncio-AAAA0002",
                result_type="video_thruplay_watched_actions",
                result_count="60", cost_per_result="0.5",
            ),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertIsNone(resultado["result_attribution_window"])
        self.assertEqual(resultado["result_count"], Decimal(100))
        self.assertEqual(resultado["tipo_resultado"], "ThruPlay")
        self.assertEqual(
            resultado["cost_per_result"], Decimal(40) / Decimal(100)
        )

    def test_janela_null_misturada_com_explicita_fica_indisponivel(self):
        linhas = self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", spend="10",
                result_type="video_thruplay_watched_actions",
                result_count="40", cost_per_result="0.25",
            ),
            linha_csv_resultado(
                "2026-08-02", "Meta Ads", spend="30",
                anuncio="Anuncio-AAAA0002",
                result_type="video_thruplay_watched_actions",
                result_count="60", result_attribution_window="default",
                cost_per_result="0.5",
            ),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_MULTIPLOS)
        self.assertEqual(resultado["status_resultado"], m.RESULTADO_INCOMPATIVEL)
        self.assertIsNone(resultado["result_count"])
        self.assertIsNone(resultado["cost_per_result"])

    def test_custo_factual_ausente_nao_vira_zero_na_interface(self):
        linha = self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", spend="10",
                result_type="video_thruplay_watched_actions",
                result_count="0",
            ),
        ])[0]
        self.assertIsNone(linha["cost_per_result"])
        self.assertEqual(linha["result_count"], Decimal(0))
        self.assertEqual(m.formatar(linha["cost_per_result"], m.MOEDA),
                         m.INDISPONIVEL)

        agregado = m.resultado_campanha([linha])
        self.assertIsNone(agregado["cost_per_result"])
        self.assertEqual(m.formatar(agregado["cost_per_result"], m.MOEDA),
                         m.INDISPONIVEL)

    def test_reach_continua_nao_aditivo_com_as_formas_novas(self):
        linhas = self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", spend="10", reach="100",
                result_type="reach", result_count="100", cost_per_result="0.1",
            ),
            linha_csv_resultado(
                "2026-08-02", "Meta Ads", spend="10", reach="80",
                anuncio="Anuncio-AAAA0002",
                result_type="reach", result_count="80", cost_per_result="0.125",
            ),
        ])
        self.assertIsNone(m.agregar(linhas)["reach"])


class TestContratoDasFormasReais(CSVComResultado, unittest.TestCase):
    """O CSV aceita janela e custo vazios, e so nas condicoes da Silver."""

    def test_janela_vazia_e_aceita_como_ausencia(self):
        linha = self._linha(
            result_type="profile_visit_view", result_count="78",
            cost_per_result="0.09551282",
        )
        self.assertIsNone(linha["result_attribution_window"])
        self.assertEqual(linha["result_count"], Decimal(78))

    def test_custo_vazio_com_quantidade_zero_e_aceito(self):
        linha = self._linha(
            result_type="video_thruplay_watched_actions", result_count="0",
            result_attribution_window="default",
        )
        self.assertEqual(linha["result_count"], Decimal(0))
        self.assertIsNone(linha["cost_per_result"])

    def test_custo_vazio_com_quantidade_positiva_falha_fechado(self):
        with self.assertRaises(dados.ContratoInvalido):
            self._linha(
                result_type="video_thruplay_watched_actions", result_count="5",
                result_attribution_window="default",
            )

    def test_quantidade_vazia_com_tipo_presente_falha_fechado(self):
        with self.assertRaises(dados.ContratoInvalido):
            self._linha(
                result_type="video_thruplay_watched_actions",
                result_attribution_window="default", cost_per_result="1",
            )

    def test_valor_sem_tipo_falha_fechado(self):
        with self.assertRaises(dados.ContratoInvalido):
            self._linha(result_count="5", cost_per_result="1")


class TestAusenciaTotalNaAgregacao(CSVComResultado, unittest.TestCase):
    """Ausencia total nao herda o Resultado observado em outro dia.

    Medicao do bloco real 2026-08-01..07: 56 campanhas, 17 apenas com ausencia
    total, 39 apenas com Resultado observado, intersecao ZERO. Nao ha uma unica
    campanha real em que a inferencia entre dias pudesse ser verificada — entao
    ela nao existe, e o recorte misto falha semanticamente fechado.
    """

    LEAD: str = "actions:offsite_conversion.fb_pixel_lead"

    def _ausente(self, data: str, anuncio: str, spend: str) -> list[str]:
        """Linha de ausencia total: a Meta nao devolveu results nem custo."""
        return linha_csv_resultado(
            data, "Meta Ads", spend=spend, anuncio=anuncio,
        )

    def _tipada(self, data: str, anuncio: str, spend: str, tipo: str,
                quantidade: str, custo: str = "",
                janela: str = "default") -> list[str]:
        return linha_csv_resultado(
            data, "Meta Ads", spend=spend, anuncio=anuncio,
            result_type=tipo, result_count=quantidade,
            result_attribution_window=janela, cost_per_result=custo,
        )

    # 2 — so ausencia total.
    def test_campanha_so_com_ausencia_total_fica_indisponivel(self):
        linhas = self._carregar([
            self._ausente("2026-08-01", "Anuncio-AAAA0001", "10"),
            self._ausente("2026-08-02", "Anuncio-AAAA0002", "20"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["status_resultado"], m.RESULTADO_AUSENTE)
        self.assertIsNone(resultado["result_type"])
        self.assertIsNone(resultado["result_count"])
        self.assertIsNone(resultado["cost_per_result"])
        self.assertIsNone(resultado["tipo_resultado"])

    # 3 — ausencia total + Lead.
    def test_ausencia_total_com_lead_fica_incompleto(self):
        linhas = self._carregar([
            self._ausente("2026-08-01", "Anuncio-AAAA0001", "10"),
            self._tipada("2026-08-02", "Anuncio-AAAA0002", "20",
                         self.LEAD, "4", "5"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_INCOMPLETO)
        self.assertEqual(resultado["status_resultado"], m.RESULTADO_PARCIAL)
        self.assertIsNone(resultado["result_count"])
        self.assertIsNone(resultado["cost_per_result"])
        self.assertIsNone(resultado["result_type"])

    # 4 — ausencia total + ThruPlay.
    def test_ausencia_total_com_thruplay_fica_incompleto(self):
        linhas = self._carregar([
            self._ausente("2026-08-01", "Anuncio-AAAA0001", "10"),
            self._tipada("2026-08-02", "Anuncio-AAAA0002", "20",
                         "video_thruplay_watched_actions", "40", "0.5"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_INCOMPLETO)
        self.assertEqual(resultado["status_resultado"], m.RESULTADO_PARCIAL)
        self.assertIsNone(resultado["result_count"])
        self.assertIsNone(resultado["cost_per_result"])

    # 5 — ausencia total + dois tipos.
    def test_ausencia_total_com_dois_tipos_fica_indisponivel(self):
        linhas = self._carregar([
            self._ausente("2026-08-01", "Anuncio-AAAA0001", "10"),
            self._tipada("2026-08-02", "Anuncio-AAAA0002", "20",
                         self.LEAD, "4", "5"),
            self._tipada("2026-08-03", "Anuncio-AAAA0003", "30",
                         "video_thruplay_watched_actions", "40", "0.75"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertIsNone(resultado["result_count"])
        self.assertIsNone(resultado["cost_per_result"])
        # O defeito mais grave e a falta de contrato, nao a multiplicidade.
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_INCOMPLETO)

    def test_investimento_sem_tipo_nunca_entra_no_denominador_alheio(self):
        # O caso que a auditoria pegou: 20 de gasto sem tipo, ao lado de 4
        # Leads em outro dia, produziria "R$ 7,50 por Lead" por inferencia.
        linhas = self._carregar([
            self._ausente("2026-08-01", "Anuncio-AAAA0001", "20"),
            self._tipada("2026-08-02", "Anuncio-AAAA0002", "10",
                         self.LEAD, "4", "2.5"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertIsNone(resultado["cost_per_result"])
        self.assertNotEqual(resultado["cost_per_result"], Decimal("7.5"))

    # 10 — FORMA A nao e ausencia total.
    def test_forma_a_nao_e_tratada_como_ausencia_total(self):
        linhas = self._carregar([
            self._tipada("2026-08-01", "Anuncio-AAAA0001", "10",
                         self.LEAD, "0"),
            self._tipada("2026-08-02", "Anuncio-AAAA0002", "10",
                         self.LEAD, "2", "5"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], "Lead")
        self.assertNotEqual(
            resultado["tipo_resultado"], m.RESULTADO_INCOMPLETO
        )
        self.assertEqual(resultado["result_count"], Decimal(2))
        # 20 / 2: a linha da FORMA A declarou o tipo e o gasto dela conta.
        self.assertEqual(resultado["cost_per_result"], Decimal(10))

    def test_forma_a_isolada_declara_tipo_com_quantidade_zero(self):
        linhas = self._carregar([
            self._tipada("2026-08-01", "Anuncio-AAAA0001", "10",
                         self.LEAD, "0"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["result_type"], self.LEAD)
        self.assertEqual(resultado["result_count"], Decimal(0))
        self.assertNotEqual(resultado["status_resultado"], m.RESULTADO_AUSENTE)
        # Denominador zero: custo indisponivel, nunca zero nem divisao.
        self.assertIsNone(resultado["cost_per_result"])

    # 11 — quantidade ausente nunca vira zero.
    def test_quantidade_ausente_nao_vira_zero(self):
        linhas = self._carregar([
            self._tipada("2026-08-01", "Anuncio-AAAA0001", "10",
                         self.LEAD, "4", "2.5"),
        ])
        # Estado que o contrato do CSV ja recusa; a defesa fica no agregado.
        linhas.append({**linhas[0], "result_count": None,
                       "anuncio_id": "Anuncio-AAAA0002"})
        resultado = m.resultado_campanha(linhas)
        self.assertIsNone(resultado["result_count"])
        self.assertNotEqual(resultado["result_count"], Decimal(0))
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_INCOMPLETO)

    # 12 — zero declarado permanece zero.
    def test_zero_declarado_permanece_zero(self):
        linha = self._carregar([
            self._tipada("2026-08-01", "Anuncio-AAAA0001", "10",
                         self.LEAD, "0"),
        ])[0]
        self.assertEqual(linha["result_count"], Decimal(0))
        self.assertIsNotNone(linha["result_count"])

    def test_ausencia_total_deixa_todos_os_campos_nulos_na_linha(self):
        linha = self._carregar([
            self._ausente("2026-08-01", "Anuncio-AAAA0001", "10"),
        ])[0]
        for campo in ("result_type", "result_count",
                      "result_attribution_window", "cost_per_result"):
            with self.subTest(campo=campo):
                self.assertIsNone(linha[campo])

    def test_objetivo_da_campanha_nao_infere_tipo_de_resultado(self):
        # OUTCOME_LEADS / LEAD_GENERATION sao contexto, nao contrato: nao
        # existe coluna deles na superficie, e a agregacao nao pode inventa-la.
        fonte = (BASE_DIR / "dashboard" / "metricas.py").read_text(
            encoding="utf-8"
        )
        corpo = fonte.split("def resultado_campanha(")[1]
        corpo = corpo.split("\ndef ")[0]
        for termo in ("objective", "optimization_goal", "OUTCOME_LEADS",
                      "LEAD_GENERATION", "campaign_name"):
            with self.subTest(termo=termo):
                self.assertNotIn(f'"{termo}"', corpo)
                self.assertNotIn(f"'{termo}'", corpo)


class TestJanelaNeutraEmResultadoZero(CSVComResultado, unittest.TestCase):
    """O NULL de janela da FORMA A e neutro, nao uma segunda semantica.

    Medido no bloco real de 2026-08-01..07: tratar os dois NULLs como iguais
    tornava 20 das 39 campanhas tipadas artificialmente incompativeis. Todas as
    20 tinham um unico result_type e nenhuma FORMA B — a segunda "janela" era o
    NULL de linhas de FORMA A ao lado de linhas com janela explicita.
    """

    LEAD: str = "actions:offsite_conversion.fb_pixel_lead"
    THRU: str = "video_thruplay_watched_actions"

    def _forma_a(self, data: str, anuncio: str, spend: str,
                 tipo: str | None = None) -> list[str]:
        """Tipo declarado, sem quantidade, sem custo e sem janela."""
        return linha_csv_resultado(
            data, "Meta Ads", spend=spend, anuncio=anuncio,
            result_type=tipo or self.LEAD, result_count="0",
        )

    def _forma_b(self, data: str, anuncio: str, spend: str, quantidade: str,
                 custo: str, tipo: str | None = None) -> list[str]:
        """Quantidade e custo presentes; a fonte nao aplica janela ao tipo."""
        return linha_csv_resultado(
            data, "Meta Ads", spend=spend, anuncio=anuncio,
            result_type=tipo or self.LEAD, result_count=quantidade,
            cost_per_result=custo,
        )

    def _explicita(self, data: str, anuncio: str, spend: str, quantidade: str,
                   custo: str = "", janela: str = "default",
                   tipo: str | None = None) -> list[str]:
        return linha_csv_resultado(
            data, "Meta Ads", spend=spend, anuncio=anuncio,
            result_type=tipo or self.LEAD, result_count=quantidade,
            result_attribution_window=janela, cost_per_result=custo,
        )

    # 1, 2, 3 e 13 — o caso central medido no bloco real.
    def test_forma_a_com_janela_explicita_agrega(self):
        linhas = self._carregar([
            self._forma_a("2026-08-01", "Anuncio-AAAA0001", "10"),
            self._explicita("2026-08-02", "Anuncio-AAAA0002", "10", "2", "5"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["status_resultado"], m.RESULTADO_DISPONIVEL)
        self.assertEqual(resultado["tipo_resultado"], "Lead")
        self.assertEqual(resultado["result_count"], Decimal(2))
        # A janela efetiva vem SO da linha que a declarou.
        self.assertEqual(resultado["result_attribution_window"], "default")
        # 20 / 2 = 10, nao 10 / 2 = 5: o spend da linha neutra conta.
        self.assertEqual(resultado["cost_per_result"], Decimal(10))
        self.assertNotEqual(resultado["cost_per_result"], Decimal(5))

    def test_forma_a_nao_cria_segunda_janela(self):
        linhas = self._carregar([
            self._forma_a("2026-08-01", "Anuncio-AAAA0001", "10"),
            self._explicita("2026-08-02", "Anuncio-AAAA0002", "10", "2", "5"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertNotEqual(resultado["tipo_resultado"], m.RESULTADO_MULTIPLOS)
        self.assertNotEqual(
            resultado["status_resultado"], m.RESULTADO_INCOMPATIVEL
        )

    def test_linha_neutra_nao_ganha_janela_imputada(self):
        # A neutralidade vive no agregado. O grao factual permanece NULL.
        linha = self._carregar([
            self._forma_a("2026-08-01", "Anuncio-AAAA0001", "10"),
        ])[0]
        self.assertIsNone(linha["result_attribution_window"])
        self.assertIsNone(linha["cost_per_result"])
        self.assertEqual(linha["result_count"], Decimal(0))
        self.assertFalse(m.janela_informativa(linha))

    # 4 — varias neutras e uma informativa.
    def test_varias_formas_a_com_uma_explicita_agregam(self):
        linhas = self._carregar([
            self._forma_a("2026-08-01", "Anuncio-AAAA0001", "10"),
            self._forma_a("2026-08-02", "Anuncio-AAAA0002", "10"),
            self._forma_a("2026-08-03", "Anuncio-AAAA0003", "10"),
            self._explicita("2026-08-04", "Anuncio-AAAA0004", "10", "5", "2"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["status_resultado"], m.RESULTADO_DISPONIVEL)
        self.assertEqual(resultado["result_count"], Decimal(5))
        self.assertEqual(resultado["result_attribution_window"], "default")
        self.assertEqual(resultado["cost_per_result"], Decimal(40) / Decimal(5))

    # 5 — recorte inteiramente neutro.
    def test_somente_forma_a_agrega_com_zero_e_custo_indisponivel(self):
        linhas = self._carregar([
            self._forma_a("2026-08-01", "Anuncio-AAAA0001", "10"),
            self._forma_a("2026-08-02", "Anuncio-AAAA0002", "25"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["status_resultado"], m.RESULTADO_DISPONIVEL)
        self.assertEqual(resultado["tipo_resultado"], "Lead")
        self.assertEqual(resultado["result_count"], Decimal(0))
        self.assertIsNone(resultado["result_attribution_window"])
        # Nao ha resultado para dividir; o spend nao some, so nao tem divisor.
        self.assertIsNone(resultado["cost_per_result"])

    # 6 — FORMA B continua informativa.
    def test_forma_b_com_explicita_continua_incompativel(self):
        linhas = self._carregar([
            self._forma_b("2026-08-01", "Anuncio-AAAA0001", "10", "2", "5"),
            self._explicita("2026-08-02", "Anuncio-AAAA0002", "10", "2", "5"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_MULTIPLOS)
        self.assertEqual(resultado["status_resultado"], m.RESULTADO_INCOMPATIVEL)
        self.assertIsNone(resultado["result_count"])
        self.assertIsNone(resultado["cost_per_result"])

    def test_forma_b_isolada_e_informativa(self):
        linha = self._carregar([
            self._forma_b("2026-08-01", "Anuncio-AAAA0001", "10", "2", "5"),
        ])[0]
        self.assertTrue(m.janela_informativa(linha))

    # 7 — zero declarado COM janela explicita continua informativo.
    def test_quantidade_zero_com_janela_explicita_participa(self):
        linha = self._carregar([
            self._explicita("2026-08-01", "Anuncio-AAAA0001", "10", "0"),
        ])[0]
        self.assertEqual(linha["result_count"], Decimal(0))
        self.assertIsNone(linha["cost_per_result"])
        self.assertTrue(m.janela_informativa(linha))

    def test_zero_com_janela_explicita_choca_com_outra_explicita(self):
        linhas = self._carregar([
            self._explicita("2026-08-01", "Anuncio-AAAA0001", "10", "0"),
            self._explicita("2026-08-02", "Anuncio-AAAA0002", "10", "4", "2.5",
                            janela="7d_click"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["status_resultado"], m.RESULTADO_INCOMPATIVEL)
        self.assertIsNone(resultado["result_count"])

    # 8 — duas janelas explicitas.
    def test_duas_janelas_explicitas_ficam_indisponiveis(self):
        linhas = self._carregar([
            self._explicita("2026-08-01", "Anuncio-AAAA0001", "10", "2", "5"),
            self._explicita("2026-08-02", "Anuncio-AAAA0002", "10", "3", "3.33",
                            janela="7d_click"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_MULTIPLOS)
        self.assertIsNone(resultado["cost_per_result"])

    # 9 — neutra nao salva um recorte que ja e incompativel.
    def test_forma_a_com_duas_explicitas_continua_indisponivel(self):
        linhas = self._carregar([
            self._forma_a("2026-08-01", "Anuncio-AAAA0001", "10"),
            self._explicita("2026-08-02", "Anuncio-AAAA0002", "10", "2", "5"),
            self._explicita("2026-08-03", "Anuncio-AAAA0003", "10", "3", "3.33",
                            janela="7d_click"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_MULTIPLOS)
        self.assertIsNone(resultado["result_count"])

    # 10 e 11 — ausencia total nao virou linha neutra.
    def test_ausencia_total_com_tipada_continua_incompleto(self):
        linhas = self._carregar([
            linha_csv_resultado("2026-08-01", "Meta Ads", spend="10"),
            self._explicita("2026-08-02", "Anuncio-AAAA0002", "10", "2", "5"),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_INCOMPLETO)
        self.assertEqual(resultado["status_resultado"], m.RESULTADO_PARCIAL)
        self.assertIsNone(resultado["result_count"])

    def test_ausencia_total_nao_e_linha_neutra(self):
        ausente = self._carregar([
            linha_csv_resultado("2026-08-01", "Meta Ads", spend="10"),
        ])[0]
        neutra = self._carregar([
            self._forma_a("2026-08-01", "Anuncio-AAAA0001", "10"),
        ])[0]
        # As duas tem janela NULL, e so uma delas declara tipo e quantidade.
        self.assertIsNone(ausente["result_attribution_window"])
        self.assertIsNone(neutra["result_attribution_window"])
        self.assertIsNone(ausente["result_type"])
        self.assertIsNotNone(neutra["result_type"])
        self.assertIsNone(ausente["result_count"])
        self.assertEqual(neutra["result_count"], Decimal(0))

    # 12 — dois tipos continuam "Multiplos", nao "Dados incompletos".
    def test_dois_result_types_continuam_multiplos(self):
        linhas = self._carregar([
            self._explicita("2026-08-01", "Anuncio-AAAA0001", "10", "2", "5"),
            self._explicita("2026-08-02", "Anuncio-AAAA0002", "10", "4", "2.5",
                            tipo=self.THRU),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_MULTIPLOS)
        self.assertNotEqual(resultado["tipo_resultado"], m.RESULTADO_INCOMPLETO)

    def test_tipo_unico_com_neutra_precede_checagem_de_janela(self):
        # Dois tipos + uma neutra: o defeito e a multiplicidade de tipo, e a
        # neutralidade nao pode mascara-la.
        linhas = self._carregar([
            self._forma_a("2026-08-01", "Anuncio-AAAA0001", "10"),
            self._explicita("2026-08-02", "Anuncio-AAAA0002", "10", "2", "5"),
            self._explicita("2026-08-03", "Anuncio-AAAA0003", "10", "4", "2.5",
                            tipo=self.THRU),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_MULTIPLOS)


class TestMappingSinteticoRemovido(CSVComResultado, unittest.TestCase):
    """`lead` sem prefixo saiu do mapping; `actions[lead]` continua intacto."""

    def test_indicator_lead_sem_prefixo_nao_tem_rotulo(self):
        self.assertNotIn("lead", m.ROTULOS_RESULTADO)

    def test_indicator_lead_sem_prefixo_cai_em_nao_mapeado(self):
        linhas = self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", spend="10",
                result_type="lead", result_count="9",
                result_attribution_window="default", cost_per_result="1.11",
            ),
        ])
        resultado = m.resultado_campanha(linhas)
        self.assertEqual(resultado["tipo_resultado"], m.RESULTADO_NAO_MAPEADO)
        self.assertIsNone(resultado["result_count"])

    def test_conversions_meta_continua_vindo_de_actions_lead(self):
        # Regressao conceitual: `results[].indicator` e
        # `actions[].action_type` sao vocabularios diferentes. Remover o
        # rotulo do primeiro nao pode mexer no segundo, que e a origem de
        # `conversions` (e portanto do CPL) no Meta.
        modelo = (BASE_DIR / "dbt" / "models" / "silver"
                  / "stg_meta_ads.sql").read_text(encoding="utf-8")
        self.assertIn("'lead'", modelo)

        linhas = self._carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", spend="100", conversions="4",
                result_type="actions:offsite_conversion.fb_pixel_lead",
                result_count="4", result_attribution_window="default",
                cost_per_result="25",
            ),
        ])
        self.assertEqual(m.agregar(linhas)["conversions"], Decimal(4))
        self.assertEqual(m.painel(linhas)["cpl_meta"], Decimal(25))

    def test_fixture_sintetica_usa_indicator_real(self):
        bruto = (BASE_DIR / "tests" / "fixtures"
                 / "temp_meta_raw.json").read_text(encoding="utf-8")
        self.assertNotIn('"indicator": "lead"', bruto)
        self.assertIn(
            '"indicator": "actions:offsite_conversion.fb_pixel_lead"', bruto
        )
        # O action_type real continua sendo `lead` — nao foi migrado junto.
        self.assertIn('"action_type": "lead"', bruto)


class TestContratoOpcionalDeResultado(unittest.TestCase):
    """A v2 abre sem Resultado; a futura v3 entra inteira e tipada."""

    def test_superficie_v2_recebe_null_sem_inventar_zero(self):
        linha = carregar([linha_csv("2026-08-01", "Meta Ads")]).linhas[0]
        for campo in dados.COLUNAS_RESULTADO_OPCIONAIS:
            self.assertIsNone(linha[campo])

    def test_grupo_futuro_incompleto_falha_fechado(self):
        cabecalho = CABECALHO + ["result_type"]
        with self.assertRaises(dados.ContratoInvalido):
            carregar([linha_csv("2026-08-01", "Meta Ads") + ["actions:offsite_conversion.fb_pixel_lead"]], cabecalho)

    def test_v3_google_chega_com_resultado_nulo(self):
        # O Google nao fornece Resultado neste grao da GAQL. Campo vazio no
        # CSV v3 tem de virar None, nunca Decimal(0): zero e quantidade
        # declarada, e nao ha sequer tipo sobre o que afirmar.
        linha = carregar([
            linha_csv_resultado("2026-08-01", "Google Ads")
        ], CABECALHO_RESULTADO).linhas[0]
        for campo in dados.COLUNAS_RESULTADO_OPCIONAIS:
            with self.subTest(campo=campo):
                self.assertIsNone(linha[campo])

    def test_v3_meta_historico_chega_com_resultado_nulo(self):
        # As extracoes Meta anteriores a 01/08/2026 nao tinham `results` na
        # fonte. A linha existe no artefato v3 com os quatro campos vazios —
        # ausencia de contrato, nao ausencia de desempenho.
        linha = carregar([
            linha_csv_resultado("2026-07-15", "Meta Ads")
        ], CABECALHO_RESULTADO).linhas[0]
        for campo in dados.COLUNAS_RESULTADO_OPCIONAIS:
            with self.subTest(campo=campo):
                self.assertIsNone(linha[campo])

    def test_grupo_futuro_preserva_decimal(self):
        linha = carregar([
            linha_csv_resultado(
                "2026-08-01", "Meta Ads", result_type="actions:offsite_conversion.fb_pixel_lead",
                result_count="9", result_attribution_window="default",
                cost_per_result="15.35555556",
            )
        ], CABECALHO_RESULTADO).linhas[0]
        self.assertEqual(linha["result_count"], Decimal(9))
        self.assertEqual(linha["cost_per_result"], Decimal("15.35555556"))


class TestContratoTipadoDaLinha(CSVComResultado, unittest.TestCase):
    """`LinhaDataset` descreve o runtime — nao o modifica.

    O `TypedDict` e anotacao: a linha continua sendo um `dict` comum. Estes
    testes existem para que a anotacao nao possa divergir do que
    `dados._converter` realmente produz sem alguem perceber.
    """

    def test_linha_continua_sendo_dict(self):
        linha = self._linha()
        # TypedDict nao cria classe em runtime; se criasse, mudaria igualdade,
        # serializacao e indexacao de todo o dashboard.
        self.assertIs(type(linha), dict)

    def test_contrato_e_fechado(self):
        self.assertTrue(contratos.LinhaDataset.__total__)
        self.assertEqual(contratos.LinhaDataset.__optional_keys__, frozenset())

    def test_anotacao_cobre_exatamente_as_chaves_produzidas(self):
        produzidas = set(self._linha())
        anotadas = set(contratos.LinhaDataset.__annotations__)
        self.assertEqual(produzidas, anotadas)

    def test_contrato_cobre_o_cabecalho_v2_e_o_grupo_de_resultado(self):
        anotadas = set(contratos.LinhaDataset.__annotations__)
        for coluna in dados.COLUNAS_OBRIGATORIAS:
            with self.subTest(coluna=coluna):
                self.assertIn(coluna, anotadas)
        for coluna in dados.COLUNAS_RESULTADO_OPCIONAIS:
            with self.subTest(coluna=coluna):
                self.assertIn(coluna, anotadas)

    def test_chaves_de_resultado_existem_mesmo_na_superficie_v2(self):
        # Presente-com-None nao e o mesmo que ausente. A v2 nao traz as
        # colunas, e ainda assim as chaves existem — e por isso o contrato e
        # total em vez de usar NotRequired.
        linha = carregar([linha_csv("2026-08-01", "Meta Ads")]).linhas[0]
        for campo in dados.COLUNAS_RESULTADO_OPCIONAIS:
            with self.subTest(campo=campo):
                self.assertIn(campo, linha)
                self.assertIsNone(linha[campo])

    def test_metricas_nunca_sao_none(self):
        linha = self._linha()
        for metrica in dados.METRICAS:
            with self.subTest(metrica=metrica):
                self.assertIsNotNone(linha[metrica])
                self.assertIsInstance(linha[metrica], Decimal)

    def test_result_count_none_nao_virou_zero(self):
        # A anotacao `Decimal | None` existe justamente para preservar isto.
        linha = carregar([linha_csv("2026-08-01", "Meta Ads")]).linhas[0]
        self.assertIsNone(linha["result_count"])
        self.assertNotEqual(linha["result_count"], Decimal(0))

    def test_versoes_continuam_int_e_metricas_decimal(self):
        linha = self._linha()
        for nivel in dados.NIVEIS:
            with self.subTest(nivel=nivel):
                self.assertIs(type(linha[f"{nivel}_versao"]), int)
        self.assertIs(type(linha["spend"]), Decimal)
        self.assertIs(type(linha["data"]), date)

    def test_reach_nao_ganhou_coercao(self):
        # Tipar nao pode transformar ausencia em zero nem tornar reach aditivo.
        linhas = carregar([
            linha_csv_resultado("2026-08-01", "Meta Ads", reach="100"),
            linha_csv_resultado("2026-08-02", "Meta Ads", reach="80",
                                anuncio="Anuncio-AAAA0002"),
        ], CABECALHO_RESULTADO).linhas
        self.assertIsNone(m.agregar(linhas)["reach"])


class TestFronteiraDoContrato(unittest.TestCase):
    """O modulo de contrato precisa ficar na camada mais baixa do dashboard."""

    def _fonte(self) -> str:
        return (BASE_DIR / "dashboard" / "contratos.py").read_text(
            encoding="utf-8"
        )

    def test_contrato_so_depende_da_biblioteca_padrao(self):
        # Se ele importasse `dados` ou `metricas`, criaria ciclo; se importasse
        # modulo da raiz, quebraria a imagem do painel.
        importados = re.findall(
            r"^\s*(?:import|from)\s+([\w.]+)", self._fonte(), re.MULTILINE
        )
        self.assertEqual(
            sorted(importados), ["datetime", "decimal", "typing"]
        )

    def test_contrato_nao_cria_classe_em_runtime(self):
        fonte = self._fonte()
        for proibido in ("@dataclass", "NamedTuple", "BaseModel", "__init__"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, fonte)


class TestFronteiraDaFormatacao(unittest.TestCase):
    """Formatacao nao pode voltar a conhecer o catalogo de metricas.

    A fronteira e semantica: **escolher** o formato e decisao de metrica;
    **aplicar** o formato e apresentacao. Se `formatacao` passar a importar o
    catalogo, a separacao vira apenas dois arquivos em vez de duas
    responsabilidades.
    """

    def _fonte(self) -> str:
        return (BASE_DIR / "dashboard" / "formatacao.py").read_text(
            encoding="utf-8"
        )

    def test_formatacao_so_depende_da_biblioteca_padrao(self):
        importados = re.findall(
            r"^\s*(?:import|from)\s+([\w.]+)", self._fonte(), re.MULTILINE
        )
        self.assertEqual(sorted(importados), ["datetime", "decimal"])

    def test_formatacao_nao_conhece_o_catalogo(self):
        # Inspeciona o CODIGO, nao a prosa: a docstring do modulo cita
        # `spend`, `reach` e `plataforma` justamente para dizer que ele nao os
        # conhece. Um assert por substring reprovaria a propria explicacao.
        import ast

        arvore = ast.parse(self._fonte())
        nomes = {
            no.id for no in ast.walk(arvore) if isinstance(no, ast.Name)
        } | {
            no.attr for no in ast.walk(arvore) if isinstance(no, ast.Attribute)
        }
        for proibido in ("CATALOGO", "DERIVADAS", "PAINEL", "METRICAS",
                         "META", "GOOGLE", "suportada", "agregar"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, nomes)

        literais = {
            no.value for no in ast.walk(arvore)
            if isinstance(no, ast.Constant) and isinstance(no.value, str)
        }
        for chave in ("spend", "reach", "Meta Ads", "Google Ads"):
            with self.subTest(chave=chave):
                self.assertNotIn(chave, literais)

    def test_metricas_continua_sendo_a_fachada_do_painel(self):
        # ~50 chamadas em app.py, graficos.py e nos testes usam `m.<simbolo>`.
        # A extracao nao pode ter quebrado nenhuma delas.
        for simbolo in ("formatar", "formatar_variacao", "formatar_metrica",
                        "formatar_derivada", "formatar_painel",
                        "formatar_quantidade_resultado", "INDISPONIVEL",
                        "MOEDA", "INTEIRO", "DECIMAL", "PERCENTUAL",
                        "MULTIPLICADOR"):
            with self.subTest(simbolo=simbolo):
                self.assertTrue(hasattr(m, simbolo))

    def test_adaptadores_do_catalogo_ficaram_em_metricas(self):
        fonte_metricas = (BASE_DIR / "dashboard" / "metricas.py").read_text(
            encoding="utf-8"
        )
        for adaptador in ("def formatar_metrica(", "def formatar_derivada(",
                          "def formatar_painel(",
                          "def formatar_quantidade_resultado("):
            with self.subTest(adaptador=adaptador):
                self.assertIn(adaptador, fonte_metricas)

    def test_formatacao_e_metricas_expoem_a_mesma_funcao(self):
        from dashboard import formatacao
        self.assertIs(m.formatar, formatacao.formatar)
        self.assertIs(m.formatar_variacao, formatacao.formatar_variacao)


class TestPaginaSobreExtraida(unittest.TestCase):
    """A pagina "Sobre os dados" saiu do orquestrador, sem mudar a tela.

    `app.py` chama `main()` no import e por isso nao pode ser importado num
    teste — a inspecao dele continua sendo por AST sobre o fonte. `sobre.py`,
    ao contrario, importa sem efeito colateral, o que e ganho de testabilidade
    da propria extracao.
    """

    def _arvore_app(self):
        import ast
        return ast.parse(
            (BASE_DIR / "dashboard" / "app.py").read_text(encoding="utf-8")
        )

    def _arvore_sobre(self):
        import ast
        return ast.parse(
            (BASE_DIR / "dashboard" / "sobre.py").read_text(encoding="utf-8")
        )

    def _importados(self, arvore) -> set[str]:
        import ast
        nomes = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                nomes.update(a.name for a in no.names)
            elif isinstance(no, ast.ImportFrom):
                nomes.add(no.module or "")
                nomes.update(f"{no.module}.{a.name}" for a in no.names)
        return nomes

    def test_dependencia_e_de_mao_unica(self):
        # O orquestrador conhece a pagina; a pagina nao conhece o orquestrador.
        self.assertIn("dashboard.sobre", self._importados(self._arvore_app()))
        importados_sobre = self._importados(self._arvore_sobre())
        for proibido in ("dashboard.app", "app", "dashboard.app.main"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, importados_sobre)

    def test_sobre_nao_importa_a_raiz_do_projeto(self):
        importados = self._importados(self._arvore_sobre())
        for proibido in ("config", "plataformas", "janela", "manifesto",
                         "pseudonimos", "psycopg2", "sqlalchemy"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, importados)

    def test_sobre_importa_sem_efeito_colateral(self):
        # Diferente de `app.py`, importar a pagina nao desenha nada nem chama
        # `main()`. Se algum dia passar a chamar, este teste quebra.
        import ast
        arvore = self._arvore_sobre()
        chamadas_topo = [
            no for no in arvore.body
            if isinstance(no, ast.Expr) and isinstance(no.value, ast.Call)
        ]
        self.assertEqual(chamadas_topo, [])

    def test_a_funcao_saiu_de_app_e_esta_em_sobre(self):
        fonte_app = (BASE_DIR / "dashboard" / "app.py").read_text(
            encoding="utf-8"
        )
        fonte_sobre = (BASE_DIR / "dashboard" / "sobre.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("def pagina_sobre(", fonte_app)
        self.assertIn("def pagina_sobre(", fonte_sobre)
        # O despacho continua acontecendo, agora qualificado.
        self.assertIn("sobre.pagina_sobre(dataset, linhas)", fonte_app)

    def test_widget_keys_da_pagina_preservadas(self):
        # Trocar uma `key` reseta o estado do usuario e seria mudanca
        # funcional disfarcada de refactor.
        fonte = (BASE_DIR / "dashboard" / "sobre.py").read_text(
            encoding="utf-8"
        )
        for chave in ("grade_resumo", "grade_resumo_entidades"):
            with self.subTest(chave=chave):
                self.assertIn(f'chave="{chave}"', fonte)

    def test_pagina_nao_usa_session_state(self):
        # Inspeciona o CODIGO, nao a prosa: a docstring do modulo cita
        # `session_state` justamente para dizer que a pagina nao o usa.
        import ast

        atributos = {
            no.attr for no in ast.walk(self._arvore_sobre())
            if isinstance(no, ast.Attribute)
        }
        self.assertNotIn("session_state", atributos)

    def _sobre(self):
        """Importa o modulo, ou pula onde Streamlit nao existe.

        O container do ETL de proposito nao instala as dependencias do painel;
        e o mesmo motivo do skip em :class:`TestSmokeStreamlitEPlotly`.
        """
        try:
            from dashboard import sobre
        except ImportError:
            self.skipTest("streamlit nao instalado neste ambiente")
        return sobre

    def test_texto_da_fronteira_preservado(self):
        sobre = self._sobre()
        self.assertIn("superfície de exposição", sobre.TEXTO_FRONTEIRA)
        self.assertIn("não são disponibilizados", sobre.TEXTO_FRONTEIRA)

    def test_assinatura_preservada(self):
        import inspect
        sobre = self._sobre()
        self.assertEqual(
            list(inspect.signature(sobre.pagina_sobre).parameters),
            ["dataset", "linhas"],
        )


class TestFormatacaoDePeriodo(unittest.TestCase):
    """A formatacao de data mudou de arquivo, nao de comportamento."""

    def setUp(self):
        from dashboard import formatacao
        self.f = formatacao

    def test_dia_unico(self):
        self.assertEqual(
            self.f.formatar_periodo(date(2026, 8, 12), date(2026, 8, 12)),
            "12 ago 2026",
        )

    def test_mesmo_ano(self):
        self.assertEqual(
            self.f.formatar_periodo(date(2026, 8, 12), date(2026, 8, 18)),
            "12 ago — 18 ago 2026",
        )

    def test_meses_diferentes_no_mesmo_ano(self):
        self.assertEqual(
            self.f.formatar_periodo(date(2099, 1, 31), date(2099, 2, 2)),
            "31 jan — 02 fev 2099",
        )

    def test_anos_diferentes(self):
        self.assertEqual(
            self.f.formatar_periodo(date(2025, 12, 30), date(2026, 1, 2)),
            "30 dez 2025 — 02 jan 2026",
        )

    def test_contrato_dos_nomes_dos_meses(self):
        self.assertEqual(
            self.f.MESES,
            (
                "jan", "fev", "mar", "abr", "mai", "jun",
                "jul", "ago", "set", "out", "nov", "dez",
            ),
        )

    def test_graficos_importa_meses_sem_ciclo(self):
        import ast

        def importados(caminho: Path) -> set[str]:
            arvore = ast.parse(caminho.read_text(encoding="utf-8"))
            nomes: set[str] = set()
            for no in ast.walk(arvore):
                if isinstance(no, ast.Import):
                    nomes.update(alias.name for alias in no.names)
                elif isinstance(no, ast.ImportFrom):
                    nomes.add(no.module or "")
                    nomes.update(
                        f"{no.module}.{alias.name}" for alias in no.names
                    )
            return nomes

        importados_graficos = importados(
            BASE_DIR / "dashboard" / "graficos.py"
        )
        importados_formatacao = importados(
            BASE_DIR / "dashboard" / "formatacao.py"
        )
        arvore_graficos = ast.parse(
            (BASE_DIR / "dashboard" / "graficos.py").read_text(
                encoding="utf-8"
            )
        )
        nomes_definidos = {
            no.target.id
            for no in arvore_graficos.body
            if isinstance(no, ast.AnnAssign)
            and isinstance(no.target, ast.Name)
        }

        self.assertIn("dashboard.formatacao.MESES", importados_graficos)
        self.assertNotIn("MESES", nomes_definidos)
        self.assertNotIn("dashboard.graficos", importados_formatacao)

    def test_nao_depende_de_locale(self):
        self.assertEqual(self.f._dia_mes(date(2026, 3, 5)), "05 mar")
        self.assertEqual(len(self.f.MESES), 12)

    def test_app_consome_do_modulo_de_formatacao(self):
        fonte = (BASE_DIR / "dashboard" / "app.py").read_text(encoding="utf-8")
        self.assertIn(
            "from dashboard.formatacao import formatar_periodo", fonte
        )
        self.assertNotIn("def formatar_periodo(", fonte)
        self.assertNotIn("def _dia_mes(", fonte)


class TestSmokeStreamlitEPlotly(unittest.TestCase):
    """Fumaca: os modulos de apresentacao importam e produzem figura.

    Pulados onde Streamlit e Plotly nao existem — o container do ETL, por
    exemplo, que de proposito nao instala as dependencias do painel.
    """

    def test_graficos_produzem_figura(self):
        try:
            graficos = importlib.import_module("dashboard.graficos")
        except ImportError:
            self.skipTest("plotly nao instalado neste ambiente")

        linhas = carregar([
            linha_csv("2026-06-01", "Meta Ads"),
            linha_csv("2026-06-02", "Google Ads", conta=CONTA_B,
                      campanha=CAMPANHA_B1, adset=ADSET_B1,
                      anuncio="Anuncio-BBBB0001"),
        ]).linhas

        figura = graficos.serie_temporal(
            m.serie_diaria(linhas, "spend"), "spend"
        )
        self.assertEqual(len(figura.data), 2)

        figura_indisponivel = graficos.serie_temporal(
            {"Meta Ads": [(date(2026, 6, 1), None)]}, "reach"
        )
        self.assertEqual(list(figura_indisponivel.data[0].y), [None])
        self.assertNotIn(0, figura_indisponivel.data[0].y)
        self.assertEqual(
            list(figura_indisponivel.data[0].customdata), [m.INDISPONIVEL]
        )
        self.assertFalse(figura_indisponivel.data[0].connectgaps)

        figura_zero_real = graficos.serie_temporal(
            {"Meta Ads": [(date(2026, 6, 1), Decimal(0))]}, "spend"
        )
        self.assertEqual(list(figura_zero_real.data[0].y), [0.0])

        totais = m.agregar_por(linhas, lambda linha: linha["plataforma"])
        figura = graficos.barras_plataforma(
            {p: t["reach"] for p, t in totais.items()}, "reach"
        )
        self.assertIn(m.AVISO_NAO_DISPONIVEL, list(figura.data[0].text))

        figura = graficos.barras_ranking(
            m.ranking(linhas, "campanha", "spend"), "spend"
        )
        self.assertEqual(len(figura.data), 1)

    def test_serie_temporal_preserva_rotulos_mensais(self):
        try:
            graficos = importlib.import_module("dashboard.graficos")
        except ImportError:
            self.skipTest("plotly nao instalado neste ambiente")

        figura = graficos.serie_temporal(
            {
                "Meta Ads": [
                    (date(2099, 1, 2), Decimal("1")),
                    (date(2099, 12, 3), Decimal("2")),
                ],
            },
            "spend",
        )

        self.assertEqual(
            list(figura.data[0].x),
            ["02 jan 2099", "03 dez 2099"],
        )
        self.assertEqual(
            list(figura.layout.xaxis.ticktext),
            ["02 jan", "03 dez"],
        )

    def test_cores_de_plataforma_sao_distintas(self):
        try:
            graficos = importlib.import_module("dashboard.graficos")
        except ImportError:
            self.skipTest("plotly nao instalado neste ambiente")
        self.assertNotEqual(
            graficos.cor("Meta Ads"), graficos.cor("Google Ads")
        )
        self.assertEqual(graficos.cor("Fonte Nova"), graficos.COR_PADRAO)

    def test_componentes_importam(self):
        try:
            componentes = importlib.import_module("dashboard.componentes")
        except ImportError:
            self.skipTest("streamlit nao instalado neste ambiente")
        self.assertIn("kpi", componentes.ESTILO.lower())
        self.assertEqual(componentes.rotulo_metrica("spend"), "Investimento")


class TestSmokeAplicacao(unittest.TestCase):
    """Fumaca da aplicacao inteira, via `streamlit.testing`.

    Executa `dashboard/app.py` de verdade, em modo de demonstracao, e exige
    zero excecao em cada uma das quatro paginas. Nao verifica pixel: verifica
    que a composicao das telas nao quebra com o dataset versionado.

    Pulado onde o Streamlit nao existe — o container do ETL, por exemplo.
    """

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

    def _rodar(self):
        """Executa a aplicacao em modo de demonstracao.

        Returns:
            A instancia de `AppTest` ja executada.
        """
        with mock.patch.dict(
            "os.environ", {dados.VARIAVEL_MODO: "demo"}, clear=False
        ):
            return self.AppTest.from_file(
                self.app, default_timeout=180
            ).run()

    def test_todas_as_paginas_renderizam_sem_excecao(self):
        for pagina in ("Visao Geral", "Campanhas", "Anuncios",
                       "Sobre os dados"):
            with self.subTest(pagina=pagina):
                app = self._rodar()
                app.radio[0].set_value(pagina).run()
                self.assertEqual(
                    [erro.value for erro in app.exception], []
                )

    def test_filtro_de_conta_encolhe_as_campanhas_oferecidas(self):
        app = self._rodar()
        contas = app.multiselect(key="filtro_contas").options
        antes = len(app.multiselect(key="filtro_campanhas").options)
        app.multiselect(key="filtro_contas").set_value([contas[0]]).run()
        depois = len(app.multiselect(key="filtro_campanhas").options)
        self.assertLess(depois, antes)
        self.assertEqual([erro.value for erro in app.exception], [])

    def test_limpar_filtros_devolve_a_selecao_vazia(self):
        app = self._rodar()
        contas = app.multiselect(key="filtro_contas").options
        app.multiselect(key="filtro_contas").set_value([contas[0]]).run()
        app.button[0].click().run()
        self.assertEqual(app.multiselect(key="filtro_contas").value, [])
        self.assertEqual([erro.value for erro in app.exception], [])


if __name__ == "__main__":
    unittest.main()
