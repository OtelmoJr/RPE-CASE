# Case RPE — Pipeline de Dados: Selic Diaria

Pipeline que puxa a taxa Selic diaria do Banco Central, transforma com Pentaho PDI e materializa uma camada analitica com dbt. Orquestrado pelo Airflow, roda inteiro em Docker Compose.

## Contexto

A RPE trabalha com credito ao varejo (Private Label, CDC, BNPL). A Selic impacta diretamente o custo dessas operacoes — entao faz sentido ter um pipeline que monitore e analise essa taxa de forma automatizada.

O pipeline tem 3 camadas:
- **Raw** — dado bruto da API, sem mexer em nada
- **Silver** — dado transformado pelo Pentaho PDI (query analitica + validacao)
- **Gold** — agregacao mensal pelo dbt, pronta pra consumo analitico

---

## Arquitetura

```
  API BCB (Selic serie 11)
         |
         v
  ┌─────────────────────────────────────────────────────────┐
  │                   Apache Airflow (DAG)                  │
  │                                                         │
  │  Task 1 (Python)    Task 2 (Bash)     Task 3 (Bash)    │
  │  GET API BCB        pan.sh PDI        dbt run + test   │
  │  INSERT tab_raw     tab_raw->final    tab_final->gold  │
  └────────┬──────────────────┬──────────────────┬──────────┘
           │                  │                  │
           v                  v                  v
  ┌─────────────────────────────────────────────────────────┐
  │                 DuckDB (selic.duckdb)                   │
  │                                                         │
  │   tab_raw          tab_final          tab_gold_selic_   │
  │   (raw/bronze)     (silver)           analytics (gold)  │
  └─────────────────────────────────────────────────────────┘
```

O PostgreSQL ta la so pro metadata do Airflow (scheduler, DAG runs, etc). Os dados de negocio ficam todos no DuckDB.

---

## Por que DuckDB?

- Arquivo unico, sem servidor, zero config
- Performance analitica absurda pra esse volume de dados
- Compativel com dbt-duckdb e com JDBC (Pentaho consegue ler/gravar)
- Perfeito pra um case tecnico — leve, rapido, sem dependencia externa

## Por que dbt?

- Testes de qualidade declarativos (not_null, unique, accepted_values)
- Documentacao viva do modelo de dados
- Separacao clara de camadas (silver -> gold)
- Mostra maturidade na stack moderna de dados

---

## Transformacao no Pentaho (5 steps, SQL analitico)

A estrategia aqui foi concentrar toda a logica de transformacao numa query SQL analitica dentro do Table Input do Pentaho. O DuckDB tem um motor SQL muito poderoso — POWER, EXTRACT, CASE WHEN, strftime — entao faz mais sentido explorar isso do que espalhar a logica em dezenas de steps visuais. O PDI fica responsavel pelo que ele faz bem: orquestrar leitura, filtrar, validar tipos e gravar.

| # | Step | Tipo PDI | O que faz |
|---|------|----------|-----------|
| 1 | Consulta Analitica | Table Input | Query SQL que ja faz tudo: converte data (strptime/strftime), extrai ano/mes/dia (EXTRACT), calcula taxa anualizada (POWER), classifica (CASE WHEN) e monta descricao |
| 2 | Filtrar Nulos | Filter Rows | Remove registros onde valor_diario veio nulo |
| 3 | Validar Tipos | Select Values | Forca tipos corretos — Number(10,6) pra valor_diario, Integer pra ano/mes/dia |
| 4 | Indicador Constante | Add Constants | Adiciona campo indicador = "SELIC" |
| 5 | Gravar tab_final | Table Output | Trunca e grava na tab_final (10 colunas) |

### Detalhes da Query (Step 1)

A query tem uma subquery interna que faz o trabalho pesado e uma externa que adiciona classificacao e descricao:

```sql
-- Subquery interna
SELECT
  data AS data_original,
  strftime(strptime(data, '%d/%m/%Y'), '%Y-%m-%d') AS data_formatada,
  EXTRACT(YEAR FROM strptime(data, '%d/%m/%Y'))::INTEGER AS ano,
  EXTRACT(MONTH FROM strptime(data, '%d/%m/%Y'))::INTEGER AS mes,
  EXTRACT(DAY FROM strptime(data, '%d/%m/%Y'))::INTEGER AS dia,
  CAST(valor AS DOUBLE) AS valor_diario,
  (POWER(1 + CAST(valor AS DOUBLE)/100, 252) - 1) * 100 AS valor_anualizado
FROM tab_raw
WHERE valor IS NOT NULL AND TRIM(valor) != ''

-- Query externa: classificacao e descricao
CASE WHEN valor_anualizado > 13 THEN 'ALTA'
     WHEN valor_anualizado >= 10 THEN 'MODERADA'
     ELSE 'BAIXA' END
```

### Fluxo no PDI

```
Consulta Analitica --> Filtrar Nulos --> Validar Tipos --> Indicador Constante --> Gravar tab_final
   (Table Input)     (Filter Rows)    (Select Values)      (Add Constants)       (Table Output)
```

Fluxo linear, 5 steps, sem JavaScript e sem scripts customizados. A logica toda fica no SQL — facil de entender, testar e manter.

---

## Camada Gold (dbt)

A `tab_gold_selic_analytics` agrega por mes:

| Campo | O que e |
|-------|---------|
| referencia | Primeiro dia do mes |
| selic_media_diaria | Media da taxa diaria |
| selic_media_anualizada | Media da taxa anualizada |
| selic_min_anualizada | Menor taxa no mes |
| selic_max_anualizada | Maior taxa no mes |
| variacao_mensal | Max - Min (dispersao) |
| dias_uteis_mes | Qtd de dias com cotacao |
| classificacao_predominante | Classificacao mais frequente |
| estabilidade | VOLATIL (var > 0.5pp) ou ESTAVEL |

---

## Requisitos

- Docker (20.10+) e Docker Compose (v2+)
- Porta 8080 livre (Airflow UI) e 5432 (PostgreSQL metadata)

## Como Rodar

```bash
# clonar o repo
git clone https://github.com/OtelmoJr/RPE-CASE.git
cd RPE-CASE

# criar o .env
cp .env.example .env

# subir tudo
docker-compose up -d

# acompanhar os logs se quiser
docker-compose logs -f
```

Espera os containers ficarem healthy:
```bash
docker-compose ps
```

### Executar o Pipeline

1. Abrir http://localhost:8080 (admin / admin)
2. Ativar a DAG `bcb_selic_pipeline`
3. Clicar em Trigger DAG
4. Acompanhar no Graph View — sao 3 tasks sequenciais

### Verificar Resultados

```bash
# entrar no container
docker-compose exec airflow-webserver bash

# checar com python
python3 -c "
import duckdb
conn = duckdb.connect('/opt/airflow/data/selic.duckdb')
print('=== tab_raw ===')
print(conn.execute('SELECT count(*) FROM tab_raw').fetchone())
print('=== tab_final ===')
print(conn.execute('SELECT * FROM tab_final LIMIT 3').fetchdf())
print('=== tab_gold_selic_analytics ===')
print(conn.execute('SELECT * FROM tab_gold_selic_analytics').fetchdf())
conn.close()
"
```

---

## Estrutura do Projeto

```
case_ERP/
├── Dockerfile                    # Airflow + Java + Pentaho PDI + DuckDB + dbt
├── docker-compose.yml            # Containers (PG metadata + Airflow)
├── .env.example                  # Variaveis de ambiente
├── dags/
│   └── dag_bcb_pipeline.py       # DAG com 3 tasks
├── pentaho/
│   └── transform_selic.ktr       # Transformacao PDI (5 steps, SQL analitico)
├── dbt_selic/
│   ├── dbt_project.yml           # Config dbt
│   ├── profiles.yml              # Conexao DuckDB
│   └── models/
│       ├── sources.yml           # tab_final como source + testes
│       └── gold/
│           ├── tab_gold_selic_analytics.sql  # Modelo gold
│           └── schema.yml        # Testes e documentacao
├── sql/
│   └── create_tables.sql         # DDL de referencia (DuckDB)
├── data/                         # DuckDB file (gitignored)
└── docs/
    └── README.md                 # Voce esta aqui
```

## Stack

- **Airflow 2.7.3** — orquestracao
- **Pentaho PDI 7.1** — ETL (steps nativos + SQL analitico, sem JavaScript)
- **DuckDB 1.1.3** — DW analitico (arquivo local, JDBC + Python)
- **dbt-core 1.8 + dbt-duckdb** — camada gold + testes
- **PostgreSQL 15** — apenas metadata do Airflow
- **Docker Compose** — containerizacao
