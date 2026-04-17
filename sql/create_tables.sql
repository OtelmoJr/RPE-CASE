-- ============================================================
-- Case RPE: Pipeline Airflow + Pentaho PDI + dbt
-- DuckDB — esquema de referência (DDL real é criada pela DAG)
-- ============================================================

-- tab_raw: dados brutos da API BCB, inseridos SEM NENHUMA ALTERAÇÃO
CREATE TABLE IF NOT EXISTS tab_raw (
    data       VARCHAR    NOT NULL,   -- "dd/mm/yyyy" exatamente como vem da API
    valor      VARCHAR,               -- "0.038466" como string, sem conversão
    loaded_at  TIMESTAMP  DEFAULT current_timestamp
);

-- tab_final: dados transformados pelo Pentaho PDI (7 operações)
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
);
