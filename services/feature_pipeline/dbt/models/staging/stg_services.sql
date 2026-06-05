select
    service_id,
    hospital_id,
    service_name,
    specialty,
    bed_count,
    patient_profile
from {{ source('canonical', 'services') }}
