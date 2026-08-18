"""Testes do anonimizador fail closed dos JSONs brutos."""

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pseudonimos
from scripts import anonimizar_dataset as anonimizador

CHAVE = "chave-sintetica-de-testes-com-entropia-suficiente-1234567890"


def registro_meta(**alteracoes):
    """Cria registro Meta inteiramente sintetico."""
    registro = {
        "account_id": "100000000001",
        "account_name": "Marca Sigilosa Ltda",
        "campaign_id": "200000000001",
        "campaign_name": "[Marca Sigilosa] Captacao Manaus 01/08/2026",
        "adset_id": "300000000001",
        "adset_name": "Dra. Pessoa - Amazonas",
        "ad_id": "400000000001",
        "ad_name": "Produto Confidencial",
        "spend": "123.450000",
        "impressions": "987",
        "inline_link_clicks": "65",
        "reach": "876",
        "actions": [{"action_type": "link_click", "value": "65.125000"}],
        "action_values": [
            {"action_type": "offsite_conversion.fb_pixel_custom", "value": "9.876543"}
        ],
        "date_start": "2026-08-10",
        "date_stop": "2026-08-10",
    }
    registro.update(alteracoes)
    return registro


def registro_google(**alteracoes):
    """Cria registro Google inteiramente sintetico."""
    registro = {
        "date": "2026-08-10",
        "account_id": "100000000001",
        "account_name": "Empresa Exemplo",
        "campaign_id": "500000000001",
        "campaign_name": "Campanha Produto Exemplo",
        "ad_group_id": "600000000001",
        "ad_group_name": "Grupo Localidade Exemplo",
        "ad_id": "700000000001",
        "ad_name": "",
        "impressions": 321,
        "clicks": 12,
        "cost": 45.678901,
        "conversions": 1.234567,
        "conversions_value": 98.765432,
        "video_trueview_views": 7,
    }
    registro.update(alteracoes)
    return registro


class BaseAnonimizacao(unittest.TestCase):
    """Infraestrutura comum com arquivos temporarios e chave sintetica."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.ambiente = mock.patch.dict(
            os.environ, {pseudonimos.VARIAVEL: CHAVE}, clear=False
        )
        self.ambiente.start()
        self.addCleanup(self.ambiente.stop)

    def gerar(self, registros, plataforma="meta", nome="saida.json"):
        entrada = self.raiz / f"entrada-{nome}"
        saida = self.raiz / nome
        entrada.write_text(
            json.dumps(registros, ensure_ascii=False), encoding="utf-8"
        )
        resultado = anonimizador.anonimizar_arquivo(
            entrada, saida, plataforma
        )
        dados = json.loads(saida.read_text(encoding="utf-8"))
        return entrada, saida, resultado, dados


class TestContrato(BaseAnonimizacao):
    """Campo novo nunca atravessa automaticamente."""

    def test_campo_top_level_desconhecido_meta_falha(self):
        registro = registro_meta(campo_novo="nao pode sair")
        with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
            self.gerar([registro])

    def test_campo_top_level_desconhecido_google_falha(self):
        registro = registro_google(campo_novo="nao pode sair")
        with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
            self.gerar([registro], "google")

    def test_campo_interno_desconhecido_em_actions_falha(self):
        item = {"action_type": "link_click", "value": "1", "novo": "x"}
        with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
            self.gerar([registro_meta(actions=[item])])

    def test_action_type_nao_aprovado_falha(self):
        item = {"action_type": "conversao_cliente_123", "value": "1"}
        with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
            self.gerar([registro_meta(actions=[item])])

    def test_campo_novo_nao_e_copiado_automaticamente(self):
        registro = registro_meta()
        registro["landing_page_url"] = "https://identificavel.invalid"
        saida = self.raiz / "saida.json"
        entrada = self.raiz / "entrada.json"
        entrada.write_text(json.dumps([registro]), encoding="utf-8")
        with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
            anonimizador.anonimizar_arquivo(entrada, saida, "meta")
        self.assertFalse(saida.exists())

    def test_campo_obrigatorio_ausente_falha(self):
        registro = registro_google()
        del registro["video_trueview_views"]
        with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
            self.gerar([registro], "google")

    def test_tipo_de_metrica_novo_falha(self):
        with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
            self.gerar([registro_google(conversions=1)], "google")

    def test_raiz_nao_lista_falha(self):
        entrada = self.raiz / "entrada.json"
        saida = self.raiz / "saida.json"
        entrada.write_text(json.dumps(registro_meta()), encoding="utf-8")
        with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
            anonimizador.anonimizar_arquivo(entrada, saida, "meta")

    def test_hierarquia_ambigua_falha(self):
        primeiro = registro_meta()
        segundo = registro_meta(account_id="100000000002")
        with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
            self.gerar([primeiro, segundo])


class TestIdentidade(BaseAnonimizacao):
    """IDs e nomes compartilham a mesma identidade HMAC."""

    def test_nome_real_nao_aparece(self):
        _, saida, _, dados = self.gerar([registro_meta()])
        self.assertNotIn("Marca Sigilosa", saida.read_text(encoding="utf-8"))
        self.assertNotEqual(dados[0]["account_name"], "Marca Sigilosa Ltda")

    def test_external_id_real_nao_aparece(self):
        _, saida, _, _ = self.gerar([registro_meta()])
        texto = saida.read_text(encoding="utf-8")
        for valor in ("100000000001", "200000000001", "300000000001", "400000000001"):
            self.assertNotIn(valor, texto)

    def test_mesmo_id_produz_mesmo_pseudonimo(self):
        segundo = registro_meta(date_start="2026-08-11", date_stop="2026-08-11")
        _, _, _, dados = self.gerar([registro_meta(), segundo])
        self.assertEqual(len({item["ad_id"] for item in dados}), 1)

    def test_ids_diferentes_produzem_pseudonimos_diferentes(self):
        segundo = registro_meta(
            ad_id="400000000002",
            ad_name="Outro anuncio",
            date_start="2026-08-11",
            date_stop="2026-08-11",
        )
        _, _, _, dados = self.gerar([registro_meta(), segundo])
        self.assertEqual(len({item["ad_id"] for item in dados}), 2)

    def test_meta_google_com_mesmo_numero_nao_colidem(self):
        _, _, _, meta = self.gerar([registro_meta()], "meta", "meta.json")
        _, _, _, google = self.gerar([registro_google()], "google", "google.json")
        self.assertNotEqual(meta[0]["account_id"], google[0]["account_id"])

    def test_hierarquia_permanece_consistente(self):
        segundo = registro_meta(
            ad_id="400000000002", ad_name="Segundo", date_start="2026-08-11",
            date_stop="2026-08-11",
        )
        _, _, _, dados = self.gerar([registro_meta(), segundo])
        self.assertEqual(len({item["adset_id"] for item in dados}), 1)
        self.assertEqual(len({item["ad_id"] for item in dados}), 2)

    def test_nome_e_id_da_entidade_sao_o_mesmo_rotulo(self):
        _, _, _, dados = self.gerar([registro_google()], "google")
        linha = dados[0]
        for nome, identificador in (
            ("account_name", "account_id"),
            ("campaign_name", "campaign_id"),
            ("ad_group_name", "ad_group_id"),
            ("ad_name", "ad_id"),
        ):
            self.assertEqual(linha[nome], linha[identificador])

    def test_colisao_do_digest_truncado_falha(self):
        segundo = registro_meta(
            account_id="100000000002",
            campaign_id="200000000002",
            adset_id="300000000002",
            ad_id="400000000002",
        )

        def colidir(nivel, _identidade):
            return f"{pseudonimos.NIVEIS[nivel]}-AAAAAAAA"

        with mock.patch.object(
            anonimizador.pseudonimos, "gerar_id_publico", side_effect=colidir
        ):
            with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
                self.gerar([registro_meta(), segundo])


class TestNomes(BaseAnonimizacao):
    """O nome inteiro some; nenhum esqueleto textual sobrevive."""

    def _texto_identidade(self, registro):
        _, _, _, dados = self.gerar([registro])
        return " ".join(
            str(valor)
            for campo, valor in dados[0].items()
            if campo.endswith("_name") or campo.endswith("_id")
        )

    def test_marca_some(self):
        self.assertNotIn("MARCAUNICA", self._texto_identidade(
            registro_meta(account_name="MARCAUNICA")
        ))

    def test_colchetes_nao_preservam_fingerprint(self):
        texto = self._texto_identidade(
            registro_meta(campaign_name="[OBJETIVO][MARCA][01/08/2026]")
        )
        self.assertNotIn("[", texto)
        self.assertNotIn("]", texto)

    def test_dominio_some(self):
        self.assertNotIn("cliente.example", self._texto_identidade(
            registro_meta(ad_name="cliente.example")
        ))

    def test_localidade_some(self):
        self.assertNotIn("Parintins", self._texto_identidade(
            registro_meta(adset_name="Parintins Amazonas")
        ))

    def test_tratamento_profissional_some(self):
        texto = self._texto_identidade(registro_meta(adset_name="Dra. Exemplo"))
        self.assertNotIn("Dra.", texto)

    def test_cnpj_e_telefone_somem(self):
        texto = self._texto_identidade(
            registro_meta(account_name="12.345.678/0001-99 (92) 99999-9999")
        )
        self.assertNotIn("12.345.678", texto)
        self.assertNotIn("99999-9999", texto)

    def test_rotulos_seguem_formato_uniforme(self):
        _, _, _, dados = self.gerar([registro_meta()])
        padroes = {
            "account_name": r"^Cliente-[0-9A-F]{8}$",
            "campaign_name": r"^Campanha-[0-9A-F]{8}$",
            "adset_name": r"^AdSet-[0-9A-F]{8}$",
            "ad_name": r"^Anuncio-[0-9A-F]{8}$",
        }
        for campo, padrao in padroes.items():
            self.assertRegex(dados[0][campo], padrao)


class TestMetricas(BaseAnonimizacao):
    """A transformacao nao interpreta nem arredonda numeros."""

    def test_metricas_meta_identicas(self):
        origem = registro_meta()
        _, _, _, dados = self.gerar([origem])
        for campo in ("spend", "impressions", "inline_link_clicks", "reach"):
            self.assertEqual(dados[0][campo], origem[campo])

    def test_metricas_google_identicas(self):
        origem = registro_google()
        _, _, _, dados = self.gerar([origem], "google")
        for campo in (
            "impressions", "clicks", "cost", "conversions",
            "conversions_value", "video_trueview_views",
        ):
            self.assertEqual(dados[0][campo], origem[campo])

    def test_conversions_fracionaria_preservada(self):
        origem = registro_google(conversions=0.123456789012345)
        _, _, _, dados = self.gerar([origem], "google")
        self.assertEqual(dados[0]["conversions"], origem["conversions"])
        self.assertNotEqual(dados[0]["conversions"], int(origem["conversions"]))

    def test_actions_preservam_valores(self):
        origem = registro_meta()
        _, _, _, dados = self.gerar([origem])
        self.assertEqual(dados[0]["actions"], origem["actions"])

    def test_action_values_preservam_valores(self):
        origem = registro_meta()
        _, _, _, dados = self.gerar([origem])
        self.assertEqual(dados[0]["action_values"], origem["action_values"])

    def test_nenhuma_metrica_e_zerada(self):
        _, _, _, meta = self.gerar([registro_meta()])
        _, _, _, google = self.gerar([registro_google()], "google", "google.json")
        self.assertTrue(all(meta[0][campo] != "0" for campo in (
            "spend", "impressions", "inline_link_clicks", "reach"
        )))
        self.assertTrue(all(google[0][campo] != 0 for campo in (
            "impressions", "clicks", "cost", "conversions",
            "conversions_value", "video_trueview_views",
        )))

    def test_precisao_textual_nao_e_truncada(self):
        origem = registro_meta(
            spend="0.12345678901234567890",
            actions=[{"action_type": "link_click", "value": "1.0000000000000001"}],
        )
        _, _, _, dados = self.gerar([origem])
        self.assertEqual(dados[0]["spend"], origem["spend"])
        self.assertEqual(dados[0]["actions"][0]["value"], "1.0000000000000001")


class TestEstruturaEEscrita(BaseAnonimizacao):
    """Reprodutibilidade, manifesto e escrita segura."""

    def test_mesma_quantidade_de_registros(self):
        registros = [
            registro_google(),
            registro_google(ad_id="700000000002", date="2026-08-11"),
        ]
        _, _, resultado, dados = self.gerar(registros, "google")
        self.assertEqual(resultado.registros, len(registros))
        self.assertEqual(len(dados), len(registros))

    def test_datas_identicas(self):
        registros = [
            registro_meta(),
            registro_meta(date_start="2026-08-11", date_stop="2026-08-11"),
        ]
        _, _, _, dados = self.gerar(registros)
        self.assertCountEqual(
            [(item["date_start"], item["date_stop"]) for item in dados],
            [(item["date_start"], item["date_stop"]) for item in registros],
        )

    def test_duas_execucoes_mesma_chave_sao_byte_a_byte_iguais(self):
        registros = [registro_meta(), registro_meta(
            ad_id="400000000002", date_start="2026-08-11", date_stop="2026-08-11"
        )]
        _, primeira, _, _ = self.gerar(registros, nome="primeira.json")
        _, segunda, _, _ = self.gerar(registros, nome="segunda.json")
        self.assertEqual(primeira.read_bytes(), segunda.read_bytes())

    def test_ordem_de_entrada_nao_altera_saida(self):
        registros = [registro_meta(), registro_meta(
            ad_id="400000000002", date_start="2026-08-11", date_stop="2026-08-11"
        )]
        _, primeira, _, _ = self.gerar(registros, nome="primeira.json")
        _, segunda, _, _ = self.gerar(list(reversed(registros)), nome="segunda.json")
        self.assertEqual(primeira.read_bytes(), segunda.read_bytes())

    def test_falha_nao_deixa_final_novo_nem_parcial(self):
        entrada = self.raiz / "entrada.json"
        saida = self.raiz / "saida.json"
        entrada.write_text(json.dumps([registro_meta(novo="x")]), encoding="utf-8")
        with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
            anonimizador.anonimizar_arquivo(entrada, saida, "meta")
        self.assertFalse(saida.exists())
        self.assertFalse(Path(str(saida) + anonimizador.SUFIXO_PARCIAL).exists())

    def test_falha_preserva_artefato_anterior(self):
        entrada = self.raiz / "entrada.json"
        saida = self.raiz / "saida.json"
        saida.write_text("artefato anterior", encoding="utf-8")
        entrada.write_text(json.dumps([registro_meta(novo="x")]), encoding="utf-8")
        with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
            anonimizador.anonimizar_arquivo(entrada, saida, "meta")
        self.assertEqual(saida.read_text(encoding="utf-8"), "artefato anterior")

    def test_manifesto_confere_com_artefato(self):
        _, saida, resultado, dados = self.gerar([registro_google()], "google")
        manifesto = json.loads(resultado.manifesto.read_text(encoding="utf-8"))
        self.assertEqual(manifesto["linhas"], len(dados))
        self.assertEqual(manifesto["fonte"], "google")
        self.assertEqual(
            manifesto["sha256"], hashlib.sha256(saida.read_bytes()).hexdigest()
        )
        self.assertEqual(
            manifesto["fingerprint_chave"], pseudonimos.fingerprint_chave()
        )
        self.assertEqual(
            set(manifesto["campos_esperados"]),
            set(anonimizador.CONTRATOS["google"]),
        )


class TestSeguranca(BaseAnonimizacao):
    """Segredo, destino publico e vazamento em fixture."""

    def test_segredo_nao_aparece_em_erro(self):
        segredo_curto = "segredo-super-sensivel"
        entrada = self.raiz / "entrada.json"
        entrada.write_text(json.dumps([registro_meta()]), encoding="utf-8")
        args = argparse.Namespace(
            entrada=str(entrada), saida=str(self.raiz / "saida.json"),
            plataforma="meta", diretorio_saida=str(self.raiz),
            permitir_publicacao=False,
        )
        stderr = io.StringIO()
        with mock.patch.dict(
            os.environ, {pseudonimos.VARIAVEL: segredo_curto}, clear=False
        ), contextlib.redirect_stderr(stderr):
            self.assertEqual(anonimizador.executar(args), 1)
        self.assertNotIn(segredo_curto, stderr.getvalue())

    def test_ausencia_do_segredo_falha(self):
        ambiente = {
            chave: valor for chave, valor in os.environ.items()
            if chave != pseudonimos.VARIAVEL
        }
        with mock.patch.dict(os.environ, ambiente, clear=True):
            with self.assertRaises(pseudonimos.ChaveInvalida):
                self.gerar([registro_meta()])

    def test_placeholder_do_segredo_falha(self):
        with mock.patch.dict(
            os.environ, {pseudonimos.VARIAVEL: pseudonimos.PLACEHOLDER}, clear=False
        ):
            with self.assertRaises(pseudonimos.ChaveInvalida):
                self.gerar([registro_meta()])

    def test_data_publico_sem_flag_falha(self):
        publico = self.raiz / "data" / "publico"
        entrada = self.raiz / "entrada.json"
        entrada.write_text(json.dumps([registro_meta()]), encoding="utf-8")
        with mock.patch.object(anonimizador, "DIRETORIO_PUBLICACAO", publico):
            with self.assertRaises(anonimizador.ContratoAnonimizacaoQuebrado):
                anonimizador.anonimizar_arquivo(
                    entrada, publico / "saida.json", "meta"
                )

    def test_flag_apenas_libera_escrita_no_diretorio(self):
        publico = self.raiz / "data" / "publico"
        entrada = self.raiz / "entrada.json"
        entrada.write_text(json.dumps([registro_meta()]), encoding="utf-8")
        with mock.patch.object(anonimizador, "DIRETORIO_PUBLICACAO", publico):
            resultado = anonimizador.anonimizar_arquivo(
                entrada, publico / "saida.json", "meta", True
            )
        self.assertEqual(resultado.registros, 1)

    def test_fixture_nao_contem_nome_nem_external_id_real(self):
        origem = registro_meta(
            account_name="EMPRESAULTRASSECRETA",
            campaign_name="[MARCASIGILOSA] produto.local",
            adset_name="Dra. Pessoa Manaus",
            ad_name="CNPJ 12.345.678/0001-99 telefone 99999-9999",
        )
        _, saida, _, _ = self.gerar([origem])
        texto = saida.read_text(encoding="utf-8")
        proibidos = [
            "EMPRESAULTRASSECRETA", "MARCASIGILOSA", "produto.local",
            "Manaus", "12.345.678", "99999-9999",
            origem["account_id"], origem["campaign_id"],
            origem["adset_id"], origem["ad_id"],
        ]
        self.assertFalse(any(valor in texto for valor in proibidos))

    def test_nao_ha_logica_local_de_hash_no_modulo(self):
        fonte = Path(anonimizador.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(fonte, re.compile(r"\bSALT\b"))
        self.assertNotIn("hashlib.sha256(f", fonte)
        self.assertNotIn("dict(registro)", fonte)


if __name__ == "__main__":
    unittest.main()
