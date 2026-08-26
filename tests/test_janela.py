"""Testes da janela movel de extracao.

O contrato sob teste: uma execucao do dia D extrai de D-7 ate D-1, no fuso de
Sao Paulo, sem nunca incluir o dia corrente. Cada caso aqui corresponde a um
modo de erro concreto — o mais caro deles foi descoberto em producao-de-mentira
na auditoria de 17/08/2026, quando a janela real se revelou `[D-6, D]`.

Rodar:
    python -m unittest discover -s tests -t .
"""

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from janela import (
    DIAS_DE_JANELA,
    PARAM_FIM,
    PARAM_INICIO,
    TIMEZONE,
    datas_da_janela,
    dia_de_referencia,
    janela_descricao,
    janela_extracao,
    janela_fim,
    janela_inicio,
    janela_informada,
    resolver_janela,
)

SAO_PAULO = ZoneInfo(TIMEZONE)


class DagRunFalso:
    """Minimo que a macro consome de um DagRun: o instante `run_after`.

    Reproduz de proposito o caso do run manual, em que `logical_date` e nula —
    era exatamente essa combinacao que quebrava o template antigo.
    """

    def __init__(self, run_after: datetime, logical_date: datetime | None = None):
        self.run_after = run_after
        self.logical_date = logical_date


class TestJanelaAgendada(unittest.TestCase):
    """Execucao agendada: 06:00 em Sao Paulo."""

    def test_run_normal_extrai_os_sete_dias_completos_anteriores(self):
        disparo = datetime(2026, 8, 17, 6, 0, tzinfo=SAO_PAULO)

        self.assertEqual(
            janela_extracao(disparo), ("2026-08-10", "2026-08-16")
        )

    def test_janela_termina_sempre_no_dia_anterior(self):
        disparo = datetime(2026, 8, 17, 6, 0, tzinfo=SAO_PAULO)

        _, fim = janela_extracao(disparo)

        self.assertEqual(fim, "2026-08-16")

    def test_dia_corrente_nunca_entra(self):
        disparo = datetime(2026, 8, 17, 23, 59, tzinfo=SAO_PAULO)

        self.assertNotIn("2026-08-17", datas_da_janela(disparo))

    def test_sao_exatamente_sete_datas_distintas_e_contiguas(self):
        disparo = datetime(2026, 8, 17, 6, 0, tzinfo=SAO_PAULO)

        datas = datas_da_janela(disparo)

        self.assertEqual(len(datas), DIAS_DE_JANELA)
        self.assertEqual(len(set(datas)), DIAS_DE_JANELA)
        self.assertEqual(
            datas,
            [
                "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13",
                "2026-08-14", "2026-08-15", "2026-08-16",
            ],
        )


class TestViradas(unittest.TestCase):
    """Fronteiras de mes, de ano e de ano bissexto."""

    def test_virada_de_mes(self):
        disparo = datetime(2026, 9, 3, 6, 0, tzinfo=SAO_PAULO)

        self.assertEqual(
            janela_extracao(disparo), ("2026-08-27", "2026-09-02")
        )

    def test_virada_de_ano(self):
        disparo = datetime(2027, 1, 3, 6, 0, tzinfo=SAO_PAULO)

        self.assertEqual(
            janela_extracao(disparo), ("2026-12-27", "2027-01-02")
        )

    def test_primeiro_dia_do_ano_olha_para_dezembro(self):
        disparo = datetime(2027, 1, 1, 6, 0, tzinfo=SAO_PAULO)

        self.assertEqual(
            janela_extracao(disparo), ("2026-12-25", "2026-12-31")
        )

    def test_ano_bissexto(self):
        disparo = datetime(2028, 3, 2, 6, 0, tzinfo=SAO_PAULO)

        self.assertIn("2028-02-29", datas_da_janela(disparo))


class TestTimezone(unittest.TestCase):
    """O dia e o dia civil de Sao Paulo, nao o de UTC."""

    def test_agendamento_das_06h_locais_equivale_a_09h_utc(self):
        local = datetime(2026, 8, 17, 6, 0, tzinfo=SAO_PAULO)
        utc = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)

        self.assertEqual(janela_extracao(local), janela_extracao(utc))

    def test_fim_de_dia_local_ainda_pertence_ao_dia_local(self):
        # 2026-08-18T02:00Z e 2026-08-17T23:00 em Sao Paulo: a janela tem de
        # ser a do dia 17, nao a do 18. Calcular em UTC erraria por um dia.
        instante = datetime(2026, 8, 18, 2, 0, tzinfo=timezone.utc)

        self.assertEqual(dia_de_referencia(instante).isoformat(), "2026-08-17")
        self.assertEqual(
            janela_extracao(instante), ("2026-08-10", "2026-08-16")
        )

    def test_instante_sem_fuso_e_recusado(self):
        with self.assertRaises(ValueError):
            janela_extracao(datetime(2026, 8, 17, 6, 0))


class TestRunManual(unittest.TestCase):
    """`airflow dags trigger` sem `--logical-date` precisa funcionar.

    Antes desta correcao o DagRun manual nascia com `logical_date = NULL`, `ds`
    sumia do contexto e o render estourava
    `TypeError: strptime() argument 1 must be str, not StrictUndefined`.
    """

    def test_macros_funcionam_com_logical_date_nula(self):
        dag_run = DagRunFalso(
            run_after=datetime(2026, 8, 17, 14, 32, tzinfo=timezone.utc),
            logical_date=None,
        )

        self.assertEqual(janela_inicio(dag_run), "2026-08-10")
        self.assertEqual(janela_fim(dag_run), "2026-08-16")

    def test_run_manual_e_agendado_no_mesmo_dia_dao_a_mesma_janela(self):
        manual = DagRunFalso(
            run_after=datetime(2026, 8, 17, 18, 5, tzinfo=timezone.utc)
        )
        agendado = DagRunFalso(
            run_after=datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc),
            logical_date=datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(
            (janela_inicio(manual), janela_fim(manual)),
            (janela_inicio(agendado), janela_fim(agendado)),
        )

    def test_dag_run_sem_run_after_falha_explicitamente(self):
        class SemRunAfter:
            run_after = None

        with self.assertRaises(ValueError):
            janela_inicio(SemRunAfter())


class TestProtecoes(unittest.TestCase):
    """Limites que existem para impedir dano, nao por simetria."""

    def test_janela_nunca_alcanca_2026_04_07_a_partir_de_agosto(self):
        # Reextrair 2026-04-07 achataria as versoes SCD2 do DW. Nenhuma
        # execucao a partir de agosto pode chegar la por aritmetica de janela.
        disparo = datetime(2026, 8, 17, 6, 0, tzinfo=SAO_PAULO)

        self.assertNotIn("2026-04-07", datas_da_janela(disparo))

    def test_janela_de_qualquer_dia_de_agosto_nao_toca_abril(self):
        for dia in range(1, 32):
            disparo = datetime(2026, 8, dia, 6, 0, tzinfo=SAO_PAULO)
            with self.subTest(dia=dia):
                self.assertNotIn("2026-04-07", datas_da_janela(disparo))

    def test_janela_de_zero_dias_e_recusada(self):
        disparo = datetime(2026, 8, 17, 6, 0, tzinfo=SAO_PAULO)

        with self.assertRaises(ValueError):
            janela_extracao(disparo, dias=0)

    def test_janela_e_parametrizavel(self):
        disparo = datetime(2026, 8, 17, 6, 0, tzinfo=SAO_PAULO)

        self.assertEqual(janela_extracao(disparo, dias=1), ("2026-08-16", "2026-08-16"))
        self.assertEqual(len(datas_da_janela(disparo, dias=28)), 28)

    def test_execucoes_consecutivas_cobrem_dias_consecutivos(self):
        hoje = datetime(2026, 8, 17, 6, 0, tzinfo=SAO_PAULO)
        amanha = hoje + timedelta(days=1)

        _, fim_hoje = janela_extracao(hoje)
        _, fim_amanha = janela_extracao(amanha)

        self.assertEqual(fim_hoje, "2026-08-16")
        self.assertEqual(fim_amanha, "2026-08-17")


class TestJanelaInformada(unittest.TestCase):
    """As sete regras do par `data_inicial` / `data_final`.

    Entrada invalida FALHA. Nao existe caminho em que uma data malformada, um
    intervalo invertido ou metade do par sejam corrigidos em silencio: um
    disparo manual so extrai o que foi digitado, ou nao extrai.
    """

    def test_par_vazio_significa_janela_automatica(self):
        self.assertIsNone(janela_informada(None, None))

    def test_campo_em_branco_conta_como_vazio(self):
        # A tela de disparo do Airflow envia string vazia quando o campo nao
        # foi preenchido. Isso e ausencia, nao entrada invalida.
        self.assertIsNone(janela_informada("", ""))
        self.assertIsNone(janela_informada("   ", None))

    def test_par_valido_e_devolvido_como_esta(self):
        self.assertEqual(
            janela_informada("2026-08-12", "2026-08-18"),
            ("2026-08-12", "2026-08-18"),
        )

    def test_inicio_igual_ao_fim_extrai_um_unico_dia(self):
        self.assertEqual(
            janela_informada("2026-08-14", "2026-08-14"),
            ("2026-08-14", "2026-08-14"),
        )

    def test_somente_inicio_falha_citando_o_campo_ausente(self):
        with self.assertRaises(ValueError) as erro:
            janela_informada("2026-08-12", None)

        self.assertIn(PARAM_FIM, str(erro.exception))

    def test_somente_fim_falha_citando_o_campo_ausente(self):
        with self.assertRaises(ValueError) as erro:
            janela_informada(None, "2026-08-18")

        self.assertIn(PARAM_INICIO, str(erro.exception))

    def test_fim_anterior_ao_inicio_falha(self):
        with self.assertRaises(ValueError) as erro:
            janela_informada("2026-08-19", "2026-08-18")

        self.assertIn(PARAM_FIM, str(erro.exception))

    def test_data_fora_do_calendario_falha(self):
        for inicio, fim in (
            ("2026-13-45", "2026-08-18"),
            ("2026-08-12", "2026-02-30"),
        ):
            with self.subTest(inicio=inicio, fim=fim):
                with self.assertRaises(ValueError):
                    janela_informada(inicio, fim)

    def test_grafia_diferente_de_ano_mes_dia_falha(self):
        # `date.fromisoformat` aceitaria as tres no Python 3.11. O contrato
        # publicado na interface e YYYY-MM-DD, e so ele vale.
        for texto in ("20260812", "2026-W33-3", "12/08/2026"):
            with self.subTest(texto=texto):
                with self.assertRaises(ValueError):
                    janela_informada(texto, "2026-08-18")

    def test_intervalo_maior_que_a_janela_padrao_e_aceito(self):
        # Quem digitou a data respondeu pela escolha: a janela manual e
        # substituicao, nao ajuste da automatica.
        self.assertEqual(
            janela_informada("2026-08-01", "2026-08-31"),
            ("2026-08-01", "2026-08-31"),
        )


class TestResolucaoDaJanela(unittest.TestCase):
    """A decisao entre janela automatica e informada, num ponto so."""

    def setUp(self):
        self.run = DagRunFalso(
            run_after=datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)
        )

    def test_sem_params_usa_a_janela_automatica(self):
        self.assertEqual(
            resolver_janela(self.run, None),
            ("2026-08-18", "2026-08-24", False),
        )

    def test_params_vazios_usam_a_janela_automatica(self):
        for params in ({}, {PARAM_INICIO: None, PARAM_FIM: None},
                       {PARAM_INICIO: "", PARAM_FIM: ""}):
            with self.subTest(params=params):
                self.assertEqual(
                    resolver_janela(self.run, params),
                    ("2026-08-18", "2026-08-24", False),
                )

    def test_params_preenchidos_substituem_a_janela(self):
        self.assertEqual(
            resolver_janela(
                self.run,
                {PARAM_INICIO: "2026-08-12", PARAM_FIM: "2026-08-18"},
            ),
            ("2026-08-12", "2026-08-18", True),
        )

    def test_janela_manual_ignora_o_instante_do_disparo(self):
        # Mesmo par de datas, dois instantes de disparo distintos: a janela
        # manual nao depende de quando a DAG foi acionada.
        outro = DagRunFalso(
            run_after=datetime(2027, 3, 4, 21, 0, tzinfo=timezone.utc)
        )
        params = {PARAM_INICIO: "2026-08-12", PARAM_FIM: "2026-08-18"}

        self.assertEqual(
            resolver_janela(self.run, params), resolver_janela(outro, params)
        )

    def test_params_invalidos_falham_na_resolucao(self):
        with self.assertRaises(ValueError):
            resolver_janela(self.run, {PARAM_INICIO: "2026-08-12"})

    def test_macros_seguem_a_resolucao(self):
        params = {PARAM_INICIO: "2026-08-12", PARAM_FIM: "2026-08-18"}

        self.assertEqual(janela_inicio(self.run, params), "2026-08-12")
        self.assertEqual(janela_fim(self.run, params), "2026-08-18")

    def test_macros_sem_params_preservam_a_assinatura_antiga(self):
        # A chamada de um argumento so continua valendo e continua
        # significando janela automatica.
        self.assertEqual(janela_inicio(self.run), "2026-08-18")
        self.assertEqual(janela_fim(self.run), "2026-08-24")

    def test_descricao_declara_a_origem_da_janela(self):
        self.assertEqual(
            janela_descricao(self.run, None),
            "Janela de extração automática: 2026-08-18 a 2026-08-24",
        )
        self.assertEqual(
            janela_descricao(
                self.run,
                {PARAM_INICIO: "2026-08-12", PARAM_FIM: "2026-08-18"},
            ),
            "Janela de extração manual: 2026-08-12 a 2026-08-18",
        )

    def test_descricao_nao_vaza_conteudo_alem_das_datas(self):
        # O log declara a janela, nao os params. Um valor extra no dicionario
        # (um segredo colado por engano no conf, por exemplo) nao aparece.
        texto = janela_descricao(
            self.run,
            {PARAM_INICIO: "2026-08-12", PARAM_FIM: "2026-08-18",
             "token": "nao-deve-vazar"},
        )

        self.assertNotIn("nao-deve-vazar", texto)
        self.assertNotIn("token", texto)


if __name__ == "__main__":
    unittest.main()
