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

from dashboard import dados, filtros, gerar_dados_demo
from dashboard import metricas as m

BASE_DIR = Path(__file__).resolve().parent.parent

CABECALHO = list(dados.COLUNAS_OBRIGATORIAS)

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
        link_clicks: Cliques no link.
        conversions: Conversoes.
        conversion_value: Valor de conversao.
        video_views: Visualizacoes de video.
        reach: Alcance.
        profile_views: Visitas ao perfil.
        purchases: Compras.
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
        video_views, reach, profile_views, purchases,
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

    # As seis metricas dos cartoes principais de `app.KPIS_PRINCIPAIS`,
    # repetidas aqui porque importar `dashboard.app` executaria a aplicacao
    # inteira: o modulo chama `main()` no fim do arquivo.
    METRICAS_EM_CARTAO = (
        "spend", "impressions", "link_clicks",
        "conversions", "conversion_value", "purchases",
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


class TestCatalogoDeMetricas(unittest.TestCase):
    """O catalogo espelha as limitacoes reais das duas APIs."""

    def test_cobre_as_nove_metricas_do_pipeline(self):
        self.assertEqual(set(m.METRICAS), set(dados.METRICAS))
        self.assertEqual(len(m.METRICAS), 9)

    def test_metricas_sem_suporte_no_google(self):
        for metrica in ("reach", "profile_views", "purchases"):
            with self.subTest(metrica=metrica):
                self.assertFalse(m.suportada(metrica, "Google Ads"))
                self.assertTrue(m.suportada(metrica, "Meta Ads"))

    def test_video_views_nao_soma_entre_plataformas(self):
        # Definicoes diferentes: TrueView de 30s no Google, 3s no Meta.
        self.assertFalse(
            m.CATALOGO["video_views"].comparavel_entre_plataformas
        )
        self.assertNotIn("video_views", m.METRICAS_CONSOLIDAVEIS)

    def test_reach_nao_e_aditiva_no_tempo(self):
        self.assertFalse(m.CATALOGO["reach"].aditiva_no_tempo)

    def test_metricas_consolidaveis_sao_as_cinco_comuns(self):
        self.assertEqual(
            set(m.METRICAS_CONSOLIDAVEIS),
            {"spend", "impressions", "link_clicks", "conversions",
             "conversion_value"},
        )

    def test_metrica_desconhecida_nao_e_suportada(self):
        self.assertFalse(m.suportada("clicks_totais", "Meta Ads"))


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
            for metrica in ("reach", "profile_views", "purchases"):
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

        totais = m.agregar_por(linhas, lambda linha: linha["plataforma"])
        figura = graficos.barras_plataforma(
            {p: t["reach"] for p, t in totais.items()}, "reach"
        )
        self.assertIn(m.AVISO_NAO_DISPONIVEL, list(figura.data[0].text))

        figura = graficos.barras_ranking(
            m.ranking(linhas, "campanha", "spend"), "spend"
        )
        self.assertEqual(len(figura.data), 1)

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
        self.assertIn("kpi", componentes.ESTILO)
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
