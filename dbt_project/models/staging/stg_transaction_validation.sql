{#
  One row per validation error, latest version only.
  When an error is cleared the source sends the same row again with a processed date,
  so we keep the newest copy of each transaction_val_skey.

  Cleaned up here:
    - the repeated error type and description are dropped (the error lookup is the truth)
    - the two processed-date columns become one: processed_at
    - status text is tidied
#}
with source as (

    select * from {{ source('raw', 'transaction_validation') }}

),

typed as (

    select
        transaction_val_skey::bigint                                 as transaction_val_skey,
        error_detail_skey_fk::integer                                as error_detail_skey_fk,
        file_skey_fk::integer                                        as file_skey_fk,
        rule_skey_fk::integer                                        as rule_skey_fk,
        trim(message_identification)                                 as message_id,
        trim(end_to_end_identification)                              as end_to_end_id,
        sequence_number,
        sub_sequence,
        line_number,
        trim(entity_code)                                            as entity_code,
        trim(entity_name)                                            as entity_name,
        trim(transaction_type)                                       as transaction_type,
        initcap(trim(error_status))                                  as error_status,
        initcap(trim(transaction_status))                            as transaction_status,
        created_date                                                 as created_at,
        coalesce(processed_date_time, processed_date::timestamp)     as processed_at,
        last_update_date                                             as last_updated_at,
        to_date(replace(batch_id, 'batch_', ''), 'YYYY-MM-DD')       as batch_date,
        loaded_at
    from source

),

ranked as (

    select
        *,
        row_number() over (
            partition by transaction_val_skey
            order by batch_date desc, loaded_at desc
        ) as row_rank
    from typed

)

select
    transaction_val_skey, error_detail_skey_fk, file_skey_fk, rule_skey_fk,
    message_id, end_to_end_id, sequence_number, sub_sequence, line_number,
    entity_code, entity_name, transaction_type, error_status, transaction_status,
    created_at, processed_at, last_updated_at, batch_date, loaded_at
from ranked
where row_rank = 1