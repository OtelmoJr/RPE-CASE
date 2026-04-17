-- ============================================================
-- Case ERP: Pipeline Airflow + Pentaho PDI
-- Banco Central do Brasil — Taxa Selic (Série 11)
-- ============================================================

-- tab_raw: dados brutos da API BCB, inseridos SEM NENHUMA ALTERAÇÃO
-- Requisito: manter exatamente como veio da origem
CREATE TABLE IF NOT EXISTS tab_raw (
    id         SERIAL       PRIMARY KEY,
    data       VARCHAR(10)  NOT NULL,     -- "dd/mm/yyyy" exatamente como vem da API
    valor      VARCHAR(20),               -- "0.038466" como string, sem conversão
    loaded_at  TIMESTAMP    DEFAULT NOW() -- timestamp de carga
);

-- tab_final: dados transformados pelo Pentaho PDI
-- 7 operações aplicadas: conversão de data, conversão numérica, extração de
-- componentes, anualização, classificação, uppercase e concatenação
CREATE TABLE IF NOT EXISTS tab_final (
    id                SERIAL        PRIMARY KEY,
    data_original     VARCHAR(10),               -- data original da API (preservada)
    data_formatada    DATE,                      -- OP2: data convertida para tipo DATE
    ano               INTEGER,                   -- OP4: ano extraído da data
    mes               INTEGER,                   -- OP4: mês extraído da data
    dia               INTEGER,                   -- OP4: dia extraído da data
    valor_diario      DECIMAL(10,6),             -- OP3: valor convertido para numérico
    valor_anualizado  DECIMAL(10,4),             -- OP5: ((1+r/100)^252 - 1) * 100
    classificacao     VARCHAR(20),               -- OP6: ALTA / MODERADA / BAIXA
    descricao         VARCHAR(100),              -- OP7: "TAXA SELIC - {classificacao}"
    indicador         VARCHAR(50),               -- OP7: "SELIC" (uppercase)
    processed_at      TIMESTAMP    DEFAULT NOW() -- timestamp de processamento
);

-- Índices para consultas analíticas
CREATE INDEX IF NOT EXISTS idx_tab_final_data ON tab_final (data_formatada);
CREATE INDEX IF NOT EXISTS idx_tab_final_classificacao ON tab_final (classificacao);
CREATE INDEX IF NOT EXISTS idx_tab_final_ano_mes ON tab_final (ano, mes);
