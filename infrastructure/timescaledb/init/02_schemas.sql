CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS canonical;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS feature_store;

CREATE TABLE IF NOT EXISTS raw.ingestion_events (
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),
    topic TEXT NOT NULL,
    source_system TEXT NOT NULL,
    message_type TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS canonical.admissions (
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),
    patient_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    hospital_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    admission_time TIMESTAMPTZ NOT NULL,
    admission_type TEXT NOT NULL,
    source_system TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS canonical.discharges (
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),
    patient_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL,
    hospital_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    discharge_time TIMESTAMPTZ NOT NULL,
    discharge_disposition TEXT NOT NULL,
    source_system TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS canonical.staffing (
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),
    hospital_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    shift_start TIMESTAMPTZ NOT NULL,
    shift_end TIMESTAMPTZ NOT NULL,
    nurse_count NUMERIC(8, 2) NOT NULL,
    aide_count NUMERIC(8, 2) NOT NULL,
    overtime_hours NUMERIC(8, 2) NOT NULL DEFAULT 0,
    avg_seniority_months NUMERIC(8, 2),
    source_system TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS canonical.care_load (
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),
    hospital_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    measured_at TIMESTAMPTZ NOT NULL,
    siips_score NUMERIC(10, 2) NOT NULL,
    aas_score NUMERIC(10, 2),
    patient_count INTEGER NOT NULL,
    source_system TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS canonical.services (
    service_id TEXT PRIMARY KEY,
    hospital_id TEXT NOT NULL,
    service_name TEXT NOT NULL,
    specialty TEXT NOT NULL,
    bed_count INTEGER NOT NULL,
    patient_profile TEXT NOT NULL
);
