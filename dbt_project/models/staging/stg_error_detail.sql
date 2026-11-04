{#
  One row per error version. When a version changes (for example it gets an inactive
  date) the source sends the row again, so we keep the latest copy of each version.
#}
with source as (

    select * from {{ source('raw', 'error_detail') }}

),

typed as (

    select
        error_detail_skey::integer                                   as error_detail_skey,
        trim(error_code)                                             as error_code,
        trim(error_description)                                      as error_description,
        trim(response)                                               as response,
        initcap(trim(error_level))                                   as error_level,
        trim(error_type)                                             as error_type,
        active_date,
        inactive_date,
        created_date                                                 as created_at,
        updated_date                                                 as updated_at,
        to_date(replace(batch_id, 'batch_', ''), 'YYYY-MM-DD')       as batch_date,
        loaded_at
    from source

),

ranked as (

    select
        *,
        row_number() over (
            partition by error_detail_skey
            order by batch_date desc, loaded_at desc
        ) as row_rank
    from typed

)

select
    error_detail_skey, error_code, error_description, response, error_level,
    error_type, active_date, inactive_date, created_at, updated_at, batch_date, loaded_at
from ranked
where row_rank = 1