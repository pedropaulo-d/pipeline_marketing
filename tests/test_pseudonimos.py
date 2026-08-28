"""Testes do primitivo de pseudonimizacao da fronteira de exposicao.

O contrato sob teste: o mesmo par (chave, entidade) produz sempre o mesmo
rotulo; entidades e niveis diferentes produzem rotulos diferentes; e sem chave
valida nao ha rotulo nenhum — nao existe fallback.

A regressao que motiva a suite: a versao anterior desta camada usava um salt
fixo versionado no codigo, o que tornava o pseudonimo reversivel por
dicionario. Aqui a chave vem do ambiente e nunca aparece em mensagem de erro.

Rodar:
    python -m unittest discover -s tests -t .
"""

import logging
import os
import unittest
from unittest import mock

import pseudonimos

CHAVE = "chave-de-teste-com-tamanho-suficiente-para-passar-1234567890"
OUTRA_CHAVE = "outra-chave-de-teste-igualmente-longa-0987654321-abcdef"

NK_EXEMPLO = "0123456789abcdef0123456789abcdef"
OUTRO_NK = "fedcba9876543210fedcba9876543210"


def com_chave(valor: str = CHAVE):
    """Contexto que instala uma chave de pseudonimizacao no ambiente.

    Args:
        valor: Valor da chave.

    Returns:
        Gerenciador de contexto do `mock.patch.dict`.
    """
    return mock.patch.dict(
        os.environ, {pseudonimos.VARIAVEL: valor}, clear=False
    )


def sem_chave():
    """Contexto que remove a chave do ambiente.

    Returns:
        Gerenciador de contexto do `mock.patch.dict`.
    """
    ambiente = {k: v for k, v in os.environ.items() if k != pseudonimos.VARIAVEL}
    return mock.patch.dict(os.environ, ambiente, clear=True)


class TestDeterminismo(unittest.TestCase):
    """Mesma entrada, mesmo rotulo — sem mapa persistente."""

    def test_mesma_chave_e_mesma_entrada_produzem_o_mesmo_id(self):
        with com_chave():
            primeiro = pseudonimos.gerar_id_publico("conta", NK_EXEMPLO)
            segundo = pseudonimos.gerar_id_publico("conta", NK_EXEMPLO)

        self.assertEqual(primeiro, segundo)

    def test_entradas_diferentes_produzem_ids_diferentes(self):
        with com_chave():
            self.assertNotEqual(
                pseudonimos.gerar_id_publico("conta", NK_EXEMPLO),
                pseudonimos.gerar_id_publico("conta", OUTRO_NK),
            )

    def test_niveis_diferentes_sao_dominios_separados(self):
        # A mesma chave natural em niveis diferentes nao pode colidir: o nivel
        # entra no material assinado.
        with com_chave():
            rotulos = {
                nivel: pseudonimos.gerar_id_publico(nivel, NK_EXEMPLO)
                for nivel in pseudonimos.NIVEIS
            }

        sufixos = {r.split("-", 1)[1] for r in rotulos.values()}
        self.assertEqual(len(sufixos), len(pseudonimos.NIVEIS))

    def test_chave_diferente_troca_todos_os_pseudonimos(self):
        with com_chave():
            com_uma = pseudonimos.gerar_id_publico("campanha", NK_EXEMPLO)
        with com_chave(OUTRA_CHAVE):
            com_outra = pseudonimos.gerar_id_publico("campanha", NK_EXEMPLO)

        self.assertNotEqual(com_uma, com_outra)


class TestFormato(unittest.TestCase):
    """O rotulo e o nome publico da entidade: precisa ser previsivel."""

    def test_formato_prefixo_e_oito_hex(self):
        padroes = {
            "conta": r"^Cliente-[0-9A-F]{8}$",
            "campanha": r"^Campanha-[0-9A-F]{8}$",
            "adset": r"^AdSet-[0-9A-F]{8}$",
            "anuncio": r"^Anuncio-[0-9A-F]{8}$",
        }
        with com_chave():
            for nivel, padrao in padroes.items():
                with self.subTest(nivel=nivel):
                    rotulo = pseudonimos.gerar_id_publico(nivel, NK_EXEMPLO)
                    self.assertRegex(rotulo, padrao)

    def test_nivel_desconhecido_e_recusado(self):
        with com_chave(), self.assertRaises(ValueError):
            pseudonimos.gerar_id_publico("anunciante", NK_EXEMPLO)

    def test_chave_natural_vazia_e_recusada(self):
        with com_chave(), self.assertRaises(ValueError):
            pseudonimos.gerar_id_publico("conta", "")

    def test_fingerprint_tem_tamanho_declarado_e_nao_e_a_chave(self):
        with com_chave():
            impressao = pseudonimos.fingerprint_chave()

        self.assertEqual(len(impressao), pseudonimos.TAMANHO_FINGERPRINT)
        self.assertRegex(impressao, r"^[0-9A-F]+$")
        self.assertNotIn(CHAVE, impressao)

    def test_fingerprint_muda_quando_a_chave_muda(self):
        with com_chave():
            primeira = pseudonimos.fingerprint_chave()
        with com_chave(OUTRA_CHAVE):
            segunda = pseudonimos.fingerprint_chave()

        self.assertNotEqual(primeira, segunda)


class TestChaveInvalida(unittest.TestCase):
    """Sem chave utilizavel nao ha pseudonimo. Nenhum fallback."""

    def test_ausencia_de_chave_falha(self):
        with sem_chave(), self.assertRaises(pseudonimos.ChaveInvalida):
            pseudonimos.gerar_id_publico("conta", NK_EXEMPLO)

    def test_chave_vazia_falha(self):
        with com_chave("   "), self.assertRaises(pseudonimos.ChaveInvalida):
            pseudonimos.gerar_id_publico("conta", NK_EXEMPLO)

    def test_placeholder_do_template_falha(self):
        with com_chave(pseudonimos.PLACEHOLDER):
            self.assertRaises(
                pseudonimos.ChaveInvalida, pseudonimos.fingerprint_chave
            )

    def test_chave_curta_falha(self):
        with com_chave("curta-demais"):
            self.assertRaises(
                pseudonimos.ChaveInvalida, pseudonimos.fingerprint_chave
            )

    def test_chave_disponivel_responde_sem_levantar(self):
        with com_chave():
            self.assertTrue(pseudonimos.chave_disponivel())
        with sem_chave():
            self.assertFalse(pseudonimos.chave_disponivel())


class TestSegredoNaoVaza(unittest.TestCase):
    """A chave nao pode aparecer em mensagem, log ou valor derivado visivel."""

    def test_mensagem_de_erro_nao_contem_a_chave(self):
        for valor in (pseudonimos.PLACEHOLDER, "curta"):
            with self.subTest(valor=valor):
                with com_chave(valor):
                    try:
                        pseudonimos.fingerprint_chave()
                    except pseudonimos.ChaveInvalida as erro:
                        self.assertNotIn(valor, str(erro))
                    else:
                        self.fail("deveria ter levantado ChaveInvalida")

    def test_chave_nao_aparece_no_log_ao_gerar(self):
        with com_chave(), self.assertLogs(level=logging.DEBUG) as capturado:
            logging.getLogger("teste").debug("gerando pseudonimos")
            pseudonimos.gerar_id_publico("conta", NK_EXEMPLO)
            pseudonimos.fingerprint_chave()

        self.assertNotIn(CHAVE, "\n".join(capturado.output))

    def test_rotulo_nao_contem_a_chave_nem_a_entrada(self):
        with com_chave():
            rotulo = pseudonimos.gerar_id_publico("anuncio", NK_EXEMPLO)

        self.assertNotIn(CHAVE, rotulo)
        self.assertNotIn(NK_EXEMPLO, rotulo)
        self.assertNotIn(NK_EXEMPLO[:8], rotulo)


class TestColisao(unittest.TestCase):
    """8 hex sao 32 bits: colisao precisa ser rara no volume do projeto."""

    def test_mil_entidades_sem_colisao(self):
        with com_chave():
            rotulos = {
                pseudonimos.gerar_id_publico("anuncio", f"nk-sintetico-{i}")
                for i in range(1000)
            }

        self.assertEqual(len(rotulos), 1000)

    def test_sufixo_usa_todo_o_espaco_hexadecimal(self):
        with com_chave():
            sufixos = [
                pseudonimos.gerar_id_publico("conta", f"nk-{i}").split("-")[1]
                for i in range(200)
            ]

        caracteres = set("".join(sufixos))
        self.assertTrue(caracteres <= set("0123456789ABCDEF"))
        self.assertGreater(len(caracteres), 10)


if __name__ == "__main__":
    unittest.main()
