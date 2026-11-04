with source as (

    select * from {{ source('raw', 'file_registry') }}

),

typed as (

    select
        file_skey::integer                                           as file_skey,
        trim(file_name)                                              as file_name,
        received_at,
        row_count,
        to_date(replace(batch_id, 'batch_', ''), 'YYYY-MM-DD')       as batch_date,
        loaded_at
    from source

),

ranked as (

    select
        *,
        row_number() over (
            partition by file_skey
            order by batch_date desc, loaded_at desc
        ) as row_rank
    from typed

)

select file_skey, file_name, received_at, row_count, batch_date, loaded_at
from ranked
where row_rank = 1