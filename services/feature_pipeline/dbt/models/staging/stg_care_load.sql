select
    event_id,
    hospital_id,
    service_id,
    measured_at,
    siips_score,
    aas_score,
    patient_count,
    source_system,
    received_at
from {{ source('canonical', 'care_load') }}
