-- Two versions of the same rule must never be valid on the same day.
select
    a.rule_skey,
    a.rule_key,
    b.rule_key as other_rule_key
from {{ ref('dim_rule') }} a
join {{ ref('dim_rule') }} b
    on a.rule_skey = b.rule_skey
   and a.rule_key < b.rule_key
   and a.valid_from <= b.valid_to
   and b.valid_from <= a.valid_to
