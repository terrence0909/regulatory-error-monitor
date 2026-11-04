-- Same proof for rules.
select
    f.validation_error_key,
    f.created_at,
    r.valid_from,
    r.valid_to
from {{ ref('fact_validation_error') }} f
join {{ ref('dim_rule') }} r on r.rule_key = f.rule_key
where f.created_at::date not between r.valid_from and r.valid_to