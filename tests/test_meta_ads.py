"""Testes da descoberta de contas do extrator Meta, sem chamada a API."""

import unittest
from collections.abc import Iterator
from unittest import mock

from facebook_business.adobjects.adaccount import AdAccount

from extractors import meta_ads


class CursorFalso:
    """Cursor minimo com paginacao compativel com o SDK da Meta."""

    def __init__(self, paginas: list[list[dict]]) -> None:
        self.paginas = paginas
        self.indice = 0

    def __iter__(self) -> Iterator[dict]:
        return iter(self.paginas[self.indice])

    def load_next_page(self) -> bool:
        """Avanca uma pagina e informa se ainda havia conteudo."""
        if self.indice + 1 >= len(self.paginas):
            return False
        self.indice += 1
        return True


def conta(sufixo: str, status: int) -> dict:
    """Cria uma conta sintetica no contrato interno da descoberta."""
    return {
        "id": f"EXTERNAL_ID_{sufixo}",
        "name": f"EMPRESA_{sufixo}",
        "status": status,
    }


class TestPaginacaoDeContas(unittest.TestCase):
    """A descoberta percorre todas as paginas e deduplica por ID."""

    def test_percorre_paginas_e_remove_duplicata(self) -> None:
        cursor = CursorFalso([
            [
                {
                    "account_id": "EXTERNAL_ID_A",
                    "name": "EMPRESA_A",
                    "account_status": 1,
                },
                {
                    "account_id": "EXTERNAL_ID_B",
                    "name": "EMPRESA_B",
                    "account_status": 2,
                },
            ],
            [
                {
                    "account_id": "EXTERNAL_ID_B",
                    "name": "EMPRESA_B",
                    "account_status": 2,
                },
                {
                    "account_id": "EXTERNAL_ID_C",
                    "name": "EMPRESA_C",
                    "account_status": 1,
                },
            ],
        ])

        resultado = meta_ads._paginate_accounts(cursor)

        self.assertEqual(
            set(resultado),
            {"EXTERNAL_ID_A", "EXTERNAL_ID_B", "EXTERNAL_ID_C"},
        )
        self.assertEqual(resultado["EXTERNAL_ID_B"]["status"], 2)


class TestEstadosConsultaveis(unittest.TestCase):
    """Estado atual de entrega nao apaga participacao historica."""

    def test_conta_ativa_e_incluida(self) -> None:
        contas = [conta("A", AdAccount.AccountStatus.active)]

        self.assertEqual(meta_ads._selecionar_contas_consultaveis(contas), contas)

    def test_conta_desabilitada_mas_acessivel_e_incluida(self) -> None:
        contas = [conta("A", AdAccount.AccountStatus.disabled)]

        self.assertEqual(meta_ads._selecionar_contas_consultaveis(contas), contas)

    def test_estados_sem_entrega_mas_com_historico_sao_incluidos(self) -> None:
        statuses = (
            AdAccount.AccountStatus.unsettled,
            AdAccount.AccountStatus.pending_review,
            AdAccount.AccountStatus.in_grace_period,
            AdAccount.AccountStatus.pending_closure,
        )
        contas = [
            conta(str(indice), status)
            for indice, status in enumerate(statuses)
        ]

        self.assertEqual(meta_ads._selecionar_contas_consultaveis(contas), contas)

    def test_indisponibilidade_aborta_em_vez_de_gerar_snapshot_parcial(
        self,
    ) -> None:
        contas = [
            conta("A", AdAccount.AccountStatus.active),
            conta("B", AdAccount.AccountStatus.temporarily_unavailable),
        ]

        with self.assertRaises(RuntimeError) as erro:
            meta_ads._selecionar_contas_consultaveis(contas)

        self.assertNotIn("EXTERNAL_ID_B", str(erro.exception))
        self.assertNotIn("EMPRESA_B", str(erro.exception))

    def test_status_novo_falha_fechado(self) -> None:
        with self.assertRaises(ValueError):
            meta_ads._selecionar_contas_consultaveis([conta("A", 999)])


class TestDesvioExcepcionalDeIndisponibilidade(unittest.TestCase):
    """O desvio para conta indisponivel e opt-in por execucao, nunca default.

    Uma conta presa em ``temporarily_unavailable`` bloqueia toda extracao
    Meta. O desvio existe para recuperacao autorizada e precisa continuar
    sendo excecao: default fechado, escopo minimo, status desconhecido
    abortando de qualquer jeito.
    """

    def test_default_continua_abortando(self) -> None:
        """Sem opt-in explicito, indisponibilidade aborta — inclusive quando o
        parametro e passado como ``False``."""
        contas = [
            conta("A", AdAccount.AccountStatus.active),
            conta("B", AdAccount.AccountStatus.temporarily_unavailable),
        ]

        with self.assertRaises(RuntimeError):
            meta_ads._selecionar_contas_consultaveis(contas)

        with self.assertRaises(RuntimeError):
            meta_ads._selecionar_contas_consultaveis(
                contas, permitir_contas_indisponiveis=False
            )

    def test_opt_in_exclui_apenas_temporariamente_indisponivel(self) -> None:
        """O desvio remove so o estado indisponivel; todo estado consultavel
        continua entrando, com a ordem preservada."""
        consultaveis = [
            conta("A", AdAccount.AccountStatus.active),
            conta("C", AdAccount.AccountStatus.disabled),
            conta("D", AdAccount.AccountStatus.unsettled),
            conta("E", AdAccount.AccountStatus.pending_review),
            conta("F", AdAccount.AccountStatus.in_grace_period),
            conta("G", AdAccount.AccountStatus.pending_closure),
        ]
        indisponivel = conta("B", AdAccount.AccountStatus.temporarily_unavailable)

        resultado = meta_ads._selecionar_contas_consultaveis(
            [consultaveis[0], indisponivel, *consultaveis[1:]],
            permitir_contas_indisponiveis=True,
        )

        self.assertEqual(resultado, consultaveis)

    def test_status_desconhecido_aborta_mesmo_com_opt_in(self) -> None:
        """O desvio cobre indisponibilidade conhecida, nao contrato novo."""
        with self.assertRaises(ValueError):
            meta_ads._selecionar_contas_consultaveis(
                [conta("A", AdAccount.AccountStatus.active), conta("Z", 999)],
                permitir_contas_indisponiveis=True,
            )

        # Indisponivel + desconhecido na mesma descoberta: o desconhecido
        # continua mandando, mesmo com o desvio ligado.
        with self.assertRaises(ValueError):
            meta_ads._selecionar_contas_consultaveis(
                [
                    conta("B", AdAccount.AccountStatus.temporarily_unavailable),
                    conta("Z", 999),
                ],
                permitir_contas_indisponiveis=True,
            )

    def test_exclusao_e_registrada_em_log_sem_identificador(self) -> None:
        """A exclusao precisa aparecer no log, e sem vazar identificador."""
        contas = [
            conta("A", AdAccount.AccountStatus.active),
            conta("B", AdAccount.AccountStatus.temporarily_unavailable),
        ]

        with self.assertLogs(meta_ads.logger, level="WARNING") as registro:
            meta_ads._selecionar_contas_consultaveis(
                contas, permitir_contas_indisponiveis=True
            )

        texto = "\n".join(registro.output)
        self.assertIn("1", texto)
        self.assertNotIn("EXTERNAL_ID_B", texto)
        self.assertNotIn("EMPRESA_B", texto)

    @mock.patch.object(meta_ads, "_paginate_accounts")
    @mock.patch.object(meta_ads, "Business")
    def test_discover_accounts_propaga_o_desvio(
        self, business: mock.Mock, paginar: mock.Mock
    ) -> None:
        """`discover_accounts` e a porta do desvio: fechada por default."""
        contas = {
            "A": conta("A", AdAccount.AccountStatus.active),
            "B": conta("B", AdAccount.AccountStatus.temporarily_unavailable),
        }
        paginar.side_effect = [contas, {}]

        with self.assertRaises(RuntimeError):
            meta_ads.discover_accounts()

        paginar.side_effect = [contas, {}]
        resultado = meta_ads.discover_accounts(permitir_contas_indisponiveis=True)

        self.assertEqual([item["id"] for item in resultado], ["EXTERNAL_ID_A"])


class TestDescobertaOwnedEClient(unittest.TestCase):
    """Owned e client formam um conjunto unico antes da classificacao."""

    @mock.patch.object(meta_ads, "_paginate_accounts")
    @mock.patch.object(meta_ads, "Business")
    def test_conta_duplicada_owned_client_aparece_uma_vez(
        self, business: mock.Mock, paginar: mock.Mock
    ) -> None:
        paginar.side_effect = [
            {"A": conta("A", AdAccount.AccountStatus.active)},
            {
                "A": conta("A", AdAccount.AccountStatus.active),
                "B": conta("B", AdAccount.AccountStatus.disabled),
            },
        ]

        resultado = meta_ads.discover_accounts()

        self.assertEqual(
            [item["id"] for item in resultado],
            ["EXTERNAL_ID_A", "EXTERNAL_ID_B"],
        )
        self.assertEqual(paginar.call_count, 2)
        instancia = business.return_value
        instancia.get_owned_ad_accounts.assert_called_once()
        instancia.get_client_ad_accounts.assert_called_once()


class TestFlagDeDesvioNoOrquestrador(unittest.TestCase):
    """A flag existe no `main.py`, alcanca so o Meta e nao vaza para o resto.

    O desvio precisa ser visivel na linha de comando da execucao: e assim que
    ele fica auditavel depois. Variavel de ambiente sobreviveria a execucao
    seguinte sem ninguem notar.
    """

    def _args(self, *argv: str) -> object:
        import sys

        import main

        with mock.patch.object(sys, "argv", ["main.py", *argv]):
            return main.parse_args()

    def test_default_da_cli_e_fail_closed(self) -> None:
        self.assertFalse(self._args().permitir_contas_meta_indisponiveis)

    def test_flag_liga_o_desvio(self) -> None:
        args = self._args(
            "--platforms", "meta", "--permitir-contas-meta-indisponiveis"
        )

        self.assertTrue(args.permitir_contas_meta_indisponiveis)

    def test_flag_sem_meta_e_erro_de_uso(self) -> None:
        with self.assertRaises(SystemExit):
            self._args(
                "--platforms", "google", "--permitir-contas-meta-indisponiveis"
            )

    def test_flag_com_skip_extract_e_erro_de_uso(self) -> None:
        with self.assertRaises(SystemExit):
            self._args("--skip-extract", "--permitir-contas-meta-indisponiveis")

    def test_opcao_alcanca_apenas_a_plataforma_declarada(self) -> None:
        import main
        from plataformas import Plataforma

        chamadas: dict[str, dict] = {}

        def extrair(self, start, end, run_id=None, **opcoes):
            chamadas[self.chave] = opcoes
            return 0

        with mock.patch.object(Plataforma, "extrair", extrair):
            main.run_extraction(
                "2026-08-05",
                "2026-08-09",
                ["meta", "google"],
                "run",
                {"meta": {"permitir_contas_indisponiveis": True}},
            )

        self.assertEqual(chamadas["meta"], {"permitir_contas_indisponiveis": True})
        self.assertEqual(chamadas["google"], {})

    def test_sem_opcoes_a_extracao_nao_recebe_nada(self) -> None:
        import main
        from plataformas import Plataforma

        chamadas: dict[str, dict] = {}

        def extrair(self, start, end, run_id=None, **opcoes):
            chamadas[self.chave] = opcoes
            return 0

        with mock.patch.object(Plataforma, "extrair", extrair):
            main.run_extraction("2026-08-05", "2026-08-09", ["meta"], "run")

        self.assertEqual(chamadas, {"meta": {}})


class TestRepasseRealDaOpcao(unittest.TestCase):
    """Os dois elos que so eram exercitados por execucao real.

    Os testes do orquestrador fazem patch de `Plataforma.extrair`, entao a
    linha que repassa as opcoes ao `run` do extrator nunca era executada. E
    `meta_ads.run` monta a chamada de descoberta num lambda que tambem ficava
    fora da suite. Sao os dois pontos onde um desvio pode se perder em
    silencio: a opcao chega ao orquestrador e nao chega ao SDK.
    """

    def test_extrair_repassa_opcoes_ao_run_do_extrator(self) -> None:
        import importlib

        from plataformas import PLATAFORMAS

        recebido: dict = {}

        class ModuloFalso:
            @staticmethod
            def run(start_date, end_date, run_id=None, **opcoes):
                recebido.update(
                    start=start_date, end=end_date, run_id=run_id, opcoes=opcoes
                )
                return 7

        with mock.patch.object(
            importlib, "import_module", return_value=ModuloFalso
        ) as importar:
            total = PLATAFORMAS["meta"].extrair(
                "2026-08-05", "2026-08-09", "run-1",
                permitir_contas_indisponiveis=True,
            )

        importar.assert_called_once_with("extractors.meta_ads")
        self.assertEqual(total, 7)
        self.assertEqual(recebido["start"], "2026-08-05")
        self.assertEqual(recebido["end"], "2026-08-09")
        self.assertEqual(recebido["run_id"], "run-1")
        self.assertEqual(recebido["opcoes"], {"permitir_contas_indisponiveis": True})

    def test_extrair_sem_opcoes_nao_inventa_argumento(self) -> None:
        import importlib

        from plataformas import PLATAFORMAS

        recebido: dict = {}

        class ModuloFalso:
            @staticmethod
            def run(start_date, end_date, run_id=None, **opcoes):
                recebido["opcoes"] = opcoes
                return 0

        with mock.patch.object(importlib, "import_module", return_value=ModuloFalso):
            PLATAFORMAS["google"].extrair("2026-08-05", "2026-08-09", "run-1")

        self.assertEqual(recebido["opcoes"], {})

    def test_run_do_meta_encaminha_o_desvio_a_descoberta(self) -> None:
        """`meta_ads.run` liga a flag ao lambda que chama a descoberta."""
        registrado: list[bool] = []

        def descoberta_falsa(permitir_contas_indisponiveis: bool = False):
            registrado.append(permitir_contas_indisponiveis)
            return []

        def executar_falso(plataforma, descobrir_contas, **resto):
            # A casca so chama `descobrir_contas()`; e essa chamada que carrega
            # (ou perde) o desvio.
            descobrir_contas()
            return 0

        with mock.patch.object(meta_ads, "validate_env"), \
                mock.patch.object(meta_ads, "init_api"), \
                mock.patch.object(meta_ads, "discover_accounts", descoberta_falsa), \
                mock.patch.object(meta_ads, "executar_extracao", executar_falso):
            meta_ads.run("2026-08-05", "2026-08-09", "run-1")
            meta_ads.run(
                "2026-08-05", "2026-08-09", "run-1",
                permitir_contas_indisponiveis=True,
            )

        self.assertEqual(registrado, [False, True])


class TestDagNaoUsaODesvio(unittest.TestCase):
    """A DAG nunca liga o desvio: ela roda o extrator standalone, que nem o
    aceita. Teste de codigo-fonte porque vale mesmo sem Airflow instalado."""

    def test_dag_nao_menciona_a_flag(self) -> None:
        from pathlib import Path

        raiz = Path(__file__).resolve().parent.parent
        fonte = (
            raiz / "airflow" / "dags" / "pipeline_marketing_diario.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("permitir-contas-meta-indisponiveis", fonte)
        self.assertNotIn("permitir_contas_indisponiveis", fonte)

    def test_cli_standalone_do_extrator_nao_expoe_a_flag(self) -> None:
        import sys

        from extractors import comum
        from plataformas import PLATAFORMAS

        argv = ["meta_ads", "--start-date", "2026-08-05", "--end-date", "2026-08-09"]
        with mock.patch.object(sys, "argv", argv):
            args = comum._parse_args(PLATAFORMAS["meta"])

        self.assertFalse(hasattr(args, "permitir_contas_indisponiveis"))
        self.assertFalse(hasattr(args, "permitir_contas_meta_indisponiveis"))


if __name__ == "__main__":
    unittest.main()
