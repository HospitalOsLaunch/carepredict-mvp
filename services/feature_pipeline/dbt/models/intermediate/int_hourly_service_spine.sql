with care_load as (
    select distinct
        hospital_id,
        service_id,
        date_trunc('hour', measured_at) as event_hour
    from {{ ref('stg_care_load') }}
)

select *
from care_load
