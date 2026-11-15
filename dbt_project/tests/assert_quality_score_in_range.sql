-- A percentage must be between 0 and 100, and loaded + rejected must equal read.
select batch_date, rows_read, rows_loaded, rows_rejected, quality_score_pct
from {{ ref('dq_daily_score') }}
where quality_score_pct < 0
   or quality_score_pct > 100
   or rows_loaded + rows_rejected <> rows_read
