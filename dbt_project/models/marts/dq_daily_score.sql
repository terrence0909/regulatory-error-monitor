{#
  One row per batch day: how many transaction rows came in, how many passed every
  check, and the quality score (the share that passed).
  Only the transaction file counts: that is the data the fact table is built from.
#}
with loads as (

    select
        to_date(replace(batch_id, 'batch_', ''), 'YYYY-MM-DD')   as batch_date,
        sum(rows_read)                                            as rows_read,
        sum(rows_loaded)                                          as rows_loaded,
        sum(rows_rejected)                                        as rows_rejected
    from {{ source('audit', 'load_log') }}
    where source_file like '%/transaction_validation.csv'
    group by 1

)

select
    batch_date,
    rows_read,
    rows_loaded,
    rows_rejected,
    round(100.0 * rows_loaded / nullif(rows_read, 0), 2)         as quality_score_pct
from loads
