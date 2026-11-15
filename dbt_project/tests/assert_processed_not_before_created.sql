select validation_error_key, created_at, processed_at
from {{ ref('fact_validation_error') }}
where processed_at is not null
  and processed_at::date < created_at::date
