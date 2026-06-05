select
    hospital_id,
    service_id,
    date_trunc('hour', shift_start) as event_hour,
    avg(nurse_count) as nurse_count_shift,
    avg(aide_count) as aide_count_shift,
    avg(overtime_hours) as overtime_hours_shift,
    avg(avg_seniority_months) as avg_seniority_months
from {{ ref('stg_staffing') }}
group by 1, 2, 3
