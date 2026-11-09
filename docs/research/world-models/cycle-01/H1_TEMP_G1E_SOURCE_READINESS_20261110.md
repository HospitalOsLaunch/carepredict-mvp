# WM-DISCOVERY-01/H1-TEMP — G1e: evidence status for versioned as-of data

**Date:** 2026-11-10. **Mode:** documentary read-only source-code / specification review. **Verdict:** `G1E_DISCOVERY_DONE_REAL_SOURCE_NOT_QUALIFIED`. **G1:** NOT FROZEN. **G2:** NO-GO.

## Evidence boundaries

- The operational research contract (`src/hospitalos/operational/contract.py`) has explicit event, recording, ingestion, and availability clocks, event versions, as-of cursor, and negative tests for future receipts, late revisions, identity conflicts, and changing local clocks.
- Its adapter (`src/hospitalos/operational/adapter.py`) explicitly labels output `synthetic_only: true` and `real_connector_validated: false`. These are **synthetic research** guarantees, not evidence that a clinical connector is installed or its lags validated.
- The canonical SIH v1 schema declares `event_time` and `available_at`; its own migration note says that approximating availability by `received_at` requires independent validation of ingestion latency. The inspected Timescale SQL still stores `received_at` without an explicit per-version `available_at` field. Do **not** infer actual knowledge-at-D from either declaration alone.
- The inspected dbt hourly feature models group by event hour; no version-specific as-of cutoff is visible in those SQL queries. This is a potential leakage boundary **if reused for H1-TEMP**, not proof of leakage in a completed H1 experiment.
- A prospective hospital-data specification requires a versioned event log, availability provenance and point-in-time reconstruction. This is a **contract requirement**, not evidence that an actual export or access approval exists. Evidence and detailed contract references reside in the restricted project dossier.

## Source qualification gates

| Stage | Required evidence | Current verdict |
|---|---|---|
| Schema | source dictionary, field definitions, versioning and business timestamp | Design evidence present, source confirmation missing |
| As-of version availability | native `available_at`, or independently demonstrated transactional proxy per version | **UNVERIFIED ON REAL SIH** |
| Historical revision replay | correction/tombstone history as known at decision D | **UNVERIFIED ON REAL SIH** |
| Topology and physical target | timestamped service/bed boundaries and agreed H+24 queue semantics | **NOT FROZEN** |
| Baseline C0/C1 / witness N0–N3 | as-of admissible raw history, support and missingness audits | **DEFINED, NOT VALIDATED** |
| Real pilot G0 | secure in-situ reconstruction and quality review, under separate authorization | **NOT PERFORMED** |

**Target mismatch warning:** The archived `queue_urgent_hospital` target cannot be silently equated with `ed_waiting` in the operational research schema; the latter denotes bed-placement demand for the observed perimeter, not every ED visit. Clinical-operational sign-off on the target and counting convention is required.

**Access boundary:** no identifiable hospital data, clinical extracts, private data dictionaries, or patient-level files belong in public GitHub or model chat. Only permitted metadata/dictionary documents may be used for this gate; an actual patient-data G0 audit must remain in the authorized secure hospital environment.

A no-ML, synthetic-only documentation preflight found remaining blocker classes: source availability evidence, exact target, final metric, useful delta, history window, witness-support comparability, and historical transmitted-vs-executed mandate provenance.

**No H24 inference, new simulation, training, real-hospital data read, API/GPU spending, or model promotion was performed or authorized.** This is an inventory/readiness note, not a claim of scientific or regulatory compliance.