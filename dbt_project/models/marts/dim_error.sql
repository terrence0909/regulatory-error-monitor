{#
  Error codes with full history. Each version keeps its own key and the dates it was
  valid. The current version has valid_to = 9999-12-31, so date comparisons stay simple.
  The source already keeps its own versions, so we model them directly.
  error_version_key is the source's own version key, which never changes between runs.
#}
select
    error_detail_skey                              as error_version_key,
    error_code,
    error_description,
    error_level,
    error_type,
    response,
    active_date                                    as valid_from,
    coalesce(inactive_date, date '9999-12-31')     as valid_to,
    inactive_date is null                          as is_current
from {{ ref('stg_error_detail') }}
