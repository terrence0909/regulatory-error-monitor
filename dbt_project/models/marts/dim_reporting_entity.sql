{# The entity code itself is the key: it is stable and already unique. #}
select distinct on (entity_code)
    entity_code,
    entity_name
from {{ ref('stg_transaction_validation') }}
order by entity_code, batch_date desc
