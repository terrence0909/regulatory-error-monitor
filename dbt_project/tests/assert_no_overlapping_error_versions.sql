-- Two versions of the same error code must never be valid on the same day.
select
    a.error_code,
    a.error_version_key,
    b.error_version_key as other_version_key
from {{ ref('dim_error') }} a
join {{ ref('dim_error') }} b
    on a.error_code = b.error_code
   and a.error_version_key < b.error_version_key
   and a.valid_from <= b.valid_to
   and b.valid_from <= a.valid_to