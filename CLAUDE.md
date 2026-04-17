# CLAUDE.md — Case ERP: Pipeline Airflow + Pentaho PDI

## Contexto do Projeto

Case técnico para a **RPE** (fintech de pagamentos para o varejo — Private Label, CDC/BNPL, processamento de cartões).
Pipeline de dados que ingere a taxa Selic diária da API do Banco Central em `tab_raw` (PostgreSQL)
e dispara uma transformação Pentaho PDI com 7 operações, gravando o resultado em `tab_final`.
Tudo containerizado com Docker Compose.

## Dados Técnicos

- **API**: Banco Central do Brasil — SGS série 11 (Selic diária)
  - Endpoint: `https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados?formato=json&dataInicial=DD/MM/YYYY&dataFinal=DD/MM/YYYY`
  - Response: `[{"data": "dd/mm/yyyy", "valor": "0.038466"}, ...]`
  - Limite: consultas de séries diárias limitadas a 10 anos
- **Banco**: PostgreSQL 15 via Docker Compose, database `erp_case`
- **Orquestração**: Apache Airflow 2.7.3 (imagem oficial Docker)
- **Transformação**: Pentaho PDI 9.4 (pan.sh), arquivo .ktr (XML)

---

## Estrutura de Arquivos

```
case_ERP/
├── CLAUDE.md                             # Este arquivo — plano e contexto do projeto
├── .gitignore                            # Python, Docker, logs, __pycache__, .env
├── docker-compose.yml                    # Infraestrutura containerizada
├── Dockerfile                            # Imagem Airflow customizada com Java + PDI
├── .env.example                          # Exemplo de variáveis de ambiente
├── dags/
│   └── dag_bcb_pipeline.py               # DAG Airflow com 2 tasks
├── pentaho/
│   └── transform_selic.ktr               # Transformação PDI (XML)
├── sql/
│   └── create_tables.sql                 # DDL tab_raw + tab_final
└── docs/
    └── README.md                         # Documentação do processo
```

---

## Git Strategy

```
main                       ← versão final, recebe merge de dev ao final
  └─ dev                   ← integração, recebe merge de feature
      └─ feature/pipeline  ← todo o desenvolvimento acontece aqui
```

### Fluxo
1. `git init` + `.gitignore` + commit inicial na `main`
2. `git checkout -b dev` a partir de `main`
3. `git checkout -b feature/pipeline` a partir de `dev`
4. Commits descritivos por fase na `feature/pipeline`
5. Ao concluir: merge `feature/pipeline` → `dev`, depois `dev` → `main`
6. Repositório apenas local (sem remote)

### Convenção de Commits
- `feat: add docker-compose infrastructure`
- `feat: add SQL schema for tab_raw and tab_final`
- `feat: add airflow DAG for BCB Selic ingestion`
- `feat: add pentaho transformation for Selic data`
- `docs: add project documentation`

---

## Phase 0: Git Setup

**Step 0 — Inicializar repositório**
- `git init` na pasta `case_ERP`
- Criar `.gitignore` com regras para Python, Docker, Airflow, IDE, OS
- Commit inicial na `main`
- Criar `dev` → criar `feature/pipeline`

---

## Phase 1: Infraestrutura (Docker Compose)

### Step 1 — `docker-compose.yml` + `Dockerfile`

**Services:**

| Service | Imagem | Porta | Função |
|---------|--------|-------|--------|
| `postgres` | `postgres:15` | 5432 | Banco de dados com tab_raw e tab_final |
| `airflow-webserver` | Custom (Dockerfile) | 8080 | Interface web do Airflow |
| `airflow-scheduler` | Custom (Dockerfile) | — | Scheduler para executar DAGs |
| `airflow-init` | Custom (Dockerfile) | — | Init container (airflow db init + user admin) |

**Dockerfile customizado:**
- Base: `apache/airflow:2.7.3`
- Instala Java JRE 11 (necessário para Pentaho)
- Instala `psycopg2-binary` e `requests` via pip
- Pentaho PDI montado via volume

**Volumes:**
- `./dags:/opt/airflow/dags`
- `./pentaho:/opt/pentaho`
- `./sql:/docker-entrypoint-initdb.d/`
- `./logs:/opt/airflow/logs`

**Rede:** `erp_network` para comunicação entre containers

**Variáveis (.env):**
- `POSTGRES_USER=erp_user`
- `POSTGRES_PASSWORD=erp_pass`
- `POSTGRES_DB=erp_case`
- `AIRFLOW__CORE__EXECUTOR=LocalExecutor`
- `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://erp_user:erp_pass@postgres:5432/erp_case`

### Step 2 — `sql/create_tables.sql`

```sql
-- tab_raw: dados brutos da API BCB, sem nenhuma alteração
CREATE TABLE IF NOT EXISTS tab_raw (
    id SERIAL PRIMARY KEY,
    data VARCHAR(10) NOT NULL,
    valor VARCHAR(20),
    loaded_at TIMESTAMP DEFAULT NOW()
);

-- tab_final: dados transformados pelo Pentaho PDI
CREATE TABLE IF NOT EXISTS tab_final (
    id SERIAL PRIMARY KEY,
    data_original VARCHAR(10),
    data_formatada DATE,
    ano INTEGER,
    mes INTEGER,
    dia INTEGER,
    valor_diario DECIMAL(10,6),
    valor_anualizado DECIMAL(10,4),
    classificacao VARCHAR(20),
    descricao VARCHAR(100),
    indicador VARCHAR(50),
    processed_at TIMESTAMP DEFAULT NOW()
);
```

---

## Phase 2: DAG Airflow

### Step 3 — `dags/dag_bcb_pipeline.py`

**Config:**
- `dag_id = 'bcb_selic_pipeline'`
- `schedule_interval = None` (trigger manual)
- `start_date = datetime(2024, 1, 1)`, `catchup = False`
- `tags = ['bcb', 'selic', 'erp']`

**Task 1 — `extract_and_load_raw` (PythonOperator)**
1. Calcula `dataInicial` (12 meses atrás) e `dataFinal` (hoje) no formato DD/MM/YYYY
2. GET request para API BCB série 11
3. Valida response (status 200, lista não-vazia)
4. Conecta ao PostgreSQL via `psycopg2`
5. `TRUNCATE TABLE tab_raw` (idempotência)
6. `INSERT INTO tab_raw (data, valor) VALUES (%s, %s)` em batch
7. Log: quantidade de registros inseridos

**Task 2 — `run_pentaho_transform` (BashOperator)**
- `bash_command='/opt/pentaho/data-integration/pan.sh -file=/opt/pentaho/transform_selic.ktr -level=Basic'`

**Flow:** `extract_and_load_raw >> run_pentaho_transform`

---

## Phase 3: Transformação Pentaho PDI

### Step 4 — `pentaho/transform_selic.ktr`

Sequência de steps no Pentaho:

```
[Table Input] → [Filter Rows] → [Select Values] → [Calculator] → [Modified JavaScript] → [Table Output]
```

**7 operações de transformação:**

| # | Operação | Tipo | Campo de Saída |
|---|----------|------|----------------|
| 1 | Filtro de nulos | Filter Rows | Remove registros com valor vazio/nulo |
| 2 | Conversão de data | Select Values (metadata) | `data_formatada` (DATE) |
| 3 | Conversão numérica | Select Values (metadata) | `valor_diario` (DECIMAL) |
| 4 | Extração de componentes de data | Calculator | `ano`, `mes`, `dia` |
| 5 | Cálculo: anualização da Selic | Modified JavaScript | `valor_anualizado = ((1+r/100)^252 -1)*100` |
| 6 | Classificação condicional | Modified JavaScript | `classificacao`: ALTA (>13%), MODERADA (10-13%), BAIXA (<10%) |
| 7 | Uppercase + concatenação | Modified JavaScript | `indicador = "SELIC"`, `descricao = "TAXA SELIC - " + classificacao` |

**Conexão JDBC:**
```xml
<connection>
  <name>erp_postgres</name>
  <server>postgres</server>
  <type>POSTGRESQL</type>
  <database>erp_case</database>
  <port>5432</port>
  <username>erp_user</username>
  <password>erp_pass</password>
</connection>
```

**Table Output:**
- Tabela: `tab_final`
- Truncate antes do insert (idempotência)
- Mapeamento: `data_original`, `data_formatada`, `ano`, `mes`, `dia`, `valor_diario`, `valor_anualizado`, `classificacao`, `descricao`, `indicador`

---

## Phase 4: Documentação

### Step 5 — `docs/README.md`

- Título e descrição
- Diagrama do pipeline (ASCII art / Mermaid)
- Pré-requisitos (Docker, Docker Compose)
- Instruções de execução
- Descrição das 7 transformações
- Justificativa: Selic relevante para RPE (impacta CDC/BNPL)
- Estrutura de tabelas
- Troubleshooting

---

## Verificação Final

1. `docker-compose up -d` → todos os containers healthy
2. Acessar Airflow UI em `http://localhost:8080` (admin/admin)
3. Trigger manual da DAG `bcb_selic_pipeline`
4. Task 1 (verde) → `SELECT COUNT(*) FROM tab_raw` → ~250 registros
5. Task 2 (verde) → `SELECT * FROM tab_final LIMIT 10` → dados transformados
6. Validações:
   - `data_formatada` é DATE válido
   - `valor_anualizado` com cálculo correto
   - `classificacao` na faixa correta
   - `indicador` = "SELIC" (uppercase)
   - `descricao` = "TAXA SELIC - {classificacao}"

---

## Decisões e Premissas

| Decisão | Justificativa |
|---------|---------------|
| API BCB Selic (série 11) | Relevante para RPE — Selic impacta crédito ao varejo (CDC/BNPL) |
| PostgreSQL 15 | Natural em Docker, suportado por Airflow e Pentaho nativamente |
| TRUNCATE + INSERT | Idempotência — re-execuções seguras sem duplicatas |
| .ktr como XML | Gerado sem GUI Spoon, versionável com Git |
| 7 operações no Pentaho | Demonstra profundidade técnica nível sênior |
| Docker Compose | Reprodutível, profissional, fácil de avaliar |
| Período 12 meses | ~250 registros — volume adequado sem exceder limites da API |
| Dockerfile customizado | Airflow + Java JRE necessário para rodar Pentaho pan.sh |

## Fora de Escopo
- Testes unitários
- CI/CD
- Monitoramento / alertas
- Autenticação avançada do Airflow
- Múltiplas séries temporais
