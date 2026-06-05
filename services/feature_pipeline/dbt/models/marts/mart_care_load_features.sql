select
    spine.hospital_id,
    spine.service_id,
    spine.event_hour,
    avg(care_load.siips_score) as siips_mean_1h,
    avg(care_load.patient_count) as patient_count_mean_1h
from {{ ref('int_hourly_service_spine') }} as spine
left join {{ ref('stg_care_load') }} as care_load
    on spine.hospital_id = care_load.hospital_id
    and spine.service_id = care_load.service_id
    and date_trunc('hour', care_load.measured_at) = spine.event_hour
group by 1, 2, 3
