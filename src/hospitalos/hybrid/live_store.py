"""Transactional local observations, resource confirmations and immutable shadow runs.

Receipt timestamps are supplied by the trusted local adapter, not by a batch.
This store is single-unit research infrastructure, not a hospital write adapter.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from hospitalos.operational.contract import instant

from .journal import canonical, reconstruct
from .live_models import (
    Assessment,
    Availability,
    LivePolicy,
    LiveSnapshot,
    ObservationBatch,
    PlanningOptions,
    ResourceBudget,
    ShadowEpisode,
)
from .models import Bed, FactEvent, Patient, ResourcePool, Unit
from .planning import PlanRequest, plan


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class LiveStore:
    """All ingestion, claims and command transitions share one SQLite transaction.

    BEGIN IMMEDIATE also serializes distinct connections to the same local file.
    No historical claim reconstruction: past evidence is read from frozen episodes.
    """

    def __init__(self, policy: LivePolicy, path: str = ":memory:") -> None:
        self.policy = policy
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS live_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS live_batches (id TEXT PRIMARY KEY, body TEXT NOT NULL, "
            "received TEXT NOT NULL, sequence INTEGER NOT NULL UNIQUE);"
            "CREATE TABLE IF NOT EXISTS live_facts (event TEXT, version INTEGER, "
            "original TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(event, version));"
            "CREATE TABLE IF NOT EXISTS live_resources (sequence INTEGER PRIMARY KEY, "
            "body TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS live_episodes (id TEXT PRIMARY KEY, body TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS live_proposals (id TEXT PRIMARY KEY, body TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS live_transitions (sequence INTEGER PRIMARY KEY, "
            "proposal TEXT NOT NULL, status TEXT NOT NULL, at TEXT NOT NULL, "
            "actor TEXT NOT NULL, evidence TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS live_holds (proposal TEXT, resource TEXT, "
            "expires TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY(proposal, resource));"
        )
        try:
            with self.lock, self.db:
                self.db.execute("BEGIN IMMEDIATE")
                row = self.db.execute("SELECT value FROM live_meta WHERE key='policy'").fetchone()
                if row and LivePolicy.model_validate_json(row[0]) != policy:
                    raise ValueError("Stored policy is immutable; use a new database")
                self.db.execute(
                    "INSERT OR IGNORE INTO live_meta VALUES ('policy', ?)",
                    (policy.model_dump_json(),),
                )
        except Exception:
            self.db.close()
            raise

    @contextmanager
    def transaction(self, now: datetime) -> Iterator[datetime]:
        now = instant(now)
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT value FROM live_meta WHERE key='clock'").fetchone()
            if row and now < datetime.fromisoformat(row[0]):
                raise ValueError("Live time must be monotonic; read frozen episodes for history")
            self.db.execute(
                "INSERT OR REPLACE INTO live_meta VALUES ('clock', ?)", (now.isoformat(),)
            )
            # Only UNSENT local holds expire. A dispatched/unknown command never does.
            self.db.execute(
                "DELETE FROM live_holds WHERE sent=0 AND expires<=?", (now.isoformat(),)
            )
            yield now

    def ingest(self, batch: ObservationBatch, received_at: datetime) -> bool:
        received_at = instant(received_at)
        # An exact replay is a read-only no-op, even after the live clock advanced.
        # The duplicate check is repeated under the write transaction for races.
        with self.lock:
            old = self.db.execute(
                "SELECT body FROM live_batches WHERE id=?", (batch.batch_id,)
            ).fetchone()
            if old:
                if ObservationBatch.model_validate_json(old[0]) != batch:
                    raise ValueError("Conflicting batch identity")
                return False
        with self.transaction(received_at) as now:
            policy = self.policy
            if batch.hospital_id != policy.hospital_id or batch.source not in policy.sources:
                raise ValueError("Unconfigured hospital or source")
            old = self.db.execute(
                "SELECT body FROM live_batches WHERE id=?", (batch.batch_id,)
            ).fetchone()
            if old:
                if ObservationBatch.model_validate_json(old[0]) != batch:
                    raise ValueError("Conflicting batch identity")
                return False
            previous = self.db.execute(
                "SELECT body, sequence FROM live_batches ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1
            if previous:
                last = ObservationBatch.model_validate_json(previous[0])
                sequence = int(previous[1]) + 1
                if batch.manifest_version not in {last.manifest_version, last.manifest_version + 1}:
                    raise ValueError("Manifest versions must advance one step at a time")
                if batch.manifest_version == last.manifest_version and set(
                    batch.expected_entities
                ) != set(last.expected_entities):
                    raise ValueError("Changed manifest requires a new version")
            elif batch.manifest_version != 1:
                raise ValueError("Initial manifest must be version 1")
            for key in batch.expected_entities:
                kind, separator, identifier = key.partition(":")
                if (
                    not separator
                    or not identifier
                    or kind not in {"unit", "bed", "patient", "pool", "discharge"}
                ):
                    raise ValueError("Malformed manifest entity")
                if kind == "unit" and identifier != policy.unit_id:
                    raise ValueError("This database is restricted to one unit")
            if f"unit:{policy.unit_id}" not in batch.expected_entities:
                raise ValueError("The configured unit is mandatory")
            for event in batch.events:
                if f"{event.fact.kind}:{event.fact.id}" not in batch.expected_entities:
                    raise ValueError("Undeclared event entity")
                if event.available_at > now:
                    raise ValueError("Future source timestamps are not observations")
                self._scope(event)
                self._ingest_fact(event, now)
            for observation in batch.availability:
                if observation.observed_at > now:
                    raise ValueError("Future availability confirmation")
                entity = (
                    f"unit:{observation.target_id}"
                    if observation.resource in {"staffed", "cleaning"}
                    else f"pool:{observation.target_id}"
                )
                if entity not in batch.expected_entities:
                    raise ValueError("Undeclared resource confirmation")
                self.db.execute(
                    "INSERT INTO live_resources(body) VALUES (?)",
                    (observation.model_dump_json(),),
                )
            self.db.execute(
                "INSERT INTO live_batches VALUES (?, ?, ?, ?)",
                (batch.batch_id, batch.model_dump_json(), now.isoformat(), sequence),
            )
        return True

    def _scope(self, event: FactEvent) -> None:
        fact = event.fact
        unit = self.policy.unit_id
        if (
            (isinstance(fact, Unit) and fact.id != unit)
            or (isinstance(fact, Bed) and fact.unit_id != unit)
            or (isinstance(fact, ResourcePool) and fact.unit_ids != (unit,))
            or (isinstance(fact, Patient) and unit not in fact.compatible_units)
        ):
            raise ValueError("Fact outside the configured unit")

    def _ingest_fact(self, event: FactEvent, received: datetime) -> None:
        for (body,) in self.db.execute(
            "SELECT original FROM live_facts WHERE event=?", (event.event_id,)
        ):
            old = FactEvent.model_validate_json(body)
            if (old.source, old.event_time, old.fact.kind, old.fact.id) != (
                event.source,
                event.event_time,
                event.fact.kind,
                event.fact.id,
            ):
                raise ValueError("An event correction cannot change its identity")
            if old.version == event.version:
                if canonical(old) != canonical(event):
                    raise ValueError("Conflicting event version")
                return  # Retransmission never refreshes a fact or its first receipt.
        stamped = event.model_copy(update={"available_at": received})
        self.db.execute(
            "INSERT INTO live_facts VALUES (?, ?, ?, ?)",
            (event.event_id, event.version, canonical(event), canonical(stamped)),
        )

    def _events(self, manifest: tuple[str, ...]) -> tuple[FactEvent, ...]:
        # Keep the latest revision per event and latest fact per source, including ties.
        # The complete, receipt-stamped history remains in live_facts.
        revisions: dict[str, FactEvent] = {}
        for (body,) in self.db.execute("SELECT body FROM live_facts"):
            event = FactEvent.model_validate_json(body)
            if f"{event.fact.kind}:{event.fact.id}" not in manifest:
                continue
            old = revisions.get(event.event_id)
            if old is None or event.version > old.version:
                revisions[event.event_id] = event
        groups: dict[tuple[str, str, str], list[FactEvent]] = defaultdict(list)
        for event in revisions.values():
            groups[(event.fact.kind, event.fact.id, event.source)].append(event)
        return tuple(
            e
            for key in sorted(groups)
            for e in sorted(groups[key], key=lambda e: (e.event_id, e.version))
            if e.event_time == max(v.event_time for v in groups[key])
        )

    def snapshot(self, now: datetime) -> LiveSnapshot:
        with self.transaction(now) as now:
            return self._snapshot(now)

    def _snapshot(self, now: datetime) -> LiveSnapshot:
        rows = self.db.execute(
            "SELECT body, received FROM live_batches ORDER BY sequence"
        ).fetchall()
        if not rows:
            raise ValueError("No observed perimeter; ingest a manifest first")
        last = ObservationBatch.model_validate_json(rows[-1][0])
        manifest = tuple(sorted(last.expected_entities))
        events = self._events(manifest)
        state = reconstruct(
            events,
            self.policy.hospital_id,
            now,
            manifest,
            max_age_minutes=math.ceil(self.policy.fact_ttl_seconds / 60),
        )
        issues = list(state.issues)
        issues.extend(
            f"stale:{e.fact.kind}:{e.fact.id}"
            for e in events
            if (now - e.event_time).total_seconds() > self.policy.fact_ttl_seconds
        )
        state = state.model_copy(update={"issues": tuple(sorted(set(issues)))})
        expected = {f"staffed:{self.policy.unit_id}", f"cleaning:{self.policy.unit_id}"}
        expected.update(
            f"{e.fact.resource}:{e.fact.id}" for e in events if isinstance(e.fact, ResourcePool)
        )
        # Persisted claims remain visible even if their entity leaves the manifest.
        expected.update(
            str(row[0])
            for row in self.db.execute("SELECT resource FROM live_holds")
            if str(row[0]).partition(":")[0] in {"staffed", "cleaning", "transport", "downstream"}
        )
        histories: dict[tuple[str, str], list[Availability]] = defaultdict(list)
        for (body,) in self.db.execute("SELECT body FROM live_resources"):
            observation = Availability.model_validate_json(body)
            if observation.key in expected:
                histories[(observation.key, observation.source)].append(observation)
        active: dict[str, list[Availability]] = defaultdict(list)
        for (key, _source), history in histories.items():
            latest = max(o.observed_at for o in history)
            active[key].extend(o for o in history if o.observed_at == latest)
        held = Counter(str(r[0]) for r in self.db.execute("SELECT resource FROM live_holds"))
        resources: list[ResourceBudget] = []
        warnings = list(state.warnings)
        for key in sorted(expected):
            observations = tuple(sorted(set(active[key]), key=lambda o: (o.source, o.evidence_ref)))
            errors: list[str] = []
            values = {o.available for o in observations}
            available = next(iter(values)) if len(values) == 1 else None
            if not observations:
                errors.append(f"missing_confirmation:{key}")
            elif len(values) != 1:
                errors.append(f"conflicting_confirmation:{key}")
            if available is None:
                errors.append(f"unknown_availability:{key}")
            if any(
                (now - o.observed_at).total_seconds() > self.policy.resource_ttl_seconds
                for o in observations
            ):
                errors.append(f"stale_confirmation:{key}")
            resources.append(
                ResourceBudget(
                    key=key,
                    observed_available=available,
                    held=held[key],
                    remaining=None if available is None else max(0, available - held[key]),
                    observations=observations,
                    issues=tuple(errors),
                )
            )
            issues.extend(errors)
            if available is not None and held[key] > available:
                warnings.append(f"local_holds_exceed_observed_free:{key}")
        # Independent source confirmation is required; disagreeing pool counts block.
        by_key = {r.key: r for r in resources}
        for pool in state.pools:
            if by_key[f"{pool.resource}:{pool.id}"].observed_available != pool.available:
                issues.append(f"pool_confirmation_mismatch:{pool.id}")
        for unit in state.units:
            committed = sum(b.state == "occupied" or b.reserved_for is not None for b in state.beds)
            for key, maximum in (
                (
                    f"staffed:{unit.id}",
                    None if unit.staffed_beds is None else max(0, unit.staffed_beds - committed),
                ),
                (f"cleaning:{unit.id}", unit.cleaning_teams),
            ):
                count = by_key[key].observed_available
                if count is not None and maximum is not None and count > maximum:
                    issues.append(f"confirmation_exceeds_capacity:{key}")
        received = {
            ObservationBatch.model_validate_json(body).source: str(receipt)
            for body, receipt in rows
        }
        semantic = {
            "hospital": state.hospital_id,
            "manifest": manifest,
            "manifest_version": last.manifest_version,
            "facts": state.model_dump(
                mode="json", exclude={"at", "fingerprint", "issues", "warnings"}
            ),
            "available": {r.key: r.observed_available for r in resources},
        }
        return LiveSnapshot(
            mode=self.policy.mode,
            state=state,
            manifest_version=last.manifest_version,
            expected_entities=manifest,
            events=events,
            resources=tuple(resources),
            received_at_by_source=received,
            semantic_fingerprint=digest(semantic),
            policy_fingerprint=digest(self.policy.model_dump(mode="json")),
            issues=tuple(sorted(set(issues))),
            warnings=tuple(sorted(set(warnings))),
        )

    @staticmethod
    def planning_events(snapshot: LiveSnapshot) -> tuple[FactEvent, ...]:
        """Explicit conservative projection: busy external resources never return.

        These derived inputs are NOT appended as observations. Raw facts and all
        confirmations remain in the snapshot. No learned forecast is enabled here.
        """
        budgets = {r.key: r.observed_available for r in snapshot.resources}
        committed = sum(
            b.state == "occupied" or b.reserved_for is not None for b in snapshot.state.beds
        )
        projected: list[FactEvent] = []
        for event in snapshot.events:
            fact = event.fact
            if isinstance(fact, Unit):
                free = budgets[f"staffed:{fact.id}"]
                cleaning = budgets[f"cleaning:{fact.id}"]
                if free is None or cleaning is None or fact.staffed_beds is None:
                    raise ValueError("Cannot project unknown availability")
                fact = fact.model_copy(
                    update={
                        "staffed_beds": min(fact.staffed_beds, committed + free),
                        "cleaning_teams": cleaning,
                    }
                )
            projected.append(event.model_copy(update={"fact": fact}))
        return tuple(projected)

    def _assess(self, now: datetime, options: PlanningOptions) -> Assessment:
        snapshot = self._snapshot(now)
        reasons = list(snapshot.issues)
        if self.db.execute("SELECT 1 FROM live_holds LIMIT 1").fetchone():
            reasons.append("unresolved_local_action_requires_reconciliation")
        if len(snapshot.events) > 2000:
            reasons.append("planner_event_budget_exceeded")
        result = None
        if not reasons:
            result = plan(
                PlanRequest(
                    hospital_id=self.policy.hospital_id,
                    at=now,
                    expected_entities=snapshot.expected_entities,
                    events=self.planning_events(snapshot),
                    max_age_minutes=math.ceil(self.policy.fact_ttl_seconds / 60),
                    **options.model_dump(),
                )
            )
        return Assessment(
            snapshot=snapshot,
            plan=result,
            gate_reasons=tuple(sorted(set(reasons))),
            expires_at=now + timedelta(seconds=self.policy.proposal_ttl_seconds),
        )

    def record_shadow(self, now: datetime, options: PlanningOptions | None = None) -> ShadowEpisode:
        if self.policy.mode != "shadow":
            raise ValueError("Shadow observations require a shadow database")
        with self.transaction(now) as now:
            episode = ShadowEpisode(
                episode_id=uuid.uuid4().hex,
                assessment=self._assess(now, options or PlanningOptions()),
            )
            self.db.execute(
                "INSERT INTO live_episodes VALUES (?, ?)",
                (episode.episode_id, episode.model_dump_json()),
            )
            return episode

    def episode(self, episode_id: str) -> ShadowEpisode:
        with self.lock:
            row = self.db.execute(
                "SELECT body FROM live_episodes WHERE id=?", (episode_id,)
            ).fetchone()
        if row is None:
            raise ValueError("Unknown episode")
        return ShadowEpisode.model_validate_json(row[0])

    def close(self) -> None:
        with self.lock:
            self.db.close()
