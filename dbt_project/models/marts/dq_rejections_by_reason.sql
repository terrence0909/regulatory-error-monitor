{# Which problems were found each day, and how many rows each one rejected. #}
select
    to_date(replace(batch_id, 'batch_', ''), 'YYYY-MM-DD')       as batch_date,
    reason,
    count(*)                                                      as rows_rejected
from {{ source('quarantine', 'rejected_rows') }}
where table_name = 'transaction_validation'
group by 1, 2
