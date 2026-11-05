"""
Regulatory Error Monitor: the daily pipeline.

For each day it:
  1. waits until that day's files have arrived
  2. loads them into the raw tables (bad rows go to quarantine)
  3. builds the models and runs every test with dbt
  4. saves the test results, even if a test failed
  5. writes a one-line summary of the day

Safe to rerun: every step can be repeated for the same day and gives the same result.
If a serious test fails, the run is marked failed and stops. A warning is reported
and the run carries on.

The demo data covers 1 to 30 January 2026, so the schedule starts and ends there.
When this is connected to a real feed, remove end_date.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

log = logging.getLogger(__name__)

# Locations. The defaults match the Docker setup; docker-compose.yml sets them explicitly.
PROJECT = os.environ.get("PROJECT_DIR", "/opt/project")
DBT = os.environ.get("DBT_BIN", "dbt")
DBT_TARGET = os.environ.get("DBT_TARGET_PATH", f"{PROJECT}/dbt_project/target")
LANDING = Path(os.environ.get("LANDING_DIR", f"{PROJECT}/data/landing"))
REQUIRED_FILES = ["error_detail.csv", "validation_rule.csv",
                  "file_registry.csv", "transaction_validation.csv"]

FIRST_DAY = datetime(2026, 1, 1)
LAST_DAY = datetime(2026, 1, 30)


def files_arrived(day: str) -> bool:
    """True once all four files for the day are in the landing folder."""
    folder = LANDING / day
    missing = [f for f in REQUIRED_FILES if not (folder / f).exists()]
    if missing:
        log.info("Waiting for %s. Missing: %s", folder, ", ".join(missing))
        return False
    return True


def alert_on_failure(context):
    """Runs when a task fails for good (after its retries). Replace with email or Slack later."""
    ti = context["task_instance"]
    log.error("PIPELINE FAILURE: task '%s' failed for day %s after %s attempt(s). Log: %s",
              ti.task_id, context["ds"], ti.try_number, ti.log_url)


def log_summary(ds: str, **_):
    """Writes one line about the day: how clean it was and how the tests went."""
    import psycopg2

    conn = psycopg2.connect(
        host=os.environ["POSTGRES_HOST"], port=os.environ.get("POSTGRES_PORT", "5432"),
        user=os.environ["POSTGRES_USER"], password=os.environ.get("POSTGRES_PASSWORD", ""),
        dbname=os.environ["POSTGRES_DB"],
    )
    with conn, conn.cursor() as cur:
        cur.execute("SELECT rows_read, rows_loaded, rows_rejected, quality_score_pct "
                    "FROM marts.dq_daily_score WHERE batch_date = %s", (ds,))
        day = cur.fetchone()
        cur.execute("SELECT tests_passed, tests_warned, tests_failed FROM audit.dbt_runs "
                    "ORDER BY recorded_at DESC LIMIT 1")
        tests = cur.fetchone()
    conn.close()
    if day is None:
        raise ValueError(f"No quality score found for {ds}. Did the load run?")
    log.info("SUMMARY %s: read %s rows, loaded %s, rejected %s (quality score %s%%). "
             "Latest dbt run: %s passed, %s warned, %s failed.",
             ds, f"{day[0]:,}", f"{day[1]:,}", f"{day[2]:,}", day[3], *(tests or (0, 0, 0)))


default_args = {
    "owner": "data-engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(minutes=15),
    "on_failure_callback": alert_on_failure,
}

with DAG(
    dag_id="regulatory_error_monitor",
    description="Daily load, build, test and record for the regulatory error warehouse",
    schedule="@daily",
    start_date=FIRST_DAY,
    end_date=LAST_DAY,
    catchup=True,                 # fills in every missed day, one after another
    max_active_runs=1,            # never two days at once: later days rely on earlier ones
    is_paused_upon_creation=True,
    default_args=default_args,
    tags=["regulatory", "dbt"],
    doc_md=__doc__,
) as dag:

    check_files = PythonSensor(
        task_id="check_files_arrived",
        python_callable=files_arrived,
        op_kwargs={"day": "{{ ds }}"},
        poke_interval=60,
        timeout=10 * 60,
        mode="reschedule",        # frees the worker between checks
        retries=0,
    )

    load_batch = BashOperator(
        task_id="load_batch",
        bash_command="python " + PROJECT + "/loader/load_batch.py --date {{ ds }} --dir " + str(LANDING),
        depends_on_past=True,     # yesterday must be loaded first (reference data comes in order)
    )

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=(DBT + " build --project-dir " + PROJECT + "/dbt_project"
                      " --profiles-dir " + PROJECT + "/dbt_project"),
    )

    record_results = BashOperator(
        task_id="record_test_results",
        bash_command="python " + PROJECT + "/loader/record_dbt_results.py --target " + DBT_TARGET,
        trigger_rule="all_done",  # save the results even when dbt reported a failure
    )

    summary = PythonOperator(
        task_id="log_summary",
        python_callable=log_summary,
        trigger_rule="none_failed",   # skipped if dbt failed
    )

    check_files >> load_batch >> dbt_build >> record_results >> summary
    dbt_build >> summary