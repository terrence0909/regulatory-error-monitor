select
    file_skey          as file_key,
    file_name,
    received_at,
    row_count          as row_count_claimed
from {{ ref('stg_file_registry') }}