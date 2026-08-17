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
    TIMEZONE,
    datas_da_janela,
    dia_de_referencia,
    janela_extracao,
    janela_fim,
    janela_inicio,
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


if __name__ == "__main__":
    unittest.main()
