-- The source says which error version each row used. Our date-based join must agree.
-- If they ever differ, the source link and the dates are telling different stories.
select
    f.validation_error_key,
    f.error_version_key       as warehouse_version_key,
    s.error_detail_skey_fk    as source_version_key
from {{ ref('fact_validation_error') }} f
join {{ ref('stg_transaction_validation') }} s
    on s.transaction_val_skey = f.validation_error_key
where f.error_version_key <> s.error_detail_skey_fk
