select
    hospital_id,
    service_id,
    event_hour,
    extract(hour from event_hour)::int as hour_of_day,
    extract(isodow from event_hour)::int as day_of_week,
    (extract(isodow from event_hour)::int in (6, 7)) as is_weekend,
    extract(month from event_hour)::int as month_of_year
from {{ ref('int_hourly_service_spine') }}
