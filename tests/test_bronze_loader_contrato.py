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

from sqlalchemy.exc import IntegrityError

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
    alem de `execute`, `commit` e `rollback` — a superficie que `load_source` e
    `run` de fato usam. Se o loader passar a chamar outro metodo da sessao, o
    teste quebra com `AttributeError` — que e o comportamento desejado, e o
    motivo de nao usar `MagicMock` aqui.
    """

    def __init__(self, retorno=()):
        self.execucoes: list[tuple[str, object]] = []
        # `_conferir_replay` itera o resultado do SELECT. O dublê devolve
        # sempre a mesma lista de tuplas — nao interpreta o SQL para decidir.
        self.retorno = list(retorno)

        self.commits = 0
        self.rollbacks = 0

    def execute(self, instrucao, parametros=None):
        self.execucoes.append((str(instrucao), parametros))
        return list(self.retorno)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

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
            sessao, "meta_ads", self._arquivo(registros), campo_data,
            self.lote, RUN_ATUAL,
        )
        return total, sessao

    def test_arquivo_ausente_nao_emite_instrucao(self):
        sessao = SessaoDuble()
        total = bronze_loader.load_source(
            sessao, "meta_ads", self.diretorio / "nao_existe.json",
            "date_start", self.lote, RUN_ATUAL,
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
            self.sessao, "meta_ads", caminho, "date_start", self.lote, RUN_ATUAL
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

    def test_ingestion_log_nomeia_as_colunas(self):
        # INSERT posicional quebraria em silencio quando a tabela ganhasse uma
        # coluna no meio — foi o que aconteceu ao acrescentar `run_id`.
        sql = self.sessao.sql(1)
        self.assertIn(
            "(batch_id, source, run_id, start_date, end_date, row_count)", sql
        )

    def test_ingestion_log_carrega_o_run_id(self):
        # A execucao logica fica gravada: e por ela que o replay e detectado.
        self.assertEqual(self.sessao.params(1)["run_id"], RUN_ATUAL)

    def test_run_id_nao_entra_em_raw_ads(self):
        # `batch_id` ja liga a linha bruta ao lote; duplicar `run_id` em 52 mil
        # linhas nao acrescenta nada que o log nao responda.
        self.assertNotIn("run_id", self.sessao.sql(0))
        for linha in self.sessao.params(0):
            self.assertNotIn("run_id", linha)


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
        def espiar(session, source, path, date_field, batch_id, run_id):
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


class TestIdempotenciaPorRunId(unittest.TestCase):
    """Uma execucao nao pode confirmar duas vezes a mesma fonte.

    O `batch_id` e sorteado a cada carga, entao ele nunca detectaria o replay:
    a segunda tentativa nascia com identidade nova e a bronze terminava com
    tudo duplicado, sem erro no caminho. A identidade operacional que estes
    testes exercitam e `(source, run_id)`.
    """

    def _rodar(self, sources, run_id, ja_confirmadas=(), carregadas=None):
        """Executa `run` com a sessao substituida pelo dublê.

        `ja_confirmadas` sao as fontes que o `ingestion_log` devolveria para
        este `run_id` — o estado que a consulta de replay enxerga.
        """
        sessao = SessaoDuble(retorno=[(fonte,) for fonte in ja_confirmadas])
        registradas = [] if carregadas is None else carregadas

        def espiar(session, source, path, date_field, batch_id, run_id_recebido):
            registradas.append((source, run_id_recebido))
            return 0

        with mock.patch.object(bronze_loader, "get_engine"), \
             mock.patch.object(bronze_loader, "ensure_schema"), \
             mock.patch.object(bronze_loader, "_conferir_artefatos"), \
             mock.patch.object(bronze_loader, "Session") as fabrica, \
             mock.patch.object(bronze_loader, "load_source", side_effect=espiar):
            fabrica.return_value.__enter__.return_value = sessao
            total = bronze_loader.run(
                sources=sources, run_id=run_id,
                start_date=INICIO, end_date=FIM,
            )
        return total, sessao, registradas

    def test_primeira_carga_da_execucao_passa(self):
        total, sessao, carregadas = self._rodar(["meta_ads"], RUN_ATUAL)
        self.assertEqual(total, 0)
        self.assertEqual(carregadas, [("meta_ads", RUN_ATUAL)])

    def test_replay_da_mesma_fonte_falha(self):
        with self.assertRaises(bronze_loader.LoteJaCarregado):
            self._rodar(["meta_ads"], RUN_ATUAL, ja_confirmadas=["meta_ads"])

    def test_replay_nao_e_sucesso_silencioso(self):
        # O modo errado de "resolver" replay e devolver 0 e seguir em frente:
        # a operacao pedida nao aconteceu, e quem chamou precisa saber.
        with self.assertRaises(bronze_loader.LoteJaCarregado) as capturado:
            self._rodar(["meta_ads"], RUN_ATUAL, ja_confirmadas=["meta_ads"])
        self.assertIn("meta_ads", str(capturado.exception))
        self.assertIn(RUN_ATUAL, str(capturado.exception))

    def test_replay_falha_antes_de_qualquer_insert(self):
        carregadas = []
        with self.assertRaises(bronze_loader.LoteJaCarregado):
            self._rodar(
                ["meta_ads"], RUN_ATUAL,
                ja_confirmadas=["meta_ads"], carregadas=carregadas,
            )
        # Nenhuma fonte chegou a `load_source` — nada foi preparado nem gravado.
        self.assertEqual(carregadas, [])

    def test_replay_de_uma_fonte_recusa_a_carga_inteira(self):
        # Aceitar o Google e so entao recusar o Meta deixaria meia execucao
        # dentro — mesmo motivo de `_conferir_artefatos` conferir tudo antes.
        carregadas = []
        with self.assertRaises(bronze_loader.LoteJaCarregado):
            self._rodar(
                ["meta_ads", "google_ads"], RUN_ATUAL,
                ja_confirmadas=["google_ads"], carregadas=carregadas,
            )
        self.assertEqual(carregadas, [])

    def test_fonte_diferente_com_mesmo_run_id_e_aceita(self):
        # Um run carrega as duas plataformas: (meta_ads, R) e (google_ads, R)
        # sao lotes legitimos. A chave e o par, nao o run_id sozinho.
        total, _, carregadas = self._rodar(
            ["google_ads"], RUN_ATUAL, ja_confirmadas=["meta_ads"]
        )
        self.assertEqual(total, 0)
        self.assertEqual(carregadas, [("google_ads", RUN_ATUAL)])

    def test_consulta_de_replay_filtra_por_run_id(self):
        _, sessao, _ = self._rodar(["meta_ads"], RUN_ATUAL)
        self.assertIn("bronze.ingestion_log", sessao.sql(0))
        self.assertIn("run_id = :run_id", sessao.sql(0))
        self.assertEqual(sessao.params(0), {"run_id": RUN_ATUAL})

    def test_replay_faz_rollback_e_nao_commita(self):
        sessao = mock.MagicMock()
        sessao.execute.return_value = [("meta_ads",)]
        with mock.patch.object(bronze_loader, "get_engine"), \
             mock.patch.object(bronze_loader, "ensure_schema"), \
             mock.patch.object(bronze_loader, "_conferir_artefatos"), \
             mock.patch.object(bronze_loader, "Session") as fabrica, \
             mock.patch.object(bronze_loader, "load_source") as carga:
            fabrica.return_value.__enter__.return_value = sessao
            with self.assertRaises(bronze_loader.LoteJaCarregado):
                bronze_loader.run(
                    sources=["meta_ads"], run_id=RUN_ATUAL,
                    start_date=INICIO, end_date=FIM,
                )
        carga.assert_not_called()
        sessao.rollback.assert_called_once()
        sessao.commit.assert_not_called()


class TestCargaLocalSemRunId(unittest.TestCase):
    """`--skip-extract` nao tem execucao de origem para declarar.

    Continua funcionando, com `run_id` nulo no log — o indice unico e parcial
    justamente para nao transformar esse modo em erro. A contrapartida esta
    documentada e e testada aqui: sem `run_id` nao ha protecao contra replay.
    """

    def _rodar(self):
        sessao = SessaoDuble()
        with mock.patch.object(bronze_loader, "get_engine"), \
             mock.patch.object(bronze_loader, "ensure_schema"), \
             mock.patch.object(bronze_loader, "Session") as fabrica, \
             mock.patch.object(bronze_loader, "load_source", return_value=0):
            fabrica.return_value.__enter__.return_value = sessao
            bronze_loader.run(sources=["meta_ads"])
        return sessao

    def test_carga_local_nao_consulta_replay(self):
        # Sem run_id nao ha o que comparar: a consulta seria sempre vazia.
        sessao = self._rodar()
        self.assertEqual(sessao.execucoes, [])

    def test_carga_local_avisa_que_nao_ha_protecao(self):
        with self.assertLogs(bronze_loader.logger, level="WARNING") as capturado:
            self._rodar()
        self.assertIn("replay", "\n".join(capturado.output))

    def test_run_id_nulo_chega_ao_ingestion_log(self):
        diretorio = Path(tempfile.mkdtemp(prefix="tcc_local_"))
        self.addCleanup(shutil.rmtree, diretorio, ignore_errors=True)
        caminho = diretorio / "bruto.json"
        caminho.write_text(
            json.dumps([{"date_start": "2026-08-01", "ad_id": "A"}]),
            encoding="utf-8",
        )
        sessao = SessaoDuble()
        bronze_loader.load_source(
            sessao, "meta_ads", caminho, "date_start",
            uuid.UUID("00000000-0000-4000-8000-000000000003"), None,
        )
        self.assertIsNone(sessao.params(1)["run_id"])


class TestCorridaEntreCargas(unittest.TestCase):
    """A consulta previa nao basta; a unicidade do banco e que decide.

    Dois processos podem consultar o `ingestion_log` antes de qualquer um
    confirmar: os dois passam pela checagem e os dois tentam gravar. O perdedor
    recebe a violacao de unicidade no INSERT do log — depois de ja ter inserido
    linhas em `raw_ads` na mesma transacao.
    """

    def test_violacao_de_unicidade_desfaz_as_linhas_ja_inseridas(self):
        sessao = mock.MagicMock()
        sessao.execute.return_value = []
        violacao = IntegrityError(
            "INSERT INTO bronze.ingestion_log", {},
            Exception("duplicate key value violates unique constraint "
                      "\"uq_ingestion_log_source_run_id\""),
        )
        with mock.patch.object(bronze_loader, "get_engine"), \
             mock.patch.object(bronze_loader, "ensure_schema"), \
             mock.patch.object(bronze_loader, "_conferir_artefatos"), \
             mock.patch.object(bronze_loader, "Session") as fabrica, \
             mock.patch.object(
                 bronze_loader, "load_source", side_effect=violacao
             ):
            fabrica.return_value.__enter__.return_value = sessao
            with self.assertRaises(IntegrityError):
                bronze_loader.run(
                    sources=["meta_ads"], run_id=RUN_ATUAL,
                    start_date=INICIO, end_date=FIM,
                )
        # Rollback unico: as raw_ads da tentativa perdedora nao sobrevivem.
        sessao.rollback.assert_called_once()
        sessao.commit.assert_not_called()

    def test_tentativa_que_falhou_nao_deixa_lock_logico(self):
        # Falha antes do commit nao grava ingestion_log, entao o mesmo run_id
        # continua carregavel. Nada de bloquear por "ja tentou uma vez".
        sessao = SessaoDuble()
        with mock.patch.object(bronze_loader, "get_engine"), \
             mock.patch.object(bronze_loader, "ensure_schema"), \
             mock.patch.object(bronze_loader, "_conferir_artefatos"), \
             mock.patch.object(bronze_loader, "Session") as fabrica, \
             mock.patch.object(bronze_loader, "load_source", return_value=0):
            fabrica.return_value.__enter__.return_value = sessao
            bronze_loader.run(
                sources=["meta_ads"], run_id=RUN_ATUAL,
                start_date=INICIO, end_date=FIM,
            )
        # A consulta nao encontrou nada, e a carga seguiu.
        self.assertEqual(len(sessao.execucoes), 1)


class TestSchemaDaIngestionLog(unittest.TestCase):
    """O DDL e a ultima linha de defesa; estes testes leem o arquivo.

    Nao substituem o teste contra Postgres real — afirmam que a intencao esta
    escrita no unico DDL do projeto, que `ensure_schema` reaplica a cada carga.
    """

    @classmethod
    def setUpClass(cls):
        cls.ddl = bronze_loader.DDL_PATH.read_text(encoding="utf-8")

    def test_ingestion_log_declara_run_id(self):
        self.assertIn("run_id          TEXT", self.ddl)

    def test_run_id_e_nulavel(self):
        # Os 67 lotes anteriores a esta coluna nao tem run_id, e a carga local
        # tambem nao. Exigir NOT NULL obrigaria a fabricar identidade.
        self.assertNotIn("run_id          TEXT        NOT NULL", self.ddl)

    def test_banco_existente_recebe_a_coluna(self):
        # `CREATE TABLE IF NOT EXISTS` nao altera tabela que ja existe: sem o
        # ALTER, banco novo e banco antigo divergiriam em silencio.
        self.assertIn("ADD COLUMN IF NOT EXISTS run_id TEXT", self.ddl)

    def test_unicidade_e_por_fonte_e_execucao(self):
        self.assertIn("CREATE UNIQUE INDEX IF NOT EXISTS", self.ddl)
        self.assertIn("ON bronze.ingestion_log (source, run_id)", self.ddl)

    def test_unicidade_ignora_run_id_nulo(self):
        self.assertIn("WHERE run_id IS NOT NULL", self.ddl)

    def test_raw_ads_nao_ganhou_run_id(self):
        criacao = self.ddl.split("CREATE TABLE IF NOT EXISTS bronze.raw_ads")[1]
        criacao = criacao.split(");")[0]
        self.assertNotIn("run_id", criacao)

    def test_ddl_continua_reaplicavel(self):
        # Toda instrucao que cria ou altera estrutura e idempotente: o DDL roda
        # inteiro a cada carga.
        for instrucao in ("CREATE SCHEMA IF NOT EXISTS",
                          "CREATE TABLE IF NOT EXISTS",
                          "CREATE INDEX IF NOT EXISTS",
                          "CREATE UNIQUE INDEX IF NOT EXISTS",
                          "ADD COLUMN IF NOT EXISTS"):
            with self.subTest(instrucao=instrucao):
                self.assertIn(instrucao, self.ddl)
