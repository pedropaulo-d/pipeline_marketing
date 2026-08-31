"""Testes do exportador da superficie de exposicao.

O contrato sob teste tem dois lados. O primeiro e negativo: nome real,
external ID, chave natural e chave substituta **nunca** chegam ao artefato,
e coluna nova na view aborta a exportacao em vez de vazar por omissao — o
mesmo `fail closed` que a silver ja aplica em `assert_campos_extraidos_sao_
consumidos`. O segundo e positivo: contagem, grao, hierarquia, datas, versoes
SCD2 e as nove metricas atravessam a pseudonimizacao sem mudar.

A suite nao toca no banco: uma conexao falsa devolve linhas no formato da
view, o que permite plantar cenarios que o DW real nao tem (coluna nova,
colisao de pseudonimo).

Rodar:
    python -m unittest discover -s tests -t .
"""

import json
import os
import unittest
from decimal import Decimal
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pseudonimos
from scripts import exportar_dataset_exposicao as exportador

CHAVE = "chave-de-teste-com-tamanho-suficiente-para-passar-1234567890"

# Valores plantados na "view" para provar que nao escapam. Sao sinteticos:
# nenhum dado real de cliente entra nesta suite.
NOME_PLANTADO = "Nome Ficticio De Anunciante"
EXTERNAL_ID_PLANTADO = "999888777666555"


def com_chave(valor: str = CHAVE):
    """Instala uma chave de pseudonimizacao no ambiente.

    Args:
        valor: Valor da chave.

    Returns:
        Gerenciador de contexto.
    """
    return mock.patch.dict(
        os.environ, {pseudonimos.VARIAVEL: valor}, clear=False
    )


def linhas_da_view() -> list[dict]:
    """Monta linhas sinteticas no formato de `gold.vw_metricas_completas`.

    Hierarquia: 2 contas, 2 campanhas por conta, 2 adsets por campanha,
    2 anuncios por adset, em 3 datas e 2 plataformas. Uma campanha aparece em
    duas versoes, para exercitar SCD2.

    Returns:
        Lista de dicionarios com todas as colunas que o exportador consome,
        mais as colunas proibidas que a view tambem tem.
    """
    linhas: list[dict] = []
    datas = [date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)]

    for i_conta in range(2):
        plataforma = "Meta Ads" if i_conta == 0 else "Google Ads"
        for i_campanha in range(2):
            for i_adset in range(2):
                for i_anuncio in range(2):
                    for i_data, dia in enumerate(datas):
                        sufixo = f"{i_conta}{i_campanha}{i_adset}{i_anuncio}"
                        linhas.append({
                            "data": dia,
                            "plataforma": plataforma,
                            "conta_nk": f"nk-conta-{i_conta}",
                            "conta_versao": 1,
                            "campanha_nk": f"nk-campanha-{i_conta}{i_campanha}",
                            # A campanha 0 muda de versao no ultimo dia.
                            "campanha_versao": (
                                2 if (i_campanha == 0 and i_data == 2) else 1
                            ),
                            "adset_nk": f"nk-adset-{i_conta}{i_campanha}{i_adset}",
                            "adset_versao": 1,
                            "anuncio_nk": f"nk-anuncio-{sufixo}",
                            "anuncio_versao": 1,
                            "spend": Decimal(f"{10 + i_data}.123456"),
                            "impressions": 1000 + i_data,
                            "link_clicks": 10 + i_data,
                            # Fracionaria de proposito: e como o Google
                            # reporta conversao por modelagem de atribuicao.
                            "conversions": Decimal("1.750000"),
                            "conversion_value": Decimal("25.500000"),
                            "video_views": 5,
                            "reach": 900,
                            "profile_views": 0,
                            "purchases": 0,
                            "purchase_value": Decimal("0.000000"),
                            # Resultado: so o Meta declara. O Google nao tem o
                            # campo na fonte, entao os quatro sao NULL — e a
                            # fixture reproduz isso em vez de zerar, que e
                            # justamente a distincao que o contrato preserva.
                            "result_type": (
                                "actions:offsite_conversion.fb_pixel_lead"
                                if plataforma == "Meta Ads" else None
                            ),
                            "result_count": (
                                Decimal("3.000000")
                                if plataforma == "Meta Ads" else None
                            ),
                            # Janela explicita so em parte das linhas do Meta:
                            # a FORMA A declara tipo sem janela aplicavel.
                            "result_attribution_window": (
                                "7d_click"
                                if plataforma == "Meta Ads" and i_data == 0
                                else None
                            ),
                            "cost_per_result": (
                                Decimal("4.041152")
                                if plataforma == "Meta Ads" and i_data == 0
                                else None
                            ),
                            # Contexto que fica SO no DW: presente na view,
                            # nunca no artefato.
                            "objective": "OUTCOME_LEADS",
                            "optimization_goal": "LEAD_GENERATION",
                            # Colunas proibidas, presentes na view real.
                            "conta_nome": NOME_PLANTADO,
                            "conta_external_id": EXTERNAL_ID_PLANTADO,
                            "campanha_nome": NOME_PLANTADO,
                            "campanha_external_id": EXTERNAL_ID_PLANTADO,
                            "adset_nome": NOME_PLANTADO,
                            "adset_external_id": EXTERNAL_ID_PLANTADO,
                            "anuncio_nome": NOME_PLANTADO,
                            "anuncio_external_id": EXTERNAL_ID_PLANTADO,
                        })
    return linhas


class CursorFalso:
    """Cursor que responde as duas consultas do exportador."""

    def __init__(self, colunas_view: list[str], linhas: list[dict]):
        self.colunas_view = colunas_view
        self.linhas = linhas
        self.resultado: list[tuple] = []
        self.description: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql: str, params=None) -> None:
        """Despacha conforme a consulta recebida.

        Args:
            sql: Consulta emitida pelo exportador.
            params: Parametros posicionais.
        """
        if "information_schema" in sql:
            self.resultado = [(coluna,) for coluna in self.colunas_view]
            self.description = [("column_name",)]
            return

        colunas = exportador.COLUNAS_ORIGEM
        self.description = [(coluna,) for coluna in colunas]
        self.resultado = [
            tuple(linha[coluna] for coluna in colunas) for linha in self.linhas
        ]

    def fetchall(self) -> list[tuple]:
        """Devolve o resultado da ultima consulta.

        Returns:
            Lista de tuplas.
        """
        return self.resultado


class ConexaoFalsa:
    """Conexao que devolve `CursorFalso`, sem tocar em banco nenhum."""

    def __init__(self, colunas_view: list[str], linhas: list[dict]):
        self.colunas_view = colunas_view
        self.linhas = linhas

    def cursor(self) -> CursorFalso:
        """Abre um cursor falso.

        Returns:
            O cursor.
        """
        return CursorFalso(self.colunas_view, self.linhas)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class BaseExportacao(unittest.TestCase):
    """Infra comum: exporta para um diretorio temporario."""

    def setUp(self):
        self.origem = linhas_da_view()
        self.colunas_view = sorted(exportador.CLASSIFICACAO)
        self.temporario = TemporaryDirectory()
        self.destino = Path(self.temporario.name) / "exposicao"
        self.addCleanup(self.temporario.cleanup)

    def exportar(self, colunas_view=None, linhas=None, **kwargs) -> int:
        """Roda o exportador contra a conexao falsa.

        Args:
            colunas_view: Colunas que a "view" declara ter.
            linhas: Linhas devolvidas pela "view".
            **kwargs: Repassados a `exportar`.

        Returns:
            Exit code do exportador.
        """
        conexao = ConexaoFalsa(
            colunas_view if colunas_view is not None else self.colunas_view,
            linhas if linhas is not None else self.origem,
        )
        with com_chave(), mock.patch.object(
            exportador, "_conectar", return_value=conexao
        ):
            return exportador.exportar(self.destino, **kwargs)

    @property
    def csv(self) -> Path:
        """Caminho do CSV gerado.

        Returns:
            Caminho.
        """
        return self.destino / exportador.NOME_CSV

    @property
    def manifesto(self) -> dict:
        """Manifesto gerado.

        Returns:
            Manifesto carregado.
        """
        return json.loads(
            (self.destino / exportador.NOME_MANIFESTO).read_text(encoding="utf-8")
        )

    def linhas_do_csv(self) -> list[dict]:
        """Le o CSV gerado.

        Returns:
            Lista de dicionarios, valores como texto.
        """
        import csv as _csv

        texto = self.csv.read_text(encoding="utf-8")
        leitor = _csv.reader(texto.splitlines())
        cabecalho = next(leitor)
        return [dict(zip(cabecalho, campos)) for campos in leitor]


COLUNAS_V2: tuple[str, ...] = (
    "data", "plataforma",
    "conta_id", "conta_versao", "campanha_id", "campanha_versao",
    "adset_id", "adset_versao", "anuncio_id", "anuncio_versao",
    "spend", "impressions", "link_clicks", "conversions", "conversion_value",
    "video_views", "reach", "profile_views", "purchases", "purchase_value",
)

COLUNAS_RESULTADO: tuple[str, ...] = (
    "result_type", "result_count", "result_attribution_window",
    "cost_per_result",
)


class TestSchemaDeSaida(BaseExportacao):
    """As 24 colunas do contrato v3, nem uma a mais."""

    def test_schema_final_tem_vinte_e_quatro_colunas(self):
        """Vinte e quatro desde o contrato v3: as quatro colunas de Resultado
        entraram, e acrescentar coluna e mudanca de schema neste contrato."""
        self.assertEqual(len(exportador.COLUNAS_SAIDA), 24)
        self.assertEqual(exportador.VERSAO_CONTRATO, 3)
        self.assertEqual(self.exportar(), 0)

        cabecalho = self.csv.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(cabecalho.split(","), list(exportador.COLUNAS_SAIDA))

    def test_schema_v3_e_a_lista_inteira_esperada(self):
        # Nao basta contar: a lista e o contrato, e e por igualdade que os
        # consumidores decidem aceitar ou recusar o artefato.
        self.assertEqual(
            exportador.COLUNAS_SAIDA, COLUNAS_V2 + COLUNAS_RESULTADO
        )

    def test_prefixo_v2_preservado_na_ordem(self):
        # As quatro novas entram no FIM. Reordenar o prefixo trocaria coluna de
        # lugar para qualquer leitor posicional sem mudar a contagem.
        self.assertEqual(exportador.COLUNAS_SAIDA[:20], COLUNAS_V2)

    def test_nenhuma_coluna_v2_removida_ou_renomeada(self):
        for coluna in COLUNAS_V2:
            with self.subTest(coluna=coluna):
                self.assertIn(coluna, exportador.COLUNAS_SAIDA)

    def test_exatamente_quatro_colunas_novas(self):
        novas = tuple(
            c for c in exportador.COLUNAS_SAIDA if c not in COLUNAS_V2
        )
        self.assertEqual(novas, COLUNAS_RESULTADO)

    def test_origem_le_resultado_e_nao_le_contexto(self):
        for coluna in COLUNAS_RESULTADO:
            with self.subTest(coluna=coluna):
                self.assertIn(coluna, exportador.COLUNAS_ORIGEM)
        # `objective` e `optimization_goal` existem no Gold e continuam la:
        # ler para nao usar so ampliaria a fronteira sem consumidor.
        self.assertNotIn("objective", exportador.COLUNAS_ORIGEM)
        self.assertNotIn("optimization_goal", exportador.COLUNAS_ORIGEM)

    def test_nenhuma_coluna_proibida_no_schema_de_saida(self):
        # 12 campos nunca saem: 4 nomes, 4 external IDs, 4 chaves naturais.
        # As `_nk` sao lidas da view (entrada do HMAC) mas nao sao expostas —
        # por isso a lista de campos nao expostos e maior que a de colunas
        # classificadas como PROIBIDA.
        self.assertEqual(len(exportador.CAMPOS_NUNCA_EXPOSTOS), 12)
        self.assertEqual(
            exportador.CAMPOS_NUNCA_EXPOSTOS & set(exportador.COLUNAS_SAIDA),
            set(),
        )

        proibidas = {
            c for c, k in exportador.CLASSIFICACAO.items()
            if k == exportador.PROIBIDA
        }
        self.assertEqual(proibidas, exportador.CAMPOS_NUNCA_EXPOSTOS - {
            f"{nivel}_nk" for nivel in exportador.NIVEIS
        })

    def test_nao_existe_coluna_de_nome_publico(self):
        for coluna in exportador.COLUNAS_SAIDA:
            self.assertNotIn("nome", coluna)

    def test_nao_existe_linha_id(self):
        self.assertNotIn("linha_id", exportador.COLUNAS_SAIDA)

    def test_resultado_e_publico_no_contrato_v3(self):
        publicas = {
            coluna for coluna, classe in exportador.CLASSIFICACAO.items()
            if classe == exportador.USADA
        }
        for coluna in COLUNAS_RESULTADO:
            with self.subTest(coluna=coluna):
                self.assertIn(coluna, publicas)

    def test_nenhum_campo_ficou_reservado_por_acidente(self):
        # A categoria continua existindo para o proximo campo aprovado mas nao
        # exportado; o que nao pode e sobrar ocupante silencioso dela agora que
        # os quatro de Resultado sairam.
        reservadas = {
            coluna for coluna, classe in exportador.CLASSIFICACAO.items()
            if classe == exportador.RESERVADA_EXPOSICAO
        }
        self.assertEqual(reservadas, set())

    def test_tipos_do_manifesto_cobrem_o_schema(self):
        self.assertEqual(
            set(exportador.TIPOS_SAIDA), set(exportador.COLUNAS_SAIDA)
        )
        for coluna in COLUNAS_RESULTADO:
            with self.subTest(coluna=coluna):
                self.assertIn("nullable", exportador.TIPOS_SAIDA[coluna])

    def test_contexto_de_resultado_fica_somente_no_dw(self):
        somente_dw = {
            coluna for coluna, classe in exportador.CLASSIFICACAO.items()
            if classe == exportador.SOMENTE_DW
        }
        self.assertEqual(somente_dw, {"objective", "optimization_goal"})


class TestResultadoNaSuperficie(BaseExportacao):
    """Os quatro campos viajam intactos, inclusive quando sao ausencia."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.exportar(), 0)
        self.linhas = self.linhas_do_csv()

    def test_as_quatro_colunas_chegam_ao_artefato(self):
        for coluna in COLUNAS_RESULTADO:
            with self.subTest(coluna=coluna):
                self.assertIn(coluna, self.linhas[0])

    def test_contexto_do_dw_nao_chega_ao_artefato(self):
        # Lidos da view pelo Gold, nunca projetados: a fronteira de exposicao
        # e allowlist, e estes dois estao classificados SOMENTE_DW.
        for coluna in ("objective", "optimization_goal"):
            with self.subTest(coluna=coluna):
                self.assertNotIn(coluna, self.linhas[0])
                self.assertNotIn(coluna, self.csv.read_text(encoding="utf-8"))

    def test_meta_com_resultado_preserva_o_valor(self):
        meta = [l for l in self.linhas if l["plataforma"] == "Meta Ads"]
        self.assertTrue(meta)
        for linha in meta:
            self.assertEqual(
                linha["result_type"],
                "actions:offsite_conversion.fb_pixel_lead",
            )
            self.assertEqual(linha["result_count"], "3.000000")

    def test_google_sai_com_resultado_vazio(self):
        # O Google nao fornece Resultado neste grao. Ausencia de suporte da
        # fonte vira campo vazio, nunca zero: zero afirmaria quantidade.
        google = [l for l in self.linhas if l["plataforma"] == "Google Ads"]
        self.assertTrue(google)
        for linha in google:
            for coluna in COLUNAS_RESULTADO:
                with self.subTest(coluna=coluna):
                    self.assertEqual(linha[coluna], "")

    def test_ausencia_nao_vira_zero_nem_texto(self):
        # A linha Meta sem janela/custo (FORMA A) sai vazia nos dois campos.
        # `0`, `"0"`, `N/A` e `None` seriam todos invencao de valor.
        sem_janela = [
            l for l in self.linhas
            if l["plataforma"] == "Meta Ads" and not l["result_attribution_window"]
        ]
        self.assertTrue(sem_janela)
        for linha in sem_janela:
            self.assertEqual(linha["result_attribution_window"], "")
            self.assertEqual(linha["cost_per_result"], "")
        texto = self.csv.read_text(encoding="utf-8")
        for invencao in (",N/A,", ",None,", ",Nao disponivel,", ",null,"):
            with self.subTest(invencao=invencao):
                self.assertNotIn(invencao, texto)

    def test_janela_explicita_preservada_quando_existe(self):
        com_janela = [
            l for l in self.linhas if l["result_attribution_window"]
        ]
        self.assertTrue(com_janela)
        for linha in com_janela:
            self.assertEqual(linha["result_attribution_window"], "7d_click")
            self.assertEqual(linha["cost_per_result"], "4.041152")

    def test_custo_nao_e_recalculado(self):
        # O exportador transporta o custo factual do Gold. Recalcular aqui
        # (spend/result_count) daria outro numero e mudaria o significado.
        com_custo = [l for l in self.linhas if l["cost_per_result"]]
        self.assertTrue(com_custo)
        for linha in com_custo:
            self.assertEqual(linha["cost_per_result"], "4.041152")
            self.assertNotEqual(
                linha["cost_per_result"],
                str(Decimal(linha["spend"]) / Decimal(linha["result_count"])),
            )

    def test_manifesto_declara_v3_e_as_24_colunas(self):
        manifesto = self.manifesto
        self.assertEqual(manifesto["versao_contrato"], 3)
        self.assertEqual(manifesto["colunas"], list(exportador.COLUNAS_SAIDA))
        self.assertEqual(set(manifesto["tipos"]), set(manifesto["colunas"]))

    def test_pseudonimos_nao_mudaram_com_a_v3(self):
        # A evolucao do contrato nao toca na identidade publica: mesmo formato
        # de ID e fingerprint da mesma chave em uso. Os quatro campos de
        # Resultado nao sao identificadores e nao passam por `gerar_id_publico`.
        manifesto = self.manifesto
        self.assertEqual(
            len(manifesto["fingerprint_chave"]), pseudonimos.TAMANHO_FINGERPRINT
        )
        for linha in self.linhas:
            self.assertTrue(linha["conta_id"].startswith("Cliente-"))
            self.assertTrue(linha["anuncio_id"].startswith("Anuncio-"))

    def test_resultado_nao_passa_por_pseudonimizacao(self):
        with mock.patch.object(
            exportador.pseudonimos, "gerar_id_publico",
            wraps=exportador.pseudonimos.gerar_id_publico,
        ) as gerar:
            self.assertEqual(self.exportar(), 0)
        niveis = {chamada.args[0] for chamada in gerar.call_args_list}
        self.assertEqual(niveis, set(exportador.NIVEIS))


class TestFailClosed(BaseExportacao):
    """Evolucao do schema de origem nao pode passar em silencio."""

    def test_coluna_nova_na_view_aborta(self):
        colunas = self.colunas_view + ["landing_page_url"]

        self.assertEqual(self.exportar(colunas_view=colunas), 1)
        self.assertFalse(self.csv.exists())

    def test_coluna_consumida_que_some_da_view_aborta(self):
        colunas = [c for c in self.colunas_view if c != "conta_versao"]

        self.assertEqual(self.exportar(colunas_view=colunas), 1)
        self.assertFalse(self.csv.exists())

    def test_view_vazia_aborta(self):
        self.assertEqual(self.exportar(linhas=[]), 1)
        self.assertFalse(self.csv.exists())

    def test_sem_chave_nao_gera_artefato(self):
        conexao = ConexaoFalsa(self.colunas_view, self.origem)
        ambiente = {
            k: v for k, v in os.environ.items() if k != pseudonimos.VARIAVEL
        }
        with mock.patch.dict(os.environ, ambiente, clear=True), \
                mock.patch.object(exportador, "_conectar", return_value=conexao):
            codigo = exportador.exportar(self.destino)

        self.assertEqual(codigo, 1)
        self.assertFalse(self.csv.exists())

    def test_destino_de_publicacao_exige_flag(self):
        conexao = ConexaoFalsa(self.colunas_view, self.origem)
        with com_chave(), mock.patch.object(
            exportador, "_conectar", return_value=conexao
        ):
            codigo = exportador.exportar(exportador.DIRETORIO_PUBLICACAO)

        self.assertEqual(codigo, 1)

    def test_falha_nos_pos_checks_nao_deixa_artefato(self):
        # Colisao forcada: dois anuncios distintos com o mesmo pseudonimo.
        original = pseudonimos.gerar_id_publico

        def colidir(nivel, nk):
            if nivel == "anuncio":
                return "Anuncio-AAAAAAAA"
            return original(nivel, nk)

        conexao = ConexaoFalsa(self.colunas_view, self.origem)
        with com_chave(), \
                mock.patch.object(exportador, "_conectar", return_value=conexao), \
                mock.patch.object(
                    exportador.pseudonimos, "gerar_id_publico", side_effect=colidir
                ):
            codigo = exportador.exportar(self.destino)

        self.assertEqual(codigo, 1)
        self.assertFalse(self.csv.exists())
        self.assertFalse(
            (self.destino / (exportador.NOME_CSV + ".parcial")).exists()
        )


class TestIdentidadeNaoVaza(BaseExportacao):
    """Nome, external ID, `_nk` e `_sk` nao chegam ao artefato."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.exportar(), 0)
        self.texto = self.csv.read_text(encoding="utf-8")

    def test_nome_real_nao_sai(self):
        self.assertNotIn(NOME_PLANTADO, self.texto)

    def test_external_id_nao_sai(self):
        self.assertNotIn(EXTERNAL_ID_PLANTADO, self.texto)

    def test_chave_natural_nao_sai(self):
        for linha in self.origem:
            for nivel in exportador.NIVEIS:
                self.assertNotIn(linha[f"{nivel}_nk"], self.texto)

    def test_nenhuma_coluna_com_sufixo_interno(self):
        cabecalho = self.texto.splitlines()[0].split(",")
        for coluna in cabecalho:
            for sufixo in ("_nk", "_sk", "_external_id", "_nome"):
                self.assertFalse(coluna.endswith(sufixo))

    def test_identificadores_publicos_tem_o_formato_declarado(self):
        import re

        padroes = {
            "conta_id": r"^Cliente-[0-9A-F]{8}$",
            "campanha_id": r"^Campanha-[0-9A-F]{8}$",
            "adset_id": r"^AdSet-[0-9A-F]{8}$",
            "anuncio_id": r"^Anuncio-[0-9A-F]{8}$",
        }
        for linha in self.linhas_do_csv():
            for coluna, padrao in padroes.items():
                self.assertRegex(linha[coluna], re.compile(padrao))

    def test_chave_de_pseudonimizacao_nao_aparece_no_artefato(self):
        self.assertNotIn(CHAVE, self.texto)
        self.assertNotIn(CHAVE, json.dumps(self.manifesto))


class TestValorAnaliticoPreservado(BaseExportacao):
    """O que atravessa a pseudonimizacao tem de sair identico."""

    def setUp(self):
        super().setUp()
        self.assertEqual(self.exportar(), 0)
        self.artefato = self.linhas_do_csv()

    def test_contagem_preservada(self):
        self.assertEqual(len(self.artefato), len(self.origem))
        self.assertEqual(self.manifesto["linhas"], len(self.origem))

    def test_grao_preservado(self):
        graos = {(l["anuncio_id"], l["data"]) for l in self.artefato}
        self.assertEqual(len(graos), len(self.artefato))

    def test_hierarquia_preservada(self):
        for pai, filho in (("conta", "campanha"), ("campanha", "adset"),
                           ("adset", "anuncio")):
            mapa: dict = {}
            for linha in self.artefato:
                mapa.setdefault(linha[f"{filho}_id"], set()).add(
                    linha[f"{pai}_id"]
                )
            for pais in mapa.values():
                self.assertEqual(len(pais), 1)

        origem_niveis = {
            nivel: len({l[f"{nivel}_nk"] for l in self.origem})
            for nivel in exportador.NIVEIS
        }
        artefato_niveis = {
            nivel: len({l[f"{nivel}_id"] for l in self.artefato})
            for nivel in exportador.NIVEIS
        }
        self.assertEqual(origem_niveis, artefato_niveis)

    def test_metricas_preservadas_exatamente(self):
        for metrica in exportador.METRICAS:
            na_origem = sum(Decimal(str(l[metrica])) for l in self.origem)
            no_artefato = sum(Decimal(l[metrica]) for l in self.artefato)
            with self.subTest(metrica=metrica):
                self.assertEqual(na_origem, no_artefato)

    def test_conversao_fracionaria_continua_fracionaria(self):
        valores = {Decimal(l["conversions"]) for l in self.artefato}

        self.assertTrue(valores)
        self.assertTrue(
            any(v != v.to_integral_value() for v in valores),
            "conversao virou inteiro no caminho",
        )

    def test_escala_decimal_do_spend_preservada(self):
        # `10.123456` nao pode virar `10.12` nem `10.123456000001`.
        textos = {l["spend"] for l in self.artefato}
        for texto in textos:
            self.assertRegex(texto, r"^\d+\.\d{6}$")

    def test_datas_preservadas(self):
        self.assertEqual(
            {str(l["data"]) for l in self.origem},
            {l["data"] for l in self.artefato},
        )

    def test_versoes_scd2_preservadas(self):
        self.assertEqual(
            exportador.versoes_por_nivel(self.origem),
            exportador.versoes_por_nivel(
                [
                    {f"{n}_versao": int(l[f"{n}_versao"])
                     for n in exportador.NIVEIS}
                    for l in self.artefato
                ]
            ),
        )

    def test_mesma_entidade_mantem_o_mesmo_id_entre_versoes(self):
        # A identidade natural pseudonimizada nao muda quando a entidade e
        # renomeada — e o que permite demonstrar SCD2 sem revelar o nome.
        por_id: dict = {}
        for linha in self.artefato:
            por_id.setdefault(linha["campanha_id"], set()).add(
                linha["campanha_versao"]
            )
        com_duas_versoes = [k for k, v in por_id.items() if len(v) > 1]

        self.assertTrue(com_duas_versoes)


class TestPosChecksDeIdentidade(unittest.TestCase):
    """Congela as checagens estruturais antes de extraí-las de ``conferir``."""

    def setUp(self):
        self.origem = linhas_da_view()
        with com_chave():
            self.artefato = exportador.transformar(self.origem)

    def test_artefato_valido_nao_produz_problema(self):
        self.assertEqual(exportador.conferir(self.origem, self.artefato), [])

    def test_colisao_de_pseudonimo_preserva_mensagem(self):
        contas = list(dict.fromkeys(
            linha["conta_id"] for linha in self.artefato
        ))
        for linha in self.artefato:
            if linha["conta_id"] == contas[1]:
                linha["conta_id"] = contas[0]

        self.assertEqual(
            exportador.conferir(self.origem, self.artefato),
            [
                "colisao de pseudonimo em conta: 2 entidades na origem para "
                "1 identificadores publicos"
            ],
        )

    def test_hierarquia_quebrada_preserva_mensagem(self):
        contas = list(dict.fromkeys(
            linha["conta_id"] for linha in self.artefato
        ))
        self.artefato[0]["conta_id"] = contas[1]

        self.assertEqual(
            exportador.conferir(self.origem, self.artefato),
            ["hierarquia quebrada: 1 campanha(s) com mais de um conta"],
        )

    def test_ordem_de_colisao_e_schema_permanece_estavel(self):
        contas = list(dict.fromkeys(
            linha["conta_id"] for linha in self.artefato
        ))
        for linha in self.artefato:
            if linha["conta_id"] == contas[1]:
                linha["conta_id"] = contas[0]

        primeira = self.artefato[0]
        self.artefato[0] = {
            "plataforma": primeira["plataforma"],
            "data": primeira["data"],
            **{
                coluna: valor for coluna, valor in primeira.items()
                if coluna not in {"data", "plataforma"}
            },
        }

        self.assertEqual(
            exportador.conferir(self.origem, self.artefato),
            [
                "colisao de pseudonimo em conta: 2 entidades na origem para "
                "1 identificadores publicos",
                f"schema do artefato tem {len(exportador.COLUNAS_SAIDA)} "
                f"colunas, esperadas {len(exportador.COLUNAS_SAIDA)}",
            ],
        )

    def test_chave_natural_em_valor_preserva_mensagem(self):
        conta_nk = self.origem[0]["conta_nk"]
        with com_chave():
            conta_id = pseudonimos.gerar_id_publico("conta", conta_nk)
        for linha in self.artefato:
            if linha["conta_id"] == conta_id:
                linha["conta_id"] = conta_nk

        self.assertEqual(
            exportador.conferir(self.origem, self.artefato),
            ["chave natural de conta encontrada entre os valores do artefato"],
        )


class TestDeterminismoEManifesto(BaseExportacao):
    """Duas geracoes iguais, e um manifesto que descreve o artefato."""

    def test_duas_execucoes_produzem_csv_identico(self):
        self.assertEqual(self.exportar(), 0)
        primeiro = self.csv.read_bytes()

        self.assertEqual(self.exportar(), 0)
        segundo = self.csv.read_bytes()

        self.assertEqual(primeiro, segundo)

    def test_ordem_da_origem_nao_altera_o_csv(self):
        self.assertEqual(self.exportar(), 0)
        original = self.csv.read_bytes()

        embaralhado = list(reversed(self.origem))
        self.assertEqual(self.exportar(linhas=embaralhado), 0)

        self.assertEqual(self.csv.read_bytes(), original)

    def test_manifesto_descreve_o_artefato(self):
        self.assertEqual(self.exportar(), 0)
        manifesto = self.manifesto

        import hashlib

        sha = hashlib.sha256(self.csv.read_bytes()).hexdigest()
        self.assertEqual(manifesto["sha256"], sha)
        self.assertEqual(manifesto["colunas"], list(exportador.COLUNAS_SAIDA))
        self.assertEqual(manifesto["data_min"], "2026-08-10")
        self.assertEqual(manifesto["data_max"], "2026-08-12")
        self.assertIn("video_views", manifesto["avisos"])
        self.assertIn("cross-platform", manifesto["avisos"]["video_views"])
        self.assertEqual(
            len(manifesto["fingerprint_chave"]), pseudonimos.TAMANHO_FINGERPRINT
        )

    def test_fingerprint_do_manifesto_acompanha_a_chave(self):
        self.assertEqual(self.exportar(), 0)
        com_uma = self.manifesto["fingerprint_chave"]

        conexao = ConexaoFalsa(self.colunas_view, self.origem)
        with com_chave("outra-chave-de-teste-igualmente-longa-0987654321-ab"), \
                mock.patch.object(exportador, "_conectar", return_value=conexao):
            self.assertEqual(exportador.exportar(self.destino), 0)

        self.assertNotEqual(self.manifesto["fingerprint_chave"], com_uma)


if __name__ == "__main__":
    unittest.main()
