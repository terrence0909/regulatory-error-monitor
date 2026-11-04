#!/usr/bin/env bash
# Builds everything with dbt, then ALWAYS saves the test results, even if tests failed.
# Keeps dbt's exit code, so a failing build still looks like a failure to whatever called it.
# Usage:  bash run_build.sh            bash run_build.sh --full-refresh
cd "$(dirname "$0")" || exit 1
bash run_dbt.sh build "$@"
status=$?
python3 loader/record_dbt_results.py
exit $status