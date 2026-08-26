"""Testes da descoberta de subcontas do extrator Google, sem chamada a API."""

import importlib
import inspect
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from google.ads.googleads.client import _DEFAULT_VERSION
from google.ads.googleads.errors import GoogleAdsException

from extractors import google_ads
from extractors.google_ads import CUSTOMER_NOT_ENABLED, CustomerStatus

_ERROS = importlib.import_module(
    f"google.ads.googleads.{_DEFAULT_VERSION}.errors.types.errors"
)
_QUOTA = importlib.import_module(
    f"google.ads.googleads.{_DEFAULT_VERSION}.errors"
).QuotaErrorEnum.QuotaError

RAIZ = Path(__file__).resolve().parent.parent


def conta(sufixo: str, status: int) -> dict:
    """Cria uma subconta sintetica no contrato interno da descoberta."""
    return {
        "id": f"EXTERNAL_ID_{sufixo}",
        "name": f"EMPRESA_{sufixo}",
        "status": status,
    }


def linha(sufixo: str, status: int, manager: bool = False) -> SimpleNamespace:
    """Cria uma linha de resposta da GAQL de descoberta.

    O extrator usa ``use_proto_plus: False``, entao o SDK devolve o protobuf
    cru: ``status`` chega como inteiro e ``id`` como int64.
    """
    return SimpleNamespace(
        customer_client=SimpleNamespace(
            id=int.from_bytes(sufixo.encode(), "big"),
            descriptive_name=f"EMPRESA_{sufixo}",
            status=int(status),
            manager=manager,
        )
    )


def falha(**codigos: int) -> GoogleAdsException:
    """Monta uma GoogleAdsException real a partir dos codigos informados.

    Os tipos vem do SDK instalado: um dublê de mensagem provaria so que o
    classificador entende o dublê.
    """
    erros = [
        _ERROS.GoogleAdsError(error_code=_ERROS.ErrorCode(**{campo: valor}))
        for campo, valor in codigos.items()
    ]
    return GoogleAdsException(
        None, None, _ERROS.GoogleAdsFailure(errors=erros), "req-teste"
    )


def extrair_com_recusa(status: int, excecao: Exception) -> tuple[list, Counter]:
    """Roda a borda de tolerancia com `extract_daily_ads` sempre recusando."""
    excluidas: Counter = Counter()
    with mock.patch.object(google_ads, "extract_daily_ads", side_effect=excecao):
        linhas = google_ads._extrair_conta_tolerando_desativacao(
            mock.Mock(),
            {"EXTERNAL_ID_A": status},
            excluidas,
            "EXTERNAL_ID_A",
            "EMPRESA_A",
            "2026-08-01",
            "2026-08-04",
        )
    return linhas, excluidas


def descobrir(linhas: list[SimpleNamespace]) -> list[dict]:
    """Roda ``discover_accounts`` contra um GoogleAdsService dublado."""
    client = mock.Mock()
    client.get_service.return_value.search.return_value = linhas
    return google_ads.discover_accounts(client)


class TestContratoDoEnumDoSdk(unittest.TestCase):
    """Os estados classificados vem do SDK instalado, nao de numero magico.

    Se uma versao nova da biblioteca acrescentar ou remover status, e aqui que
    isso aparece — antes de a descoberta abortar em producao.
    """

    def test_enum_tem_exatamente_os_seis_estados_conhecidos(self) -> None:
        self.assertEqual(
            {nome: int(valor) for nome, valor in CustomerStatus.__members__.items()},
            {
                "UNSPECIFIED": 0,
                "UNKNOWN": 1,
                "ENABLED": 2,
                "CANCELED": 3,
                "SUSPENDED": 4,
                "CLOSED": 5,
            },
        )

    def test_todo_estado_conhecido_esta_classificado_ou_aborta(self) -> None:
        """Nenhum membro do enum pode ficar sem decisao explicita."""
        aborta = {CustomerStatus.UNSPECIFIED, CustomerStatus.UNKNOWN}

        self.assertEqual(
            set(CustomerStatus.__members__.values()),
            set(google_ads.CUSTOMER_STATUSES_CONSULTAVEIS) | aborta,
        )


class TestEstadosConsultaveis(unittest.TestCase):
    """Estado corrente da conta nao apaga participacao historica."""

    def test_conta_ativa_e_incluida(self) -> None:
        contas = [conta("A", CustomerStatus.ENABLED)]

        self.assertEqual(
            google_ads._selecionar_contas_consultaveis(contas), contas
        )

    def test_estados_sem_entrega_mas_com_historico_sao_incluidos(self) -> None:
        """CANCELED, SUSPENDED e CLOSED nao servem anuncios hoje — e nao
        precisam: a consulta e sobre dias em que a conta podia servir."""
        statuses = (
            CustomerStatus.CANCELED,
            CustomerStatus.SUSPENDED,
            CustomerStatus.CLOSED,
        )
        contas = [
            conta(str(indice), status) for indice, status in enumerate(statuses)
        ]

        self.assertEqual(
            google_ads._selecionar_contas_consultaveis(contas), contas
        )

    def test_ordem_e_conteudo_preservados(self) -> None:
        contas = [
            conta("A", CustomerStatus.CLOSED),
            conta("B", CustomerStatus.ENABLED),
            conta("C", CustomerStatus.SUSPENDED),
        ]

        self.assertEqual(
            google_ads._selecionar_contas_consultaveis(contas), contas
        )


class TestFalhaFechada(unittest.TestCase):
    """Estado nao classificado aborta em vez de gerar lote parcial."""

    def test_status_fora_do_enum_falha_fechado(self) -> None:
        with self.assertRaises(ValueError):
            google_ads._selecionar_contas_consultaveis([conta("A", 99)])

    def test_unspecified_e_unknown_abortam(self) -> None:
        """Sao membros do enum, mas descrevem contrato ausente ou mais novo do
        que a versao da biblioteca — nao estado de conta."""
        for status in (CustomerStatus.UNSPECIFIED, CustomerStatus.UNKNOWN):
            with self.subTest(status=CustomerStatus(status).name):
                with self.assertRaises(ValueError):
                    google_ads._selecionar_contas_consultaveis(
                        [
                            conta("A", CustomerStatus.ENABLED),
                            conta("B", status),
                        ]
                    )

    def test_uma_conta_desconhecida_derruba_a_descoberta_inteira(self) -> None:
        """Nao existe caminho que devolva 'as outras contas' e siga em frente."""
        contas = [
            conta("A", CustomerStatus.ENABLED),
            conta("B", CustomerStatus.CANCELED),
            conta("Z", 99),
        ]

        with self.assertRaises(ValueError):
            google_ads._selecionar_contas_consultaveis(contas)

    def test_erro_nao_vaza_identificador_de_cliente(self) -> None:
        with self.assertRaises(ValueError) as erro:
            google_ads._selecionar_contas_consultaveis([conta("Z", 99)])

        self.assertNotIn("EXTERNAL_ID_Z", str(erro.exception))
        self.assertNotIn("EMPRESA_Z", str(erro.exception))


class TestAusenciaDeFallbackParaEnabled(unittest.TestCase):
    """Nenhum caminho reintroduz 'somente ENABLED', nem na GAQL nem em Python."""

    def test_gaql_nao_filtra_por_estado_corrente(self) -> None:
        self.assertNotIn("customer_client.status", google_ads.GAQL_DISCOVERY.split("WHERE")[1])
        self.assertIn("customer_client.status", google_ads.GAQL_DISCOVERY)

    def test_gaql_mantem_o_filtro_estrutural_de_conta_gestora(self) -> None:
        """`manager` nao e estado de entrega: conta gestora nao tem anuncio."""
        self.assertIn("customer_client.manager = FALSE", google_ads.GAQL_DISCOVERY)

    def test_classificacao_nao_e_apenas_enabled(self) -> None:
        self.assertNotEqual(
            set(google_ads.CUSTOMER_STATUSES_CONSULTAVEIS),
            {CustomerStatus.ENABLED},
        )

    def test_descoberta_sem_nenhuma_conta_enabled_nao_volta_vazia(self) -> None:
        contas = [
            conta("A", CustomerStatus.CANCELED),
            conta("B", CustomerStatus.SUSPENDED),
            conta("C", CustomerStatus.CLOSED),
        ]

        self.assertEqual(
            google_ads._selecionar_contas_consultaveis(contas), contas
        )


class TestDescobertaContraOSdk(unittest.TestCase):
    """A ponta que fala com o SDK entrega o contrato que a casca espera."""

    def test_discover_accounts_devolve_id_texto_nome_e_status(self) -> None:
        linhas = [
            linha("A", CustomerStatus.ENABLED),
            linha("B", CustomerStatus.CANCELED),
        ]

        resultado = descobrir(linhas)

        self.assertEqual(len(resultado), 2)
        for item, esperado in zip(resultado, linhas):
            self.assertEqual(set(item), {"id", "name", "status"})
            self.assertIsInstance(item["id"], str)
            self.assertEqual(item["id"], str(esperado.customer_client.id))
            self.assertEqual(item["name"], esperado.customer_client.descriptive_name)
        self.assertEqual(
            [item["status"] for item in resultado],
            [CustomerStatus.ENABLED, CustomerStatus.CANCELED],
        )

    def test_discover_accounts_usa_a_gaql_de_descoberta(self) -> None:
        client = mock.Mock()
        client.get_service.return_value.search.return_value = []

        with mock.patch.dict(
            google_ads.os.environ, {"GOOGLE_LOGIN_CUSTOMER_ID": "EXTERNAL_ID_MCC"}
        ):
            google_ads.discover_accounts(client)

        client.get_service.assert_called_once_with("GoogleAdsService")
        client.get_service.return_value.search.assert_called_once_with(
            customer_id="EXTERNAL_ID_MCC", query=google_ads.GAQL_DISCOVERY
        )

    def test_discover_accounts_propaga_a_falha_fechada(self) -> None:
        with self.assertRaises(ValueError):
            descobrir([linha("A", CustomerStatus.ENABLED), linha("Z", 99)])

    def test_log_resume_por_status_sem_identificador(self) -> None:
        linhas = [
            linha("A", CustomerStatus.ENABLED),
            linha("B", CustomerStatus.CLOSED),
        ]

        with self.assertLogs(google_ads.logger, level="INFO") as registro:
            resultado = descobrir(linhas)

        texto = "\n".join(registro.output)
        self.assertEqual(len(resultado), 2)
        self.assertIn("CLOSED", texto)
        self.assertNotIn("EMPRESA_A", texto)
        self.assertNotIn("EMPRESA_B", texto)


class TestToleranciaDeContaDesativada(unittest.TestCase):
    """A descoberta corrigida oferece conta desativada; a extracao precisa
    sobreviver a recusa dela sem engolir erro nenhum.

    Medido em 26/08/2026 sobre as 51 subcontas nao-ENABLED do MCC: 47 de 48
    `CANCELED` e as 3 `CLOSED` recusaram com `CUSTOMER_NOT_ENABLED`. Sem esta
    borda, uma unica conta nesse estado abortaria toda extracao Google.
    """

    def test_canceled_recusada_e_excluida_de_forma_auditavel(self) -> None:
        linhas, excluidas = extrair_com_recusa(
            CustomerStatus.CANCELED,
            falha(authorization_error=CUSTOMER_NOT_ENABLED),
        )

        self.assertEqual(linhas, [])
        self.assertEqual(excluidas, Counter({CustomerStatus.CANCELED: 1}))

    def test_closed_recusada_e_excluida_de_forma_auditavel(self) -> None:
        linhas, excluidas = extrair_com_recusa(
            CustomerStatus.CLOSED,
            falha(authorization_error=CUSTOMER_NOT_ENABLED),
        )

        self.assertEqual(linhas, [])
        self.assertEqual(excluidas, Counter({CustomerStatus.CLOSED: 1}))

    def test_ausencia_nao_vira_linha_zerada(self) -> None:
        """A conta excluida contribui com NADA — nao com metrica zero. E o que
        deixa a Silver preservar a ultima observacao conhecida em vez de
        sobrescreve-la com zero."""
        linhas, _ = extrair_com_recusa(
            CustomerStatus.CANCELED,
            falha(authorization_error=CUSTOMER_NOT_ENABLED),
        )

        self.assertEqual(linhas, [])
        self.assertNotIn({}, linhas)

    def test_enabled_recusada_aborta(self) -> None:
        """Recusa em conta habilitada e anomalia, nao rotina."""
        with self.assertRaises(GoogleAdsException):
            extrair_com_recusa(
                CustomerStatus.ENABLED,
                falha(authorization_error=CUSTOMER_NOT_ENABLED),
            )

    def test_suspended_recusada_aborta_por_falta_de_evidencia(self) -> None:
        """Nenhuma subconta SUSPENDED apareceu na medicao desta sessao. Sem
        evidencia sobre o comportamento do servidor, fail closed."""
        self.assertNotIn(
            CustomerStatus.SUSPENDED,
            google_ads.CUSTOMER_STATUSES_DESATIVACAO_ESPERADA,
        )

        with self.assertRaises(GoogleAdsException):
            extrair_com_recusa(
                CustomerStatus.SUSPENDED,
                falha(authorization_error=CUSTOMER_NOT_ENABLED),
            )

    def test_outro_erro_de_autorizacao_aborta(self) -> None:
        outro = int(google_ads._AUTORIZACAO.USER_PERMISSION_DENIED)

        with self.assertRaises(GoogleAdsException):
            extrair_com_recusa(CustomerStatus.CANCELED, falha(authorization_error=outro))

    def test_erro_de_outra_familia_aborta(self) -> None:
        """Quota, rede e consulta nao sao desativacao de conta."""
        with self.assertRaises(GoogleAdsException):
            extrair_com_recusa(
                CustomerStatus.CANCELED,
                falha(quota_error=int(_QUOTA.RESOURCE_EXHAUSTED)),
            )

    def test_falha_mista_aborta(self) -> None:
        """Basta um erro fora do codigo tolerado para a falha voltar a subir."""
        mista = GoogleAdsException(
            None,
            None,
            _ERROS.GoogleAdsFailure(errors=[
                _ERROS.GoogleAdsError(
                    error_code=_ERROS.ErrorCode(
                        authorization_error=CUSTOMER_NOT_ENABLED
                    )
                ),
                _ERROS.GoogleAdsError(
                    error_code=_ERROS.ErrorCode(
                        quota_error=int(_QUOTA.RESOURCE_EXHAUSTED)
                    )
                ),
            ]),
            "req-teste",
        )

        with self.assertRaises(GoogleAdsException):
            extrair_com_recusa(CustomerStatus.CANCELED, mista)

    def test_excecao_que_nao_e_do_sdk_aborta(self) -> None:
        """A borda captura `GoogleAdsException`, nunca `Exception`."""
        with self.assertRaises(TimeoutError):
            extrair_com_recusa(CustomerStatus.CANCELED, TimeoutError("rede"))

    def test_conta_desativada_acessivel_continua_sendo_consultada(self) -> None:
        """Uma das 48 CANCELED respondeu normalmente na medicao. A tolerancia
        nao pode virar exclusao preventiva de conta desativada."""
        registros = [{"date": "2026-08-01", "account_id": "EXTERNAL_ID_A"}]
        excluidas: Counter = Counter()

        with mock.patch.object(
            google_ads, "extract_daily_ads", return_value=registros
        ) as extrair:
            linhas = google_ads._extrair_conta_tolerando_desativacao(
                mock.Mock(),
                {"EXTERNAL_ID_A": CustomerStatus.CANCELED},
                excluidas,
                "EXTERNAL_ID_A",
                "EMPRESA_A",
                "2026-08-01",
                "2026-08-04",
            )

        self.assertEqual(linhas, registros)
        self.assertEqual(excluidas, Counter())
        extrair.assert_called_once()


class TestRunLigaStatusEExtracao(unittest.TestCase):
    """O status descoberto tem de alcancar a extracao, e o resumo tem de sair
    no log sem identificador. Sao os dois elos que so uma execucao real
    exercitaria."""

    def _rodar(self, contas: list[dict], excecao: Exception) -> list[str]:
        def executar_falso(plataforma, descobrir_contas, extrair_conta, **resto):
            for item in descobrir_contas():
                extrair_conta(
                    item["id"], item["name"], "2026-08-01", "2026-08-04"
                )
            return 0

        with mock.patch.object(google_ads, "validate_env"), \
                mock.patch.object(google_ads, "init_client"), \
                mock.patch.object(
                    google_ads, "discover_accounts", return_value=contas
                ), \
                mock.patch.object(
                    google_ads, "extract_daily_ads", side_effect=excecao
                ), \
                mock.patch.object(
                    google_ads, "executar_extracao", executar_falso
                ):
            with self.assertLogs(google_ads.logger, level="WARNING") as registro:
                google_ads.run("2026-08-01", "2026-08-04", "run-1")
        return registro.output

    def test_resumo_agregado_sai_no_log_sem_identificador(self) -> None:
        contas = [
            conta("A", CustomerStatus.CANCELED),
            conta("B", CustomerStatus.CLOSED),
        ]

        texto = "\n".join(
            self._rodar(contas, falha(authorization_error=CUSTOMER_NOT_ENABLED))
        )

        self.assertIn("CANCELED: 1", texto)
        self.assertIn("CLOSED: 1", texto)
        self.assertNotIn("EXTERNAL_ID_A", texto)
        self.assertNotIn("EMPRESA_A", texto)
        self.assertNotIn("EXTERNAL_ID_B", texto)
        self.assertNotIn("EMPRESA_B", texto)

    def test_status_desconhecido_pela_extracao_nao_habilita_tolerancia(
        self,
    ) -> None:
        """Se o mapa nao souber o status da conta, a recusa nao e esperada."""
        excluidas: Counter = Counter()

        with mock.patch.object(
            google_ads,
            "extract_daily_ads",
            side_effect=falha(authorization_error=CUSTOMER_NOT_ENABLED),
        ):
            with self.assertRaises(GoogleAdsException):
                google_ads._extrair_conta_tolerando_desativacao(
                    mock.Mock(), {}, excluidas,
                    "EXTERNAL_ID_A", "EMPRESA_A", "2026-08-01", "2026-08-04",
                )


class TestNaoAlcancaOMeta(unittest.TestCase):
    """A correcao e do lado Google e nao empresta nem toma nada do Meta."""

    def test_extrator_google_nao_importa_o_sdk_nem_o_modulo_do_meta(self) -> None:
        """O Meta aparece no arquivo so como comentario de contraste; nenhum
        import atravessa a fronteira entre os dois contratos."""
        fonte = (RAIZ / "extractors" / "google_ads.py").read_text(encoding="utf-8")
        imports = [
            linha.strip()
            for linha in fonte.splitlines()
            if linha.startswith(("import ", "from "))
        ]

        for linha_import in imports:
            self.assertNotIn("facebook_business", linha_import)
            self.assertNotIn("meta_ads", linha_import)

    def test_google_nao_aceita_o_desvio_opt_in_do_meta(self) -> None:
        """O desvio do Meta existe porque a descoberta dele declara
        indisponibilidade. A do Google nao declara — e a opcao dirigida a
        plataforma errada tem de estourar, nao ser ignorada."""
        from plataformas import PLATAFORMAS

        parametros = inspect.signature(google_ads.run).parameters
        self.assertNotIn("permitir_contas_indisponiveis", parametros)

        with mock.patch.object(google_ads, "validate_env"), \
                mock.patch.object(google_ads, "init_client"), \
                mock.patch.object(google_ads, "executar_extracao", return_value=0):
            with self.assertRaises(TypeError):
                PLATAFORMAS["google"].extrair(
                    "2026-08-05", "2026-08-09", "run-1",
                    permitir_contas_indisponiveis=True,
                )

    def test_classificacao_do_meta_segue_com_os_proprios_estados(self) -> None:
        """Os dois contratos sao independentes: nenhum conjunto foi reusado."""
        from extractors import meta_ads

        self.assertTrue(meta_ads.ACCOUNT_STATUSES_CONSULTAVEIS)
        self.assertTrue(meta_ads.ACCOUNT_STATUSES_INDISPONIVEIS)
        self.assertIsNot(
            meta_ads.ACCOUNT_STATUSES_CONSULTAVEIS,
            google_ads.CUSTOMER_STATUSES_CONSULTAVEIS,
        )


if __name__ == "__main__":
    unittest.main()
