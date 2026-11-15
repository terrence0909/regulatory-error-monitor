-- Reconciliation: the rejections listed by reason must add up to what the load log says.
select
    s.batch_date,
    s.rows_rejected                              as load_log_rejected,
    coalesce(r.rows_by_reason, 0)                as quarantine_rejected
from {{ ref('dq_daily_score') }} s
left join (
    select batch_date, sum(rows_rejected) as rows_by_reason
    from {{ ref('dq_rejections_by_reason') }}
    group by 1
) r on r.batch_date = s.batch_date
where s.rows_rejected <> coalesce(r.rows_by_reason, 0)
