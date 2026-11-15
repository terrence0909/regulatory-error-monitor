#!/usr/bin/env python3
"""
Smoke test for the dashboard: it starts, shows its seven tabs, and survives changing filters.

Needs Streamlit installed and a database that has been built (loader + dbt).
Run:  python3 tests/smoke_dashboard.py
Exits with an error if anything breaks, so CI can use it.
"""
from __future__ import annotations

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
problems = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"   ({detail})" if detail else ""))
    if not ok:
        problems.append(name)


def errors_in_period(app):
    values = [m.value for m in app.metric if m.label == "Errors in period"]
    return int(values[0].replace(",", "")) if values else None


app = AppTest.from_file(str(APP), default_timeout=120).run()
check("dashboard starts without errors", not app.exception,
      "; ".join(e.value[:120] for e in app.exception))
check("shows all seven tabs", len(app.tabs) == 7, f"{len(app.tabs)} tabs")
total = errors_in_period(app)
check("overview shows a positive error count", bool(total and total > 0), f"{total}")

entity_filter = app.sidebar.multiselect[0]
first_entity = entity_filter.options[0]
app.sidebar.multiselect[0].set_value([first_entity]).run()
one = errors_in_period(app)
check("filtering to one entity works and shows fewer errors",
      not app.exception and one is not None and total is not None and 0 < one < total, f"{one} of {total}")

app.sidebar.multiselect[1].set_value(["Critical"]).run()
check("filtering by severity works", not app.exception)

app.sidebar.multiselect[0].set_value([]).run()
check("an empty selection is handled", not app.exception)

fresh = AppTest.from_file(str(APP), default_timeout=120).run()
for choice in ("Severity", "Entity (top 5)"):
    fresh.radio[0].set_value(choice).run()
    check(f"trends split by '{choice}' works", not fresh.exception)

if problems:
    sys.exit(f"{len(problems)} check(s) failed: {', '.join(problems)}")
print("\nDashboard smoke test passed.")
