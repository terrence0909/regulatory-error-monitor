#!/usr/bin/env python3
"""
Empties everything the pipeline has loaded, so it can start again from day one.

It empties the raw tables, the quarantine table, the load log and the saved dbt test
results. It does NOT touch your generated files in data/landing, and it does not drop
any table.

After running it, rebuild the (now empty) dbt tables:
    bash run_dbt.sh run --full-refresh

Use this before the first Airflow run, or any time you want a clean slate.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loader.load_batch import connect  # noqa: E402


def main():
    conn = connect()
    with conn, conn.cursor() as cur:
        cur.execute("TRUNCATE raw.error_detail, raw.validation_rule, raw.file_registry, "
                    "raw.transaction_validation")
        cur.execute("TRUNCATE quarantine.rejected_rows, audit.load_log RESTART IDENTITY")
        cur.execute("SELECT to_regclass('audit.dbt_runs')")
        if cur.fetchone()[0] is not None:
            cur.execute("TRUNCATE audit.dbt_runs CASCADE")
    conn.close()
    print("Raw, quarantine, load log and dbt test history are now empty.")
    print("Next: bash run_dbt.sh run --full-refresh")


if __name__ == "__main__":
    main()
