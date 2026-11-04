{#
  Rules with full history. Rules are renamed in place in the source, but the loader keeps
  every batch, so each version is already in raw. We read the versions and work out when
  each one was valid (from its own date until the day before the next version).
  rule_key = rule_skey * 1000 + version number, which is stable as new versions arrive.
#}
with versions as (

    select
        rule_skey, rule_code, rule_name, rule_category,
        updated_at::date as valid_from
    from {{ ref('stg_validation_rule') }}

),

numbered as (

    select
        *,
        row_number() over (partition by rule_skey order by valid_from) as version_no,
        lead(valid_from) over (partition by rule_skey order by valid_from) as next_valid_from
    from versions

)

select
    (rule_skey * 1000 + version_no)::bigint              as rule_key,
    rule_skey,
    rule_code,
    rule_name,
    rule_category,
    valid_from,
    coalesce(next_valid_from - 1, date '9999-12-31')     as valid_to,
    next_valid_from is null                              as is_current
from numbered