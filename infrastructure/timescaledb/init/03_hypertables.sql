SELECT create_hypertable('raw.ingestion_events', 'event_time', if_not_exists => TRUE);
SELECT create_hypertable('canonical.admissions', 'admission_time', if_not_exists => TRUE);
SELECT create_hypertable('canonical.discharges', 'discharge_time', if_not_exists => TRUE);
SELECT create_hypertable('canonical.staffing', 'shift_start', if_not_exists => TRUE);
SELECT create_hypertable('canonical.care_load', 'measured_at', if_not_exists => TRUE);

ALTER TABLE raw.ingestion_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'topic, source_system'
);

ALTER TABLE canonical.admissions SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'hospital_id, service_id'
);

ALTER TABLE canonical.discharges SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'hospital_id, service_id'
);

ALTER TABLE canonical.staffing SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'hospital_id, service_id'
);

ALTER TABLE canonical.care_load SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'hospital_id, service_id'
);

SELECT add_compression_policy('raw.ingestion_events', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('canonical.admissions', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('canonical.discharges', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('canonical.staffing', INTERVAL '30 days', if_not_exists => TRUE);
SELECT add_compression_policy('canonical.care_load', INTERVAL '30 days', if_not_exists => TRUE);
