# Regulatory Error Monitoring Warehouse

A data pipeline that loads payment validation errors, keeps a full history of how error definitions change, checks data quality, runs daily on a schedule, and shows a dashboard of which rules fail and why.

> **About the data:** all data in this project is generated. It is shaped like a regulatory reporting system, but it contains no real transactions, names or accounts.

## Status

| Phase | What | State |
|---|---|---|
| 0 | Repo and setup | Done |
| 1 | Data model design | Done |
| 2 | Docker and database | Done |
| 3 | Fake data generator | Not started |
| 4 | Loader | Not started |
| 5 | dbt models and tests | Not started |
| 6 | Data quality tracking | Not started |
| 7 | Airflow | Not started |
| 8 | Dashboard | Not started |
| 9 | Performance | Not started |
| 10 | CI/CD | Not started |
| 11 | Docs and polish | Not started |
| 12 | Azure version | Not started |

## Stack

Python, PostgreSQL, dbt, Apache Airflow, Docker, Streamlit, GitHub Actions.

## Documentation

- [Data model](docs/data_model.md): grain, diagram and design decisions
- [Data dictionary](docs/data_dictionary.md): every column in plain English

## Quick start

Coming in phase 11.
