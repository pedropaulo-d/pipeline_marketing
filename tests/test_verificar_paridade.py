"""Testes da comparacao golden x estado atual do Data Warehouse.

O que esta sob teste e a DETECCAO, nao o banco: `comparar` recebe duas
estruturas em memoria e devolve as divergencias. Por isso a suite roda sem
Docker, sem Postgres e sem credencial — usa o golden versionado como fixture.

A propriedade central: `por_plataforma_dia` e `contagens` tem chave natural, e
ordem de lista NAO e divergencia. Antes disso, um dia novo deslocava todas as
posicoes seguintes e o relatorio virava cascata de diferencas falsas — foi o
que aconteceu no primeiro DagRun real de 17/08/2026 (77 diferencas relatadas,
10 chaves historicas intactas).

Rodar:
    python -m unittest discover -s tests -t .
"""

import contextlib
import copy
import io
import json
import random
import unittest
from unittest import mock

from scripts import verificar_paridade as vp

GOLDEN = json.loads(vp.GOLDEN_PATH.read_text(encoding="utf-8"))["agregados"]

CHAVE_META = ("Meta Ads", "2026-08-16")

# Chaves que precisam NAO existir no golden: os testes as inserem para simular
# um dia novo. Datas distantes de proposito — uma data plausivel vira chave
# real assim que o recorte avanca, e o teste passa a inserir DUPLICATA em vez
# de novidade. Quando isso acontece, `_indexar` recusa a colecao, a comparacao
# cai para posicional e o bloco some de `keyed`: o sintoma e um `KeyError`
# distante da causa. Ja aconteceu duas vezes neste arquivo.
CHAVE_NOVA_META = ("Meta Ads", "2099-12-31")
CHAVE_NOVA_MEIO = ("Meta Ads", "2098-06-15")


def _conferir_chaves_sinteticas() -> None:
    """Falha na importacao se uma chave sintetica ja existir no golden.

    Raises:
        AssertionError: Se o golden tiver passado a conter a data sintetica.
    """
    presentes = {
        (linha["plataforma"], linha["data"])
        for linha in GOLDEN["por_plataforma_dia"]
    }
    for chave in (CHAVE_NOVA_META, CHAVE_NOVA_MEIO):
        assert chave not in presentes, (
            f"A chave sintetica {chave} passou a existir no golden. "
            "Escolha outra data distante em vez de ajustar o golden."
        )


_conferir_chaves_sinteticas()


def agregados() -> dict:
    """Devolve uma copia independente dos agregados do golden versionado.

    Returns:
        Estrutura no mesmo formato que `coletar` produz.
    """
    return copy.deepcopy(GOLDEN)


def item_por_chave(dados: dict, chave: tuple[str, str]) -> dict:
    """Localiza uma linha de `por_plataforma_dia` pela chave natural.

    Args:
        dados: Agregados.
        chave: Par ``(plataforma, data)``.

    Returns:
        O dict da linha, para mutacao no proprio `dados`.

    Raises:
        KeyError: Se a chave nao existir no golden.
    """
    for linha in dados["por_plataforma_dia"]:
        if (linha["plataforma"], linha["data"]) == chave:
            return linha
    raise KeyError(chave)


def diff_de(dados: dict, nome: str) -> vp.DiffKeyed:
    """Extrai o resultado keyed de um bloco especifico.

    Args:
        dados: Divergencias ja calculadas.
        nome: Nome do bloco.

    Returns:
        O `DiffKeyed` correspondente.

    Raises:
        KeyError: Se o bloco nao tiver sido comparado por chave.
    """
    for diff in dados.keyed:
        if diff.nome == nome:
            return diff
    raise KeyError(nome)


def agregados_resultado_sinteticos() -> dict:
    """Monta as duas colecoes Result sem dado real nem identificador privado.

    Returns:
        Snapshot minimo com Google sem suporte, Meta historico sem contrato e
        Meta atual com ausencia, zero factual e resultado positivo.
    """
    return {
        vp.COLECAO_COBERTURA_RESULTADO: [
            {
                "plataforma": "Google Ads",
                "data": "2026-08-01",
                "linhas": 2,
                "linhas_com_result_type": 0,
                "linhas_sem_result_type": 2,
                "linhas_com_result_count": 0,
                "linhas_com_result_count_zero": 0,
                "linhas_com_cost_per_result": 0,
                "linhas_com_result_attribution_window": 0,
            },
            {
                "plataforma": "Meta Ads",
                "data": "2026-07-15",
                "linhas": 2,
                "linhas_com_result_type": 0,
                "linhas_sem_result_type": 2,
                "linhas_com_result_count": 0,
                "linhas_com_result_count_zero": 0,
                "linhas_com_cost_per_result": 0,
                "linhas_com_result_attribution_window": 0,
            },
            {
                "plataforma": "Meta Ads",
                "data": "2026-08-01",
                "linhas": 3,
                "linhas_com_result_type": 2,
                "linhas_sem_result_type": 1,
                "linhas_com_result_count": 2,
                "linhas_com_result_count_zero": 1,
                "linhas_com_cost_per_result": 1,
                "linhas_com_result_attribution_window": 1,
            },
        ],
        vp.COLECAO_DISTRIBUICAO_RESULTADO: [
            {
                "plataforma": "Meta Ads",
                "data": "2026-08-01",
                "result_type": "actions:offsite_conversion.fb_pixel_lead",
                "result_attribution_window": None,
                "linhas": 1,
                "soma_result_count_no_grupo": "0.000000",
                "linhas_com_result_count_zero": 1,
                "linhas_com_result_count_positivo": 0,
                "linhas_com_cost_per_result": 0,
                "checksum_tecnico_result_count": "a" * 32,
                "checksum_tecnico_cost_per_result": "b" * 32,
            },
            {
                "plataforma": "Meta Ads",
                "data": "2026-08-01",
                "result_type": "actions:offsite_conversion.fb_pixel_lead",
                "result_attribution_window": "default",
                "linhas": 1,
                "soma_result_count_no_grupo": "2.000000",
                "linhas_com_result_count_zero": 0,
                "linhas_com_result_count_positivo": 1,
                "linhas_com_cost_per_result": 1,
                "checksum_tecnico_result_count": "c" * 32,
                "checksum_tecnico_cost_per_result": "d" * 32,
            },
        ],
    }


def cobertura_resultado(
    dados: dict, plataforma: str, data: str
) -> dict:
    """Localiza uma cobertura Result pela chave natural.

    Args:
        dados: Snapshot sintetico.
        plataforma: Plataforma da chave.
        data: Data da chave.

    Returns:
        Item da cobertura, para mutacao no proprio snapshot.

    Raises:
        KeyError: Se a chave nao existir.
    """
    for linha in dados[vp.COLECAO_COBERTURA_RESULTADO]:
        if (linha["plataforma"], linha["data"]) == (plataforma, data):
            return linha
    raise KeyError((plataforma, data))


def distribuicao_resultado(dados: dict, janela) -> dict:
    """Localiza o grupo Lead sintetico por janela.

    Args:
        dados: Snapshot sintetico.
        janela: Janela factual, inclusive ``None``.

    Returns:
        Grupo da distribuicao, para mutacao no proprio snapshot.

    Raises:
        KeyError: Se a janela nao existir.
    """
    for linha in dados[vp.COLECAO_DISTRIBUICAO_RESULTADO]:
        if linha["result_attribution_window"] == janela:
            return linha
    raise KeyError(janela)


class TestCoberturaGoldenDeResultado(unittest.TestCase):
    """Result e protegido como factual, nunca como KPI global heterogeneo."""

    def test_snapshot_captura_cobertura_e_distribuicao(self):
        dados = agregados_resultado_sinteticos()

        self.assertEqual(
            set(dados), {
                vp.COLECAO_COBERTURA_RESULTADO,
                vp.COLECAO_DISTRIBUICAO_RESULTADO,
            },
        )
        self.assertEqual(
            vp._CHAVES_NATURAIS[vp.COLECAO_COBERTURA_RESULTADO],
            ("plataforma", "data"),
        )
        self.assertEqual(
            vp._CHAVES_NATURAIS[vp.COLECAO_DISTRIBUICAO_RESULTADO],
            (
                "plataforma", "data", "result_type",
                "result_attribution_window",
            ),
        )

    def test_typed_virar_ausencia_diverge(self):
        esperado = agregados_resultado_sinteticos()
        atual = copy.deepcopy(esperado)
        cobertura = cobertura_resultado(atual, "Meta Ads", "2026-08-01")
        cobertura.update({
            "linhas_com_result_type": 1,
            "linhas_sem_result_type": 2,
            "linhas_com_result_count": 1,
        })

        diff = diff_de(
            vp.comparar(esperado, atual), vp.COLECAO_COBERTURA_RESULTADO
        )

        self.assertEqual(len(diff.alteradas), 1)

    def test_mudanca_de_result_type_diverge(self):
        esperado = agregados_resultado_sinteticos()
        atual = copy.deepcopy(esperado)
        distribuicao_resultado(atual, "default")["result_type"] = (
            "video_thruplay_watched_actions"
        )

        diff = diff_de(
            vp.comparar(esperado, atual), vp.COLECAO_DISTRIBUICAO_RESULTADO
        )

        self.assertEqual(len(diff.novas), 1)
        self.assertEqual(len(diff.removidas), 1)

    def test_mudanca_de_result_count_diverge(self):
        esperado = agregados_resultado_sinteticos()
        atual = copy.deepcopy(esperado)
        grupo = distribuicao_resultado(atual, "default")
        grupo["soma_result_count_no_grupo"] = "3.000000"
        grupo["checksum_tecnico_result_count"] = "e" * 32

        diff = diff_de(
            vp.comparar(esperado, atual), vp.COLECAO_DISTRIBUICAO_RESULTADO
        )

        self.assertEqual(len(diff.alteradas), 1)
        self.assertEqual(
            {campo.campo for campo in diff.alteradas[0].campos},
            {
                "soma_result_count_no_grupo",
                "checksum_tecnico_result_count",
            },
        )

    def test_mudanca_de_cost_per_result_diverge(self):
        esperado = agregados_resultado_sinteticos()
        atual = copy.deepcopy(esperado)
        distribuicao_resultado(atual, "default")[
            "checksum_tecnico_cost_per_result"
        ] = "f" * 32

        diff = diff_de(
            vp.comparar(esperado, atual), vp.COLECAO_DISTRIBUICAO_RESULTADO
        )

        self.assertEqual(
            diff.alteradas[0].campos[0].campo,
            "checksum_tecnico_cost_per_result",
        )

    def test_mudanca_de_attribution_window_diverge(self):
        esperado = agregados_resultado_sinteticos()
        atual = copy.deepcopy(esperado)
        distribuicao_resultado(atual, "default")[
            "result_attribution_window"
        ] = "7d_click"

        diff = diff_de(
            vp.comparar(esperado, atual), vp.COLECAO_DISTRIBUICAO_RESULTADO
        )

        self.assertEqual(len(diff.novas), 1)
        self.assertEqual(len(diff.removidas), 1)

    def test_result_inesperado_no_google_diverge(self):
        esperado = agregados_resultado_sinteticos()
        atual = copy.deepcopy(esperado)
        google = cobertura_resultado(atual, "Google Ads", "2026-08-01")
        google.update({
            "linhas_com_result_type": 1,
            "linhas_sem_result_type": 1,
            "linhas_com_result_count": 1,
            "linhas_com_cost_per_result": 1,
        })

        diff = diff_de(
            vp.comparar(esperado, atual), vp.COLECAO_COBERTURA_RESULTADO
        )

        self.assertEqual(len(diff.alteradas), 1)

    def test_result_inesperado_no_meta_historico_diverge(self):
        esperado = agregados_resultado_sinteticos()
        atual = copy.deepcopy(esperado)
        historico = cobertura_resultado(atual, "Meta Ads", "2026-07-15")
        historico.update({
            "linhas_com_result_type": 1,
            "linhas_sem_result_type": 1,
            "linhas_com_result_count": 1,
        })

        diff = diff_de(
            vp.comparar(esperado, atual), vp.COLECAO_COBERTURA_RESULTADO
        )

        self.assertEqual(len(diff.alteradas), 1)

    def test_ordem_das_duas_colecoes_nao_diverge(self):
        esperado = agregados_resultado_sinteticos()
        atual = copy.deepcopy(esperado)
        atual[vp.COLECAO_COBERTURA_RESULTADO].reverse()
        atual[vp.COLECAO_DISTRIBUICAO_RESULTADO].reverse()

        self.assertFalse(vp.comparar(esperado, atual).houve())

    def test_nao_existe_resultados_totais_como_kpi(self):
        dados = agregados_resultado_sinteticos()

        self.assertNotIn("resultados_totais", dados)
        self.assertNotIn("soma_result_count_global", dados)
        for linha in dados[vp.COLECAO_COBERTURA_RESULTADO]:
            self.assertNotIn("soma_result_count_no_grupo", linha)

    def test_janela_null_permanece_null(self):
        dados = agregados_resultado_sinteticos()

        self.assertIsNone(
            distribuicao_resultado(dados, None)[
                "result_attribution_window"
            ]
        )

    def test_snapshot_sintetico_e_deterministico(self):
        primeiro = agregados_resultado_sinteticos()
        segundo = agregados_resultado_sinteticos()

        self.assertEqual(primeiro, segundo)
        self.assertFalse(vp.comparar(primeiro, segundo).houve())


class TestSemDivergencia(unittest.TestCase):
    """O golden comparado consigo mesmo, e com ele embaralhado."""

    def test_golden_igual_a_si_mesmo_nao_diverge(self):
        divergencias = vp.comparar(agregados(), agregados())

        self.assertFalse(divergencias.houve())
        self.assertEqual(divergencias.total, 0)
        self.assertEqual(divergencias.outros, ())

    def test_ordem_diferente_nao_e_diferenca(self):
        # A propriedade obrigatoria: mesmo conteudo, ordem trocada, zero
        # divergencias. E o caso que o `zip` posicional errava.
        atual = agregados()
        atual["por_plataforma_dia"].reverse()
        random.Random(20260817).shuffle(atual["contagens"])

        divergencias = vp.comparar(agregados(), atual)

        self.assertFalse(divergencias.houve())

    def test_todas_as_chaves_contam_como_identicas(self):
        divergencias = vp.comparar(agregados(), agregados())
        diff = diff_de(divergencias, "por_plataforma_dia")

        self.assertEqual(diff.identicas, len(GOLDEN["por_plataforma_dia"]))
        self.assertEqual(diff.novas, ())
        self.assertEqual(diff.removidas, ())
        self.assertEqual(diff.alteradas, ())


class TestChavesNovasERemovidas(unittest.TestCase):
    """Dia que entra, dia que sai — o cenario da proxima reextracao."""

    def test_chave_nova_aparece_como_novo(self):
        atual = agregados()
        nova = copy.deepcopy(item_por_chave(atual, CHAVE_META))
        nova["data"] = CHAVE_NOVA_META[1]
        atual["por_plataforma_dia"].append(nova)

        divergencias = vp.comparar(agregados(), atual)
        diff = diff_de(divergencias, "por_plataforma_dia")

        self.assertTrue(divergencias.houve())
        self.assertEqual(diff.novas, (CHAVE_NOVA_META,))
        self.assertEqual(diff.removidas, ())
        self.assertEqual(diff.alteradas, ())
        self.assertEqual(diff.identicas, len(GOLDEN["por_plataforma_dia"]))

    def test_chave_nova_no_meio_da_lista_nao_desloca_as_demais(self):
        # O bug original: inserir no meio produzia dezenas de diferencas
        # falsas nas posicoes seguintes.
        atual = agregados()
        nova = copy.deepcopy(item_por_chave(atual, CHAVE_META))
        nova["data"] = CHAVE_NOVA_MEIO[1]
        atual["por_plataforma_dia"].insert(1, nova)

        diff = diff_de(vp.comparar(agregados(), atual), "por_plataforma_dia")

        self.assertEqual(len(diff.novas), 1)
        self.assertEqual(diff.alteradas, ())
        self.assertEqual(diff.identicas, len(GOLDEN["por_plataforma_dia"]))

    def test_chave_removida_aparece_como_removido(self):
        atual = agregados()
        atual["por_plataforma_dia"] = [
            linha for linha in atual["por_plataforma_dia"]
            if (linha["plataforma"], linha["data"]) != CHAVE_META
        ]

        diff = diff_de(vp.comparar(agregados(), atual), "por_plataforma_dia")

        self.assertEqual(diff.removidas, (CHAVE_META,))
        self.assertEqual(diff.novas, ())
        self.assertEqual(diff.identicas, len(GOLDEN["por_plataforma_dia"]) - 1)

    def test_novo_removido_e_alterado_ao_mesmo_tempo(self):
        atual = agregados()
        nova = copy.deepcopy(item_por_chave(atual, CHAVE_META))
        nova["data"] = CHAVE_NOVA_META[1]
        atual["por_plataforma_dia"].append(nova)
        atual["por_plataforma_dia"] = [
            linha for linha in atual["por_plataforma_dia"]
            if (linha["plataforma"], linha["data"]) != ("Google Ads", "2026-08-01")
        ]
        item_por_chave(atual, ("Meta Ads", "2026-08-15"))["spend"] = "999.000000"

        diff = diff_de(vp.comparar(agregados(), atual), "por_plataforma_dia")

        self.assertEqual(diff.novas, (CHAVE_NOVA_META,))
        self.assertEqual(diff.removidas, (("Google Ads", "2026-08-01"),))
        self.assertEqual(len(diff.alteradas), 1)
        self.assertEqual(diff.alteradas[0].chave, ("Meta Ads", "2026-08-15"))
        self.assertEqual(diff.divergencias, 3)
        self.assertEqual(diff.identicas, len(GOLDEN["por_plataforma_dia"]) - 2)


class TestMetricasAlteradas(unittest.TestCase):
    """Deriva retroativa: mesma chave, numero diferente."""

    def alterar(self, **valores) -> vp.ItemAlterado:
        """Altera campos de uma chave conhecida e devolve o item alterado.

        Args:
            **valores: Campo e novo valor.

        Returns:
            O `ItemAlterado` correspondente a `CHAVE_META`.
        """
        atual = agregados()
        item_por_chave(atual, CHAVE_META).update(valores)
        diff = diff_de(vp.comparar(agregados(), atual), "por_plataforma_dia")
        self.assertEqual(len(diff.alteradas), 1)
        return diff.alteradas[0]

    def test_uma_metrica_alterada(self):
        golden_spend = item_por_chave(agregados(), CHAVE_META)["spend"]
        alterado = self.alterar(spend="9999.000000")

        self.assertEqual(alterado.chave, CHAVE_META)
        self.assertEqual(len(alterado.campos), 1)
        self.assertEqual(alterado.campos[0].campo, "spend")
        self.assertEqual(alterado.campos[0].golden, golden_spend)
        self.assertEqual(alterado.campos[0].atual, "9999.000000")

    def test_varias_metricas_alteradas_na_mesma_chave(self):
        alterado = self.alterar(
            spend="9999.000000", conversions="1.000000", linhas=7
        )

        self.assertEqual(
            [campo.campo for campo in alterado.campos],
            ["conversions", "linhas", "spend"],
        )

    def test_diferenca_fracionaria_minima_e_divergencia(self):
        # Sem tolerancia numerica: o ultimo decimal conta. Conversao do Google
        # e fracionada de proposito (armadilha nº 5).
        original = item_por_chave(agregados(), CHAVE_META)["conversions"]
        mudado = original[:-1] + ("1" if original[-1] != "1" else "2")
        alterado = self.alterar(conversions=mudado)

        self.assertEqual(alterado.campos[0].campo, "conversions")
        self.assertNotEqual(alterado.campos[0].golden, alterado.campos[0].atual)

    def test_zero_vira_valor_positivo(self):
        item = item_por_chave(agregados(), CHAVE_META)
        self.assertEqual(item["profile_views"], "0.000000")

        alterado = self.alterar(profile_views="5.000000")
        campo = alterado.campos[0]

        self.assertEqual(campo.campo, "profile_views")
        # Delta absoluto sai; percentual nao — nao ha variacao relativa a
        # partir de zero, e a divisao seria por zero.
        self.assertEqual(vp._delta(campo.golden, campo.atual), "+5")

    def test_valor_positivo_vira_zero(self):
        alterado = self.alterar(impressions="0.000000")
        campo = alterado.campos[0]

        self.assertEqual(campo.campo, "impressions")
        self.assertIn("-100%", vp._delta(campo.golden, campo.atual))

    def test_campo_que_some_do_item_e_divergencia(self):
        atual = agregados()
        del item_por_chave(atual, CHAVE_META)["purchases"]

        diff = diff_de(vp.comparar(agregados(), atual), "por_plataforma_dia")

        self.assertEqual(diff.alteradas[0].campos[0].campo, "purchases")
        self.assertIs(diff.alteradas[0].campos[0].atual, vp._AUSENTE)


class TestEstruturasSemChaveNatural(unittest.TestCase):
    """`totais_fato` e `travessia` continuam na comparacao recursiva."""

    def test_diferenca_em_totais_fato_e_detectada(self):
        atual = agregados()
        atual["totais_fato"]["linhas"] = 4163

        divergencias = vp.comparar(agregados(), atual)

        self.assertTrue(divergencias.houve())
        self.assertEqual(len(divergencias.outros), 1)
        self.assertIn("totais_fato.linhas", divergencias.outros[0])

    def test_diferenca_em_travessia_e_detectada(self):
        # Inflacao de join (armadilha nº 3): a travessia devolve mais linhas
        # que o fato. E o angulo que nenhum teste de schema pega.
        atual = agregados()
        atual["travessia"]["via_hierarquia"] = 4500

        divergencias = vp.comparar(agregados(), atual)

        self.assertTrue(divergencias.houve())
        self.assertIn("travessia.via_hierarquia", divergencias.outros[0])

    def test_bloco_novo_no_estado_atual_e_reportado(self):
        atual = agregados()
        atual["bloco_inesperado"] = {"x": 1}

        divergencias = vp.comparar(agregados(), atual)

        self.assertTrue(divergencias.houve())
        self.assertIn("bloco_inesperado", divergencias.outros[0])

    def test_chave_repetida_cai_para_comparacao_posicional(self):
        # Colecao nao indexavel nao pode virar sucesso silencioso: perde o
        # keyed, ganha aviso, e a comparacao posicional continua valendo.
        atual = agregados()
        atual["por_plataforma_dia"].append(
            copy.deepcopy(atual["por_plataforma_dia"][0])
        )

        divergencias = vp.comparar(agregados(), atual)

        self.assertTrue(divergencias.houve())
        nomes_keyed = [diff.nome for diff in divergencias.keyed]
        self.assertNotIn("por_plataforma_dia", nomes_keyed)
        self.assertIn("contagens", nomes_keyed)
        self.assertIn("nao foi possivel indexar", divergencias.outros[0])
        self.assertIn("por_plataforma_dia", divergencias.outros[0])


class TestDimensoesESCD2(unittest.TestCase):
    """`contagens` tem chave natural (`objeto`) e cobre as dimensoes SCD2."""

    def alterar_contagem(self, objeto: str, **valores) -> vp.DiffKeyed:
        """Altera uma linha de `contagens` e devolve o diff do bloco.

        Args:
            objeto: Nome do objeto na contagem.
            **valores: Campos a sobrescrever.

        Returns:
            O `DiffKeyed` de `contagens`.
        """
        atual = agregados()
        for linha in atual["contagens"]:
            if linha["objeto"] == objeto:
                linha.update(valores)
        return diff_de(vp.comparar(agregados(), atual), "contagens")

    def test_versao_scd2_a_mais_e_detectada(self):
        # Linhas > entidades e exatamente a assinatura de uma dimensao
        # versionada; uma versao nova nao pode passar despercebida.
        diff = self.alterar_contagem("gold.dim_campanha", linhas=210)

        self.assertEqual(len(diff.alteradas), 1)
        self.assertEqual(diff.alteradas[0].chave, ("gold.dim_campanha",))
        self.assertEqual(diff.alteradas[0].campos[0].campo, "linhas")

    def test_entidade_a_menos_e_detectada(self):
        diff = self.alterar_contagem("gold.dim_conta", entidades=63)

        self.assertEqual(diff.alteradas[0].campos[0].campo, "entidades")

    def test_dimensao_nova_aparece_como_novo(self):
        atual = agregados()
        atual["contagens"].append(
            {"objeto": "gold.dim_geografia", "linhas": 5, "entidades": 5}
        )

        diff = diff_de(vp.comparar(agregados(), atual), "contagens")

        self.assertEqual(diff.novas, (("gold.dim_geografia",),))


class TestRelatorio(unittest.TestCase):
    """A apresentacao: legivel, deterministica e sem tolerancia escondida."""

    def divergente(self) -> vp.Divergencias:
        """Monta um cenario com nova, alterada e nao-keyed ao mesmo tempo.

        Returns:
            Divergencias calculadas.
        """
        atual = agregados()
        nova = copy.deepcopy(item_por_chave(atual, CHAVE_META))
        nova["data"] = CHAVE_NOVA_META[1]
        atual["por_plataforma_dia"].append(nova)
        item_por_chave(atual, CHAVE_META)["spend"] = "9999.000000"
        atual["totais_fato"]["linhas"] = 4163
        return vp.comparar(agregados(), atual)

    def test_relatorio_traz_chave_campo_valores_e_delta(self):
        texto = "\n".join(vp.formatar(self.divergente()))

        self.assertIn("PARIDADE DIVERGENTE", texto)
        self.assertIn("por_plataforma_dia (chave: plataforma | data)", texto)
        self.assertIn("NOVO:", texto)
        self.assertIn(f"+ {' | '.join(CHAVE_NOVA_META)}", texto)
        self.assertIn("ALTERADO:", texto)
        self.assertIn("~ Meta Ads | 2026-08-16", texto)
        self.assertIn("spend:", texto)
        self.assertIn("golden:", texto)
        self.assertIn("atual:", texto)
        self.assertIn("delta:", texto)
        self.assertIn("totais_fato.linhas", texto)

    def test_relatorio_conta_identicas(self):
        texto = "\n".join(vp.formatar(self.divergente()))

        self.assertIn(f"identicas: {len(GOLDEN['por_plataforma_dia']) - 1}", texto)

    def test_relatorio_e_deterministico_independente_da_ordem(self):
        esperado = agregados()
        atual = agregados()
        item_por_chave(atual, CHAVE_META)["spend"] = "9999.000000"
        nova = copy.deepcopy(item_por_chave(atual, CHAVE_META))
        nova["data"] = CHAVE_NOVA_META[1]
        atual["por_plataforma_dia"].append(nova)

        primeiro = vp.formatar(vp.comparar(esperado, atual))

        for semente in (1, 2, 3):
            embaralhado = copy.deepcopy(atual)
            random.Random(semente).shuffle(embaralhado["por_plataforma_dia"])
            random.Random(semente).shuffle(embaralhado["contagens"])
            embaralhado_esperado = copy.deepcopy(esperado)
            random.Random(semente + 10).shuffle(
                embaralhado_esperado["por_plataforma_dia"]
            )

            self.assertEqual(
                vp.formatar(vp.comparar(embaralhado_esperado, embaralhado)),
                primeiro,
            )

    def test_comparacao_nao_muta_nenhum_dos_lados(self):
        esperado = agregados()
        atual = agregados()
        atual["por_plataforma_dia"].reverse()
        item_por_chave(atual, CHAVE_META)["spend"] = "9999.000000"
        copia_esperado = copy.deepcopy(esperado)
        copia_atual = copy.deepcopy(atual)

        vp.formatar(vp.comparar(esperado, atual))

        self.assertEqual(esperado, copia_esperado)
        self.assertEqual(atual, copia_atual)

    def test_delta_nao_arredonda_a_comparacao(self):
        # O delta e apresentacao. Dois valores que so diferem no sexto decimal
        # continuam divergindo, mesmo que o delta apresentado seja minusculo.
        divergencias = vp.comparar(
            {"totais_fato": {"spend": "1.000000"}},
            {"totais_fato": {"spend": "1.000001"}},
        )

        self.assertTrue(divergencias.houve())
        self.assertEqual(
            vp._delta("1.000000", "1.000001"), "+0.000001 (+<0.01%)"
        )


class TestExitCode(unittest.TestCase):
    """A CLI: 0 quando bate, 1 quando diverge. Sem tocar no banco."""

    def rodar(self, atual: dict) -> int:
        """Executa `verificar` com o banco substituido por um duplo.

        Args:
            atual: Agregados que o coletor devolveria.

        Returns:
            Exit code de `verificar`.
        """
        # O relatorio vai para stdout/stderr; aqui interessa so o exit code.
        with mock.patch.object(vp, "_conectar", mock.MagicMock()), \
                mock.patch.object(vp, "coletar", return_value=atual), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return vp.verificar()

    def test_exit_zero_quando_bate(self):
        self.assertEqual(self.rodar(agregados()), 0)

    def test_exit_zero_com_listas_em_outra_ordem(self):
        atual = agregados()
        atual["por_plataforma_dia"].reverse()

        self.assertEqual(self.rodar(atual), 0)

    def test_exit_um_quando_uma_metrica_muda(self):
        atual = agregados()
        item_por_chave(atual, CHAVE_META)["spend"] = "9999.000000"

        self.assertEqual(self.rodar(atual), 1)

    def test_exit_um_quando_estrutura_sem_chave_muda(self):
        atual = agregados()
        atual["travessia"]["no_fato"] = 1

        self.assertEqual(self.rodar(atual), 1)


if __name__ == "__main__":
    unittest.main()
