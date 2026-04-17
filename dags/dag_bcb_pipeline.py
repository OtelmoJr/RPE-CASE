"""
DAG: bcb_selic_pipeline
=======================
Pipeline de ingestão e transformação da taxa Selic diária (BCB série 11).

Fase 1 (PythonOperator): Extrai dados da API do Banco Central e carrega em tab_raw.
Fase 2 (BashOperator):   Executa transformação Pentaho PDI (pan.sh) que lê tab_raw,
                          aplica 7 operações de transformação e grava em tab_final.

Case técnico para RPE — fintech de pagamentos para o varejo.
"""

import json
import logging
from datetime import datetime, timedelta

import psycopg2
import requests
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------
BCB_API_URL = (
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados"
    "?formato=json&dataInicial={data_inicial}&dataFinal={data_final}"
)

PG_CONN_PARAMS = {
    "host": "postgres",
    "port": 5432,
    "dbname": "erp_case",
    "user": "erp_user",
    "password": "erp_pass",
}

PENTAHO_CMD = (
    "/opt/pentaho/data-integration/pan.sh "
    "-file=/opt/pentaho/transform_selic.ktr "
    "-level=Basic"
)

# ---------------------------------------------------------------------------
# Task 1: Extrair dados da API BCB e carregar em tab_raw
# ---------------------------------------------------------------------------
def extract_and_load_raw(**context):
    """
    Extrai a taxa Selic diária (série 11) da API do Banco Central do Brasil
    e insere os dados SEM NENHUMA ALTERAÇÃO em tab_raw (PostgreSQL).
    """
    # Calcula período: últimos 12 meses
    data_final = datetime.now()
    data_inicial = data_final - timedelta(days=365)

    url = BCB_API_URL.format(
        data_inicial=data_inicial.strftime("%d/%m/%Y"),
        data_final=data_final.strftime("%d/%m/%Y"),
    )

    logger.info("Chamando API BCB: %s", url)

    # --- Extração ---
    response = requests.get(url, timeout=60)
    response.raise_for_status()

    dados = response.json()

    if not dados:
        raise ValueError("API BCB retornou lista vazia. Verifique o período.")

    logger.info("API retornou %d registros.", len(dados))

    # --- Carga em tab_raw ---
    conn = psycopg2.connect(**PG_CONN_PARAMS)
    try:
        with conn.cursor() as cur:
            # Idempotência: limpa tabela antes de recarregar
            cur.execute("TRUNCATE TABLE tab_raw;")

            # Insert em batch — dados SEM alteração (requisito)
            insert_sql = "INSERT INTO tab_raw (data, valor) VALUES (%s, %s)"
            registros = [(item["data"], item["valor"]) for item in dados]

            cur.executemany(insert_sql, registros)

            conn.commit()
            logger.info(
                "Carga concluída: %d registros inseridos em tab_raw.", len(registros)
            )
    finally:
        conn.close()

    return len(registros)


# ---------------------------------------------------------------------------
# DAG Definition
# ---------------------------------------------------------------------------
default_args = {
    "owner": "rpe",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    "email_on_failure": False,
    "email_on_retry": False,
}

with DAG(
    dag_id="bcb_selic_pipeline",
    default_args=default_args,
    description="Pipeline BCB Selic: API → tab_raw → Pentaho PDI → tab_final",
    schedule_interval=None,  # Trigger manual
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["bcb", "selic", "erp", "rpe"],
) as dag:

    # Task 1: Python — Extração e carga raw
    task_extract_load = PythonOperator(
        task_id="extract_and_load_raw",
        python_callable=extract_and_load_raw,
        provide_context=True,
    )

    # Task 2: Bash — Execução do Pentaho PDI
    task_pentaho = BashOperator(
        task_id="run_pentaho_transform",
        bash_command=PENTAHO_CMD,
    )

    # Dependência: primeiro extrai, depois transforma
    task_extract_load >> task_pentaho
