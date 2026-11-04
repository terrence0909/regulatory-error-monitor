#!/usr/bin/env python3
"""
Loader (phase 4): reads the daily files and loads them into the raw tables.

For each day it:
  1. checks every row, and sends bad rows to quarantine.rejected_rows with a reason
  2. loads the good rows into the raw tables using COPY (fast)
  3. writes one line per file into audit.load_log

Safe to rerun: each day is one database transaction. It first removes anything
that same day loaded before, then loads again. Run the same day twice and the
database ends up exactly the same. If anything fails, nothing is half-loaded.

Examples
    python3 loader/load_batch.py --date 2026-01-01
    python3 loader/load_batch.py --all
    python3 loader/load_batch.py --all --reset     # empty the tables first

Connection settings come from the .env file (or from environment variables).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402
from psycopg2.extras import execute_values  # noqa: E402

from generator.generate import (  # noqa: E402
    ERROR_DETAIL_COLS, FILE_COLS, RULE_COLS, TRANSACTION_COLS,
)
from loader import validators as v  # noqa: E402

RAW_TABLES = ["error_detail", "validation_rule", "file_registry", "transaction_validation"]


def load_env_file(path: Path):
    """Read KEY=VALUE lines from .env. Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def connect():
    load_env_file(ROOT / ".env")
    try:
        return psycopg2.connect(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=os.environ.get("POSTGRES_PORT", "5432"),
            user=os.environ["POSTGRES_USER"],
            password=os.environ.get("POSTGRES_PASSWORD", ""),
            dbname=os.environ["POSTGRES_DB"],
        )
    except KeyError as missing:
        sys.exit(f"Missing setting {missing}. Check your .env file.")
    except psycopg2.OperationalError as err:
        sys.exit(
            f"Could not connect to the database:\n  {err}\n"
            "Is Docker running? Try: docker compose up -d postgres\n"
            "Also check POSTGRES_PORT in your .env file."
        )


def read_rows(path: Path, expected_cols):
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != list(expected_cols):
            sys.exit(f"{path} does not have the expected columns.")
        return list(reader)


def copy_rows(cur, table: str, cols, rows, batch_id: str):
    if not rows:
        return
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for r in rows:
        writer.writerow([r[c] for c in cols] + [batch_id])
    buf.seek(0)
    col_list = ", ".join(list(cols) + ["batch_id"])
    cur.copy_expert(f"COPY raw.{table} ({col_list}) FROM STDIN WITH (FORMAT csv)", buf)


def quarantine(cur, batch_id: str, table: str, rejected):
    if not rejected:
        return
    execute_values(
        cur,
        "INSERT INTO quarantine.rejected_rows (batch_id, table_name, row_as_text, reason) VALUES %s",
        [(batch_id, table, json.dumps(row), reason) for row, reason in rejected],
    )


def log_load(cur, batch_id, source_file, read, loaded, rejected, seconds):
    cur.execute(
        """INSERT INTO audit.load_log
           (batch_id, source_file, rows_read, rows_loaded, rows_rejected, seconds_taken)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (batch_id, source_file, read, loaded, rejected, round(seconds, 3)),
    )


def load_table(cur, folder: Path, batch_id: str, table: str, cols, check, ctx=None):
    """Check, quarantine, copy and log one file. Returns (read, loaded, rejected)."""
    started = perf_counter()
    rows = read_rows(folder / f"{table}.csv", cols)
    good, bad = [], []
    for row in rows:
        reason = check(row, ctx, cols)
        if reason is None:
            good.append(row)
        else:
            bad.append((row, reason))
    quarantine(cur, batch_id, table, bad)
    copy_rows(cur, table, cols, good, batch_id)
    seconds = perf_counter() - started
    log_load(cur, batch_id, f"{folder.name}/{table}.csv", len(rows), len(good), len(bad), seconds)
    return len(rows), len(good), len(bad), seconds


def fetch_keys(cur, column: str, table: str):
    cur.execute(f"SELECT DISTINCT {column} FROM raw.{table} WHERE {column} IS NOT NULL")
    return {row[0] for row in cur.fetchall()}


def load_day(conn, folder: Path, batch_date: date):
    batch_id = f"batch_{batch_date.isoformat()}"
    with conn:  # one transaction: commit on success, roll back on any error
        with conn.cursor() as cur:
            # Rerun safety: remove anything this batch loaded before.
            for t in RAW_TABLES:
                cur.execute(f"DELETE FROM raw.{t} WHERE batch_id = %s", (batch_id,))
            cur.execute("DELETE FROM quarantine.rejected_rows WHERE batch_id = %s", (batch_id,))
            cur.execute("DELETE FROM audit.load_log WHERE batch_id = %s", (batch_id,))

            summary = {}
            # Reference tables first, because transactions point at them.
            summary["error_detail"] = load_table(
                cur, folder, batch_id, "error_detail", ERROR_DETAIL_COLS,
                lambda row, ctx, cols: v.check_error_detail(row))
            summary["validation_rule"] = load_table(
                cur, folder, batch_id, "validation_rule", RULE_COLS,
                lambda row, ctx, cols: v.check_rule(row))
            summary["file_registry"] = load_table(
                cur, folder, batch_id, "file_registry", FILE_COLS,
                lambda row, ctx, cols: v.check_file(row))

            ctx = v.BatchContext(
                batch_date,
                error_keys=fetch_keys(cur, "error_detail_skey", "error_detail"),
                rule_keys=fetch_keys(cur, "rule_skey", "validation_rule"),
                file_keys=fetch_keys(cur, "file_skey", "file_registry"),
            )
            summary["transaction_validation"] = load_table(
                cur, folder, batch_id, "transaction_validation", TRANSACTION_COLS,
                v.check_transaction, ctx=ctx)
    return summary


def reset_tables(conn):
    with conn, conn.cursor() as cur:
        cur.execute("TRUNCATE raw.error_detail, raw.validation_rule, raw.file_registry, "
                    "raw.transaction_validation")
        cur.execute("TRUNCATE quarantine.rejected_rows, audit.load_log RESTART IDENTITY")
    print("All raw, quarantine and audit tables emptied.")


def main():
    ap = argparse.ArgumentParser(description="Load daily files into the raw tables.")
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--date", help="load one day, YYYY-MM-DD")
    which.add_argument("--all", action="store_true", help="load every day found, in date order")
    ap.add_argument("--dir", default=str(ROOT / "data" / "landing"), help="folder with the daily folders")
    ap.add_argument("--reset", action="store_true", help="empty raw, quarantine and audit tables first")
    a = ap.parse_args()

    root = Path(a.dir)
    folders = sorted(d for d in root.glob("*") if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name))
    if a.date:
        folders = [d for d in folders if d.name == a.date]
    if not folders:
        sys.exit(f"No daily folders found in {root}. Run: python3 generator/generate.py")

    conn = connect()
    if a.reset:
        reset_tables(conn)

    if a.date:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM raw.error_detail")
            if cur.fetchone()[0] == 0 and a.date != sorted(
                    d.name for d in root.glob("*") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name))[0]:
                print("Warning: nothing has been loaded yet. Load the earlier days first "
                      "(use --all), or most rows will be rejected.")
        conn.rollback()

    t0 = perf_counter()
    totals = [0, 0, 0]
    for folder in folders:
        summary = load_day(conn, folder, date.fromisoformat(folder.name))
        tx = summary["transaction_validation"]
        totals[0] += tx[0]; totals[1] += tx[1]; totals[2] += tx[2]
        print(f"{folder.name}  transactions: read {tx[0]:>6,}  loaded {tx[1]:>6,}  "
              f"rejected {tx[2]:>4,}  ({tx[3]:.1f}s)")
    print(f"\nFinished {len(folders)} day(s) in {perf_counter() - t0:.1f}s. "
          f"Transactions: read {totals[0]:,}, loaded {totals[1]:,}, rejected {totals[2]:,}.")
    conn.close()


if __name__ == "__main__":
    main()