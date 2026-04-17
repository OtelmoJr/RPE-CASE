# Case ERP: Pipeline Airflow + Pentaho PDI

Pipeline de dados que ingere a **taxa Selic diária** (série 11) da API do Banco Central do Brasil, carrega os dados brutos em `tab_raw` (PostgreSQL) e executa uma transformação Pentaho PDI com **7 operações** que grava o resultado em `tab_final`. Tudo orquestrado pelo Apache Airflow e containerizado com Docker Compose.

## Por que a Selic?

A **RPE** atua como fintech de pagamentos para o varejo, oferecendo soluções de **Private Label**, **CDC (Crédito Direto ao Consumidor)** e **BNPL (Buy Now, Pay Later)**. A taxa Selic é o principal driver de custo dessas operações de crédito — monitorá-la e analisá-la é fundamental para precificação, gestão de risco e estratégia comercial.

---

## Arquitetura do Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Apache Airflow (DAG)                        │
│                                                                     │
│  ┌──────────────────────┐       ┌────────────────────────────────┐  │
│  │   Task 1 (Python)    │       │     Task 2 (Bash)              │  │
│  │                      │       │                                │  │
│  │  API BCB (Selic)     │──────▶│  pan.sh transform_selic.ktr    │  │
│  │  GET série 11        │       │                                │  │
│  │  INSERT → tab_raw    │       │  Pentaho PDI                   │  │
│  └──────────────────────┘       │  tab_raw → 7 ops → tab_final   │  │
│                                 └────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                          ┌─────────▼──────────┐
                          │   PostgreSQL 15     │
                          │                     │
                          │  tab_raw  (bruto)   │
                          │  tab_final (final)  │
                          └─────────────────────┘
```

### Fluxo Obrigatório

1. **Tarefa Airflow (Python):** `Extrair API BCB` → `Carregar tab_raw`
2. **Tarefa Airflow (Bash):** `Chamar pan.sh` (Pentaho PDI)
3. **Processo Pentaho:** `Ler tab_raw` → `7 Transformações` → `Gravar tab_final`

---

## Transformações Aplicadas (Pentaho PDI)

| # | Operação | Tipo (Step PDI) | Entrada | Saída |
|---|----------|-----------------|---------|-------|
| 1 | **Filtro de nulos** | Filter Rows | `valor` | Remove registros com valor vazio/nulo |
| 2 | **Conversão de data** | Select Values (metadata) | `data` (string "dd/MM/yyyy") | `data_formatada` (DATE) |
| 3 | **Conversão numérica** | Select Values (metadata) | `valor` (string) | `valor_diario` (DECIMAL 10,6) |
| 4 | **Extração de componentes** | Calculator | `data_formatada` | `ano`, `mes`, `dia` (INTEGER) |
| 5 | **Anualização da Selic** | Modified JavaScript | `valor_diario` | `valor_anualizado` = ((1+r/100)^252 -1)×100 |
| 6 | **Classificação condicional** | Modified JavaScript | `valor_anualizado` | `classificacao`: ALTA (>13%), MODERADA (10-13%), BAIXA (<10%) |
| 7 | **Uppercase + concatenação** | Modified JavaScript | — | `indicador` = "SELIC", `descricao` = "TAXA SELIC - {classificação}" |

---

## Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) (20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2+)
- [Pentaho Data Integration 9.4](https://sourceforge.net/projects/pentaho/files/Pentaho-9.4/) — extrair em `./pentaho/data-integration/`

## Como Executar

### 1. Configurar ambiente

```bash
# Clonar/acessar o repositório
cd case_ERP

# Criar .env a partir do exemplo
cp .env.example .env

# Baixar e extrair o Pentaho PDI (se ainda não tiver)
# Extrair o conteúdo de pdi-ce-9.4.0.0-343.zip em ./pentaho/data-integration/
```

### 2. Subir os containers

```bash
docker-compose up -d
```

Aguarde até que todos os serviços estejam healthy:

```bash
docker-compose ps
```

### 3. Acessar o Airflow

- URL: http://localhost:8080
- Usuário: `admin`
- Senha: `admin`

### 4. Executar o pipeline

1. Na interface do Airflow, localize a DAG `bcb_selic_pipeline`
2. Ative a DAG (toggle ON)
3. Clique em **Trigger DAG** (botão play)
4. Acompanhe a execução no Graph View

### 5. Verificar resultados

```bash
# Conectar ao PostgreSQL
docker-compose exec postgres psql -U erp_user -d erp_case

# Verificar dados brutos
SELECT COUNT(*) FROM tab_raw;
SELECT * FROM tab_raw LIMIT 5;

# Verificar dados transformados
SELECT COUNT(*) FROM tab_final;
SELECT * FROM tab_final LIMIT 10;

# Verificar distribuição de classificações
SELECT classificacao, COUNT(*) as qtd,
       ROUND(AVG(valor_anualizado), 2) as media_anualizada
FROM tab_final
GROUP BY classificacao
ORDER BY media_anualizada DESC;
```

---

## Estrutura do Projeto

```
case_ERP/
├── CLAUDE.md                 # Plano detalhado do projeto
├── .gitignore                # Regras de ignore
├── docker-compose.yml        # Orquestração de containers
├── Dockerfile                # Imagem Airflow customizada (+ Java JRE)
├── .env.example              # Template de variáveis de ambiente
├── dags/
│   └── dag_bcb_pipeline.py   # DAG Airflow — 2 tasks
├── pentaho/
│   └── transform_selic.ktr   # Transformação PDI (7 operações)
├── sql/
│   └── create_tables.sql     # DDL: tab_raw + tab_final
└── docs/
    └── README.md             # Esta documentação
```

## Estrutura das Tabelas

### `tab_raw` — Dados Brutos (sem alteração)

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | SERIAL PK | Identificador auto-incremento |
| `data` | VARCHAR(10) | Data no formato "dd/mm/yyyy" (exatamente como vem da API) |
| `valor` | VARCHAR(20) | Valor da taxa Selic como string (sem conversão) |
| `loaded_at` | TIMESTAMP | Timestamp de carga |

### `tab_final` — Dados Transformados

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | SERIAL PK | Identificador auto-incremento |
| `data_original` | VARCHAR(10) | Data original preservada |
| `data_formatada` | DATE | Data convertida para tipo DATE |
| `ano` | INTEGER | Ano extraído |
| `mes` | INTEGER | Mês extraído |
| `dia` | INTEGER | Dia extraído |
| `valor_diario` | DECIMAL(10,6) | Taxa Selic diária (numérico) |
| `valor_anualizado` | DECIMAL(10,4) | Taxa anualizada: ((1+r/100)^252 -1)×100 |
| `classificacao` | VARCHAR(20) | ALTA / MODERADA / BAIXA |
| `descricao` | VARCHAR(100) | "TAXA SELIC - {classificação}" |
| `indicador` | VARCHAR(50) | "SELIC" (uppercase) |
| `processed_at` | TIMESTAMP | Timestamp de processamento |

---

## Troubleshooting

| Problema | Solução |
|----------|---------|
| Airflow não inicia | Verificar se PostgreSQL está healthy: `docker-compose ps` |
| Erro na API BCB | Verificar conectividade; API tem limite de 10 anos por consulta |
| Pentaho falha | Verificar se Java está instalado: `docker-compose exec airflow-webserver java -version` |
| pan.sh permission denied | Executar: `chmod +x ./pentaho/data-integration/pan.sh` |
| Tabelas não existem | Verificar se SQL init rodou: `docker-compose logs postgres` |

---

## Tecnologias

- **Apache Airflow 2.7.3** — Orquestração de pipeline
- **Pentaho Data Integration 9.4** — ETL e transformação de dados
- **PostgreSQL 15** — Banco de dados relacional
- **Docker / Docker Compose** — Containerização
- **Python 3.11** — Scripts de ingestão
- **API BCB SGS** — Fonte de dados (série 11 — Selic diária)

---

*Case técnico desenvolvido para a RPE — fintech de pagamentos para o varejo.*
