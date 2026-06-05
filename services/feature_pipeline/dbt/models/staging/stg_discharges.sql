select
    event_id,
    patient_id,
    encounter_id,
    hospital_id,
    service_id,
    discharge_time,
    discharge_disposition,
    source_system,
    received_at
from {{ source('canonical', 'discharges') }}
