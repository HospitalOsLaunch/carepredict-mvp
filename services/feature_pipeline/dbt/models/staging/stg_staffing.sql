select
    event_id,
    hospital_id,
    service_id,
    shift_start,
    shift_end,
    nurse_count,
    aide_count,
    overtime_hours,
    avg_seniority_months,
    source_system,
    received_at
from {{ source('canonical', 'staffing') }}
