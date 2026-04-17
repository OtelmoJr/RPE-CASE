"""
DAG: bcb_selic_pipeline
Pipeline de ingestao e transformacao da taxa Selic diaria (BCB serie 11).

Task 1 (Python)  — extrai da API do BCB e carrega bruto em tab_raw (DuckDB).
Task 2 (Bash)    — chama o Pentaho PDI (pan.sh) que le tab_raw, transforma e grava tab_final.
Task 3 (Bash)    — roda dbt pra materializar a camada gold e executar testes de qualidade.
"""

import logging
import os
from datetime import datetime, timedelta

import duckdb
import requests
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — num projeto real eu usaria Airflow Variables ou Vault.
# Pra esse case, hardcoded mesmo pra simplificar a avaliacao.
# ---------------------------------------------------------------------------
BCB_API_URL = (
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados"
    "?formato=json&dataInicial={data_inicial}&dataFinal={data_final}"
)

DUCKDB_PATH = os.environ.get("DUCKDB_PATH", "/opt/airflow/data/selic.duckdb")

PENTAHO_CMD = (
    "/opt/pentaho/data-integration/pan.sh "
    "-file=/opt/pentaho/transform_selic.ktr "
    "-level=Basic"
)

DBT_CMD = "cd /opt/airflow/dbt_selic && dbt run --profiles-dir . && dbt test --profiles-dir ."

# ---------------------------------------------------------------------------
# DDL — garante que as tabelas existem antes de qualquer operacao
# ---------------------------------------------------------------------------
DDL_TAB_RAW = """
CREATE TABLE IF NOT EXISTS tab_raw (
    data       VARCHAR    NOT NULL,
    valor      VARCHAR,
    loaded_at  TIMESTAMP  DEFAULT current_timestamp
)
"""

DDL_TAB_FINAL = """
CREATE TABLE IF NOT EXISTS tab_final (
    data_original     VARCHAR,
    data_formatada    DATE,
    ano               INTEGER,
    mes               INTEGER,
    dia               INTEGER,
    valor_diario      DOUBLE,
    valor_anualizado  DOUBLE,
    classificacao     VARCHAR,
    descricao         VARCHAR,
    indicador         VARCHAR,
    processed_at      TIMESTAMP  DEFAULT current_timestamp
)
"""


# ---------------------------------------------------------------------------
# Task 1: Extrair dados da API BCB e carregar em tab_raw (DuckDB)
# ---------------------------------------------------------------------------
def extract_and_load_raw(**context):
    """
    Puxa a Selic diaria (serie 11) do BCB e joga em tab_raw sem mexer em nada.
    Idempotencia: deleta registros do periodo antes de inserir, assim re-execucoes
    nao duplicam dados e tambem nao apagam historico de outros periodos.
    """
    data_final = datetime.now()
    data_inicial = data_final - timedelta(days=365)

    data_ini_str = data_inicial.strftime("%d/%m/%Y")
    data_fim_str = data_final.strftime("%d/%m/%Y")

    url = BCB_API_URL.format(data_inicial=data_ini_str, data_final=data_fim_str)
    logger.info("Chamando API BCB: %s", url)

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    dados = response.json()
    if not dados:
        raise ValueError("API BCB retornou lista vazia — verificar periodo.")

    logger.info("API retornou %d registros.", len(dados))

    conn = duckdb.connect(DUCKDB_PATH)
    try:
        conn.execute(DDL_TAB_RAW)
        conn.execute(DDL_TAB_FINAL)

        # Idempotencia: limpa so o range que vamos reinserir
        conn.execute(
            "DELETE FROM tab_raw WHERE data IN (SELECT UNNEST($1::VARCHAR[]))",
            [[item["data"] for item in dados]],
        )

        # Dados brutos, sem alteracao nenhuma — requisito do edital
        conn.executemany(
            "INSERT INTO tab_raw (data, valor) VALUES ($1, $2)",
            [(item["data"], item["valor"]) for item in dados],
        )

        count = conn.execute("SELECT count(*) FROM tab_raw").fetchone()[0]
        logger.info("tab_raw agora tem %d registros no total.", count)
    finally:
        conn.close()

    return len(dados)


# ---------------------------------------------------------------------------
# DAG
# ---------------------------------------------------------------------------
default_args = {
    "owner": "rpe",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="bcb_selic_pipeline",
    default_args=default_args,
    description="BCB Selic: API -> DuckDB(raw) -> Pentaho(final) -> dbt(gold)",
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["bcb", "selic", "rpe"],
) as dag:

    task_extract = PythonOperator(
        task_id="extract_and_load_raw",
        python_callable=extract_and_load_raw,
    )

    task_pentaho = BashOperator(
        task_id="run_pentaho_transform",
        bash_command=PENTAHO_CMD,
    )

    task_dbt = BashOperator(
        task_id="run_dbt",
        bash_command=DBT_CMD,
    )

    task_extract >> task_pentaho >> task_dbt
