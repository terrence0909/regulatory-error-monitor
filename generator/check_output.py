#!/usr/bin/env python3
"""
Checks the generated files without touching the database.

It re-discovers the planted problems from the CSV files alone and compares
them with the manifest the generator wrote. It also checks that every row
links to the error version that was active on the day the row was created.
If everything passes, the generator is doing what it claims.

Usage
    python3 generator/check_output.py                 # checks data/landing
    python3 generator/check_output.py --dir /tmp/x    # checks another folder

Uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

FAR_FUTURE = date(9999, 12, 31)
results = []


def check(name: str, ok: bool, detail: str = ""):
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name + (f"   ({detail})" if detail else ""))


def read(path: Path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/landing")
    root = Path(ap.parse_args().dir)
    manifest_path = root / "_manifest.json"
    if not manifest_path.exists():
        sys.exit(f"No manifest in {root}. Run generator/generate.py first.")
    manifest = json.loads(manifest_path.read_text())
    day_dirs = sorted(d for d in root.iterdir() if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name))

    check("one folder per day", len(day_dirs) == manifest["days"], f"{len(day_dirs)} folders")

    # Latest version of every error_detail row wins (changed rows are sent again).
    versions, rule_keys, file_keys, file_claimed = {}, set(), set(), 0
    for d in day_dirs:
        for r in read(d / "error_detail.csv"):
            versions[int(r["error_detail_skey"])] = r
        for r in read(d / "validation_rule.csv"):
            rule_keys.add(int(r["rule_skey"]))
        for r in read(d / "file_registry.csv"):
            file_keys.add(int(r["file_skey"]))
            file_claimed += int(r["row_count"])

    found = Counter()
    total_rows = pit_checked = pit_bad = bad_rule = bad_file = 0
    new_rows = update_rows = 0
    for d in day_dirs:
        folder_date = date.fromisoformat(d.name)
        seen = set()
        seen_keys = set()
        for r in read(d / "transaction_validation.csv"):
            total_rows += 1
            fingerprint = tuple(r.values())
            if fingerprint in seen:
                found["duplicate_row"] += 1
                continue
            seen.add(fingerprint)

            skey, fk = r["transaction_val_skey"], r["error_detail_skey_fk"]
            created = date.fromisoformat(r["created_date"][:10])
            is_problem = True
            if skey == "":
                found["null_row_key"] += 1
            elif fk == "":
                found["null_error_key"] += 1
            elif int(fk) not in versions:
                found["orphan_error_key"] += 1
            elif created > folder_date:
                found["future_created_date"] += 1
            elif r["processed_date"] and date.fromisoformat(r["processed_date"]) < created:
                found["processed_before_created"] += 1
            else:
                is_problem = False

            if skey != "":
                if skey in seen_keys:
                    update_rows += 1
                else:
                    seen_keys.add(skey)
                    new_rows += 1

            if not is_problem:
                v = versions[int(fk)]
                start = date.fromisoformat(v["active_date"])
                end = date.fromisoformat(v["inactive_date"]) if v["inactive_date"] else FAR_FUTURE
                pit_checked += 1
                if not (start <= created <= end):
                    pit_bad += 1
            if r["rule_skey_fk"] and int(r["rule_skey_fk"]) not in rule_keys:
                bad_rule += 1
            if r["file_skey_fk"] and int(r["file_skey_fk"]) not in file_keys:
                bad_file += 1

    check("total rows match the manifest", total_rows == manifest["rows_written"],
          f"{total_rows:,} rows")
    for kind, planted in manifest["planted_totals"].items():
        check(f"planted '{kind}' all found, none extra", found[kind] == planted,
              f"planted {planted}, found {found[kind]}")
    check("every good row links to the error version active on its created date",
          pit_bad == 0, f"{pit_checked:,} rows checked, {pit_bad} wrong")
    check("every row links to a real rule", bad_rule == 0, f"{bad_rule} bad")
    check("every row links to a real file", bad_file == 0, f"{bad_file} bad")
    changed = {c["error_code"] for c in manifest["error_definition_changes"]}
    codes_with_history = Counter(v["error_code"] for v in versions.values())
    check("changed error codes have two versions each",
          all(codes_with_history[c] == 2 for c in changed), f"{len(changed)} codes changed")
    open_versions = [v for v in versions.values() if not v["inactive_date"]]
    check("exactly one open version per error code",
          len(open_versions) == len({v['error_code'] for v in versions.values()}),
          f"{len(open_versions)} open versions")

    print()
    if all(results):
        print("All checks passed.")
    else:
        print("Some checks FAILED. Do not move on until they pass.")
        sys.exit(1)


if __name__ == "__main__":
    main()