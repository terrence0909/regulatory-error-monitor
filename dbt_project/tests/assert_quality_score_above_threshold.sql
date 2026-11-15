{{ config(severity='warn') }}

-- A SOFT check: a bad day is reported, but it does not stop the pipeline.
-- The threshold is the variable min_quality_score in dbt_project.yml.
select batch_date, rows_read, rows_rejected, quality_score_pct
from {{ ref('dq_daily_score') }}
where quality_score_pct < {{ var('min_quality_score') }}
