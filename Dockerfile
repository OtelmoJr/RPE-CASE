FROM apache/airflow:2.7.3

USER root

# Install Java JRE 11 (required for Pentaho PDI pan.sh)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openjdk-11-jre-headless \
        procps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

USER airflow

# Install Python dependencies
RUN pip install --no-cache-dir \
    psycopg2-binary \
    requests
