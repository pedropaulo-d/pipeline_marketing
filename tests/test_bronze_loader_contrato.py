"""Testes do contrato de entrada da carga bronze.

Verificam a porta de entrada do loader — o que ele aceita carregar — sem tocar
no banco: as checagens acontecem antes de qualquer conexao, de proposito, para
que uma execucao invalida falhe sem escrever nada.

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
