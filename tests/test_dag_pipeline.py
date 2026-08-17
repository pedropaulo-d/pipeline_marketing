"""Testes da DAG — grafo e render dos comandos.

Rodam so onde o Airflow esta instalado (a imagem do orquestrador); no
`etl_app` sao pulados, e nao falhos, porque ali o Airflow nao e dependencia.

    docker exec tcc_airflow_scheduler bash -c \\
      "cd /opt/project && python -m unittest discover -s tests -t ."

O que estes testes protegem: a janela renderizada em run agendado E em run
manual (o caso que quebrava antes, com `logical_date` nula), a presenca do
`run_id` nos comandos — sem ele a carga nao consegue provar a origem dos
artefatos — e a forma do grafo.
"""

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.exc import ArgumentError

# Duas — e apenas duas — situacoes significam "aqui nao da para testar a DAG",
# ambas observadas neste projeto:
#
# - `ImportError`: o Airflow nao esta instalado (imagem `etl_app`). A deteccao
#   pergunta por `airflow.sdk`, e nao por `airflow`: rodando da raiz do projeto,
#   o diretorio `airflow/` (dags, Dockerfile, README) vira namespace package e
#   faz `import airflow` funcionar mesmo sem o Airflow instalado.
# - `sqlalchemy.exc.ArgumentError`: dentro de uma TaskInstance do Airflow 3 a
#   conexao com o banco de metadados nao e exposta ao processo (isolamento da
#   Task Execution API), e importar o pacote levanta
#   "Could not parse SQLAlchemy URL from given URL string" ao configurar o ORM.
#
# Qualquer OUTRA excecao no import e problema de verdade — plugin quebrado,
# configuracao invalida, incompatibilidade de versao — e deve estourar a suite
# em vez de virar um "pulado" silencioso. Por isso a captura e estreita, e nao
# `except Exception`. O comportamento esta afirmado em `TestDeteccaoDeAmbiente`.
EXCECOES_DE_AMBIENTE = (ImportError, ArgumentError)


def _importar_airflow() -> None:
    """Importa o SDK do Airflow. Isolado para poder ser substituido em teste."""
    from airflow.sdk import DAG  # noqa: F401


def airflow_disponivel(importar=_importar_airflow) -> bool:
    """Diz se este ambiente consegue carregar a DAG.

    Args:
        importar: Callable que faz o import. Parametrizado para o teste de
            que excecao inesperada NAO e mascarada.

    Returns:
        ``True`` se o Airflow esta importavel aqui, ``False`` nos dois casos
        conhecidos de indisponibilidade.

    Raises:
        Exception: Qualquer falha que nao seja uma das duas conhecidas.
    """
    try:
        importar()
    except EXCECOES_DE_AMBIENTE:
        return False
    return True


TEM_AIRFLOW = airflow_disponivel()

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_DAG = RAIZ / "airflow" / "dags" / "pipeline_marketing_diario.py"


class DagRunFalso:
    """DagRun manual: `run_after` presente, `logical_date` nula."""

    def __init__(self, run_after: datetime, logical_date: datetime | None = None):
        self.run_after = run_after
        self.logical_date = logical_date


def carregar_dag():
    """Importa o modulo da DAG sem depender do DagBag.

    Returns:
        O objeto ``DAG`` declarado no arquivo.
    """
    spec = importlib.util.spec_from_file_location("dag_pipeline", ARQUIVO_DAG)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo.dag


class TestDeteccaoDeAmbiente(unittest.TestCase):
    """A deteccao pula o que nao da para rodar — e so isso.

    Roda em todo ambiente: e justamente o guarda-corpo contra o `except
    Exception` que mascararia bug real de configuracao.
    """

    def test_airflow_ausente_resulta_em_pular(self):
        def sem_airflow():
            raise ImportError("No module named 'airflow.sdk'")

        self.assertFalse(airflow_disponivel(sem_airflow))

    def test_orm_sem_conexao_dentro_da_task_resulta_em_pular(self):
        def dentro_da_task():
            raise ArgumentError("Could not parse SQLAlchemy URL from given URL string")

        self.assertFalse(airflow_disponivel(dentro_da_task))

    def test_excecao_inesperada_nao_e_mascarada(self):
        def plugin_quebrado():
            raise RuntimeError("provider mal configurado")

        with self.assertRaises(RuntimeError):
            airflow_disponivel(plugin_quebrado)

    def test_import_bem_sucedido_resulta_em_rodar(self):
        self.assertTrue(airflow_disponivel(lambda: None))


@unittest.skipUnless(TEM_AIRFLOW, "requer Airflow instalado")
class TestGrafo(unittest.TestCase):

    def setUp(self):
        self.dag = carregar_dag()

    def test_as_quatro_tasks_existem(self):
        self.assertEqual(
            sorted(self.dag.task_dict),
            ["carrega_bronze", "extrai_google", "extrai_meta", "transforma_dbt"],
        )

    def test_extracoes_convergem_na_carga(self):
        for extracao in ("extrai_meta", "extrai_google"):
            with self.subTest(task=extracao):
                self.assertEqual(
                    self.dag.get_task(extracao).downstream_task_ids,
                    {"carrega_bronze"},
                )

    def test_extracoes_sao_paralelas_entre_si(self):
        meta = self.dag.get_task("extrai_meta")

        self.assertNotIn("extrai_google", meta.downstream_task_ids)
        self.assertNotIn("extrai_google", meta.upstream_task_ids)

    def test_dbt_depende_da_carga(self):
        self.assertEqual(
            self.dag.get_task("carrega_bronze").downstream_task_ids,
            {"transforma_dbt"},
        )

    def test_falha_em_uma_extracao_bloqueia_a_carga(self):
        # `all_success` e o que garante que a bronze nao roda com meia
        # execucao — e com um dos JSON sobrado do run anterior.
        self.assertEqual(
            self.dag.get_task("carrega_bronze").trigger_rule, "all_success"
        )

    def test_retry_configurado_em_todas_as_tasks(self):
        for task in self.dag.tasks:
            with self.subTest(task=task.task_id):
                self.assertEqual(task.retries, 2)

    def test_dag_nao_faz_catchup_e_roda_uma_por_vez(self):
        self.assertFalse(self.dag.catchup)
        self.assertEqual(self.dag.max_active_runs, 1)


@unittest.skipUnless(TEM_AIRFLOW, "requer Airflow instalado")
class TestRenderDosComandos(unittest.TestCase):

    def setUp(self):
        self.dag = carregar_dag()
        self.env = self.dag.get_template_env()

    def render(self, task_id: str, dag_run: DagRunFalso, run_id: str) -> str:
        """Renderiza o `bash_command` de uma task com um contexto minimo."""
        comando = self.dag.get_task(task_id).bash_command
        return self.env.from_string(comando).render(dag_run=dag_run, run_id=run_id)

    def test_run_agendado_pede_os_sete_dias_anteriores(self):
        agendado = DagRunFalso(
            run_after=datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc),
            logical_date=datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc),
        )

        comando = self.render("extrai_meta", agendado, "scheduled__2026-08-17")

        self.assertIn("--start-date 2026-08-10", comando)
        self.assertIn("--end-date 2026-08-16", comando)
        self.assertNotIn("2026-08-17", comando.split("--run-id")[0])

    def test_run_manual_sem_logical_date_renderiza(self):
        # Este era o bug: `airflow dags trigger` sem `--logical-date` criava um
        # run com `logical_date = NULL`, `ds` sumia e o render estourava.
        manual = DagRunFalso(
            run_after=datetime(2026, 8, 17, 18, 42, tzinfo=timezone.utc),
            logical_date=None,
        )

        for task_id in ("extrai_meta", "extrai_google", "carrega_bronze"):
            with self.subTest(task=task_id):
                comando = self.render(task_id, manual, "manual__2026-08-17T18:42:00")

                self.assertIn("2026-08-10", comando)
                self.assertIn("2026-08-16", comando)

    def test_as_duas_extracoes_recebem_a_mesma_janela(self):
        run = DagRunFalso(run_after=datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc))

        meta = self.render("extrai_meta", run, "manual__x")
        google = self.render("extrai_google", run, "manual__x")

        def datas(comando: str) -> tuple[str, str]:
            partes = comando.split()
            return (
                partes[partes.index("--start-date") + 1],
                partes[partes.index("--end-date") + 1],
            )

        self.assertEqual(datas(meta), datas(google))

    def test_carga_recebe_a_mesma_janela_das_extracoes(self):
        run = DagRunFalso(run_after=datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc))

        extracao = self.render("extrai_meta", run, "manual__x")
        carga = self.render("carrega_bronze", run, "manual__x")

        self.assertIn("--start-date 2026-08-10", extracao)
        self.assertIn("--start-date 2026-08-10", carga)
        self.assertIn("--end-date 2026-08-16", carga)

    def test_run_id_chega_as_tres_tasks_do_contrato(self):
        run = DagRunFalso(run_after=datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc))
        run_id = "manual__2026-08-17T09:00:00+00:00"

        for task_id in ("extrai_meta", "extrai_google", "carrega_bronze"):
            with self.subTest(task=task_id):
                self.assertIn(run_id, self.render(task_id, run, run_id))

    def test_carga_restringe_as_fontes_do_run(self):
        run = DagRunFalso(run_after=datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc))

        comando = self.render("carrega_bronze", run, "manual__x")

        self.assertIn("--sources meta_ads,google_ads", comando)

    def test_dbt_nao_recebe_datas_nem_chama_api(self):
        run = DagRunFalso(run_after=datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc))

        comando = self.render("transforma_dbt", run, "manual__x")

        self.assertIn("run_dbt", comando)
        self.assertNotIn("--start-date", comando)
        self.assertNotIn("extractors", comando)


if __name__ == "__main__":
    unittest.main()
