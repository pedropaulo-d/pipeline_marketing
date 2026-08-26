"""Testes da descoberta de contas do extrator Meta, sem chamada a API."""

import inspect
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

    def test_status_novo_falha_fechado(self) -> None:
        with self.assertRaises(ValueError):
            meta_ads._selecionar_contas_consultaveis([conta("A", 999)])


class TestLacunaDeCoberturaConhecida(unittest.TestCase):
    """`temporarily_unavailable` e lacuna conhecida, nao motivo para abortar.

    A politica anterior abortava a extracao inteira. Ela protegia contra um
    risco que deixou de existir: a Silver passou a escolher a observacao mais
    recente por entidade x dia pela chave hierarquica, entao conta ausente num
    snapshot nao apaga a observacao anterior. Medido em producao no DagRun
    `scheduled__2026-08-26T09:00:00+00:00`: duas contas nesse estado
    bloquearam as tres tentativas de `extrai_meta` e derrubaram a DAG inteira.
    """

    def test_indisponibilidade_nao_aborta_mais(self) -> None:
        contas = [
            conta("A", AdAccount.AccountStatus.active),
            conta("B", AdAccount.AccountStatus.temporarily_unavailable),
        ]

        resultado = meta_ads._selecionar_contas_consultaveis(contas)

        self.assertEqual(resultado, [contas[0]])

    def test_exclui_somente_a_conta_indisponivel(self) -> None:
        """Todo estado consultavel continua entrando, na ordem em que veio."""
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
            [consultaveis[0], indisponivel, *consultaveis[1:]]
        )

        self.assertEqual(resultado, consultaveis)

    def test_varias_indisponiveis_sao_contabilizadas(self) -> None:
        contas = [
            conta("A", AdAccount.AccountStatus.active),
            conta("B", AdAccount.AccountStatus.temporarily_unavailable),
            conta("C", AdAccount.AccountStatus.temporarily_unavailable),
            conta("D", AdAccount.AccountStatus.temporarily_unavailable),
        ]

        with self.assertLogs(meta_ads.logger, level="WARNING") as registro:
            resultado = meta_ads._selecionar_contas_consultaveis(contas)

        self.assertEqual(resultado, [contas[0]])
        self.assertIn("3 conta(s)", "\n".join(registro.output))

    def test_ausencia_nao_vira_linha_zerada(self) -> None:
        """A conta excluida contribui com NADA — nao com registro zerado. E o
        que deixa a Silver preservar a ultima observacao conhecida."""
        contas = [conta("B", AdAccount.AccountStatus.temporarily_unavailable)]

        resultado = meta_ads._selecionar_contas_consultaveis(contas)

        self.assertEqual(resultado, [])

    def test_log_e_agregado_e_sem_identificador(self) -> None:
        contas = [
            conta("A", AdAccount.AccountStatus.active),
            conta("B", AdAccount.AccountStatus.temporarily_unavailable),
        ]

        with self.assertLogs(meta_ads.logger, level="WARNING") as registro:
            meta_ads._selecionar_contas_consultaveis(contas)

        texto = "\n".join(registro.output)
        self.assertIn("1 conta(s)", texto)
        self.assertNotIn("EXTERNAL_ID_B", texto)
        self.assertNotIn("EMPRESA_B", texto)

    def test_status_desconhecido_continua_abortando(self) -> None:
        """A politica nova cobre indisponibilidade conhecida, nao contrato
        novo — inclusive quando os dois aparecem juntos."""
        with self.assertRaises(ValueError):
            meta_ads._selecionar_contas_consultaveis(
                [conta("A", AdAccount.AccountStatus.active), conta("Z", 999)]
            )

        with self.assertRaises(ValueError):
            meta_ads._selecionar_contas_consultaveis(
                [
                    conta("B", AdAccount.AccountStatus.temporarily_unavailable),
                    conta("Z", 999),
                ]
            )

    def test_descoberta_nao_exige_flag_para_prosseguir(self) -> None:
        """`discover_accounts` nao tem parametro de desvio: a politica normal
        ja e a degradacao controlada."""
        self.assertEqual(
            list(inspect.signature(meta_ads.discover_accounts).parameters), []
        )

        contas = {
            "A": conta("A", AdAccount.AccountStatus.active),
            "B": conta("B", AdAccount.AccountStatus.temporarily_unavailable),
        }
        with mock.patch.object(meta_ads, "Business"), \
                mock.patch.object(
                    meta_ads, "_paginate_accounts", side_effect=[contas, {}]
                ):
            resultado = meta_ads.discover_accounts()

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


class TestCanalGenericoDeOpcoes(unittest.TestCase):
    """`Plataforma.extrair(**opcoes)` sobreviveu a remocao do opt-in do Meta.

    Ele nao existe para o desvio que foi removido: e o canal generico de
    desvio especifico de plataforma, e sua garantia util e que uma opcao
    dirigida a plataforma errada estoura em vez de ser ignorada em silencio.
    Sem essa propriedade, um desvio futuro poderia ser pedido e nao valer.
    """

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
                {"meta": {"desvio_ficticio": True}},
            )

        self.assertEqual(chamadas["meta"], {"desvio_ficticio": True})
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

    def test_extrair_repassa_opcoes_ao_run_do_extrator(self) -> None:
        """O elo que so uma execucao real exercitaria: a opcao chega ao
        orquestrador e nao chega ao `run` do extrator."""
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
                "2026-08-05", "2026-08-09", "run-1", desvio_ficticio=True
            )

        importar.assert_called_once_with("extractors.meta_ads")
        self.assertEqual(total, 7)
        self.assertEqual(recebido["start"], "2026-08-05")
        self.assertEqual(recebido["end"], "2026-08-09")
        self.assertEqual(recebido["run_id"], "run-1")
        self.assertEqual(recebido["opcoes"], {"desvio_ficticio": True})

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

    def test_opcao_dirigida_a_plataforma_errada_estoura(self) -> None:
        with mock.patch.object(meta_ads, "validate_env"), \
                mock.patch.object(meta_ads, "init_api"), \
                mock.patch.object(meta_ads, "executar_extracao", return_value=0):
            from plataformas import PLATAFORMAS

            with self.assertRaises(TypeError):
                PLATAFORMAS["meta"].extrair(
                    "2026-08-05", "2026-08-09", "run-1", opcao_inexistente=True
                )


class TestRunDoMetaLigaADescoberta(unittest.TestCase):
    """`meta_ads.run` entrega a descoberta a casca comum sem intermediario.

    Com a politica nova nao ha mais desvio para propagar: a casca chama
    `discover_accounts` diretamente, e e ela quem aplica a degradacao.
    """

    def test_run_passa_discover_accounts_direto(self) -> None:
        recebido: dict = {}

        def executar_falso(plataforma, descobrir_contas, **resto):
            recebido["descobrir"] = descobrir_contas
            descobrir_contas()
            return 0

        with mock.patch.object(meta_ads, "validate_env"), \
                mock.patch.object(meta_ads, "init_api"), \
                mock.patch.object(
                    meta_ads, "discover_accounts", return_value=[]
                ) as descoberta, \
                mock.patch.object(meta_ads, "executar_extracao", executar_falso):
            meta_ads.run("2026-08-05", "2026-08-09", "run-1")

        descoberta.assert_called_once_with()
        self.assertEqual(
            list(inspect.signature(meta_ads.run).parameters),
            ["start_date", "end_date", "run_id"],
        )


class TestDagNaoPrecisaDeFlagExcepcional(unittest.TestCase):
    """A DAG roda o extrator standalone e nao passa flag nenhuma.

    Antes isso era uma proibicao — a DAG nao podia ligar o desvio. Agora e uma
    consequencia: a degradacao controlada e a politica normal, entao nao ha
    flag a passar. Teste de codigo-fonte porque vale mesmo sem Airflow.
    """

    def test_dag_nao_menciona_flag_de_desvio(self) -> None:
        from pathlib import Path

        raiz = Path(__file__).resolve().parent.parent
        fonte = (
            raiz / "airflow" / "dags" / "pipeline_marketing_diario.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("permitir-contas-meta-indisponiveis", fonte)
        self.assertNotIn("permitir_contas_indisponiveis", fonte)

    def test_cli_do_orquestrador_nao_expoe_mais_a_flag(self) -> None:
        import sys

        import main

        with mock.patch.object(sys, "argv", ["main.py", "--skip-extract"]):
            args = main.parse_args()

        self.assertFalse(hasattr(args, "permitir_contas_meta_indisponiveis"))

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
