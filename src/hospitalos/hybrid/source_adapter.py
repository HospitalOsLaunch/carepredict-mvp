"""Read-only local JSON import, explicit mapping and value-free quality reports.

No HTTP, FHIR/HL7 parser, credentials, raw identity conversion or hospital writes.
Accepted facts and import audit commit atomically in the shadow store.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import JsonValue, ValidationError

from hospitalos.operational.contract import Closed, instant

from .live_models import Availability, ObservationBatch, PlanningOptions
from .live_store import LiveStore, digest
from .models import FactEvent, ResourcePool
from .source_contract import (
    FACT_TYPES,
    ColumnManifest,
    QualityReport,
    SourceExport,
    SourceIssue,
    SourceProfile,
    TableMapping,
    forbidden_column,
    timestamp,
)

MAX_BYTES = 8 * 1024 * 1024


def strict_json(data: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(_value: str) -> None:
        raise ValueError("Non-finite JSON value")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def check_columns(profile: SourceProfile, manifest: ColumnManifest) -> tuple[SourceIssue, ...]:
    issues: list[SourceIssue] = []
    if manifest.source_schema != profile.source_schema:
        issues.append(SourceIssue(code="scope_mismatch"))
    expected = {t.table for t in profile.tables}
    actual = set(manifest.tables)
    if actual - expected:
        issues.append(SourceIssue(code="unexpected_tables", count=len(actual - expected)))
    if expected - actual:
        issues.append(SourceIssue(code="missing_tables", count=len(expected - actual)))
    for table in profile.tables:
        if table.table in manifest.tables:
            issues.extend(_columns(table, manifest.tables[table.table]))
    return tuple(issues)


def _columns(table: TableMapping, columns: list[str]) -> list[SourceIssue]:
    issues: list[SourceIssue] = []
    expected, actual = set(table.columns.values()), set(columns)
    for code, count in (
        ("unexpected_columns", len(actual - expected)),
        ("missing_columns", len(expected - actual)),
        ("forbidden_columns", sum(forbidden_column(c) for c in actual)),
        ("duplicate_columns", len(columns) - len(actual)),
    ):
        if count:
            issues.append(
                SourceIssue.model_validate({"code": code, "kind": table.kind, "count": count})
            )
    return issues


def _record(
    table: TableMapping,
    row: dict[str, JsonValue],
    profile: SourceProfile,
) -> tuple[FactEvent | Availability | None, list[SourceIssue]]:
    errors = _columns(table, list(row))
    if errors:
        return None, errors
    payload: dict[str, Any] = {}
    for target, column in table.columns.items():
        value = row[column]
        mapping = table.value_maps.get(target)
        if mapping is not None and value is not None:
            if not isinstance(value, str) or value not in mapping:
                errors.append(SourceIssue(code="unknown_code", kind=table.kind, field=target))
                continue
            value = mapping[value]
        if target in {"event_time", "available_at", "observed_at", "fact.waiting_since"}:
            try:
                payload[target] = timestamp(value)
            except (ValueError, OverflowError):
                errors.append(SourceIssue(code="invalid_field", kind=table.kind, field=target))
        else:
            payload[target] = value
    if errors:
        return None, errors
    try:
        if table.kind == "availability":
            return Availability(source=profile.source, **payload), []
        if payload["available_at"] < payload["event_time"]:
            return None, [SourceIssue(code="clock_order", kind=table.kind)]
        fact = FACT_TYPES[table.kind].model_validate(
            {
                key.removeprefix("fact."): value
                for key, value in payload.items()
                if key.startswith("fact.")
            }
        )
        event = FactEvent(
            hospital_id=profile.hospital_id,
            source=profile.source,
            fact=fact,
            **{key: value for key, value in payload.items() if not key.startswith("fact.")},
        )
        return event, []
    except ValidationError as error:
        # Never render str(error), error.inputs or source values in diagnostics/logs.
        return None, [
            SourceIssue(code="invalid_record", kind=table.kind, count=error.error_count())
        ]


class ImportResult(Closed):
    report: QualityReport
    duplicate: bool = False
    current_state_assessed: bool = False
    episode_id: str | None = None


class SourceAdapter:
    def __init__(
        self,
        store: LiveStore,
        profile: SourceProfile,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if store.policy.mode != "shadow":
            raise ValueError("Source imports require an immutable shadow-mode store")
        if (
            store.policy.hospital_id != profile.hospital_id
            or store.policy.unit_id != profile.unit_id
            or profile.source not in store.policy.sources
        ):
            raise ValueError("Source profile does not match the configured store")
        self.store, self.clock = store, clock
        # Snapshot mutable mapping dictionaries; outside mutation cannot alter an import.
        self._profile_json = profile.model_dump_json()
        self.fingerprint = digest(profile.model_dump(mode="json"))
        with store.lock, store.db:
            store.db.execute("BEGIN IMMEDIATE")
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS source_imports (id TEXT PRIMARY KEY, "
                "content_hash TEXT NOT NULL, body TEXT NOT NULL)"
            )
            key = f"source_profile:{profile.source}"
            previous = store.db.execute(
                "SELECT value FROM live_meta WHERE key=?", (key,)
            ).fetchone()
            if previous and previous[0] != self.fingerprint:
                raise ValueError(
                    "Source mapping is immutable; use a new database or a reviewed migration"
                )
            store.db.execute(
                "INSERT OR IGNORE INTO live_meta VALUES (?, ?)", (key, self.fingerprint)
            )

    def _existing(self, export_key: str, content_hash: str) -> ImportResult | None:
        row = self.store.db.execute(
            "SELECT content_hash, body FROM source_imports WHERE id=?", (export_key,)
        ).fetchone()
        if row is None:
            return None
        if row[0] != content_hash:
            raise ValueError("Export identity reused with different content")
        old = ImportResult.model_validate_json(row[1])
        return old.model_copy(update={"duplicate": True, "current_state_assessed": False})

    def _reject(self, report: QualityReport) -> ImportResult:
        # A failed feed must not leave the last good snapshot silently actionable.
        # Persist only a redacted block; no rejected source rows or values.
        profile = SourceProfile.model_validate_json(self._profile_json)
        with self.store.lock, self.store.db:
            self.store.db.execute("BEGIN IMMEDIATE")
            key = f"source_block:{profile.source}"
            old = self.store.db.execute(
                "SELECT value FROM live_meta WHERE key=?", (key,)
            ).fetchone()
            at = (
                max(report.receipt_at, datetime.fromisoformat(old[0])) if old else report.receipt_at
            )
            self.store.db.execute(
                "INSERT OR REPLACE INTO live_meta VALUES (?, ?)", (key, at.isoformat())
            )
        return ImportResult(report=report)

    def _recover(self, batch: ObservationBatch) -> None:
        key = f"source_block:{batch.source}"
        row = self.store.db.execute("SELECT value FROM live_meta WHERE key=?", (key,)).fetchone()
        if row:
            blocked = datetime.fromisoformat(row[0])
            if all(e.event_time >= blocked for e in batch.events) and all(
                a.observed_at >= blocked for a in batch.availability
            ):
                self.store.db.execute("DELETE FROM live_meta WHERE key=?", (key,))

    def receive(self, data: bytes, options: PlanningOptions | None = None) -> ImportResult:
        now = instant(self.clock())
        profile = SourceProfile.model_validate_json(self._profile_json)
        base = QualityReport(
            status="REJECTED",
            receipt_at=now,
            evaluation_mode=profile.evaluation_mode,
            profile_fingerprint=self.fingerprint,
            content_fingerprint=hashlib.sha256(data).hexdigest(),
            records_by_kind={},
        )
        if len(data) > MAX_BYTES:
            return self._reject(
                base.model_copy(update={"issues": (SourceIssue(code="export_too_large"),)})
            )
        try:
            raw = strict_json(data)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return self._reject(
                base.model_copy(update={"issues": (SourceIssue(code="invalid_json"),)})
            )
        try:
            export = SourceExport.model_validate(raw)
        except (ValidationError, RecursionError):
            return self._reject(
                base.model_copy(update={"issues": (SourceIssue(code="invalid_envelope"),)})
            )
        # Whitespace/order differences do not create a second import or update receipt time.
        content_hash = digest(export.model_dump(mode="json"))
        base = base.model_copy(update={"content_fingerprint": content_hash})
        export_key = digest((profile.source, export.export_id))
        with self.store.lock:
            try:
                old = self._existing(export_key, content_hash)
                if old is not None:
                    return old
            except ValueError:
                return self._reject(
                    base.model_copy(
                        update={"issues": (SourceIssue(code="export_identity_conflict"),)}
                    )
                )
        errors: list[SourceIssue] = []
        if (export.hospital_id, export.unit_id, export.source, export.source_schema) != (
            profile.hospital_id,
            profile.unit_id,
            profile.source,
            profile.source_schema,
        ):
            errors.append(SourceIssue(code="scope_mismatch"))
        if export.exported_at > now:
            errors.append(SourceIssue(code="future_export"))
        expected_tables = {t.table for t in profile.tables}
        if set(export.tables) - expected_tables:
            errors.append(
                SourceIssue(
                    code="unexpected_tables", count=len(set(export.tables) - expected_tables)
                )
            )
        if expected_tables - set(export.tables):
            errors.append(
                SourceIssue(code="missing_tables", count=len(expected_tables - set(export.tables)))
            )
        counts = {t.kind: len(export.tables.get(t.table, [])) for t in profile.tables}
        if (
            sum(n for kind, n in counts.items() if kind != "availability") > 2000
            or counts["availability"] > 100
        ):
            errors.append(SourceIssue(code="row_budget_exceeded"))
        base = base.model_copy(
            update={
                "records_by_kind": counts,
                "expected_entities": len(export.expected_entities),
                "export_transfer_seconds": (now - export.exported_at).total_seconds(),
            }
        )
        events: list[FactEvent] = []
        confirmations: list[Availability] = []
        missing: Counter[str] = Counter()
        seen: set[str] = set()
        if not errors:
            for table in profile.tables:
                for row in export.tables[table.table]:
                    record, problems = _record(table, row, profile)
                    errors.extend(problems)
                    if record is None:
                        continue
                    canonical = record.model_dump(mode="json")
                    for target in table.columns:
                        value = (
                            canonical["fact"][target.removeprefix("fact.")]
                            if target.startswith("fact.")
                            else canonical[target]
                        )
                        if value is None:
                            missing[f"{table.kind}.{target}"] += 1
                    if isinstance(record, FactEvent):
                        key = f"{record.fact.kind}:{record.fact.id}"
                        observed = record.available_at
                        events.append(record)
                    else:
                        key = f"availability:{record.key}"
                        observed = record.observed_at
                        confirmations.append(record)
                    if observed > export.exported_at:
                        errors.append(SourceIssue(code="future_record", kind=table.kind))
                    if key in seen:
                        errors.append(SourceIssue(code="duplicate_record", kind=table.kind))
                    seen.add(key)
        if not errors:
            delivered = {f"{e.fact.kind}:{e.fact.id}" for e in events}
            expected = set(export.expected_entities)
            for code, difference in (
                ("missing_entities", expected - delivered),
                ("unexpected_entities", delivered - expected),
            ):
                if difference:
                    errors.append(
                        SourceIssue.model_validate({"code": code, "count": len(difference)})
                    )
            required_resources = {f"staffed:{profile.unit_id}", f"cleaning:{profile.unit_id}"}
            required_resources.update(
                f"{e.fact.resource}:{e.fact.id}" for e in events if isinstance(e.fact, ResourcePool)
            )
            delivered_resources = {a.key for a in confirmations}
            for code, difference in (
                ("missing_confirmations", required_resources - delivered_resources),
                ("unexpected_confirmations", delivered_resources - required_resources),
            ):
                if difference:
                    errors.append(
                        SourceIssue.model_validate({"code": code, "count": len(difference)})
                    )
        base = base.model_copy(
            update={
                "delivered_entities": len({f"{e.fact.kind}:{e.fact.id}" for e in events}),
                "missing_values_by_field": dict(sorted(missing.items())),
                "max_fact_age_seconds": max(
                    ((now - e.event_time).total_seconds() for e in events), default=None
                ),
                "max_source_delay_seconds": max(
                    ((e.available_at - e.event_time).total_seconds() for e in events), default=None
                ),
                "max_resource_age_seconds": max(
                    ((now - a.observed_at).total_seconds() for a in confirmations), default=None
                ),
            }
        )
        if errors:
            return self._reject(base.model_copy(update={"issues": tuple(errors)}))
        try:
            batch = ObservationBatch(
                batch_id=f"source:{export_key}",
                hospital_id=profile.hospital_id,
                source=profile.source,
                manifest_version=export.manifest_version,
                expected_entities=export.expected_entities,
                events=tuple(events),
                availability=tuple(confirmations),
            )
            with self.store.transaction(now):
                # Recheck under the same lock as observation ingestion and audit persistence.
                old = self._existing(export_key, content_hash)
                if old is not None:
                    return old
                if not self.store._ingest(batch, now):
                    raise ValueError("Observation exists without its import audit")
                self._recover(batch)
                snapshot = self.store._snapshot(now)
                episode = (
                    self.store._record_shadow(now, options)
                    if profile.evaluation_mode == "shadow"
                    else None
                )
                gate_counts = Counter(reason.partition(":")[0] for reason in snapshot.issues)
                report = base.model_copy(
                    update={
                        "status": "SHADOW_EVALUATED"
                        if episode is not None and not snapshot.issues
                        else "OBSERVATION_ONLY",
                        "state_ready": not snapshot.issues,
                        "shadow_episode_created": episode is not None,
                        "issues": (SourceIssue(code="state_gate", count=len(snapshot.issues)),)
                        if snapshot.issues
                        else (),
                        "state_gate_counts": dict(sorted(gate_counts.items())),
                    }
                )
                result = ImportResult(
                    report=report,
                    current_state_assessed=True,
                    episode_id=episode.episode_id if episode else None,
                )
                self.store.db.execute(
                    "INSERT INTO source_imports VALUES (?, ?, ?)",
                    (
                        export_key,
                        content_hash,
                        result.model_dump_json(),
                    ),
                )
                return result
        except ValueError:
            # Ingestion, episode and import audit roll back together; no partial source batch.
            return self._reject(
                base.model_copy(update={"issues": (SourceIssue(code="journal_rejected"),)})
            )
