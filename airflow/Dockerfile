# Airflow, plus dbt in its own virtual environment so dbt's libraries
# cannot clash with Airflow's.
FROM apache/airflow:2.10.5-python3.12

RUN python -m venv /home/airflow/dbt_venv \
    && /home/airflow/dbt_venv/bin/pip install --no-cache-dir \
        "dbt-core>=1.10.5,<1.11" "dbt-postgres>=1.10,<1.11" \
    && mkdir -p /opt/airflow/dbt_work