"""Testes do contrato entre extracao e carga (manifesto de artefato).

Cada teste corresponde a um modo de falha que a auditoria de 17/08/2026 listou
como possivel hoje: Meta novo com Google velho, artefato de outro DagRun,
arquivo ausente, arquivo trocado depois da extracao, fonte errada, janela
diferente da pedida e extracao legitimamente vazia.

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
from manifesto import ManifestoInvalido
from plataformas import PLATAFORMAS, Plataforma

RUN_ATUAL = "manual__2026-08-17T12:00:00+00:00"
RUN_ANTERIOR = "scheduled__2026-08-10T09:00:00+00:00"
JANELA = ("2026-08-10", "2026-08-16")


def plataforma_em(diretorio: Path, chave: str) -> Plataforma:
    """Copia uma entrada do registro apontando para um diretorio temporario.

    Args:
        diretorio: Onde os artefatos de teste serao escritos.
        chave: Chave da plataforma no registro (``meta`` / ``google``).

    Returns:
        Plataforma identica a real, exceto pelo caminho do arquivo bruto.
    """
    original = PLATAFORMAS[chave]
    return Plataforma(
        chave=original.chave,
        nome=original.nome,
        fonte_bronze=original.fonte_bronze,
        arquivo_bruto=diretorio / original.arquivo_bruto.name,
        campo_data=original.campo_data,
        modulo_extrator=original.modulo_extrator,
        variaveis_obrigatorias=original.variaveis_obrigatorias,
    )


class BaseArtefato(unittest.TestCase):
    """Monta um diretorio temporario com artefatos controlados."""

    def setUp(self):
        self.diretorio = Path(tempfile.mkdtemp(prefix="tcc_manifesto_"))
        self.addCleanup(shutil.rmtree, self.diretorio, ignore_errors=True)
        self.meta = plataforma_em(self.diretorio, "meta")
        self.google = plataforma_em(self.diretorio, "google")

    def extrair(
        self,
        plataforma: Plataforma,
        run_id: str = RUN_ATUAL,
        janela: tuple[str, str] = JANELA,
        registros: int = 2,
    ) -> None:
        """Simula uma extracao: grava o bruto e o manifesto correspondente."""
        linhas = [{"ad_id": str(i)} for i in range(registros)]
        plataforma.arquivo_bruto.write_text(
            json.dumps(linhas, ensure_ascii=False), encoding="utf-8"
        )
        manifesto.gravar(
            plataforma,
            run_id=run_id,
            start_date=janela[0],
            end_date=janela[1],
            registros=registros,
        )


class TestArtefatoValido(BaseArtefato):

    def test_artefato_do_run_atual_e_aceito(self):
        self.extrair(self.meta)

        registro = manifesto.validar(
            self.meta, run_id=RUN_ATUAL, start_date=JANELA[0], end_date=JANELA[1]
        )

        self.assertEqual(registro.fonte, "meta_ads")
        self.assertEqual(registro.run_id, RUN_ATUAL)
        self.assertEqual(registro.registros, 2)

    def test_extracao_vazia_e_valida_e_distinguivel_de_arquivo_ausente(self):
        self.extrair(self.meta, registros=0)

        registro = manifesto.validar(
            self.meta, run_id=RUN_ATUAL, start_date=JANELA[0], end_date=JANELA[1]
        )

        self.assertEqual(registro.registros, 0)
        self.assertEqual(json.loads(self.meta.arquivo_bruto.read_text()), [])

    def test_reextracao_no_mesmo_run_continua_valida(self):
        # Retry da task: o extrator roda de novo com o mesmo run_id e reescreve
        # os dois arquivos. Tem de continuar aceito.
        self.extrair(self.meta, registros=2)
        self.extrair(self.meta, registros=5)

        registro = manifesto.validar(
            self.meta, run_id=RUN_ATUAL, start_date=JANELA[0], end_date=JANELA[1]
        )

        self.assertEqual(registro.registros, 5)


class TestArtefatoRejeitado(BaseArtefato):

    def test_artefato_de_run_anterior(self):
        self.extrair(self.meta, run_id=RUN_ANTERIOR)

        with self.assertRaises(ManifestoInvalido) as erro:
            manifesto.validar(
                self.meta, run_id=RUN_ATUAL,
                start_date=JANELA[0], end_date=JANELA[1],
            )

        self.assertIn("outra execucao", str(erro.exception))

    def test_manifesto_ausente_arquivo_legado(self):
        # O caso do arquivo que sobrou em disco de uma execucao pre-manifesto.
        self.meta.arquivo_bruto.write_text("[]", encoding="utf-8")

        with self.assertRaises(ManifestoInvalido) as erro:
            manifesto.validar(
                self.meta, run_id=RUN_ATUAL,
                start_date=JANELA[0], end_date=JANELA[1],
            )

        self.assertIn("Manifesto ausente", str(erro.exception))

    def test_arquivo_bruto_ausente(self):
        self.extrair(self.meta)
        self.meta.arquivo_bruto.unlink()

        with self.assertRaises(ManifestoInvalido) as erro:
            manifesto.validar(
                self.meta, run_id=RUN_ATUAL,
                start_date=JANELA[0], end_date=JANELA[1],
            )

        self.assertIn("arquivo bruto ausente", str(erro.exception))

    def test_conteudo_alterado_depois_da_extracao(self):
        self.extrair(self.meta)
        self.meta.arquivo_bruto.write_text('[{"ad_id": "999"}]', encoding="utf-8")

        with self.assertRaises(ManifestoInvalido) as erro:
            manifesto.validar(
                self.meta, run_id=RUN_ATUAL,
                start_date=JANELA[0], end_date=JANELA[1],
            )

        self.assertIn("sha256", str(erro.exception))

    def test_janela_diferente_da_pedida(self):
        self.extrair(self.meta, janela=("2026-08-01", "2026-08-07"))

        with self.assertRaises(ManifestoInvalido) as erro:
            manifesto.validar(
                self.meta, run_id=RUN_ATUAL,
                start_date=JANELA[0], end_date=JANELA[1],
            )

        self.assertIn("janela", str(erro.exception))

    def test_fonte_trocada(self):
        # Manifesto do Google ao lado do arquivo do Meta.
        self.extrair(self.meta)
        dados = json.loads(self.meta.arquivo_manifesto.read_text(encoding="utf-8"))
        dados["fonte"] = "google_ads"
        self.meta.arquivo_manifesto.write_text(json.dumps(dados), encoding="utf-8")

        with self.assertRaises(ManifestoInvalido) as erro:
            manifesto.validar(
                self.meta, run_id=RUN_ATUAL,
                start_date=JANELA[0], end_date=JANELA[1],
            )

        self.assertIn("fonte", str(erro.exception))

    def test_manifesto_ilegivel(self):
        self.extrair(self.meta)
        self.meta.arquivo_manifesto.write_text("{nao e json", encoding="utf-8")

        with self.assertRaises(ManifestoInvalido):
            manifesto.validar(
                self.meta, run_id=RUN_ATUAL,
                start_date=JANELA[0], end_date=JANELA[1],
            )

    def test_versao_de_formato_incompativel(self):
        self.extrair(self.meta)
        dados = json.loads(self.meta.arquivo_manifesto.read_text(encoding="utf-8"))
        dados["versao"] = manifesto.VERSAO + 1
        self.meta.arquivo_manifesto.write_text(json.dumps(dados), encoding="utf-8")

        with self.assertRaises(ManifestoInvalido) as erro:
            manifesto.validar(
                self.meta, run_id=RUN_ATUAL,
                start_date=JANELA[0], end_date=JANELA[1],
            )

        self.assertIn("versao", str(erro.exception))


class TestPares(BaseArtefato):
    """As duas fontes precisam ser do MESMO run — meia execucao nao serve."""

    def test_meta_novo_com_google_velho(self):
        self.extrair(self.meta, run_id=RUN_ATUAL)
        self.extrair(self.google, run_id=RUN_ANTERIOR)

        manifesto.validar(
            self.meta, run_id=RUN_ATUAL, start_date=JANELA[0], end_date=JANELA[1]
        )
        with self.assertRaises(ManifestoInvalido):
            manifesto.validar(
                self.google, run_id=RUN_ATUAL,
                start_date=JANELA[0], end_date=JANELA[1],
            )

    def test_google_novo_com_meta_velho(self):
        self.extrair(self.google, run_id=RUN_ATUAL)
        self.extrair(self.meta, run_id=RUN_ANTERIOR)

        manifesto.validar(
            self.google, run_id=RUN_ATUAL, start_date=JANELA[0], end_date=JANELA[1]
        )
        with self.assertRaises(ManifestoInvalido):
            manifesto.validar(
                self.meta, run_id=RUN_ATUAL,
                start_date=JANELA[0], end_date=JANELA[1],
            )


class TestEscritaAtomica(BaseArtefato):
    """O caminho final nunca fica com JSON pela metade."""

    def test_escrita_bem_sucedida_nao_deixa_arquivo_parcial(self):
        self.extrair(self.meta)

        restos = list(self.diretorio.glob(f"*{manifesto.SUFIXO_PARCIAL}"))

        self.assertEqual(restos, [])

    def test_interrupcao_preserva_o_arquivo_anterior(self):
        # Cenario A: processo morre durante a escrita do bruto.
        self.extrair(self.meta, registros=2)
        antes = self.meta.arquivo_bruto.read_text(encoding="utf-8")

        with mock.patch("manifesto.json.dump", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                manifesto.escrever_json_atomico(
                    self.meta.arquivo_bruto, [{"ad_id": "novo"}]
                )

        self.assertEqual(self.meta.arquivo_bruto.read_text(encoding="utf-8"), antes)
        self.assertEqual(list(self.diretorio.glob(f"*{manifesto.SUFIXO_PARCIAL}")), [])

    def test_interrupcao_entre_bruto_e_manifesto_e_detectada(self):
        # Cenario B: o bruto novo chega ao disco, o manifesto nao. Sobra o
        # manifesto do run anterior, apontando para outro conteudo.
        self.extrair(self.meta, run_id=RUN_ANTERIOR, registros=2)
        manifesto.escrever_json_atomico(
            self.meta.arquivo_bruto, [{"ad_id": "novo"}], ensure_ascii=False
        )

        with self.assertRaises(ManifestoInvalido) as erro:
            manifesto.validar(
                self.meta, run_id=RUN_ATUAL,
                start_date=JANELA[0], end_date=JANELA[1],
            )

        problemas = str(erro.exception)
        self.assertIn("run_id", problemas)
        self.assertIn("sha256", problemas)


class TestConteudoDoManifesto(BaseArtefato):
    """O manifesto e metadado operacional — nada de segredo nem de cliente."""

    CAMPOS_ESPERADOS = {
        "versao", "fonte", "run_id", "start_date", "end_date",
        "extraido_em", "registros", "sha256",
    }

    def test_campos_sao_exatamente_os_do_contrato(self):
        self.extrair(self.meta)

        dados = json.loads(self.meta.arquivo_manifesto.read_text(encoding="utf-8"))

        self.assertEqual(set(dados), self.CAMPOS_ESPERADOS)

    def test_nao_carrega_conteudo_bruto_nem_dado_de_cliente(self):
        # O bruto tem nome de conta e de campanha; o manifesto nao pode
        # carregar nada disso — ele descreve o arquivo, nao o dado.
        linhas = [{
            "ad_id": "123",
            "account_name": "Cliente Alguma Marca LTDA",
            "campaign_name": "[MARCA] Conversao | Setembro",
        }]
        self.meta.arquivo_bruto.write_text(json.dumps(linhas), encoding="utf-8")
        manifesto.gravar(
            self.meta, run_id=RUN_ATUAL,
            start_date=JANELA[0], end_date=JANELA[1], registros=len(linhas),
        )

        texto = self.meta.arquivo_manifesto.read_text(encoding="utf-8")

        self.assertNotIn("Cliente Alguma Marca", texto)
        self.assertNotIn("MARCA", texto)
        self.assertNotIn("ad_id", texto)

    def test_nao_carrega_credencial(self):
        segredos = {
            "META_ACCESS_TOKEN": "EAA" + "F4k3T0k3nSint3tico" * 3,
            "GOOGLE_CLIENT_SECRET": "GOCSPX-sint3tico_nao_real",
            "GOOGLE_REFRESH_TOKEN": "1//0refresh_sintetico_nao_real",
        }
        with mock.patch.dict("os.environ", segredos, clear=False):
            self.extrair(self.meta)

        texto = self.meta.arquivo_manifesto.read_text(encoding="utf-8")

        for valor in segredos.values():
            self.assertNotIn(valor, texto)
        for nome in ("token", "secret", "password", "senha"):
            self.assertNotIn(nome, texto.lower())


class TestCaminhoDoManifesto(unittest.TestCase):

    def test_nome_derivado_com_with_name_e_nao_with_suffix(self):
        # `with_suffix` produziria `temp_meta_raw.manifesto.json` por acidente
        # em alguns casos e nomes duplicados em outros — a mesma familia de bug
        # do `.env.env.bak`.
        self.assertEqual(
            PLATAFORMAS["meta"].arquivo_manifesto.name,
            "temp_meta_raw.manifesto.json",
        )
        self.assertEqual(
            PLATAFORMAS["google"].arquivo_manifesto.name,
            "temp_google_raw.manifesto.json",
        )

    def test_manifesto_fica_ao_lado_do_bruto(self):
        for plataforma in PLATAFORMAS.values():
            with self.subTest(plataforma=plataforma.chave):
                self.assertEqual(
                    plataforma.arquivo_manifesto.parent,
                    plataforma.arquivo_bruto.parent,
                )


if __name__ == "__main__":
    unittest.main()
