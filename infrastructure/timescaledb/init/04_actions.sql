-- Transactional application tables for the Action Engine decision workflow.
--
-- These tables are NOT analytical marts and must never be rebuilt by dbt. They
-- hold mutable recommendation state plus an immutable append-only audit trail
-- for AI Act decision traceability. They are low-volume plain PostgreSQL
-- tables, not hypertables, and have no compression policy.

CREATE SCHEMA IF NOT EXISTS actions;

CREATE TABLE IF NOT EXISTS actions.recommendations (
    recommendation_id TEXT PRIMARY KEY,
    hospital_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    lever TEXT NOT NULL,
    severity TEXT NOT NULL,
    score NUMERIC(5, 4) NOT NULL,
    projected_impact_siips NUMERIC(10, 2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS actions.action_events (
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),
    recommendation_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_action_events_recommendation_time
    ON actions.action_events (recommendation_id, occurred_at);
