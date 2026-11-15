#!/usr/bin/env python3
"""
Proves the loader did its job, by comparing the database with the generator's manifest.

It checks that:
  - every planted problem ended up in quarantine, with the right reason, and nothing else did
  - the number of loaded rows adds up (rows written - rows rejected)
  - the error lookup has every version (including the old ones)
  - every day has a batch in the audit log

Usage
    python3 loader/verify_load.py
    python3 loader/verify_load.py --dir some/other/folder
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loader.load_batch import connect  # noqa: E402
from loader.validators import REASON_TO_PLANTED_KIND  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name + (f"   ({detail})" if detail else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "data" / "landing"), help="folder holding _manifest.json")
    manifest_path = Path(ap.parse_args().dir) / "_manifest.json"
    if not manifest_path.exists():
        sys.exit("No manifest found. Run python3 generator/generate.py first.")
    m = json.loads(manifest_path.read_text())

    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT reason, count(*) FROM quarantine.rejected_rows "
                "WHERE table_name = 'transaction_validation' GROUP BY reason")
    by_reason = {reason: n for reason, n in cur.fetchall()}
    unexpected = {r: n for r, n in by_reason.items() if r not in REASON_TO_PLANTED_KIND}
    check("no unexpected rejection reasons", not unexpected, str(unexpected) if unexpected else "none")
    for reason, kind in REASON_TO_PLANTED_KIND.items():
        planted, rejected = m["planted_totals"][kind], by_reason.get(reason, 0)
        check(f"'{kind}': planted rows all quarantined, none extra", planted == rejected,
              f"planted {planted}, quarantined {rejected}")

    cur.execute("SELECT count(*) FROM quarantine.rejected_rows WHERE table_name <> 'transaction_validation'")
    check("nothing rejected from the reference tables", cur.fetchone()[0] == 0)

    cur.execute("SELECT count(*) FROM raw.transaction_validation")
    loaded = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM quarantine.rejected_rows WHERE table_name = 'transaction_validation'")
    rejected = cur.fetchone()[0]
    check("loaded + rejected = rows written", loaded + rejected == m["rows_written"],
          f"{loaded:,} + {rejected:,} = {loaded + rejected:,}, expected {m['rows_written']:,}")

    expected_versions = 60 + 2 * len(m["error_definition_changes"])
    cur.execute("SELECT count(*) FROM raw.error_detail")
    n = cur.fetchone()[0]
    check("error lookup holds every version", n == expected_versions, f"{n} rows, expected {expected_versions}")

    cur.execute("SELECT count(DISTINCT batch_id) FROM audit.load_log")
    n = cur.fetchone()[0]
    check("one batch per day in the audit log", n == m["days"], f"{n} batches")

    cur.execute("SELECT count(*) FROM (SELECT batch_id, source_file FROM audit.load_log "
                "GROUP BY 1, 2 HAVING count(*) > 1) x")
    check("no file logged twice", cur.fetchone()[0] == 0)

    print()
    if all(results):
        print("All checks passed.")
    else:
        print("Some checks FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    main()
