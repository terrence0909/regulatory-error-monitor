with days as (

    select generate_series(date '2025-01-01', date '2027-12-31', interval '1 day')::date as full_date

)

select
    to_char(full_date, 'YYYYMMDD')::integer     as date_key,
    full_date,
    extract(year from full_date)::integer        as year,
    extract(month from full_date)::integer       as month,
    to_char(full_date, 'Mon')                    as month_name,
    to_char(full_date, 'YYYY-MM')                as year_month,
    extract(isodow from full_date)::integer      as day_of_week,
    extract(isodow from full_date) >= 6          as is_weekend
from days