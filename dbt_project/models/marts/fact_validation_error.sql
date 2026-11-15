{#
  One row per validation error on one transaction line (the grain).

  Incremental: after the first build, each run only reprocesses recent batches
  (var lookback_days, default 3), so late-arriving and newly cleared rows are picked up
  without rebuilding everything. Rows are replaced by key (delete+insert), so rerunning
  is safe. To rebuild from scratch: bash run_dbt.sh run --full-refresh

  Point-in-time join: each row is linked to the version of its error code (and rule)
  that was valid on the day the row was created, not the latest version.
  Left joins are used on purpose: a row that finds no match keeps a null key and fails
  the not_null tests loudly, instead of silently disappearing.
#}
{{
    config(
        materialized='incremental',
        unique_key='validation_error_key',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

with source_rows as (

    select *
    from {{ ref('stg_transaction_validation') }}
    {% if is_incremental() %}
    where batch_date >= (
        select coalesce(max(batch_date), date '1900-01-01') from {{ this }}
    ) - {{ var('lookback_days') }}
    {% endif %}

),

with_error_code as (

    select s.*, e.error_code
    from source_rows s
    left join {{ ref('stg_error_detail') }} e
        on e.error_detail_skey = s.error_detail_skey_fk

)

select
    w.transaction_val_skey                                   as validation_error_key,
    d.error_version_key,
    r.rule_key,
    w.file_skey_fk                                           as file_key,
    w.entity_code,
    to_char(w.created_at, 'YYYYMMDD')::integer               as created_date_key,
    w.message_id,
    w.end_to_end_id,
    w.sequence_number,
    w.sub_sequence,
    w.line_number,
    w.transaction_type,
    w.transaction_status,
    w.error_status,
    w.created_at,
    w.processed_at,
    w.processed_at is null                                   as is_open,
    case
        when w.processed_at is not null
        then w.processed_at::date - w.created_at::date
    end                                                      as days_to_clear,
    w.batch_date,
    w.loaded_at
from with_error_code w
left join {{ ref('dim_error') }} d
    on d.error_code = w.error_code
   and w.created_at::date between d.valid_from and d.valid_to
left join {{ ref('dim_rule') }} r
    on r.rule_skey = w.rule_skey_fk
   and w.created_at::date between r.valid_from and r.valid_to
