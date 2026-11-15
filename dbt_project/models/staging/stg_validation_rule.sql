{#
  One row per version of a rule. A rule is identified by rule_skey and its
  updated_date: when a rule is renamed, a new updated_date arrives.
#}
with source as (

    select * from {{ source('raw', 'validation_rule') }}

),

typed as (

    select
        rule_skey::integer                                           as rule_skey,
        trim(rule_code)                                              as rule_code,
        trim(rule_name)                                              as rule_name,
        trim(rule_category)                                          as rule_category,
        updated_date                                                 as updated_at,
        to_date(replace(batch_id, 'batch_', ''), 'YYYY-MM-DD')       as batch_date,
        loaded_at
    from source

),

ranked as (

    select
        *,
        row_number() over (
            partition by rule_skey, updated_at
            order by batch_date desc, loaded_at desc
        ) as row_rank
    from typed

)

select rule_skey, rule_code, rule_name, rule_category, updated_at, batch_date, loaded_at
from ranked
where row_rank = 1
