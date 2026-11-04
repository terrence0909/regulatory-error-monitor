select validation_error_key, is_open, processed_at
from {{ ref('fact_validation_error') }}
where is_open <> (processed_at is null)
   or (is_open and days_to_clear is not null)
   or (not is_open and days_to_clear is null)