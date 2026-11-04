-- Reconciliation: every cleaned staging row must appear in the fact table exactly once.
with staging as (select count(*) as n from {{ ref('stg_transaction_validation') }}),
     fact as (select count(*) as n from {{ ref('fact_validation_error') }})
select staging.n as staging_rows, fact.n as fact_rows
from staging, fact
where staging.n <> fact.n