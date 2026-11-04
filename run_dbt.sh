#!/usr/bin/env bash
# Runs dbt using the settings in your .env file.
# Usage:  bash run_dbt.sh build        bash run_dbt.sh test        bash run_dbt.sh docs generate
set -euo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
exec dbt "$@" --project-dir dbt_project --profiles-dir dbt_project