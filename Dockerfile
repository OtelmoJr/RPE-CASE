# Stage 1: Pentaho PDI binaries
FROM andrespp/pdi:latest AS pdi-source

# Stage 2: Airflow + Java + PDI + DuckDB + dbt
FROM apache/airflow:2.7.3

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openjdk-11-jre-headless \
        procps \
        curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

COPY --from=pdi-source /data-integration /opt/pentaho/data-integration
RUN chmod +x /opt/pentaho/data-integration/*.sh

# DuckDB JDBC driver pro Pentaho conseguir ler/gravar no DuckDB
ARG DUCKDB_VERSION=1.1.3
RUN curl -fSL \
    "https://repo1.maven.org/maven2/org/duckdb/duckdb_jdbc/${DUCKDB_VERSION}/duckdb_jdbc-${DUCKDB_VERSION}.jar" \
    -o /opt/pentaho/data-integration/lib/duckdb_jdbc.jar

ENV PENTAHO_HOME=/opt/pentaho/data-integration

# Diretório do DuckDB precisa existir antes do Airflow iniciar
RUN mkdir -p /opt/airflow/data && chown airflow:root /opt/airflow/data

USER airflow

RUN pip install --no-cache-dir \
    psycopg2-binary \
    requests \
    duckdb==1.1.3 \
    "jinja2>=3.1.2,<3.2" \
    "MarkupSafe>=2.1,<2.2" \
    dbt-core==1.8.* \
    dbt-duckdb==1.8.*
