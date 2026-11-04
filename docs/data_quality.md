# Data quality

How the pipeline decides whether to trust the data, and what it does when it should not.

## Three layers of checks

| Layer | Where | What it catches | What happens to a bad row |
|---|---|---|---|
| 1. Loader checks | `loader/validators.py` | Missing keys, keys that point to nothing, impossible dates, exact duplicates | Sent to `quarantine.rejected_rows` with a plain-English reason. Never silently dropped. |
| 2. dbt tests | `dbt_project/models/*.yml` and `dbt_project/tests/` | Broken links between tables, overlapping history, wrong statuses, rows lost on the way | The test fails or warns. Results are saved in `audit.test_results`. |
| 3. Daily quality score | `marts.dq_daily_score` | A day that is much worse than usual | A warning when the score drops below the threshold |

## The daily quality score

For each batch day:

**quality score = rows that passed every loader check, divided by rows read, as a percentage.**

Only the transaction file counts, because that is the data the fact table is built from. A normal day scores about 98 to 99.5 percent, because about 1 in 100 generated rows is deliberately broken.

The warning threshold is `min_quality_score` in `dbt_project/dbt_project.yml` (default 97).

## What stops the pipeline and what only warns

| Kind of problem | Severity | Why |
|---|---|---|
| Unique or empty keys, broken links between tables | **Stops** (error) | Reports built on this would be wrong |
| Overlapping history, a row linked to the wrong version, rows lost between staging and the fact table | **Stops** (error) | The model itself is broken |
| Processed date before created date, future dates in the fact table | **Stops** (error) | The loader should have caught these |
| A new error level or type the lookup has never seen | Warns | Something changed upstream, but the data is usable |
| A day whose quality score is below the threshold | Warns | A bad file is worth knowing about, and the good rows are still fine |

A failing test makes `dbt build` exit with an error, so a scheduler such as Airflow stops. A warning is shown and recorded, and the run carries on.

## Where the results are kept

- `audit.load_log`: one row per file loaded, with rows read, loaded and rejected.
- `quarantine.rejected_rows`: every rejected row, with its reason and batch.
- `audit.dbt_runs`: one row per dbt run, with how many tests passed, warned and failed.
- `audit.test_results`: one row per test per run, with its model, severity, status and number of failing rows.

`bash run_build.sh` runs dbt and then saves the results, **even when tests fail**. It keeps dbt's exit code, so a failed build still counts as a failure.

## Proving it works

`generator/make_bad_day.py` builds one extra day where about 28 percent of rows are broken in the six known ways, and prints how many of each. After loading it:

- Quarantine shows exactly those counts, by reason.
- The quality score for that day drops to about 71 percent.
- `assert_quality_score_above_threshold` warns, and the build still finishes.

To go back to normal data: `python3 loader/load_batch.py --all --reset`, then `bash run_build.sh --full-refresh`.