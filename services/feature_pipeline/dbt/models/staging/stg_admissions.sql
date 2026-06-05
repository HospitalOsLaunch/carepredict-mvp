select
    event_id,
    patient_id,
    encounter_id,
    hospital_id,
    service_id,
    admission_time,
    admission_type,
    source_system,
    received_at
from {{ source('canonical', 'admissions') }}
