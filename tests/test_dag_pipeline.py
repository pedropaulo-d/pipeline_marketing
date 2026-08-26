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

    def render(
        self,
        task_id: str,
        dag_run: DagRunFalso,
        run_id: str,
        params: dict | None = None,
    ) -> str:
        """Renderiza o `bash_command` de uma task com um contexto minimo.

        Args:
            task_id: Task cujo comando sera renderizado.
            dag_run: DagRun falso do contexto.
            run_id: Identificador do run.
            params: Params da execucao. ``None`` reproduz o run agendado, em
                que os dois campos ficam com o default do `Param`.

        Returns:
            O comando com os templates ja substituidos.
        """
        comando = self.dag.get_task(task_id).bash_command
        return self.env.from_string(comando).render(
            dag_run=dag_run, run_id=run_id, params=params or {}
        )

    @staticmethod
    def datas(comando: str) -> tuple[str, str]:
        """Extrai o par `--start-date` / `--end-date` de um comando."""
        partes = comando.split()
        return (
            partes[partes.index("--start-date") + 1],
            partes[partes.index("--end-date") + 1],
        )

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

        self.assertEqual(self.datas(meta), self.datas(google))

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


@unittest.skipUnless(TEM_AIRFLOW, "requer Airflow instalado")
class TestParamsDoDisparoManual(unittest.TestCase):
    """Os dois campos da tela "Trigger DAG": opcionais e tipados."""

    def setUp(self):
        self.dag = carregar_dag()

    def test_a_dag_declara_os_dois_params(self):
        self.assertEqual(
            sorted(self.dag.params), ["data_final", "data_inicial"]
        )

    def test_os_params_sao_opcionais(self):
        # Default nulo e o que faz o run agendado — que nao preenche nada —
        # continuar caindo na janela automatica.
        for nome in ("data_inicial", "data_final"):
            with self.subTest(param=nome):
                self.assertIsNone(self.dag.params[nome])

    def test_o_schema_aceita_texto_e_vazio(self):
        # Sem `null` no type, campo em branco seria recusado pela validacao do
        # proprio Airflow e o caso "deixe vazio" ficaria impossivel.
        for nome in ("data_inicial", "data_final"):
            with self.subTest(param=nome):
                tipo = self.dag.params.get_param(nome).schema["type"]
                self.assertIn("string", tipo)
                self.assertIn("null", tipo)

    def test_os_params_tem_descricao_visivel_na_interface(self):
        for nome in ("data_inicial", "data_final"):
            with self.subTest(param=nome):
                descricao = self.dag.params.get_param(nome).description
                self.assertIn("YYYY-MM-DD", descricao)
                self.assertIn("Opcional", descricao)

    def test_schema_nao_usa_format_date(self):
        # `format: "date"` faria a validacao do Airflow recusar string vazia,
        # que e o que a interface envia num campo em branco. A conferencia de
        # formato e feita em `janela.py`, com mensagem propria.
        for nome in ("data_inicial", "data_final"):
            with self.subTest(param=nome):
                self.assertNotIn(
                    "format", self.dag.params.get_param(nome).schema
                )


@unittest.skipUnless(TEM_AIRFLOW, "requer Airflow instalado")
class TestRenderComJanelaInformada(unittest.TestCase):
    """Disparo manual parametrizado: o intervalo digitado chega as tasks."""

    TASKS_DO_CONTRATO = ("extrai_meta", "extrai_google", "carrega_bronze")

    def setUp(self):
        self.dag = carregar_dag()
        self.env = self.dag.get_template_env()
        self.run = DagRunFalso(
            run_after=datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc),
            logical_date=None,
        )

    def render(self, task_id: str, params: dict | None = None) -> str:
        """Renderiza o `bash_command` de uma task com params opcionais."""
        comando = self.dag.get_task(task_id).bash_command
        return self.env.from_string(comando).render(
            dag_run=self.run, run_id="manual__2026-08-25T09:00:00",
            params=params or {},
        )

    @staticmethod
    def datas(comando: str) -> tuple[str, str]:
        """Extrai o par `--start-date` / `--end-date` de um comando."""
        partes = comando.split()
        return (
            partes[partes.index("--start-date") + 1],
            partes[partes.index("--end-date") + 1],
        )

    def test_manual_sem_params_mantem_a_janela_automatica(self):
        for params in ({}, {"data_inicial": None, "data_final": None},
                       {"data_inicial": "", "data_final": ""}):
            with self.subTest(params=params):
                comando = self.render("extrai_meta", params)

                self.assertEqual(
                    self.datas(comando), ("2026-08-18", "2026-08-24")
                )

    def test_manual_com_datas_usa_exatamente_o_intervalo_pedido(self):
        comando = self.render(
            "extrai_meta",
            {"data_inicial": "2026-08-12", "data_final": "2026-08-18"},
        )

        self.assertEqual(self.datas(comando), ("2026-08-12", "2026-08-18"))

    def test_meta_e_google_recebem_a_mesma_janela_informada(self):
        params = {"data_inicial": "2026-08-12", "data_final": "2026-08-18"}

        meta = self.datas(self.render("extrai_meta", params))
        google = self.datas(self.render("extrai_google", params))

        self.assertEqual(meta, google)
        self.assertEqual(meta, ("2026-08-12", "2026-08-18"))

    def test_a_carga_recebe_a_mesma_janela_informada(self):
        # A carga confere a janela contra o manifesto gravado pela extracao.
        # Se ela nao recebesse o mesmo intervalo, o run manual parametrizado
        # falharia no contrato — e nao ha excecao para run manual.
        params = {"data_inicial": "2026-08-12", "data_final": "2026-08-18"}

        carga = self.datas(self.render("carrega_bronze", params))

        self.assertEqual(carga, ("2026-08-12", "2026-08-18"))
        self.assertIn("--run-id", self.render("carrega_bronze", params))

    def test_as_tres_tasks_do_contrato_concordam(self):
        params = {"data_inicial": "2026-08-12", "data_final": "2026-08-18"}

        janelas = {
            task: self.datas(self.render(task, params))
            for task in self.TASKS_DO_CONTRATO
        }

        self.assertEqual(len(set(janelas.values())), 1)

    def test_um_unico_dia_e_um_intervalo_valido(self):
        comando = self.render(
            "extrai_meta",
            {"data_inicial": "2026-08-14", "data_final": "2026-08-14"},
        )

        self.assertEqual(self.datas(comando), ("2026-08-14", "2026-08-14"))

    def test_params_incoerentes_falham_no_render(self):
        # Falhar no render e falhar a task: nenhuma chamada de API acontece
        # com janela invalida.
        casos = (
            {"data_inicial": "2026-08-12"},
            {"data_final": "2026-08-18"},
            {"data_inicial": "2026-08-19", "data_final": "2026-08-18"},
            {"data_inicial": "12/08/2026", "data_final": "2026-08-18"},
            {"data_inicial": "2026-13-45", "data_final": "2026-08-18"},
        )
        for params in casos:
            for task in self.TASKS_DO_CONTRATO:
                with self.subTest(params=params, task=task):
                    with self.assertRaises(Exception):
                        self.render(task, params)

    def test_o_comando_anuncia_a_janela_no_inicio(self):
        automatico = self.render("extrai_meta")
        manual = self.render(
            "extrai_meta",
            {"data_inicial": "2026-08-12", "data_final": "2026-08-18"},
        )

        self.assertIn(
            "Janela de extração automática: 2026-08-18 a 2026-08-24",
            automatico,
        )
        self.assertIn(
            "Janela de extração manual: 2026-08-12 a 2026-08-18", manual
        )
        # O anuncio vem antes de qualquer coisa que chame API.
        self.assertLess(manual.index("echo"), manual.index("python -m"))

    def test_dbt_continua_sem_datas_mesmo_com_params(self):
        comando = self.render(
            "transforma_dbt",
            {"data_inicial": "2026-08-12", "data_final": "2026-08-18"},
        )

        self.assertNotIn("--start-date", comando)
        self.assertNotIn("2026-08-12", comando)


if __name__ == "__main__":
    unittest.main()
