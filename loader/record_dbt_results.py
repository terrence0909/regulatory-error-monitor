#!/usr/bin/env python3
"""
Saves the results of the last dbt run into the database (phase 6).

dbt writes a file called run_results.json every time it runs. This script reads it,
works out which model each test belongs to, and stores one row per test in
audit.test_results, plus one summary row per run in audit.dbt_runs.

Run it straight after dbt:
    bash run_dbt.sh build
    python3 loader/record_dbt_results.py

Or use run_build.sh, which does both and keeps dbt's exit code.
Recording the same run twice does nothing the second time.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loader.load_batch import connect  # noqa: E402

DDL_FILE = ROOT / "sql" / "init" / "04_audit_dbt_results.sql"


def parse_time(text):
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)


def describe_node(node: dict):
    """Which model and column a test belongs to, and whether it is generic or singular."""
    attached = node.get("attached_node") or ""
    if not attached:
        deps = (node.get("depends_on") or {}).get("nodes") or []
        attached = next((d for d in deps if d.startswith("model.")), "")
    model = attached.split(".")[-1] if attached else None
    kind = "generic" if node.get("test_metadata") else "singular"
    return model, node.get("column_name"), kind


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=str(ROOT / "dbt_project" / "target"),
                    help="folder holding run_results.json and manifest.json")
    target = Path(ap.parse_args().target)

    results_file, manifest_file = target / "run_results.json", target / "manifest.json"
    if not results_file.exists() or not manifest_file.exists():
        sys.exit(f"Could not find run_results.json and manifest.json in {target}.\n"
                 "Run dbt first, for example: bash run_dbt.sh build")

    run = json.loads(results_file.read_text())
    nodes = json.loads(manifest_file.read_text())["nodes"]
    run_id = run["metadata"]["invocation_id"]

    results = run["results"]
    tests = [r for r in results if r["unique_id"].startswith("test.")]
    models = [r for r in results if r["unique_id"].startswith("model.")]
    status = Counter(r["status"] for r in tests)
    model_status = Counter(r["status"] for r in models)

    conn = connect()
    with conn, conn.cursor() as cur:
        cur.execute(DDL_FILE.read_text())
        cur.execute("SELECT 1 FROM audit.dbt_runs WHERE run_id = %s", (run_id,))
        if cur.fetchone():
            print("This dbt run was already recorded. Nothing to do.")
            return

        cur.execute(
            """INSERT INTO audit.dbt_runs
               (run_id, command, started_at, elapsed_seconds, tests_total, tests_passed,
                tests_warned, tests_failed, tests_skipped, models_succeeded, models_failed)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (run_id, (run.get("args") or {}).get("which", "unknown"),
             parse_time(run["metadata"].get("generated_at")), round(run.get("elapsed_time", 0), 3),
             len(tests), status["pass"], status["warn"], status["fail"] + status["error"],
             status["skipped"], model_status["success"], model_status["error"]),
        )
        for r in tests:
            node = nodes.get(r["unique_id"], {})
            model, column, kind = describe_node(node)
            severity = str((node.get("config") or {}).get("severity", "error")).lower()
            cur.execute(
                """INSERT INTO audit.test_results
                   (run_id, test_name, test_kind, model_name, column_name, severity,
                    status, failing_rows, seconds_taken, message)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (run_id, node.get("name", r["unique_id"].split(".")[2]), kind, model, column,
                 severity, r["status"], r.get("failures"),
                 round(r.get("execution_time") or 0, 3), r.get("message")),
            )

    print(f"Recorded dbt run {run_id[:8]}: {len(tests)} tests "
          f"({status['pass']} passed, {status['warn']} warned, "
          f"{status['fail'] + status['error']} failed, {status['skipped']} skipped).")
    for r in tests:
        if r["status"] in ("warn", "fail", "error"):
            name = nodes.get(r["unique_id"], {}).get("name", r["unique_id"])
            print(f"  {r['status'].upper():<5} {name}  ({r.get('failures')} rows)")
    conn.close()


if __name__ == "__main__":
    main()