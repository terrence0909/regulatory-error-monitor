-- The point-in-time proof: every row must link to an error version that was valid
-- on the day the row was created. A changed error code is the case this protects.
select
    f.validation_error_key,
    f.created_at,
    d.error_code,
    d.valid_from,
    d.valid_to
from {{ ref('fact_validation_error') }} f
join {{ ref('dim_error') }} d on d.error_version_key = f.error_version_key
where f.created_at::date not between d.valid_from and d.valid_to
