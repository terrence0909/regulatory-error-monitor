#!/usr/bin/env python3
"""
Makes ONE deliberately bad day of data, so you can prove the quality checks work.

It takes the newest rows from your generated data, gives them new keys, moves them to
the day after the last day, and breaks a share of them in six known ways. It writes the
result to its own folder (data/landing_bad), so your normal data is not touched.

    python3 generator/make_bad_day.py
    python3 loader/load_batch.py --date 2026-01-31 --dir data/landing_bad

It prints how many rows it broke, per problem. After loading, the quarantine table
must show exactly those numbers, and the quality score for that day must drop.

Options
    --src        folder with the normal generated days   (default data/landing)
    --out        where the bad day is written            (default data/landing_bad)
    --bad-share  share of rows to break                  (default 0.30)
    --seed       random seed                             (default 99)
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.generate import (  # noqa: E402
    ERROR_DETAIL_COLS, FILE_COLS, RULE_COLS, TRANSACTION_COLS, write_csv,
)

KINDS = ["null_error_key", "null_row_key", "orphan_error_key",
         "future_created_date", "processed_before_created", "duplicate_row"]
NEW_KEY_BASE = 10_000_000


def read(path: Path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "data" / "landing"))
    ap.add_argument("--out", default=str(ROOT / "data" / "landing_bad"))
    ap.add_argument("--bad-share", type=float, default=0.30)
    ap.add_argument("--seed", type=int, default=99)
    a = ap.parse_args()

    src, out = Path(a.src), Path(a.out)
    days = sorted(d for d in src.iterdir() if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name))
    if not days:
        sys.exit(f"No daily folders in {src}. Run python3 generator/generate.py first.")
    last = days[-1]
    bad_day = date.fromisoformat(last.name) + timedelta(days=1)

    # Start from clean rows only: new rows of the last day that are not "cleared" updates,
    # not already broken, and not repeats of another row.
    valid_error_keys = {r["error_detail_skey"] for d in days for r in read(d / "error_detail.csv")}
    rows, seen_keys = [], set()
    for r in read(last / "transaction_validation.csv"):
        key = r["transaction_val_skey"]
        if (key and key not in seen_keys and r["error_detail_skey_fk"] in valid_error_keys
                and r["created_date"].startswith(last.name) and not r["processed_date"]):
            seen_keys.add(key)
            rows.append(r)
    if len(rows) < 100:
        sys.exit("Not enough rows in the last day to build a bad day.")

    file_keys = [int(r["file_skey"]) for d in days for r in read(d / "file_registry.csv")]
    new_file_key = max(file_keys) + 1
    file_name = f"FIN_{bad_day:%Y%m%d}_01.xml"

    rng = random.Random(a.seed)
    good = []
    for i, r in enumerate(rows, start=1):
        row = dict(r)
        row["transaction_val_skey"] = NEW_KEY_BASE + i
        row["transaction_error_id"] = f"TE-{NEW_KEY_BASE + i:09d}"
        row["created_date"] = row["last_update_date"] = row["updated_date"] = (
            bad_day.isoformat() + r["created_date"][10:])
        row["report_reference_number"] = r["report_reference_number"].rsplit("-", 2)[0] + f"-{bad_day:%Y%m%d}-" + \
            r["report_reference_number"].rsplit("-", 1)[1]
        row["file_skey_fk"] = new_file_key
        row["original_file_reference"] = file_name
        row["sequence_number"] = i
        good.append(row)

    # Break a share of rows, spread evenly over the six problems.
    victims = rng.sample(range(len(good)), int(len(good) * a.bad_share))
    counts = {k: 0 for k in KINDS}
    extra = []
    for n, idx in enumerate(victims):
        kind = KINDS[n % len(KINDS)]
        row = good[idx]
        counts[kind] += 1
        if kind == "null_error_key":
            row["error_detail_skey_fk"] = ""
        elif kind == "null_row_key":
            row["transaction_val_skey"] = ""
        elif kind == "orphan_error_key":
            row["error_detail_skey_fk"] = 99999
        elif kind == "future_created_date":
            created = datetime.strptime(row["created_date"], "%Y-%m-%d %H:%M:%S") + timedelta(days=30)
            row["created_date"] = row["last_update_date"] = row["updated_date"] = created.strftime("%Y-%m-%d %H:%M:%S")
        elif kind == "processed_before_created":
            early = datetime.strptime(row["created_date"], "%Y-%m-%d %H:%M:%S") - timedelta(days=2)
            row["error_status"], row["transaction_status"] = "Cleared", "Reported"
            row["processed_date"] = early.date().isoformat()
            row["processed_date_time"] = early.strftime("%Y-%m-%d %H:%M:%S")
        elif kind == "duplicate_row":
            extra.append(dict(row))

    day_dir = out / bad_day.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    write_csv(day_dir / "error_detail.csv", ERROR_DETAIL_COLS, [])
    write_csv(day_dir / "validation_rule.csv", RULE_COLS, [])
    write_csv(day_dir / "file_registry.csv", FILE_COLS, [{
        "file_skey": new_file_key, "file_name": file_name,
        "received_at": f"{bad_day.isoformat()} 21:00:00", "row_count": len(good)}])
    write_csv(day_dir / "transaction_validation.csv", TRANSACTION_COLS, good + extra)
    (out / "_bad_manifest.json").write_text(json.dumps({
        "bad_day": bad_day.isoformat(), "rows_in_file": len(good) + len(extra),
        "rows_broken": counts}, indent=2) + "\n")

    total_rejected = sum(counts.values())
    print(f"Wrote a bad day for {bad_day} to {day_dir}")
    print(f"  Rows in the file:  {len(good) + len(extra):,}")
    print(f"  Rows broken:       {total_rejected:,}  ({100 * total_rejected / (len(good) + len(extra)):.1f}% of the file)")
    for kind, n in counts.items():
        print(f"    {kind:<26}{n:>5}")
    print(f"\nNow load it:\n  python3 loader/load_batch.py --date {bad_day.isoformat()} --dir {out}")


if __name__ == "__main__":
    main()