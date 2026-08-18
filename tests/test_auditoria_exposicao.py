"""Testes do auditor independente do artefato de exposicao.

O auditor e a ultima porta antes de qualquer material sair do projeto. Estes
testes constroem o artefato **a mao**, sem chamar o exportador — se a suite
usasse o produtor para montar o insumo, um erro comum aos dois passaria
despercebido, que e exatamente o acoplamento que o auditor existe para evitar.

Cada teste planta uma violacao especifica e exige exit 1. O teste de exit 0
prova que o auditor nao reprova artefato correto, sem o qual todos os outros
seriam satisfeitos por um script que sempre falha.

Rodar:
    python -m unittest discover -s tests -t .
"""

import hashlib
import json
import unittest
from unittest import mock
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts import auditar_dataset_exposicao as auditor

NOME_REAL_PLANTADO = "Anunciante Ficticio Da Silva"
EXTERNAL_ID_PLANTADO = "987654321098765"
NK_PLANTADA = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


def linhas_validas() -> list[dict]:
    """Monta um artefato sintetico que respeita o contrato.

    Returns:
        Lista de dicionarios no schema de exposicao, valores como texto.
    """
    linhas: list[dict] = []
    datas = ["2026-08-10", "2026-08-11"]
    for i_conta in range(2):
        plataforma = "Meta Ads" if i_conta == 0 else "Google Ads"
        for i_campanha in range(2):
            for i_anuncio in range(2):
                for i_data, dia in enumerate(datas):
                    linhas.append({
                        "data": dia,
                        "plataforma": plataforma,
                        "conta_id": f"Cliente-0000000{i_conta}",
                        "conta_versao": "1",
                        "campanha_id": f"Campanha-000000{i_conta}{i_campanha}",
                        "campanha_versao": "2" if i_campanha == 0 else "1",
                        "adset_id": f"AdSet-000000{i_conta}{i_campanha}",
                        "adset_versao": "1",
                        "anuncio_id": (
                            f"Anuncio-00000{i_conta}{i_campanha}{i_anuncio}"
                        ),
                        "anuncio_versao": "1",
                        "spend": f"{10 + i_data}.123456",
                        "impressions": "1000",
                        "link_clicks": "10",
                        # Fracionaria: e assim que o Google reporta conversao.
                        "conversions": "1.750000",
                        "conversion_value": "25.500000",
                        "video_views": "5",
                        "reach": "900",
                        "profile_views": "0",
                        "purchases": "0",
                    })
    return linhas


def montar_csv(linhas: list[dict], colunas=None) -> str:
    """Serializa linhas no formato do artefato.

    Args:
        linhas: Linhas do artefato.
        colunas: Cabecalho a usar. Default: o contrato.

    Returns:
        Texto do CSV.
    """
    colunas = colunas or list(auditor.COLUNAS_ESPERADAS)
    saida = [",".join(colunas)]
    for linha in linhas:
        saida.append(",".join(str(linha.get(coluna, "")) for coluna in colunas))
    return "\n".join(saida) + "\n"


def montar_manifesto(texto_csv: str, linhas: list[dict], colunas=None) -> dict:
    """Monta um manifesto coerente com o CSV.

    Args:
        texto_csv: Conteudo do CSV.
        linhas: Linhas do artefato.
        colunas: Cabecalho declarado.

    Returns:
        Manifesto serializavel.
    """
    datas = sorted(linha["data"] for linha in linhas)
    return {
        "versao_contrato": 1,
        "gerado_em": "2026-08-18T00:00:00+00:00",
        "artefato": auditor.NOME_CSV,
        "sha256": hashlib.sha256(texto_csv.encode("utf-8")).hexdigest(),
        "linhas": len(linhas),
        "data_min": datas[0],
        "data_max": datas[-1],
        "grao": "1 anuncio x 1 dia",
        "colunas": colunas or list(auditor.COLUNAS_ESPERADAS),
        "tipos": {c: "text" for c in auditor.COLUNAS_ESPERADAS},
        "fingerprint_chave": "0123456789ABCDEF",
        "avisos": {
            "video_views": (
                "definicao diferente por plataforma; total cross-platform nao "
                "tem interpretacao comum"
            ),
        },
    }


class CursorFalso:
    """Cursor que responde as consultas do auditor com dados sinteticos."""

    def __init__(self, linhas: list[dict]):
        self.linhas = linhas
        self.resultado: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql: str, params=None) -> None:
        """Despacha conforme a consulta.

        Args:
            sql: Consulta emitida pelo auditor.
            params: Parametros posicionais.
        """
        # A consulta de versoes tambem contem "count(*) from
        # gold.vw_metricas_completas"; por isso ela e testada primeiro.
        if "union all" in sql:
            contagem: list[tuple] = []
            for nivel in auditor.NIVEIS:
                por_versao: dict = {}
                for linha in self.linhas:
                    versao = int(linha[f"{nivel}_versao"])
                    por_versao[versao] = por_versao.get(versao, 0) + 1
                for versao, quantidade in por_versao.items():
                    contagem.append((nivel, versao, quantidade))
            self.resultado = contagem
        elif "from gold.dim_" in sql:
            # Valores proibidos: nome, external_id, nk, sk de uma dimensao.
            self.resultado = [
                (NOME_REAL_PLANTADO, EXTERNAL_ID_PLANTADO, NK_PLANTADA,
                 "sk" + NK_PLANTADA)
            ]
        elif "count(*) from gold.vw_metricas_completas" in sql:
            self.resultado = [(len(self.linhas),)]
        elif "distinct data" in sql:
            self.resultado = [(d,) for d in {l["data"] for l in self.linhas}]
        elif "group by plataforma, data" in sql:
            agregados: dict = {}
            for linha in self.linhas:
                chave = (linha["plataforma"], linha["data"])
                alvo = agregados.setdefault(
                    chave, [0] + [Decimal(0)] * len(auditor.METRICAS)
                )
                alvo[0] += 1
                for i, metrica in enumerate(auditor.METRICAS, start=1):
                    alvo[i] += Decimal(linha[metrica])
            self.resultado = [
                (chave[0], chave[1], str(valores[0]),
                 *[str(v) for v in valores[1:]])
                for chave, valores in agregados.items()
            ]
        elif "count(distinct conta_nk)" in sql:
            self.resultado = [tuple(
                len({l[f"{nivel}_id"] for l in self.linhas})
                for nivel in auditor.NIVEIS
            )]
        else:
            raise AssertionError(f"consulta inesperada no auditor: {sql[:60]}")

    def fetchall(self) -> list[tuple]:
        """Devolve o resultado da ultima consulta.

        Returns:
            Lista de tuplas.
        """
        return self.resultado

    def fetchone(self):
        """Devolve a primeira linha do resultado.

        Returns:
            Tupla.
        """
        return self.resultado[0]


class ConexaoFalsa:
    """Conexao que serve `CursorFalso`, sem banco."""

    def __init__(self, linhas: list[dict]):
        self.linhas = linhas

    def cursor(self) -> CursorFalso:
        """Abre um cursor falso.

        Returns:
            O cursor.
        """
        return CursorFalso(self.linhas)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class BaseAuditoria(unittest.TestCase):
    """Grava um artefato em diretorio temporario e roda o auditor."""

    def setUp(self):
        self.temporario = TemporaryDirectory()
        self.diretorio = Path(self.temporario.name)
        self.addCleanup(self.temporario.cleanup)
        self.linhas = linhas_validas()

    def gravar(self, linhas=None, colunas=None, manifesto=None,
               texto_csv=None) -> None:
        """Grava CSV e manifesto no diretorio temporario.

        Args:
            linhas: Linhas do artefato.
            colunas: Cabecalho a usar.
            manifesto: Manifesto a gravar. Default: coerente com o CSV.
            texto_csv: Texto do CSV, se ja pronto.
        """
        linhas = self.linhas if linhas is None else linhas
        texto = texto_csv if texto_csv is not None else montar_csv(linhas, colunas)
        (self.diretorio / auditor.NOME_CSV).write_text(texto, encoding="utf-8")
        conteudo = (
            manifesto if manifesto is not None
            else montar_manifesto(texto, linhas, colunas)
        )
        (self.diretorio / auditor.NOME_MANIFESTO).write_text(
            json.dumps(conteudo, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def auditar(self, usar_dw: bool = False) -> int:
        """Roda o auditor sobre o artefato gravado.

        Args:
            usar_dw: Se deve rodar os checks que dependem do banco.

        Returns:
            Exit code.
        """
        return auditor.auditar(self.diretorio, usar_dw=usar_dw)


class TestArtefatoValido(BaseAuditoria):
    """Sem este teste, um auditor que sempre reprova passaria em todos."""

    def test_artefato_correto_aprova(self):
        self.gravar()

        self.assertEqual(self.auditar(), 0)

    def test_artefato_correto_aprova_tambem_contra_o_dw(self):
        self.gravar()
        conexao = ConexaoFalsa(self.linhas)

        with mock.patch.object(
            auditor, "_conectar", return_value=conexao
        ):
            self.assertEqual(self.auditar(usar_dw=True), 0)

    def test_arquivo_ausente_reprova(self):
        self.assertEqual(self.auditar(), 1)


class TestSchema(BaseAuditoria):
    """O cabecalho e contrato, nao sugestao."""

    def test_coluna_extra_reprova(self):
        colunas = list(auditor.COLUNAS_ESPERADAS) + ["landing_page_url"]
        linhas = [dict(l, landing_page_url="x") for l in self.linhas]
        self.gravar(linhas=linhas, colunas=colunas)

        self.assertEqual(self.auditar(), 1)

    def test_coluna_ausente_reprova(self):
        colunas = [c for c in auditor.COLUNAS_ESPERADAS if c != "conta_versao"]
        self.gravar(colunas=colunas)

        self.assertEqual(self.auditar(), 1)

    def test_coluna_com_sufixo_interno_reprova(self):
        colunas = list(auditor.COLUNAS_ESPERADAS) + ["conta_nk"]
        linhas = [dict(l, conta_nk=NK_PLANTADA) for l in self.linhas]
        self.gravar(linhas=linhas, colunas=colunas)

        self.assertEqual(self.auditar(), 1)

    def test_ordem_trocada_reprova(self):
        colunas = list(auditor.COLUNAS_ESPERADAS)
        colunas[0], colunas[1] = colunas[1], colunas[0]
        self.gravar(colunas=colunas)

        self.assertEqual(self.auditar(), 1)


class TestIdentidadePlantada(BaseAuditoria):
    """Qualquer identificador real no artefato reprova."""

    def test_nome_real_no_lugar_do_pseudonimo_reprova(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["conta_id"] = NOME_REAL_PLANTADO
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_nome_real_detectado_contra_o_dw(self):
        # Formato do pseudonimo preservado, nome real escondido em outra
        # coluna textual: so a comparacao com o Gold pega.
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["plataforma"] = NOME_REAL_PLANTADO
        self.gravar(linhas=linhas)
        conexao = ConexaoFalsa(self.linhas)

        with mock.patch.object(
            auditor, "_conectar", return_value=conexao
        ):
            self.assertEqual(self.auditar(usar_dw=True), 1)

    def test_external_id_plantado_reprova(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["anuncio_id"] = EXTERNAL_ID_PLANTADO
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_chave_natural_plantada_reprova_contra_o_dw(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["plataforma"] = NK_PLANTADA
        self.gravar(linhas=linhas)
        conexao = ConexaoFalsa(self.linhas)

        with mock.patch.object(
            auditor, "_conectar", return_value=conexao
        ):
            self.assertEqual(self.auditar(usar_dw=True), 1)

    def test_url_plantada_reprova(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["plataforma"] = "https://exemplo-ficticio.com"
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_dominio_plantado_reprova(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["plataforma"] = "exemplo-ficticio.com.br"
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_email_plantado_reprova(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["plataforma"] = "contato@exemplo-ficticio.com"
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_telefone_plantado_reprova(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["plataforma"] = "(11) 91234-5678"
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_cnpj_plantado_reprova(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["plataforma"] = "12.345.678/0001-90"
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_tratamento_pessoal_plantado_reprova(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["plataforma"] = "Dra. Ficticia"
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_nome_curto_dentro_de_pseudonimo_nao_e_falso_positivo(self):
        # Um anuncio cujo nome real sao quatro caracteres hexadecimais aparece
        # "dentro" de um pseudonimo por coincidencia aritmetica — 8 hex tem
        # muitas janelas de 4. Medido contra o DW real em 18/08/2026. O
        # pseudonimo vem de HMAC e nao carrega nada do nome: reprovar aqui
        # seria ruido que ensina a ignorar a auditoria.
        self.gravar()
        pedaco = self.linhas[0]["adset_id"].split("-")[1][:4]

        class ConexaoComNomeCurto(ConexaoFalsa):
            def cursor(self):
                cursor = CursorFalso(self.linhas)
                execute_original = cursor.execute

                def execute(sql, params=None):
                    execute_original(sql, params)
                    if "from gold.dim_" in sql:
                        cursor.resultado = [(pedaco, "1", "2", "3")]

                cursor.execute = execute
                return cursor

        with mock.patch.object(
            auditor, "_conectar", return_value=ConexaoComNomeCurto(self.linhas)
        ):
            self.assertEqual(self.auditar(usar_dw=True), 0)

    def test_nome_real_igual_a_celula_estruturada_reprova(self):
        # Igualdade continua valendo mesmo em celula bem formada: se o nome
        # real FOR o valor da celula, e vazamento.
        self.gravar()
        identificador = self.linhas[0]["conta_id"]

        class ConexaoComNomeIgual(ConexaoFalsa):
            def cursor(self):
                cursor = CursorFalso(self.linhas)
                execute_original = cursor.execute

                def execute(sql, params=None):
                    execute_original(sql, params)
                    if "from gold.dim_" in sql:
                        cursor.resultado = [(identificador, "1", "2", "3")]

                cursor.execute = execute
                return cursor

        with mock.patch.object(
            auditor, "_conectar", return_value=ConexaoComNomeIgual(self.linhas)
        ):
            self.assertEqual(self.auditar(usar_dw=True), 1)

    def test_falha_nao_reproduz_o_valor_identificavel(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["plataforma"] = NOME_REAL_PLANTADO
        self.gravar(linhas=linhas)
        conexao = ConexaoFalsa(self.linhas)

        with mock.patch.object(
            auditor, "_conectar", return_value=conexao
        ), self.assertLogs(auditor.logger, level="ERROR") as capturado:
            self.auditar(usar_dw=True)

        saida = "\n".join(capturado.output)
        self.assertNotIn(NOME_REAL_PLANTADO, saida)
        self.assertIn("FALHA", saida)


class TestEstruturaEMetricas(BaseAuditoria):
    """Contagem, grao, versoes e metricas nao podem mudar em silencio."""

    def test_grao_duplicado_reprova(self):
        linhas = list(self.linhas) + [dict(self.linhas[0])]
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_linha_removida_reprova_contra_o_dw(self):
        conexao = ConexaoFalsa(self.linhas)
        self.gravar(linhas=self.linhas[:-1])

        with mock.patch.object(
            auditor, "_conectar", return_value=conexao
        ):
            self.assertEqual(self.auditar(usar_dw=True), 1)

    def test_metrica_alterada_reprova_contra_o_dw(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["spend"] = "99999.000000"
        self.gravar(linhas=linhas)
        conexao = ConexaoFalsa(self.linhas)

        with mock.patch.object(
            auditor, "_conectar", return_value=conexao
        ):
            self.assertEqual(self.auditar(usar_dw=True), 1)

    def test_versao_scd2_alterada_reprova_contra_o_dw(self):
        linhas = [dict(l) for l in self.linhas]
        for linha in linhas:
            linha["campanha_versao"] = "1"
        self.gravar(linhas=linhas)
        conexao = ConexaoFalsa(self.linhas)

        with mock.patch.object(
            auditor, "_conectar", return_value=conexao
        ):
            self.assertEqual(self.auditar(usar_dw=True), 1)

    def test_conversao_truncada_para_inteiro_reprova(self):
        linhas = [dict(l, conversions="2") for l in self.linhas]
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_versao_nao_inteira_reprova(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["conta_versao"] = "0"
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_data_invalida_reprova(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["data"] = "10/08/2026"
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_metrica_nao_numerica_reprova(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["impressions"] = "muitas"
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)

    def test_hierarquia_quebrada_reprova(self):
        linhas = [dict(l) for l in self.linhas]
        linhas[0]["conta_id"] = "Cliente-FFFFFFFF"
        self.gravar(linhas=linhas)

        self.assertEqual(self.auditar(), 1)


class TestManifesto(BaseAuditoria):
    """O manifesto tem de descrever o artefato que esta ao lado dele."""

    def test_sha_incorreto_reprova(self):
        texto = montar_csv(self.linhas)
        manifesto = montar_manifesto(texto, self.linhas)
        manifesto["sha256"] = "0" * 64
        self.gravar(manifesto=manifesto)

        self.assertEqual(self.auditar(), 1)

    def test_contagem_declarada_errada_reprova(self):
        texto = montar_csv(self.linhas)
        manifesto = montar_manifesto(texto, self.linhas)
        manifesto["linhas"] = len(self.linhas) + 1
        self.gravar(manifesto=manifesto)

        self.assertEqual(self.auditar(), 1)

    def test_manifesto_sem_aviso_de_video_views_reprova(self):
        texto = montar_csv(self.linhas)
        manifesto = montar_manifesto(texto, self.linhas)
        manifesto["avisos"] = {}
        self.gravar(manifesto=manifesto)

        self.assertEqual(self.auditar(), 1)

    def test_manifesto_sem_campo_obrigatorio_reprova(self):
        texto = montar_csv(self.linhas)
        manifesto = montar_manifesto(texto, self.linhas)
        del manifesto["fingerprint_chave"]
        self.gravar(manifesto=manifesto)

        self.assertEqual(self.auditar(), 1)

    def test_manifesto_invalido_reprova(self):
        self.gravar()
        (self.diretorio / auditor.NOME_MANIFESTO).write_text(
            "{nao e json", encoding="utf-8"
        )

        self.assertEqual(self.auditar(), 1)

    def test_dw_indisponivel_reprova_quando_exigido(self):
        self.gravar()

        with mock.patch.object(
            auditor, "_conectar", return_value=None
        ):
            self.assertEqual(self.auditar(usar_dw=True), 1)


class TestIndependencia(unittest.TestCase):
    """O auditor nao pode confiar no produtor para se declarar seguro."""

    def test_auditor_nao_importa_o_produtor(self):
        fonte = Path(auditor.__file__).read_text(encoding="utf-8")

        self.assertNotIn("import pseudonimos", fonte)
        self.assertNotIn("exportar_dataset_exposicao", fonte)

    def test_auditor_declara_o_proprio_schema(self):
        from scripts import exportar_dataset_exposicao as produtor

        # Os dois tem de concordar hoje, mas cada um declara o seu: se o
        # produtor mudar sozinho, a auditoria reprova em vez de acompanhar.
        self.assertEqual(
            list(auditor.COLUNAS_ESPERADAS), list(produtor.COLUNAS_SAIDA)
        )
        self.assertIsNot(auditor.COLUNAS_ESPERADAS, produtor.COLUNAS_SAIDA)


if __name__ == "__main__":
    unittest.main()
