"""Testes da redacao de segredos em log.

Motivacao concreta (auditoria de 17/08/2026): o SDK do Meta manda o
``access_token`` na query string. Uma falha de REDE — nao de API — faz o
``requests`` colocar a URL inteira na mensagem da excecao, e o extrator roda
como processo proprio na DAG, entao esse traceback iria cru para o log da task
do Airflow.

Nenhum token real aparece aqui: os valores sao sinteticos, com o mesmo formato
dos verdadeiros.

Rodar:
    python -m unittest discover -s tests -t .
"""

import io
import logging
import unittest
from unittest import mock

import config
from config import REDIGIDO, FormatadorSeguro, redigir

# Sinteticos, com o formato dos reais. Montados por concatenacao para nao
# parecerem credencial de verdade num grep.
TOKEN_META = "EAA" + "F4k3T0k3nSint3tico" * 3
SECRET_GOOGLE = "GOCSPX-" + "sint3tico_nao_real_1234"
REFRESH_GOOGLE = "1//0" + "refresh_sintetico_nao_real_00000"

URL_DE_FALHA = (
    "HTTPSConnectionPool(host='graph.facebook.com', port=443): Max retries "
    f"exceeded with url: /v26.0/act_123/insights?access_token={TOKEN_META}"
    "&fields=spend%2Cimpressions&limit=100 (Caused by "
    "NewConnectionError('Failed to establish a new connection'))"
)


class TestRedigir(unittest.TestCase):

    def test_token_na_query_string_some(self):
        limpo = redigir(URL_DE_FALHA)

        self.assertNotIn(TOKEN_META, limpo)
        self.assertIn(REDIGIDO, limpo)

    def test_diagnostico_util_permanece(self):
        limpo = redigir(URL_DE_FALHA)

        self.assertIn("graph.facebook.com", limpo)
        self.assertIn("Max retries exceeded", limpo)
        self.assertIn("access_token=", limpo)
        self.assertIn("insights", limpo)

    def test_formatos_soltos_do_google(self):
        texto = f"client_secret={SECRET_GOOGLE} refresh_token={REFRESH_GOOGLE}"

        limpo = redigir(texto)

        self.assertNotIn(SECRET_GOOGLE, limpo)
        self.assertNotIn(REFRESH_GOOGLE, limpo)

    def test_valor_de_ambiente_sem_formato_reconhecivel(self):
        # Segredo que nao casa com nenhum padrao: so a leitura do ambiente
        # pega. Cobre credencial rotacionada para um formato novo.
        segredo = "valor-de-credencial-sem-formato-conhecido-123"
        with mock.patch.dict(
            "os.environ", {"GOOGLE_CLIENT_SECRET": segredo}, clear=False
        ):
            limpo = redigir(f"falha ao autenticar com {segredo} no endpoint X")

        self.assertNotIn(segredo, limpo)
        self.assertIn("falha ao autenticar", limpo)

    def test_senha_do_banco_na_url_de_conexao(self):
        with mock.patch.dict(
            "os.environ",
            {"DW_DB_URL": "postgresql://etl:senha_super_secreta@db:5432/dw"},
            clear=False,
        ):
            limpo = redigir(
                "could not connect: postgresql://etl:senha_super_secreta@db:5432/dw"
            )

        self.assertNotIn("senha_super_secreta", limpo)
        self.assertIn("db:5432", limpo)

    def test_texto_sem_segredo_fica_intacto(self):
        texto = "Extracao Meta Ads concluida. Total: 527 registros"

        self.assertEqual(redigir(texto), texto)

    def test_texto_vazio_nao_quebra(self):
        self.assertEqual(redigir(""), "")


class TestFormatadorSeguro(unittest.TestCase):
    """O traceback so existe depois de formatado — por isso a redacao mora aqui."""

    def _logger_capturado(self) -> tuple[logging.Logger, io.StringIO]:
        fluxo = io.StringIO()
        handler = logging.StreamHandler(fluxo)
        handler.setFormatter(FormatadorSeguro(config.LOG_FORMAT))
        logger = logging.getLogger(f"teste_{id(fluxo)}")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        return logger, fluxo

    def test_mensagem_com_token_e_redigida(self):
        logger, fluxo = self._logger_capturado()

        logger.error("falhou: %s", URL_DE_FALHA)

        self.assertNotIn(TOKEN_META, fluxo.getvalue())
        self.assertIn(REDIGIDO, fluxo.getvalue())

    def test_traceback_de_excecao_e_redigido(self):
        logger, fluxo = self._logger_capturado()

        try:
            raise ConnectionError(URL_DE_FALHA)
        except ConnectionError as exc:
            logger.exception("FALHA na extracao Meta Ads (%s).", type(exc).__name__)

        saida = fluxo.getvalue()

        self.assertNotIn(TOKEN_META, saida)
        self.assertIn(REDIGIDO, saida)
        # A excecao continua diagnosticavel.
        self.assertIn("ConnectionError", saida)
        self.assertIn("Traceback", saida)
        self.assertIn("graph.facebook.com", saida)

    def test_configurar_logging_instala_o_formatador(self):
        raiz = logging.getLogger()
        handlers_originais = list(raiz.handlers)
        self.addCleanup(setattr, raiz, "handlers", handlers_originais)

        raiz.handlers = [logging.StreamHandler(io.StringIO())]
        config.configurar_logging()

        self.assertTrue(
            all(
                isinstance(h.formatter, FormatadorSeguro)
                for h in logging.getLogger().handlers
            )
        )


if __name__ == "__main__":
    unittest.main()
