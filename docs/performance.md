# Performance

Measured with about **3,449,819 rows** loaded into raw and **1,917,765 rows** in the fact table (60 days of data), on Darwin arm64, 8 CPU cores, with PostgreSQL running in Docker.
Each time is the median of 3 runs where a run adds one new day. Run it yourself with `python3 benchmarks/run_benchmark.py`.

## What changed

- **Before:** the cleaning step (`stg_transaction_validation`) was a view. Every time the fact table was built, it re-cleaned **all** of the raw data, even though only the last day had changed. (A view costs nothing by itself, so its work shows up inside the fact table step.)
- **After:** the cleaning step is an incremental table. Each run reads only the last few days of batches (the same look-back window the fact table uses) and replaces those rows by key.

## Results

| Step | Before | After | Change |
|---|---|---|---|
| Daily dbt run (new day arrives) | 16.8 s | 8.1 s | 52% faster |
| Cleaning and fact table work inside that run | 14.6 s | 5.8 s | 60% faster |
| Full rebuild of everything | 27.0 s | 21.5 s | 20% faster |
| Daily run compared with a full rebuild | 38% faster | 62% faster | |

A normal `dbt build` (all 72 models and tests) takes 12.5 s. The dashboard loads all 1,917,765 rows in 7.7 s.

## Why the first version was slow

The fact table was already incremental, but it read from a view that recomputed the latest-row-per-key step over every raw row on every run. The look-back filter came after that work, so it saved almost nothing. Measuring showed it, and moving the filter to the start of the cleaning step fixed it.

## Limits

- The incremental models only look back a few days. If you reload an old day with corrected data, run `bash run_dbt.sh run --full-refresh` so the change is picked up.
- The dashboard loads the whole fact table into memory and caches it. That is fine at about a million rows. At 100 times the size it should run its summaries inside the database instead.
- Numbers depend on the machine. Compare the Before and After columns, not the absolute times.

## How it scales

Two runs of the same benchmark, one with 30 days of history and one with 60 days (same daily volume). Times are medians of 3 runs.

| History | Fact rows | Before: cleaning + fact work | After: cleaning + fact work | Before: daily run | After: daily run |
|---|---|---|---|---|---|
| 30 days | 971,328 | 5.8 s | 5.6 s | 7.5 s | 6.8 s |
| 60 days | 1,917,765 | 14.6 s | 5.8 s | 16.8 s | 8.1 s |

Before the change, doubling the history made the daily work about 2.5 times bigger. After the change it stayed flat. At 30 days the two versions look almost the same, so the benefit only shows as history grows.

The daily run as a whole still rose a little (6.8 s to 8.1 s) because a few small models still read whole tables each run.

The dashboard loads the whole fact table in 7.7 s at about 1.9 million rows. It caches the result for five minutes, but past this size it should run its summaries inside the database instead.
