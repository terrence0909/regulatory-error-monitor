#!/usr/bin/env python3
"""
Fake data generator for the Regulatory Error Monitoring Warehouse (phase 3).

It writes one folder per day, for example data/landing/2026-01-15/, holding four
CSV files that match the raw tables in the database:

    error_detail.csv            the error lookup (changed or new versions only,
                                except on day 1 when everything is sent)
    validation_rule.csv         the rules (day 1 in full, then any renamed rules)
    file_registry.csv           the files received that day
    transaction_validation.csv  new errors, late arrivals and "cleared" updates

It also writes data/landing/_manifest.json, which records exactly what problems
were planted, so later phases can prove the quality checks catch them.

Everything is made up. Nothing here is real data.

Examples
    python3 generator/generate.py                      # 30 days, about 100,000 rows
    python3 generator/generate.py --small              # about 1,000 rows (for tests and CI)
    python3 generator/generate.py --scale 40000        # about 1 million rows (performance phase)
    python3 generator/generate.py --seed 7 --days 60

Same seed and same options always give identical files.
Uses only the Python standard library (Python 3.8 or newer).
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
import re
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from time import perf_counter

# --------------------------------------------------------------------------
# Column lists. These must match sql/init/02_raw_tables.sql, in the same order,
# minus batch_id and loaded_at (the loader adds those).
# --------------------------------------------------------------------------
ERROR_DETAIL_COLS = [
    "error_detail_skey", "error_code", "source_row_id", "error_description",
    "response", "error_level", "error_type", "active_date", "inactive_date",
    "created_date", "created_by", "updated_date", "updated_by",
]
TRANSACTION_COLS = [
    "transaction_val_skey", "error_detail_skey_fk", "file_skey_fk",
    "message_identification", "end_to_end_identification", "rule_skey_fk",
    "sequence_number", "sub_sequence", "line_number", "entity_code",
    "entity_name", "reporting_attribute", "reporting_component",
    "report_reference_number", "report_start_datetime", "reporting_qualifier",
    "flow", "original_file_reference", "error_status", "error_number",
    "user_id", "transaction_error_id", "external_ref_number",
    "transaction_type", "error_type", "error_description", "last_update_date",
    "processed_date", "processed_date_time", "created_date", "created_by",
    "updated_date", "updated_by", "transaction_status",
]
RULE_COLS = ["rule_skey", "rule_code", "rule_name", "rule_category", "updated_date"]
FILE_COLS = ["file_skey", "file_name", "received_at", "row_count"]

# --------------------------------------------------------------------------
# Building blocks for the made-up catalogue
# --------------------------------------------------------------------------
ERROR_TYPES = ["Format", "Limit", "Missing value", "Reference data", "Duplicate", "Timing"]
FIELDS = [
    "Amount", "Currency code", "Beneficiary account", "Value date", "Purpose code",
    "Counterparty country", "Reference number", "Account holder name",
    "Payment channel", "Transaction type",
]
FIELD_COMPONENT = {
    "Amount": "Payment", "Currency code": "Payment", "Value date": "Payment",
    "Purpose code": "Payment", "Payment channel": "Payment",
    "Transaction type": "Payment",
    "Beneficiary account": "Beneficiary", "Account holder name": "Beneficiary",
    "Counterparty country": "Beneficiary", "Reference number": "Reference",
}
TYPE_TEMPLATE = {
    "Format": "{field} is not in the expected format.",
    "Limit": "{field} is above the allowed limit.",
    "Missing value": "{field} is missing.",
    "Reference data": "{field} is not found in the reference list.",
    "Duplicate": "{field} appears more than once in the same file.",
    "Timing": "{field} was received after the reporting deadline.",
}
LEVEL_WEIGHTS = {
    "Format": [("Error", 70), ("Warning", 30)],
    "Limit": [("Critical", 60), ("Error", 40)],
    "Missing value": [("Error", 60), ("Critical", 40)],
    "Reference data": [("Error", 70), ("Warning", 30)],
    "Duplicate": [("Warning", 70), ("Error", 30)],
    "Timing": [("Critical", 50), ("Error", 50)],
}
LEVEL_RESPONSE = {
    "Warning": "Review the value and confirm it is correct.",
    "Error": "Correct the value and resubmit the report.",
    "Critical": "Escalate to compliance before the reporting deadline.",
}
LEVEL_ROTATE = {"Warning": "Error", "Error": "Critical", "Critical": "Error"}

RULE_CATEGORY_TYPES = {
    "Amount": ["Limit", "Missing value"],
    "Currency": ["Reference data", "Format"],
    "Format": ["Format", "Missing value"],
    "Timing": ["Timing", "Duplicate"],
    "Reference": ["Reference data", "Duplicate"],
}
RULES_PER_CATEGORY = 5

ENTITIES = [(f"ENT{i:02d}", f"Sample Bank {i:02d}") for i in range(1, 13)]
WORST_ENTITY = 7      # produces far more errors than the others and clears them slowly
IMPROVING_ENTITY = 3  # starts bad and gets steadily better

TRANSACTION_TYPES = ["Cross-border payment", "Domestic payment", "Currency exchange", "Remittance"]

# Planted problems. Each row gets at most one. Chances are per error row.
PROBLEMS = [
    ("null_error_key", 0.002),            # link to the error lookup is empty
    ("null_row_key", 0.001),              # the row's own key is empty
    ("orphan_error_key", 0.003),          # link points to an error that does not exist
    ("future_created_date", 0.002),       # created date is 30 days in the future
    ("processed_before_created", 0.002),  # cleared before it was created
    ("duplicate_row", 0.005),             # exact copy of a good row, same file
]
BAD_KINDS = {"null_error_key", "null_row_key", "orphan_error_key",
             "future_created_date", "processed_before_created"}
ORPHAN_KEY = 99999
LATE_CHANCE = 0.02       # share of rows that arrive one or two days late
CLEAR_CHANCE = 0.85      # share of good errors that are eventually cleared
WEEKEND_FACTOR = 0.35


def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def weighted(rng: random.Random, pairs):
    return rng.choices([p[0] for p in pairs], [p[1] for p in pairs])[0]


def pick_problem(rng: random.Random):
    r = rng.random()
    total = 0.0
    for name, chance in PROBLEMS:
        total += chance
        if r < total:
            return name
    return None


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------
def build_catalogue(rng, start: date, n_days: int):
    """60 error codes (every error type paired with every field), version 1 of each."""
    pairs = list(itertools.product(ERROR_TYPES, FIELDS))
    rng.shuffle(pairs)
    skeys = itertools.count(1)
    active = start - timedelta(days=180)
    current, info, all_versions = {}, {}, []
    for i, (etype, field) in enumerate(pairs):
        code = f"E{1001 + i}"
        level = weighted(rng, LEVEL_WEIGHTS[etype])
        skey = next(skeys)
        v = {
            "error_detail_skey": skey, "error_code": code,
            "source_row_id": f"MDM{skey:07d}",
            "error_description": TYPE_TEMPLATE[etype].format(field=field),
            "response": LEVEL_RESPONSE[level], "error_level": level,
            "error_type": etype, "active_date": active.isoformat(),
            "inactive_date": "",
            "created_date": fmt_dt(datetime.combine(active, dtime(0, 0))),
            "created_by": "MDM_LOAD",
            "updated_date": fmt_dt(datetime.combine(active, dtime(0, 0))),
            "updated_by": "MDM_LOAD",
        }
        current[code] = v
        info[code] = {"type": etype, "field": field}
        all_versions.append(dict(v))
    return current, info, all_versions, skeys


def build_rules(rng, start: date, info):
    """25 rules. Each rule can raise a small set of error codes."""
    codes_by_type = defaultdict(list)
    for code, meta in info.items():
        codes_by_type[meta["type"]].append(code)
    rules, skey = [], 0
    stamp = fmt_dt(datetime.combine(start - timedelta(days=90), dtime(0, 0)))
    for category, types in RULE_CATEGORY_TYPES.items():
        candidates = [c for t in types for c in codes_by_type[t]]
        for n in range(1, RULES_PER_CATEGORY + 1):
            skey += 1
            rules.append({
                "rule_skey": skey, "rule_code": f"R{skey:03d}",
                "rule_name": f"{category} check {n}", "rule_category": category,
                "updated_date": stamp, "home": rng.sample(candidates, 3),
            })
    # A few rules fail much more often than the rest.
    order = list(range(len(rules)))
    rng.shuffle(order)
    weights = [0.0] * len(rules)
    for rank, idx in enumerate(order):
        weights[idx] = 1.0 / ((rank + 1) ** 1.1)
    return rules, weights


def entity_weights(t: float):
    weights = []
    for i, _ in enumerate(ENTITIES, start=1):
        w = 1.0
        if i == WORST_ENTITY:
            w = 4.0
        elif i == IMPROVING_ENTITY:
            w = 1.8 - 1.3 * t
        weights.append(w)
    return weights


# --------------------------------------------------------------------------
# Main generation
# --------------------------------------------------------------------------
def write_csv(path: Path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def clean_output(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    for child in out.iterdir():
        if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name):
            shutil.rmtree(child)
    manifest_file = out / "_manifest.json"
    if manifest_file.exists():
        manifest_file.unlink()


def generate(start: date, n_days: int, seed: int, scale: int, out: Path):
    rng = random.Random(seed)
    days = [start + timedelta(days=i) for i in range(n_days)]
    clean_output(out)

    current, info, all_versions, ed_skeys = build_catalogue(rng, start, n_days)
    rules, rule_weights = build_rules(rng, start, info)
    codes = list(current.keys())

    # Plan when error definitions and rules change (so history tracking has work to do).
    error_changes, rule_changes = defaultdict(list), defaultdict(list)
    if n_days >= 5:
        lo, hi = max(1, int(n_days * 0.2)), max(2, int(n_days * 0.8))
        for code in rng.sample(codes, 12):
            error_changes[rng.randint(lo, hi)].append(code)
        for rule in rng.sample(rules, 3):
            rule_changes[rng.randint(lo, hi)].append(rule)

    txn_skeys, file_skeys = itertools.count(1), itertools.count(1)
    pending_delivery = defaultdict(list)  # day index -> [(row, kind)]
    pending_clear = defaultdict(list)     # day index -> [row]
    manifest = {
        "seed": seed, "start_date": start.isoformat(), "days": n_days, "scale": scale,
        "planted_totals": {name: 0 for name, _ in PROBLEMS},
        "rows_new": 0, "rows_late": 0, "rows_cleared_updates": 0, "rows_written": 0,
        "error_definition_changes": [], "rule_changes": [], "per_day": [],
    }

    for idx, day in enumerate(days):
        t = idx / max(1, n_days - 1)
        midnight = datetime.combine(day, dtime(0, 0))
        ed_rows, rule_rows = [], []

        if idx == 0:
            ed_rows.extend(dict(v) for v in all_versions)
            rule_rows.extend({c: r[c] for c in RULE_COLS} for r in rules)

        # --- error definitions change: old version closes, new version opens
        for code in error_changes.get(idx, []):
            old = current[code]
            old["inactive_date"] = (day - timedelta(days=1)).isoformat()
            old["updated_date"] = fmt_dt(midnight)
            old["updated_by"] = "MDM_LOAD"
            ed_rows.append(dict(old))
            skey = next(ed_skeys)
            new = dict(old)
            new.update({
                "error_detail_skey": skey, "source_row_id": f"MDM{skey:07d}",
                "error_description": old["error_description"].rstrip(".") + ". Revised guidance applies.",
                "active_date": day.isoformat(), "inactive_date": "",
                "created_date": fmt_dt(midnight), "updated_date": fmt_dt(midnight),
            })
            if rng.random() < 0.5:
                new["error_level"] = LEVEL_ROTATE[old["error_level"]]
                new["response"] = LEVEL_RESPONSE[new["error_level"]]
            current[code] = new
            ed_rows.append(dict(new))
            manifest["error_definition_changes"].append({
                "error_code": code, "change_date": day.isoformat(),
                "old_error_detail_skey": old["error_detail_skey"],
                "new_error_detail_skey": skey,
            })

        # --- rules are renamed in place (history needs a snapshot)
        for rule in rule_changes.get(idx, []):
            rule["rule_name"] = rule["rule_name"].replace(" (revised)", "") + " (revised)"
            rule["updated_date"] = fmt_dt(midnight)
            rule_rows.append({c: rule[c] for c in RULE_COLS})
            manifest["rule_changes"].append({
                "rule_skey": rule["rule_skey"], "change_date": day.isoformat(),
                "new_name": rule["rule_name"],
            })

        # --- today's new errors
        factor = WEEKEND_FACTOR if day.weekday() >= 5 else 1.0
        target = max(1, round(scale * factor * rng.uniform(0.9, 1.1)))
        e_weights = entity_weights(t)
        created = 0
        while created < target:
            n_err = rng.choices([1, 2, 3], [70, 20, 10])[0]
            ent_no = rng.choices(range(1, len(ENTITIES) + 1), e_weights)[0]
            ent_code, ent_name = ENTITIES[ent_no - 1]
            created_at = datetime.combine(day, dtime(rng.randint(6, 18), rng.randint(0, 59), rng.randint(0, 59)))
            tx_type = rng.choice(TRANSACTION_TYPES)
            flow = rng.choice(["Inward", "Outward"])
            qualifier = "Amended" if rng.random() < 0.1 else "Standard"
            msg_id = f"MSG{day:%Y%m%d}{rng.randint(0, 99999):05d}"
            e2e = f"E2E{rng.getrandbits(48):012X}"
            ext_ref = f"EXT{rng.randint(10_000_000, 99_999_999)}"
            for line in range(1, n_err + 1):
                rule = rng.choices(rules, rule_weights)[0]
                code = rng.choices(rule["home"], [0.6, 0.3, 0.1])[0]
                ver, meta = current[code], info[code]
                skey = next(txn_skeys)
                row = {
                    "transaction_val_skey": skey,
                    "error_detail_skey_fk": ver["error_detail_skey"],
                    "file_skey_fk": "", "message_identification": msg_id,
                    "end_to_end_identification": e2e,
                    "rule_skey_fk": rule["rule_skey"], "sequence_number": "",
                    "sub_sequence": 0, "line_number": line,
                    "entity_code": ent_code, "entity_name": ent_name,
                    "reporting_attribute": meta["field"],
                    "reporting_component": FIELD_COMPONENT[meta["field"]],
                    "report_reference_number": f"RPT-{day:%Y%m%d}-{ent_no:02d}",
                    "report_start_datetime": fmt_dt(datetime.combine(day, dtime(6, 0))),
                    "reporting_qualifier": qualifier, "flow": flow,
                    "original_file_reference": "", "error_status": "Open",
                    "error_number": line, "user_id": "SYSTEM",
                    "transaction_error_id": f"TE-{skey:09d}",
                    "external_ref_number": ext_ref, "transaction_type": tx_type,
                    "error_type": ver["error_type"],
                    "error_description": ver["error_description"],
                    "last_update_date": fmt_dt(created_at),
                    "processed_date": "", "processed_date_time": "",
                    "created_date": fmt_dt(created_at), "created_by": "RULE_ENGINE",
                    "updated_date": fmt_dt(created_at), "updated_by": "RULE_ENGINE",
                    "transaction_status": "Pending",
                }
                created += 1

                kind = pick_problem(rng)
                if kind == "null_error_key":
                    row["error_detail_skey_fk"] = ""
                elif kind == "null_row_key":
                    row["transaction_val_skey"] = ""
                elif kind == "orphan_error_key":
                    row["error_detail_skey_fk"] = ORPHAN_KEY
                elif kind == "future_created_date":
                    future = fmt_dt(created_at + timedelta(days=30))
                    row["created_date"] = row["last_update_date"] = row["updated_date"] = future
                elif kind == "processed_before_created":
                    early = created_at - timedelta(days=2)
                    row["error_status"], row["transaction_status"] = "Cleared", "Reported"
                    row["processed_date"] = early.date().isoformat()
                    row["processed_date_time"] = fmt_dt(early)

                delivery = idx
                if rng.random() < LATE_CHANCE:
                    delivery = min(idx + rng.randint(1, 2), n_days - 1)
                pending_delivery[delivery].append((row, kind))

                if kind not in BAD_KINDS and rng.random() < CLEAR_CHANCE:
                    mean = 6.0 if ent_no == WORST_ENTITY else 3.0
                    clear_idx = max(idx + 1 + int(rng.expovariate(1.0 / mean)), delivery + 1)
                    if clear_idx < n_days:
                        pending_clear[clear_idx].append(row)

        # --- deliver today's files
        items = pending_delivery.pop(idx, [])
        n_files = rng.randint(3, 6) if len(items) >= 60 else rng.randint(1, 2)
        files = []
        for k in range(1, n_files + 1):
            files.append({
                "file_skey": next(file_skeys),
                "file_name": f"FIN_{day:%Y%m%d}_{k:02d}.xml",
                "received_at": fmt_dt(datetime.combine(day, dtime(20, rng.randint(0, 59), rng.randint(0, 59)))),
                "rows": 0, "seq": 0,
            })
        tx_rows, late_today, dup_today = [], 0, 0
        for row, kind in items:
            f = files[rng.randrange(n_files)]
            f["seq"] += 1
            f["rows"] += 1
            row["file_skey_fk"] = f["file_skey"]
            row["original_file_reference"] = f["file_name"]
            row["sequence_number"] = f["seq"]
            tx_rows.append(dict(row))
            if kind is not None:
                manifest["planted_totals"][kind] += 1
            if kind == "duplicate_row":
                tx_rows.append(dict(row))
                dup_today += 1
            if not str(row["created_date"]).startswith(day.isoformat()) and kind != "future_created_date":
                late_today += 1

        # --- earlier errors get cleared today (the same row is sent again, updated)
        updates = pending_clear.pop(idx, [])
        for row in updates:
            done = datetime.combine(day, dtime(rng.randint(8, 17), rng.randint(0, 59), rng.randint(0, 59)))
            user = f"USR{rng.randint(1, 20):03d}"
            row["error_status"], row["transaction_status"] = "Cleared", "Reported"
            row["processed_date"] = day.isoformat()
            row["processed_date_time"] = fmt_dt(done)
            row["last_update_date"] = row["updated_date"] = fmt_dt(done)
            row["user_id"] = row["updated_by"] = user
            tx_rows.append(dict(row))

        file_rows = [{"file_skey": f["file_skey"], "file_name": f["file_name"],
                      "received_at": f["received_at"], "row_count": f["rows"]} for f in files]

        day_dir = out / day.isoformat()
        day_dir.mkdir(parents=True, exist_ok=True)
        write_csv(day_dir / "error_detail.csv", ERROR_DETAIL_COLS, ed_rows)
        write_csv(day_dir / "validation_rule.csv", RULE_COLS, rule_rows)
        write_csv(day_dir / "file_registry.csv", FILE_COLS, file_rows)
        write_csv(day_dir / "transaction_validation.csv", TRANSACTION_COLS, tx_rows)

        manifest["rows_new"] += len(items)
        manifest["rows_late"] += late_today
        manifest["rows_cleared_updates"] += len(updates)
        manifest["rows_written"] += len(tx_rows)
        manifest["per_day"].append({
            "date": day.isoformat(), "new_rows": len(items), "late_rows": late_today,
            "cleared_updates": len(updates), "duplicate_rows": dup_today,
            "rows_in_file": len(tx_rows), "files": n_files,
        })
        print(f"  {day.isoformat()}  new {len(items):>6}  cleared {len(updates):>6}  rows written {len(tx_rows):>6}")

    with open(out / "_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    return manifest


def main():
    p = argparse.ArgumentParser(description="Generate fake regulatory error data.")
    p.add_argument("--days", type=int, default=30, help="number of days (default 30)")
    p.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    p.add_argument("--scale", type=int, default=None,
                   help="average new errors on a weekday (default 4100, or 40 with --small)")
    p.add_argument("--small", action="store_true", help="tiny dataset for tests (about 1,000 rows)")
    p.add_argument("--start-date", default="2026-01-01", help="first day, YYYY-MM-DD")
    p.add_argument("--out", default="data/landing", help="output folder (default data/landing)")
    a = p.parse_args()

    scale = a.scale if a.scale is not None else (40 if a.small else 4100)
    start = date.fromisoformat(a.start_date)
    if a.days < 1:
        sys.exit("--days must be at least 1")

    print(f"Generating {a.days} days from {start}, seed {a.seed}, scale {scale} -> {a.out}")
    t0 = perf_counter()
    m = generate(start, a.days, a.seed, scale, Path(a.out))
    secs = perf_counter() - t0

    print("\nDone in %.1f seconds." % secs)
    print(f"  New error rows:           {m['rows_new']:,}")
    print(f"  Late arrivals:            {m['rows_late']:,}")
    print(f"  'Cleared' update rows:    {m['rows_cleared_updates']:,}")
    print(f"  Total rows written:       {m['rows_written']:,}")
    print(f"  Error definitions changed: {len(m['error_definition_changes'])}")
    print("  Problems planted:")
    for name, n in m["planted_totals"].items():
        print(f"    {name:<26}{n:>6}")
    print(f"\nManifest: {Path(a.out) / '_manifest.json'}")


if __name__ == "__main__":
    main()
