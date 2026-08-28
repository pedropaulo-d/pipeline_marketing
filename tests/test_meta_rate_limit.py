"""Testes da telemetria passiva de rate limit do Meta.

Tudo sintetico: nenhum header real, nenhum identificador real, nenhuma chamada
de rede. Os IDs falsos usados aqui existem para PROVAR que nao escapam.
"""

import json
import logging
import unittest

from extractors import meta_rate_limit as rl

# IDs falsos, deliberadamente reconheciveis. Se algum aparecer em retorno, log
# ou repr, o teste de privacidade falha.
ID_FALSO_A: str = "123456789"
ID_FALSO_B: str = "987654321"


class TestLeituraDeHeaders(unittest.TestCase):
    """Os parsers extraem o que e numerico e ignoram o resto."""

    def test_app_usage_valido(self):
        obs = rl.ler_headers({
            "x-app-usage": json.dumps(
                {"call_count": 40, "total_cputime": 12, "total_time": 7}
            )
        })
        self.assertEqual(obs.app_call_count_pct, 40.0)
        self.assertEqual(obs.app_total_cputime_pct, 12.0)
        self.assertEqual(obs.app_total_time_pct, 7.0)

    def test_app_usage_ausente(self):
        obs = rl.ler_headers({"content-type": "application/json"})
        self.assertIsNone(obs.app_call_count_pct)
        self.assertTrue(obs.vazia())

    def test_json_invalido_nao_levanta(self):
        obs = rl.ler_headers({"x-app-usage": "{isso nao e json"})
        self.assertTrue(obs.vazia())

    def test_campos_extras_desconhecidos_sao_ignorados(self):
        obs = rl.ler_headers({
            "x-app-usage": json.dumps({
                "call_count": 55,
                "campo_que_a_meta_inventou_amanha": 999,
                "outro_novo": {"aninhado": 1},
            })
        })
        self.assertEqual(obs.app_call_count_pct, 55.0)
        # O campo novo nao vira metrica: allowlist, nao copia.
        self.assertNotIn(999.0, [getattr(obs, c) for c in rl._CAMPOS])

    def test_campos_parcialmente_ausentes(self):
        obs = rl.ler_headers({"x-app-usage": json.dumps({"call_count": 3})})
        self.assertEqual(obs.app_call_count_pct, 3.0)
        self.assertIsNone(obs.app_total_cputime_pct)
        self.assertIsNone(obs.app_total_time_pct)

    def test_valores_nao_numericos_viram_ausencia(self):
        obs = rl.ler_headers({
            "x-app-usage": json.dumps({
                "call_count": "muito", "total_cputime": None,
                "total_time": {"nao": "numero"},
            })
        })
        self.assertTrue(obs.vazia())

    def test_booleano_nao_vira_percentual(self):
        # `True` passa em isinstance(x, int) e viraria 1.0 silenciosamente.
        obs = rl.ler_headers({"x-app-usage": json.dumps({"call_count": True})})
        self.assertIsNone(obs.app_call_count_pct)

    def test_numero_em_string_e_aceito(self):
        obs = rl.ler_headers({"x-app-usage": json.dumps({"call_count": "62.5"})})
        self.assertEqual(obs.app_call_count_pct, 62.5)

    def test_ad_account_usage_valido(self):
        obs = rl.ler_headers({
            "x-ad-account-usage": json.dumps({"acc_id_util_pct": 18})
        })
        self.assertEqual(obs.conta_util_pct, 18.0)

    def test_insights_throttle(self):
        obs = rl.ler_headers({
            "x-fb-ads-insights-throttle": json.dumps({
                "app_id_util_pct": 71, "acc_id_util_pct": 9,
                "ads_api_access_tier": "standard_access",
            })
        })
        self.assertEqual(obs.insights_app_util_pct, 71.0)
        self.assertEqual(obs.insights_account_util_pct, 9.0)

    def test_retry_after(self):
        obs = rl.ler_headers({"retry-after": "1800"})
        self.assertEqual(obs.retry_after_segundos, 1800.0)

    def test_retry_after_como_data_http_nao_quebra(self):
        obs = rl.ler_headers({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
        self.assertIsNone(obs.retry_after_segundos)

    def test_capitalizacao_diferente(self):
        obs = rl.ler_headers({
            "X-App-Usage": json.dumps({"call_count": 42}),
            "Retry-After": "60",
        })
        self.assertEqual(obs.app_call_count_pct, 42.0)
        self.assertEqual(obs.retry_after_segundos, 60.0)

    def test_nenhum_header_relevante(self):
        obs = rl.ler_headers({"etag": "abc", "date": "hoje"})
        self.assertTrue(obs.vazia())

    def test_headers_none_nao_levanta(self):
        self.assertTrue(rl.ler_headers(None).vazia())

    def test_headers_de_tipo_inesperado_nao_levanta(self):
        for entrada in ("texto", 42, ["lista"]):
            with self.subTest(entrada=entrada):
                self.assertTrue(rl.ler_headers(entrada).vazia())


class TestBusinessUseCaseUsage(unittest.TestCase):
    """O header indexado por identificador: chaves entram, IDs nao saem."""

    def _header(self, *ids: str) -> dict:
        return {
            "x-business-use-case-usage": json.dumps({
                identificador: [{
                    "type": "ads_insights",
                    "call_count": 30 + indice * 20,
                    "total_cputime": 10 + indice,
                    "total_time": 5 + indice,
                }]
                for indice, identificador in enumerate(ids)
            })
        }

    def test_uma_chave_identificadora(self):
        obs = rl.ler_headers(self._header(ID_FALSO_A))
        self.assertEqual(obs.caso_de_uso_call_count_pct, 30.0)
        self.assertEqual(obs.caso_de_uso_cputime_pct, 10.0)

    def test_varias_chaves_consolidam_pelo_pior_caso(self):
        obs = rl.ler_headers(self._header(ID_FALSO_A, ID_FALSO_B))
        self.assertEqual(obs.caso_de_uso_call_count_pct, 50.0)
        self.assertEqual(obs.caso_de_uso_cputime_pct, 11.0)

    def test_estimated_time_to_regain_access(self):
        obs = rl.ler_headers({
            "x-business-use-case-usage": json.dumps({
                ID_FALSO_A: [{"call_count": 100,
                              "estimated_time_to_regain_access": 27}],
            })
        })
        self.assertEqual(obs.minutos_para_liberar, 27.0)

    def test_maior_estimated_time_entre_varias_entradas(self):
        obs = rl.ler_headers({
            "x-business-use-case-usage": json.dumps({
                ID_FALSO_A: [{"estimated_time_to_regain_access": 12}],
                ID_FALSO_B: [{"estimated_time_to_regain_access": 44}],
            })
        })
        self.assertEqual(obs.minutos_para_liberar, 44.0)

    def test_entrada_fora_de_lista_tambem_e_lida(self):
        obs = rl.ler_headers({
            "x-business-use-case-usage": json.dumps({
                ID_FALSO_A: {"call_count": 8},
            })
        })
        self.assertEqual(obs.caso_de_uso_call_count_pct, 8.0)

    def test_estrutura_inesperada_nao_levanta(self):
        for bruto in ("[]", "null", '{"a": "texto"}', '{"a": [null, 3]}'):
            with self.subTest(bruto=bruto):
                rl.ler_headers({"x-business-use-case-usage": bruto})


class TestPrivacidade(unittest.TestCase):
    """Obrigatorio: nenhum identificador do header bruto pode escapar."""

    def _headers_com_ids(self) -> dict:
        return {
            "x-business-use-case-usage": json.dumps({
                ID_FALSO_A: [{"type": "ads_insights", "call_count": 91,
                              "total_cputime": 40, "total_time": 33,
                              "estimated_time_to_regain_access": 18}],
                ID_FALSO_B: [{"type": "ads_management", "call_count": 12}],
            }),
            "x-ad-account-usage": json.dumps({
                "acc_id_util_pct": 55, "account_id": ID_FALSO_A,
            }),
            "x-fb-ads-insights-throttle": json.dumps({
                "app_id_util_pct": 88, "acc_id_util_pct": 4,
                "app_id": ID_FALSO_B,
            }),
        }

    def test_observacao_nao_contem_id(self):
        obs = rl.ler_headers(self._headers_com_ids())
        for identificador in (ID_FALSO_A, ID_FALSO_B):
            with self.subTest(id=identificador):
                self.assertNotIn(identificador, repr(obs))

    def test_resumo_nao_contem_id(self):
        coletor = rl.Coletor()
        coletor.observar_headers(self._headers_com_ids())
        resumo = coletor.resumo()
        self.assertIsNotNone(resumo)
        for identificador in (ID_FALSO_A, ID_FALSO_B):
            with self.subTest(id=identificador):
                self.assertNotIn(identificador, resumo)

    def test_repr_do_coletor_nao_contem_id(self):
        coletor = rl.Coletor()
        coletor.observar_headers(self._headers_com_ids())
        for identificador in (ID_FALSO_A, ID_FALSO_B):
            with self.subTest(id=identificador):
                self.assertNotIn(identificador, repr(coletor))

    def test_log_nao_contem_id(self):
        coletor = rl.Coletor()
        logger = logging.getLogger(rl.__name__)
        with self.assertLogs(logger, level="DEBUG") as capturado:
            coletor.observar_headers(self._headers_com_ids())
            coletor.registrar_resumo()
        texto = "\n".join(capturado.output)
        for identificador in (ID_FALSO_A, ID_FALSO_B):
            with self.subTest(id=identificador):
                self.assertNotIn(identificador, texto)
        # E o que interessa continua la.
        self.assertIn("91", texto)

    def test_header_bruto_nunca_e_guardado(self):
        coletor = rl.Coletor()
        headers = self._headers_com_ids()
        coletor.observar_headers(headers)
        # A assinatura de deduplicacao guarda os valores brutos e por isso NAO
        # entra no repr — `field(repr=False)`. Confirmado acima; aqui garante
        # que nenhuma metrica textual veio junto.
        for valor in coletor.maximos.values():
            self.assertIsInstance(valor, float)


class TestAgregacao(unittest.TestCase):
    """O coletor guarda maximo, ultima leitura e contagem."""

    def _obs(self, call_count: int) -> dict:
        return {"x-app-usage": json.dumps({"call_count": call_count})}

    def test_maximo_entre_observacoes(self):
        coletor = rl.Coletor()
        for valor in (40, 75, 62):
            coletor.observar_headers(self._obs(valor))
        self.assertEqual(coletor.observacoes, 3)
        self.assertEqual(coletor.maximos["app_call_count_pct"], 75.0)

    def test_ultima_leitura_e_a_mais_recente(self):
        coletor = rl.Coletor()
        for valor in (40, 75, 62):
            coletor.observar_headers(self._obs(valor))
        self.assertEqual(coletor.ultima.app_call_count_pct, 62.0)

    def test_maior_estimated_regain_da_execucao(self):
        coletor = rl.Coletor()
        for minutos in (5, 31, 12):
            coletor.observar_headers({
                "x-business-use-case-usage": json.dumps({
                    ID_FALSO_A: [{"estimated_time_to_regain_access": minutos}],
                })
            })
        self.assertEqual(coletor.maximos["minutos_para_liberar"], 31.0)

    def test_leituras_identicas_consecutivas_nao_recontam(self):
        coletor = rl.Coletor()
        for _ in range(10):
            coletor.observar_headers(self._obs(40))
        self.assertEqual(coletor.observacoes, 1)

    def test_headers_vazios_nao_contam_como_observacao(self):
        coletor = rl.Coletor()
        coletor.observar_headers({"etag": "abc"})
        self.assertEqual(coletor.observacoes, 0)
        self.assertIsNone(coletor.resumo())

    def test_resumo_omite_metrica_ausente(self):
        coletor = rl.Coletor()
        coletor.observar_headers(self._obs(40))
        resumo = coletor.resumo()
        self.assertIn("app_chamadas_pct=40", resumo)
        self.assertNotIn("None", resumo)
        self.assertNotIn("app_cpu_pct", resumo)

    def test_resumo_sem_observacao_e_none(self):
        self.assertIsNone(rl.Coletor().resumo())

    def test_alerta_so_quando_a_fonte_declara_espera(self):
        logger = logging.getLogger(rl.__name__)

        tranquilo = rl.Coletor()
        tranquilo.observar_headers(self._obs(40))
        with self.assertLogs(logger, level="INFO") as capturado:
            tranquilo.registrar_resumo()
        self.assertEqual(capturado.records[0].levelno, logging.INFO)

        apertado = rl.Coletor()
        apertado.observar_headers({"retry-after": "600"})
        with self.assertLogs(logger, level="INFO") as capturado:
            apertado.registrar_resumo()
        self.assertEqual(capturado.records[0].levelno, logging.WARNING)


class CursorFalso:
    """Cursor sintetico que conta quantos requests HTTP teria feito."""

    def __init__(self, paginas: list[list[dict]], headers: list[dict]):
        self._paginas = list(paginas)
        self._headers_por_pagina = list(headers)
        self._headers: dict = {}
        self._fila: list[dict] = []
        self.requests = 0
        self._carregar()

    def _carregar(self) -> bool:
        if not self._paginas:
            return False
        self.requests += 1
        self._fila = list(self._paginas.pop(0))
        self._headers = self._headers_por_pagina.pop(0)
        return True

    def headers(self) -> dict:
        return self._headers

    def __iter__(self):
        return self

    def __next__(self) -> dict:
        if not self._fila and not self._carregar():
            raise StopIteration
        return self._fila.pop(0)


class TestObservacaoDoCursor(unittest.TestCase):
    """A telemetria e passiva: le o que ja chegou, nao provoca chamada."""

    def _cursor(self) -> CursorFalso:
        return CursorFalso(
            paginas=[[{"ad_id": "A"}, {"ad_id": "B"}], [{"ad_id": "C"}]],
            headers=[
                {"x-app-usage": json.dumps({"call_count": 30})},
                {"x-app-usage": json.dumps({"call_count": 70})},
            ],
        )

    def test_nao_adiciona_request(self):
        sem = self._cursor()
        list(sem)
        com = self._cursor()
        list(rl.observar_cursor(com, rl.Coletor()))
        self.assertEqual(com.requests, sem.requests)
        self.assertEqual(com.requests, 2)

    def test_itens_sao_devolvidos_sem_alteracao(self):
        sem = list(self._cursor())
        com = list(rl.observar_cursor(self._cursor(), rl.Coletor()))
        self.assertEqual(com, sem)

    def test_observa_cada_pagina(self):
        coletor = rl.Coletor()
        list(rl.observar_cursor(self._cursor(), coletor))
        self.assertEqual(coletor.observacoes, 2)
        self.assertEqual(coletor.maximos["app_call_count_pct"], 70.0)

    def test_cursor_sem_acessor_de_headers_continua_funcionando(self):
        itens = [{"ad_id": "A"}, {"ad_id": "B"}]
        coletor = rl.Coletor()
        self.assertEqual(list(rl.observar_cursor(iter(itens), coletor)), itens)
        self.assertEqual(coletor.observacoes, 0)

    def test_acessor_que_levanta_nao_quebra_a_extracao(self):
        class Explosivo(CursorFalso):
            def headers(self):
                raise RuntimeError("defeito do SDK")

        cursor = Explosivo(
            paginas=[[{"ad_id": "A"}]], headers=[{}],
        )
        self.assertEqual(
            list(rl.observar_cursor(cursor, rl.Coletor())), [{"ad_id": "A"}]
        )


class ErroFalso(Exception):
    """Espelha `FacebookRequestError`: preserva os headers do 403."""

    def __init__(self, headers: dict):
        super().__init__("Call was not successful")
        self._headers = headers

    def http_headers(self) -> dict:
        return self._headers


class TestTelemetriaNoErro(unittest.TestCase):
    """O 403 de limite e a leitura mais informativa que existe."""

    def test_captura_headers_do_erro(self):
        coletor = rl.Coletor()
        rl.observar_excecao(
            ErroFalso({
                "x-app-usage": json.dumps({"call_count": 100}),
                "x-business-use-case-usage": json.dumps({
                    ID_FALSO_A: [{"estimated_time_to_regain_access": 42}],
                }),
            }),
            coletor,
        )
        self.assertEqual(coletor.maximos["app_call_count_pct"], 100.0)
        self.assertEqual(coletor.maximos["minutos_para_liberar"], 42.0)
        self.assertNotIn(ID_FALSO_A, coletor.resumo())

    def test_excecao_sem_headers_nao_levanta(self):
        coletor = rl.Coletor()
        rl.observar_excecao(ValueError("erro qualquer"), coletor)
        self.assertEqual(coletor.observacoes, 0)

    def test_acessor_defeituoso_nao_levanta(self):
        class Quebrado(Exception):
            def http_headers(self):
                raise RuntimeError("defeito")

        rl.observar_excecao(Quebrado(), rl.Coletor())


class TestSemControleAutomatico(unittest.TestCase):
    """Observabilidade sim; pacing automatico nao — ainda nao ha evidencia."""

    def test_modulo_nao_dorme_nem_repete(self):
        fonte = (
            __import__("pathlib").Path(rl.__file__).read_text(encoding="utf-8")
        )
        codigo = "\n".join(
            linha for linha in fonte.splitlines()
            if not linha.strip().startswith(("#", "-", "*"))
        )
        for proibido in ("time.sleep", "sleep(", "backoff", "retry("):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, codigo)

    def test_modulo_nao_importa_cliente_http(self):
        fonte = (
            __import__("pathlib").Path(rl.__file__).read_text(encoding="utf-8")
        )
        for proibido in ("import requests", "import urllib", "facebook_business"):
            with self.subTest(proibido=proibido):
                self.assertNotIn(proibido, fonte)


class TestContratoDoSdk(unittest.TestCase):
    """Os acessores usados sao publicos. Se o SDK mudar, isto avisa.

    Pulado onde `facebook_business` nao esta instalado — a imagem do dashboard,
    por exemplo, que de proposito nao carrega SDK de API.
    """

    def setUp(self):
        try:
            from facebook_business.api import Cursor, FacebookResponse
            from facebook_business.exceptions import FacebookRequestError
        except Exception:  # noqa: BLE001 - ausencia legitima do SDK
            self.skipTest("facebook_business nao instalado neste ambiente")
        self.Cursor = Cursor
        self.FacebookResponse = FacebookResponse
        self.FacebookRequestError = FacebookRequestError

    def test_cursor_expoe_headers(self):
        self.assertTrue(callable(getattr(self.Cursor, "headers", None)))

    def test_response_expoe_headers(self):
        self.assertTrue(
            callable(getattr(self.FacebookResponse, "headers", None))
        )

    def test_erro_preserva_headers_da_resposta(self):
        self.assertTrue(
            callable(getattr(self.FacebookRequestError, "http_headers", None))
        )


if __name__ == "__main__":
    unittest.main()
