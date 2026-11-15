#!/usr/bin/env python3
"""
Performance benchmark (phase 9): measures the pipeline at around a million rows, BEFORE and
AFTER the change that made the cleaning step incremental.

  Before: stg_transaction_validation is a view. Every run re-cleans ALL of raw.
  After:  stg_transaction_validation is an incremental table. Every run cleans only recent batches.

It runs in its own database (your normal database name plus "_perf"), so your real data,
Airflow history and dashboard are not touched. The extra database is dropped at the end.
Needs roughly 2 GB of free disk space and about 8 minutes at the default size.

    python3 benchmarks/run_benchmark.py                  # about 1 million rows
    python3 benchmarks/run_benchmark.py --scale 5000     # quick check, about 130,000 rows

Results are printed, saved to benchmarks/results.json, and written to docs/performance.md.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg2  # noqa: E402

from loader.load_batch import load_env_file  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;]*m")
MODEL_LINE = re.compile(r"OK created sql \w+ model (\S+)\s.*? in ([\d.]+)s\]")

DASHBOARD_QUERY = """
    select f.validation_error_key, f.created_at::date, f.error_version_key, f.entity_code, e.entity_name,
           r.rule_code, r.rule_name, r.rule_category, d.error_code, d.error_description,
           d.error_level, d.error_type, f.is_open, f.days_to_clear, f.batch_date
    from marts.fact_validation_error f
    join marts.dim_error d on d.error_version_key = f.error_version_key
    join marts.dim_rule r on r.rule_key = f.rule_key
    join marts.dim_reporting_entity e on e.entity_code = f.entity_code
"""


def say(text=""):
    print(text, flush=True)


def settings():
    load_env_file(ROOT / ".env")
    try:
        return {
            "host": os.environ.get("POSTGRES_HOST", "localhost"),
            "port": os.environ.get("POSTGRES_PORT", "5432"),
            "user": os.environ["POSTGRES_USER"],
            "password": os.environ.get("POSTGRES_PASSWORD", ""),
            "db": os.environ["POSTGRES_DB"],
        }
    except KeyError as missing:
        sys.exit(f"Missing setting {missing}. Check your .env file.")


def connect(cfg, dbname, autocommit=False):
    conn = psycopg2.connect(host=cfg["host"], port=cfg["port"], user=cfg["user"],
                            password=cfg["password"], dbname=dbname)
    conn.autocommit = autocommit
    return conn


def recreate_database(cfg, perf_db):
    admin = connect(cfg, cfg["db"], autocommit=True)
    with admin.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{perf_db}" WITH (FORCE)')
        cur.execute(f'CREATE DATABASE "{perf_db}"')
    admin.close()
    conn = connect(cfg, perf_db, autocommit=True)
    with conn.cursor() as cur:
        for sql_file in sorted((ROOT / "sql" / "init").glob("*.sql")):
            cur.execute(sql_file.read_text())
    conn.close()


def drop_database(cfg, perf_db):
    admin = connect(cfg, cfg["db"], autocommit=True)
    with admin.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{perf_db}" WITH (FORCE)')
    admin.close()


def run(cmd, env):
    started = perf_counter()
    done = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=ROOT)
    seconds = perf_counter() - started
    output = ANSI.sub("", done.stdout + done.stderr)
    if done.returncode != 0:
        say(output[-2500:])
        sys.exit(f"Command failed: {' '.join(cmd)}")
    return seconds, output


def model_times(output):
    return {name: float(sec) for name, sec in MODEL_LINE.findall(output)}


def make_project(variant, workdir):
    """'after' is your real dbt project. 'before' is a copy with the old view swapped back in."""
    if variant == "after":
        return ROOT / "dbt_project"
    target = Path(workdir) / "dbt_project_before"
    shutil.copytree(ROOT / "dbt_project", target,
                    ignore=shutil.ignore_patterns("target", "logs", "dbt_packages", ".user.yml"))
    shutil.copy(ROOT / "benchmarks" / "baseline" / "stg_transaction_validation_view.sql",
                target / "models" / "staging" / "stg_transaction_validation.sql")
    return target


def ensure_data(args, data_dir):
    manifest = data_dir / "_manifest.json"
    if manifest.exists() and not args.regenerate:
        m = json.loads(manifest.read_text())
        if m["scale"] == args.scale and m["days"] == args.days:
            say(f"Using the data already in {data_dir} (scale {args.scale}, {args.days} days).")
            return None, m
    say(f"Generating {args.days} days of data at scale {args.scale} ...")
    seconds, _ = run([sys.executable, str(ROOT / "generator" / "generate.py"), "--days", str(args.days),
                      "--scale", str(args.scale), "--out", str(data_dir)], os.environ.copy())
    return seconds, json.loads(manifest.read_text())


def benchmark_variant(variant, cfg, perf_db, args, data_dir, days, workdir):
    say(f"\n=== {variant.upper()} ===")
    env = {**os.environ, "POSTGRES_HOST": cfg["host"], "POSTGRES_PORT": str(cfg["port"]),
           "POSTGRES_USER": cfg["user"], "POSTGRES_PASSWORD": cfg["password"], "POSTGRES_DB": perf_db,
           "DBT_TARGET_PATH": str(Path(workdir) / f"target_{variant}"),
           "DBT_LOG_PATH": str(Path(workdir) / f"logs_{variant}"),
           "DBT_SEND_ANONYMOUS_USAGE_STATS": "False", "DO_NOT_TRACK": "1"}
    project = make_project(variant, workdir)
    dbt = lambda *a: ["dbt", *a, "--project-dir", str(project), "--profiles-dir", str(project)]  # noqa: E731
    load = lambda day: [sys.executable, str(ROOT / "loader" / "load_batch.py"),  # noqa: E731
                        "--date", day, "--dir", str(data_dir)]

    recreate_database(cfg, perf_db)
    say(f"Loading the first {len(days) - 1} days ...")
    t0 = perf_counter()
    for day in days[:-1]:
        run(load(day), env)
    load_seconds = perf_counter() - t0

    say("First full build ...")
    first_build, _ = run(dbt("run", "--full-refresh"), env)

    say("Incremental runs (a new day arrives, then dbt runs) x3 ...")
    inc_total, inc_fact, inc_stg = [], [], []
    for i in range(3):
        run(load(days[-1]), env)
        seconds, out = run(dbt("run"), env)
        times = model_times(out)
        inc_total.append(seconds)
        inc_fact.append(times.get("marts.fact_validation_error", float("nan")))
        inc_stg.append(times.get("staging.stg_transaction_validation", 0.0))
        say(f"  run {i + 1}: {seconds:.1f}s")
    inc_work = [f + g for f, g in zip(inc_fact, inc_stg)]

    say("Full rebuild of everything ...")
    full_total, full_out = run(dbt("run", "--full-refresh"), env)
    full_fact = model_times(full_out).get("marts.fact_validation_error", float("nan"))

    say("dbt build (models + all tests) ...")
    build_seconds, build_out = run(dbt("build"), env)
    summary = re.search(r"Done\. PASS=(\d+) WARN=(\d+) ERROR=(\d+)", build_out)

    conn = connect(cfg, perf_db)
    with conn.cursor() as cur:
        cur.execute("select count(*) from raw.transaction_validation")
        raw_rows = cur.fetchone()[0]
        cur.execute("select count(*) from marts.fact_validation_error")
        fact_rows = cur.fetchone()[0]
        t0 = perf_counter()
        cur.execute(DASHBOARD_QUERY)
        cur.fetchall()
        dashboard_seconds = perf_counter() - t0
    conn.close()

    med = statistics.median
    return {
        "variant": variant, "load_first_days_s": round(load_seconds, 1),
        "first_build_s": round(first_build, 1),
        "incremental_run_s": round(med(inc_total), 1), "incremental_fact_s": round(med(inc_fact), 1),
        "incremental_staging_s": round(med(inc_stg), 1), "incremental_work_s": round(med(inc_work), 1),
        "full_rebuild_s": round(full_total, 1), "full_rebuild_fact_s": round(full_fact, 1),
        "build_with_tests_s": round(build_seconds, 1),
        "tests": {"pass": int(summary.group(1)), "warn": int(summary.group(2)),
                  "error": int(summary.group(3))} if summary else None,
        "raw_rows": raw_rows, "fact_rows": fact_rows, "dashboard_load_s": round(dashboard_seconds, 1),
    }


def faster(before, after):
    if not before:
        return "n/a"
    change = 100 * (before - after) / before
    return f"{change:.0f}% faster" if change >= 0 else f"{-change:.0f}% slower"


def why_section(b, a):
    gain = (b["incremental_work_s"] - a["incremental_work_s"]) / b["incremental_work_s"] if b["incremental_work_s"] else 0
    if gain >= 0.15:
        return [
            "## Why the first version was slow",
            "",
            "The fact table was already incremental, but it read from a view that recomputed the "
            "latest-row-per-key step over every raw row on every run. The look-back filter came after that "
            "work, so it saved almost nothing. Measuring showed it, and moving the filter to the start of the "
            "cleaning step fixed it.",
            "",
        ]
    return [
        "## What this shows",
        "",
        "At this amount of history the old and new versions do about the same total work in a daily run, "
        "so the daily run is not much faster. What changed is what the cost depends on. The old version "
        "re-cleaned all of raw history every day, so it gets slower as history grows. The new version "
        "cleans only the last few days, so its daily cost stays flat. Run the benchmark with more history "
        "(for example `--days 60`) to see the two versions pull apart.",
        "",
        "The new version has a cost: a full rebuild is slower, because the cleaning step is now a table "
        "that has to be written.",
        "",
    ]


def write_report(path, b, a, meta):
    rows = [
        ("Daily dbt run (new day arrives)", b["incremental_run_s"], a["incremental_run_s"]),
        ("Cleaning and fact table work inside that run", b["incremental_work_s"], a["incremental_work_s"]),
        ("Full rebuild of everything", b["full_rebuild_s"], a["full_rebuild_s"]),
    ]
    lines = [
        "# Performance",
        "",
        f"Measured with about **{a['raw_rows']:,} rows** loaded into raw and **{a['fact_rows']:,} rows** in the "
        f"fact table ({meta['days']} days of data), on {meta['machine']}, with PostgreSQL running in Docker.",
        "Each time is the median of 3 runs where a run adds one new day. Run it yourself with "
        "`python3 benchmarks/run_benchmark.py`.",
        "",
        "## What changed",
        "",
        "- **Before:** the cleaning step (`stg_transaction_validation`) was a view. Every time the fact table "
        "was built, it re-cleaned **all** of the raw data, even though only the last day had changed. "
        "(A view costs nothing by itself, so its work shows up inside the fact table step.)",
        "- **After:** the cleaning step is an incremental table. Each run reads only the last few days of "
        "batches (the same look-back window the fact table uses) and replaces those rows by key.",
        "",
        "## Results",
        "",
        "| Step | Before | After | Change |",
        "|---|---|---|---|",
    ]
    for label, before, after in rows:
        lines.append(f"| {label} | {before:.1f} s | {after:.1f} s | {faster(before, after)} |")
    lines.append(f"| Daily run compared with a full rebuild | {faster(b['full_rebuild_s'], b['incremental_run_s'])} "
                 f"| {faster(a['full_rebuild_s'], a['incremental_run_s'])} | |")
    lines += [
        "",
        f"A normal `dbt build` (all {a['tests']['pass'] if a['tests'] else '?'} models and tests) takes "
        f"{a['build_with_tests_s']:.1f} s. The dashboard loads all {a['fact_rows']:,} rows in "
        f"{a['dashboard_load_s']:.1f} s.",
        "",
    ] + why_section(b, a) + [
        "## Limits",
        "",
        "- The incremental models only look back a few days. If you reload an old day with corrected data, "
        "run `bash run_dbt.sh run --full-refresh` so the change is picked up.",
        "- The dashboard loads the whole fact table into memory and caches it. That is fine at about a million "
        "rows. At 100 times the size it should run its summaries inside the database instead.",
        "- Numbers depend on the machine. Compare the Before and After columns, not the absolute times.",
        "",
    ]
    path.write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description="Benchmark the pipeline before and after the incremental cleaning step.")
    ap.add_argument("--scale", type=int, default=40000, help="rows per weekday (default 40000, about 1 million rows)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--data-dir", default=str(ROOT / "data" / "landing_perf"))
    ap.add_argument("--regenerate", action="store_true", help="make the test data again")
    ap.add_argument("--keep", action="store_true", help="do not drop the extra database at the end")
    args = ap.parse_args()

    cfg = settings()
    perf_db = f"{cfg['db']}_perf"
    data_dir = Path(args.data_dir)
    say(f"Benchmark database: {perf_db} (your real database '{cfg['db']}' is not touched)")

    gen_seconds, manifest = ensure_data(args, data_dir)
    first = date.fromisoformat(manifest["start_date"])
    days = [(first + timedelta(days=i)).isoformat() for i in range(manifest["days"])]

    with tempfile.TemporaryDirectory() as workdir:
        results = {}
        try:
            for variant in ("before", "after"):
                results[variant] = benchmark_variant(variant, cfg, perf_db, args, data_dir, days, workdir)
        finally:
            if not args.keep:
                drop_database(cfg, perf_db)

    b, a = results["before"], results["after"]
    meta = {"days": manifest["days"], "scale": args.scale,
            "machine": f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPU cores",
            "generate_s": None if gen_seconds is None else round(gen_seconds, 1)}
    out_dir = ROOT / "benchmarks"
    (out_dir / "results.json").write_text(json.dumps({"meta": meta, **results}, indent=2) + "\n")
    write_report(ROOT / "docs" / "performance.md", b, a, meta)

    say("\n=== RESULTS ===")
    say(f"Rows: {a['raw_rows']:,} in raw, {a['fact_rows']:,} in the fact table")
    say(f"Days of history: {meta['days']}")
    say(f"{'':<46}{'Before':>9}{'After':>9}   Change")
    for label, key in (("Daily dbt run", "incremental_run_s"),
                       ("Cleaning + fact table work in that run", "incremental_work_s"),
                       ("Full rebuild", "full_rebuild_s")):
        say(f"{label:<46}{b[key]:>8.1f}s{a[key]:>8.1f}s   {faster(b[key], a[key])}")
    say(f"{'Daily run vs a full rebuild':<46}{faster(b['full_rebuild_s'], b['incremental_run_s']):>9}"
        f"{faster(a['full_rebuild_s'], a['incremental_run_s']):>16}")
    say("\nWritten: benchmarks/results.json and docs/performance.md")


if __name__ == "__main__":
    main()