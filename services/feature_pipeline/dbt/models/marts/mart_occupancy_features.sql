select
    care_load.hospital_id,
    care_load.service_id,
    date_trunc('hour', care_load.measured_at) as event_hour,
    max(care_load.patient_count)::float / nullif(max(services.bed_count), 0) as occupancy_rate
from {{ ref('stg_care_load') }} as care_load
join {{ ref('stg_services') }} as services
    on care_load.service_id = services.service_id
group by 1, 2, 3
