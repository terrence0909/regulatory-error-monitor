select validation_error_key, created_at, batch_date
from {{ ref('fact_validation_error') }}
where created_at::date > batch_date