-- P-0D canonical bitemporal ledger.
-- Rows are assertions, never mutable state. Corrections append a new row that
-- references the assertion being corrected.

CREATE SCHEMA IF NOT EXISTS p0d;

CREATE TABLE IF NOT EXISTS p0d.canonical_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type <> ''),
    entity_type TEXT NOT NULL CHECK (entity_type <> ''),
    entity_id TEXT NOT NULL CHECK (entity_id <> ''),
    source_system TEXT NOT NULL CHECK (source_system <> ''),
    site_id TEXT NOT NULL CHECK (site_id <> ''),
    unit_id TEXT NOT NULL CHECK (unit_id <> ''),
    event_time TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    correction_of TEXT REFERENCES p0d.canonical_events(event_id),
    payload_hash CHAR(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    lineage JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(lineage) = 'array'),
    payload JSONB NOT NULL,
    CHECK (correction_of IS NULL OR correction_of <> event_id),
    CHECK (available_at <= ingested_at)
);

CREATE INDEX IF NOT EXISTS idx_p0d_events_point_in_time
    ON p0d.canonical_events (site_id, unit_id, available_at, event_time, event_id);

CREATE INDEX IF NOT EXISTS idx_p0d_events_entity_replay
    ON p0d.canonical_events (
        entity_type,
        entity_id,
        event_time,
        available_at,
        recorded_at,
        ingested_at,
        event_id
    );

CREATE INDEX IF NOT EXISTS idx_p0d_events_correction
    ON p0d.canonical_events (correction_of)
    WHERE correction_of IS NOT NULL;

CREATE OR REPLACE FUNCTION p0d.reject_ledger_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'p0d.canonical_events is append-only';
END;
$$;

DROP TRIGGER IF EXISTS p0d_no_update_or_delete ON p0d.canonical_events;
CREATE TRIGGER p0d_no_update_or_delete
BEFORE UPDATE OR DELETE ON p0d.canonical_events
FOR EACH ROW EXECUTE FUNCTION p0d.reject_ledger_mutation();

DROP TRIGGER IF EXISTS p0d_no_truncate ON p0d.canonical_events;
CREATE TRIGGER p0d_no_truncate
BEFORE TRUNCATE ON p0d.canonical_events
FOR EACH STATEMENT EXECUTE FUNCTION p0d.reject_ledger_mutation();

CREATE OR REPLACE FUNCTION p0d.validate_correction_append()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target p0d.canonical_events%ROWTYPE;
BEGIN
    IF NEW.correction_of IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT * INTO STRICT target
    FROM p0d.canonical_events
    WHERE event_id = NEW.correction_of;

    IF ROW(
        NEW.event_type,
        NEW.entity_type,
        NEW.entity_id,
        NEW.source_system,
        NEW.site_id,
        NEW.unit_id,
        NEW.event_time
    ) IS DISTINCT FROM ROW(
        target.event_type,
        target.entity_type,
        target.entity_id,
        target.source_system,
        target.site_id,
        target.unit_id,
        target.event_time
    ) THEN
        RAISE EXCEPTION 'correction must preserve assertion identity and event_time';
    END IF;

    IF NEW.recorded_at < target.recorded_at
       OR NEW.available_at < target.available_at
       OR NEW.ingested_at < target.ingested_at THEN
        RAISE EXCEPTION 'correction cannot precede its target';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS p0d_validate_correction ON p0d.canonical_events;
CREATE TRIGGER p0d_validate_correction
BEFORE INSERT ON p0d.canonical_events
FOR EACH ROW EXECUTE FUNCTION p0d.validate_correction_append();

REVOKE UPDATE, DELETE, TRUNCATE ON p0d.canonical_events FROM PUBLIC;
