"""Testes do contrato da carga bronze.

Duas frentes, ambas sem tocar no banco real:

- **porta de entrada** — o que o loader aceita carregar. As checagens
  acontecem antes de qualquer conexao, de proposito, para que uma execucao
  invalida falhe sem escrever nada;
- **preparacao e gravacao do lote** — o que `load_source` monta e emite. A
  sessao e substituida por um dublê que registra os `execute`, entao da para
  afirmar quantas instrucoes sairam, em que ordem e com quais valores, sem
  Postgres nenhum.

Rodar:
    python -m unittest discover -s tests -t .
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import manifesto
from loaders import bronze_loader
from manifesto import ManifestoInvalido
from tests.test_manifesto import plataforma_em

import uuid

RUN_ATUAL = "manual__2026-08-17T12:00:00+00:00"
RUN_ANTERIOR = "scheduled__2026-08-10T09:00:00+00:00"
INICIO, FIM = "2026-08-10", "2026-08-16"


class TestContratoDeEntrada(unittest.TestCase):

    def setUp(self):
        self.diretorio = Path(tempfile.mkdtemp(prefix="tcc_bronze_"))
        self.addCleanup(shutil.rmtree, self.diretorio, ignore_errors=True)
        self.plataformas = {
            "meta_ads": plataforma_em(self.diretorio, "meta"),
            "google_ads": plataforma_em(self.diretorio, "google"),
        }
        remendo = mock.patch.object(
            bronze_loader, "por_fonte", self.plataformas.__getitem__
        )
        remendo.start()
        self.addCleanup(remendo.stop)

    def extrair(self, fonte: str, run_id: str = RUN_ATUAL, registros: int = 3) -> None:
        """Simula a extracao de uma fonte, com bruto e manifesto."""
        plataforma = self.plataformas[fonte]
        plataforma.arquivo_bruto.write_text(
            json.dumps([{"ad_id": str(i)} for i in range(registros)]),
            encoding="utf-8",
        )
        manifesto.gravar(
            plataforma, run_id=run_id, start_date=INICIO, end_date=FIM,
            registros=registros,
        )

    # ── aceita ──

    def test_aceita_as_duas_fontes_do_run_atual(self):
        self.extrair("meta_ads")
        self.extrair("google_ads")

        bronze_loader._conferir_artefatos(
            ["meta_ads", "google_ads"], RUN_ATUAL, INICIO, FIM
        )

    def test_aceita_extracao_legitimamente_vazia(self):
        self.extrair("meta_ads", registros=0)

        bronze_loader._conferir_artefatos(["meta_ads"], RUN_ATUAL, INICIO, FIM)

    # ── recusa ──

    def test_recusa_artefato_de_outro_run(self):
        self.extrair("meta_ads", run_id=RUN_ANTERIOR)

        with self.assertRaises(ManifestoInvalido):
            bronze_loader._conferir_artefatos(["meta_ads"], RUN_ATUAL, INICIO, FIM)

    def test_recusa_o_par_inteiro_quando_so_uma_fonte_e_do_run(self):
        # Meta novo + Google velho: a carga nao pode aceitar metade.
        self.extrair("meta_ads", run_id=RUN_ATUAL)
        self.extrair("google_ads", run_id=RUN_ANTERIOR)

        with self.assertRaises(ManifestoInvalido) as erro:
            bronze_loader._conferir_artefatos(
                ["meta_ads", "google_ads"], RUN_ATUAL, INICIO, FIM
            )

        self.assertIn("google_ads", str(erro.exception))

    def test_recusa_arquivo_sem_manifesto(self):
        self.plataformas["meta_ads"].arquivo_bruto.write_text("[]", encoding="utf-8")

        with self.assertRaises(ManifestoInvalido):
            bronze_loader._conferir_artefatos(["meta_ads"], RUN_ATUAL, INICIO, FIM)

    def test_recusa_janela_diferente_da_pedida(self):
        self.extrair("meta_ads")

        with self.assertRaises(ManifestoInvalido):
            bronze_loader._conferir_artefatos(
                ["meta_ads"], RUN_ATUAL, "2026-04-01", "2026-04-07"
            )


class TestArgumentosDaCarga(unittest.TestCase):
    """Combinacoes invalidas falham antes de abrir conexao com o banco."""

    def test_run_id_sem_janela_e_recusado(self):
        with mock.patch.object(bronze_loader, "get_engine") as engine:
            with self.assertRaises(ValueError):
                bronze_loader.run(sources=["meta_ads"], run_id=RUN_ATUAL)
            engine.assert_not_called()

    def test_fonte_desconhecida_e_recusada(self):
        with mock.patch.object(bronze_loader, "get_engine") as engine:
            with self.assertRaises(ValueError):
                bronze_loader.run(sources=["tiktok_ads"])
            engine.assert_not_called()

    def test_artefato_invalido_nao_chega_a_abrir_conexao(self):
        with mock.patch.object(bronze_loader, "get_engine") as engine, \
             mock.patch.object(
                 bronze_loader, "_conferir_artefatos",
                 side_effect=ManifestoInvalido("artefato de outro run"),
             ):
            with self.assertRaises(ManifestoInvalido):
                bronze_loader.run(
                    sources=["meta_ads"], run_id=RUN_ATUAL,
                    start_date=INICIO, end_date=FIM,
                )
            engine.assert_not_called()

    def test_modo_local_sem_run_id_dispensa_a_prova(self):
        # `--skip-extract` continua funcionando: sem run_id nao ha execucao de
        # origem a exigir, e os arquivos em disco sao a entrada pretendida.
        with mock.patch.object(bronze_loader, "get_engine") as engine, \
             mock.patch.object(bronze_loader, "ensure_schema"), \
             mock.patch.object(bronze_loader, "Session"), \
             mock.patch.object(bronze_loader, "load_source", return_value=0), \
             mock.patch.object(bronze_loader, "_conferir_artefatos") as conferir:
            bronze_loader.run(sources=["meta_ads"])

            conferir.assert_not_called()
            engine.assert_called_once()


if __name__ == "__main__":
    unittest.main()


class SessaoDuble:
    """Sessao falsa que so registra os `execute` recebidos.

    Deliberadamente burra: nao valida SQL, nao simula banco e nao aceita nada
    alem de `execute`. Se `load_source` passar a chamar outro metodo da sessao,
    o teste quebra com `AttributeError` — que e o comportamento desejado, e o
    motivo de nao usar `MagicMock` aqui.
    """

    def __init__(self):
        self.execucoes: list[tuple[str, object]] = []

    def execute(self, instrucao, parametros=None):
        self.execucoes.append((str(instrucao), parametros))

    def sql(self, indice: int) -> str:
        return " ".join(self.execucoes[indice][0].split())

    def params(self, indice: int):
        return self.execucoes[indice][1]


class TestPreparacaoDoLote(unittest.TestCase):
    """Caracteriza `load_source`: o que vira linha e o que e descartado."""

    def setUp(self):
        self.diretorio = Path(tempfile.mkdtemp(prefix="tcc_lote_"))
        self.addCleanup(shutil.rmtree, self.diretorio, ignore_errors=True)
        self.lote = uuid.UUID("00000000-0000-4000-8000-000000000001")

    def _arquivo(self, registros) -> Path:
        caminho = self.diretorio / "bruto.json"
        caminho.write_text(json.dumps(registros), encoding="utf-8")
        return caminho

    def _carregar(self, registros, campo_data: str = "date_start"):
        sessao = SessaoDuble()
        total = bronze_loader.load_source(
            sessao, "meta_ads", self._arquivo(registros), campo_data, self.lote
        )
        return total, sessao

    def test_arquivo_ausente_nao_emite_instrucao(self):
        sessao = SessaoDuble()
        total = bronze_loader.load_source(
            sessao, "meta_ads", self.diretorio / "nao_existe.json",
            "date_start", self.lote,
        )
        self.assertEqual(total, 0)
        self.assertEqual(sessao.execucoes, [])

    def test_arquivo_vazio_nao_emite_instrucao(self):
        total, sessao = self._carregar([])
        self.assertEqual(total, 0)
        self.assertEqual(sessao.execucoes, [])

    def test_registro_sem_data_valida_e_descartado(self):
        total, sessao = self._carregar([
            {"date_start": "2026-08-01", "ad_id": "A"},
            {"date_start": None, "ad_id": "B"},
            {"ad_id": "C"},
            {"date_start": "nao-e-data", "ad_id": "D"},
        ])
        self.assertEqual(total, 1)
        self.assertEqual(len(sessao.params(0)), 1)

    def test_todos_descartados_nao_emite_instrucao(self):
        # Nenhuma linha valida: nem raw_ads nem ingestion_log sao tocados.
        total, sessao = self._carregar([{"ad_id": "A"}, {"ad_id": "B"}])
        self.assertEqual(total, 0)
        self.assertEqual(sessao.execucoes, [])

    def test_descarte_e_avisado_no_log(self):
        with self.assertLogs(bronze_loader.logger, level="WARNING") as capturado:
            self._carregar([
                {"date_start": "2026-08-01", "ad_id": "A"},
                {"ad_id": "B"},
            ])
        self.assertIn("descartados", "\n".join(capturado.output))

    def test_linha_carrega_fonte_data_lote_e_payload(self):
        _, sessao = self._carregar([{"date_start": "2026-08-01", "ad_id": "A"}])
        linha = sessao.params(0)[0]
        self.assertEqual(linha["source"], "meta_ads")
        self.assertEqual(str(linha["reference_date"]), "2026-08-01")
        self.assertEqual(linha["batch_id"], str(self.lote))
        self.assertEqual(json.loads(linha["payload"])["ad_id"], "A")

    def test_payload_preserva_acentuacao(self):
        # `ensure_ascii=False`: o payload guarda o texto como veio da API.
        _, sessao = self._carregar([
            {"date_start": "2026-08-01", "ad_name": "Promoção"},
        ])
        self.assertIn("Promoção", sessao.params(0)[0]["payload"])

    def test_campo_de_data_e_o_informado(self):
        # O Google usa outro nome de campo; o loader nao assume o do Meta.
        total, _ = self._carregar(
            [{"segments_date": "2026-08-01", "ad_id": "A"}], campo_data="segments_date"
        )
        self.assertEqual(total, 1)


class TestGravacaoDoLote(unittest.TestCase):
    """Caracteriza as duas instrucoes que `load_source` emite, e sua ordem."""

    def setUp(self):
        self.diretorio = Path(tempfile.mkdtemp(prefix="tcc_grav_"))
        self.addCleanup(shutil.rmtree, self.diretorio, ignore_errors=True)
        self.lote = uuid.UUID("00000000-0000-4000-8000-000000000002")
        caminho = self.diretorio / "bruto.json"
        caminho.write_text(json.dumps([
            {"date_start": "2026-08-03", "ad_id": "A"},
            {"date_start": "2026-08-01", "ad_id": "B"},
            {"date_start": "2026-08-05", "ad_id": "C"},
        ]), encoding="utf-8")
        self.sessao = SessaoDuble()
        self.total = bronze_loader.load_source(
            self.sessao, "meta_ads", caminho, "date_start", self.lote
        )

    def test_emite_exatamente_duas_instrucoes(self):
        self.assertEqual(self.total, 3)
        self.assertEqual(len(self.sessao.execucoes), 2)

    def test_raw_ads_vem_antes_do_ingestion_log(self):
        # A ordem importa: o log de ingestao descreve um lote que ja existe.
        self.assertIn("bronze.raw_ads", self.sessao.sql(0))
        self.assertIn("bronze.ingestion_log", self.sessao.sql(1))

    def test_insere_e_nao_atualiza(self):
        # Bronze e append-only: nada de UPDATE, DELETE ou UPSERT.
        for indice in (0, 1):
            sql = self.sessao.sql(indice).upper()
            with self.subTest(instrucao=indice):
                self.assertTrue(sql.startswith("INSERT INTO"))
                for proibido in ("ON CONFLICT", "UPDATE", "DELETE", "MERGE"):
                    self.assertNotIn(proibido, sql)

    def test_payload_entra_como_jsonb(self):
        self.assertIn("CAST(:payload AS JSONB)", self.sessao.sql(0))

    def test_ingestion_log_resume_o_lote_pelo_intervalo_real(self):
        # Minimo e maximo das datas presentes, nao a janela pedida.
        registro = self.sessao.params(1)
        self.assertEqual(registro["batch_id"], str(self.lote))
        self.assertEqual(registro["source"], "meta_ads")
        self.assertEqual(str(registro["start_date"]), "2026-08-01")
        self.assertEqual(str(registro["end_date"]), "2026-08-05")
        self.assertEqual(registro["row_count"], 3)

    def test_row_count_bate_com_as_linhas_inseridas(self):
        self.assertEqual(self.sessao.params(1)["row_count"],
                         len(self.sessao.params(0)))


class TestAtomicidadeDaCarga(unittest.TestCase):
    """Falha na carga faz rollback e nao deixa lote pela metade."""

    def test_erro_no_insert_faz_rollback_e_propaga(self):
        sessao = mock.MagicMock()
        with mock.patch.object(bronze_loader, "get_engine"), \
             mock.patch.object(bronze_loader, "ensure_schema"), \
             mock.patch.object(bronze_loader, "Session") as fabrica, \
             mock.patch.object(
                 bronze_loader, "load_source", side_effect=RuntimeError("falha")
             ):
            fabrica.return_value.__enter__.return_value = sessao
            with self.assertRaises(RuntimeError):
                bronze_loader.run(sources=["meta_ads"])
        sessao.rollback.assert_called_once()
        sessao.commit.assert_not_called()

    def test_sucesso_faz_um_unico_commit(self):
        sessao = mock.MagicMock()
        with mock.patch.object(bronze_loader, "get_engine"), \
             mock.patch.object(bronze_loader, "ensure_schema"), \
             mock.patch.object(bronze_loader, "Session") as fabrica, \
             mock.patch.object(bronze_loader, "load_source", return_value=7):
            fabrica.return_value.__enter__.return_value = sessao
            total = bronze_loader.run(sources=["meta_ads", "google_ads"])
        self.assertEqual(total, 14)
        sessao.commit.assert_called_once()
        sessao.rollback.assert_not_called()

    def test_cada_fonte_recebe_um_batch_id_proprio(self):
        lotes = []
        def espiar(session, source, path, date_field, batch_id):
            lotes.append(batch_id)
            return 0
        with mock.patch.object(bronze_loader, "get_engine"), \
             mock.patch.object(bronze_loader, "ensure_schema"), \
             mock.patch.object(bronze_loader, "Session") as fabrica, \
             mock.patch.object(bronze_loader, "load_source", side_effect=espiar):
            fabrica.return_value.__enter__.return_value = mock.MagicMock()
            bronze_loader.run(sources=["meta_ads", "google_ads"])
        self.assertEqual(len(lotes), 2)
        self.assertNotEqual(lotes[0], lotes[1])
