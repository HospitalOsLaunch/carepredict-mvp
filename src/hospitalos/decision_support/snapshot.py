"""Build a PublicSnapshot from timestamped observations, as of a decision instant.

Only observations whose event_time AND available_at are <= as_of are used (T02). The latest
usable version per (kind, subject) wins. Missing or contradictory information becomes an
explicit issue; nothing is defaulted to zero or to 'available'. Fixtures keep a separate
``private_truth`` section that this module never reads.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .clock import utc
from .contracts import (
    AdmissionRequest,
    BedState,
    CareProfile,
    CareTask,
    Distribution,
    Observation,
    Provenance,
    PublicSnapshot,
    ReinforcementOption,
    RosterCoverage,
    StaffShift,
    StayState,
    TeamCapacity,
    UnitInfo,
)

ROOT = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT / "configs" / "decision_support"


def load_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _prov(o: Observation) -> Provenance:
    return Provenance(
        obs_id=o.obs_id, source=o.source, event_time=o.event_time, available_at=o.available_at
    )


def usable(observations: Iterable[Observation], as_of: datetime) -> tuple[
    dict[tuple[str, str], Observation], dict[str, int]
]:
    as_of = utc(as_of)
    latest: dict[tuple[str, str], Observation] = {}
    excluded = {"event_after_decision": 0, "available_after_decision": 0}
    for o in observations:
        if o.event_time > as_of:
            excluded["event_after_decision"] += 1
            continue
        if o.available_at > as_of:
            excluded["available_after_decision"] += 1
            continue
        key = (o.kind, o.subject)
        old = latest.get(key)
        if old is None or (o.event_time, o.available_at, o.obs_id) > (
            old.event_time,
            old.available_at,
            old.obs_id,
        ):
            latest[key] = o
    return latest, excluded


def _dist(raw: Any) -> Distribution | None:
    return None if raw is None else Distribution.model_validate(raw)


def build_snapshot(
    observations: Iterable[Observation | Mapping[str, Any]],
    as_of: datetime,
    profile: Mapping[str, Any],
) -> PublicSnapshot:
    obs = [o if isinstance(o, Observation) else Observation.model_validate(o) for o in observations]
    latest, excluded = usable(obs, as_of)
    by_kind: dict[str, list[Observation]] = {}
    for (kind, _), o in sorted(latest.items()):
        by_kind.setdefault(kind, []).append(o)
    issues: list[str] = []

    def of(kind: str, stay: str) -> list[Observation]:
        return [
            o
            for o in by_kind.get(kind, [])
            if o.value.get("stay_id", o.subject) == stay and not o.value.get("cancelled")
        ]

    beds: list[BedState] = []
    for o in by_kind.get("bed", []):
        beds.append(
            BedState(
                bed_id=o.subject,
                status=o.value.get("status", "unknown"),
                capabilities=tuple(o.value.get("capabilities", ())),
                cleaning=_dist(o.value.get("cleaning_hours")),
                provenance=_prov(o),
            )
        )
    stays: list[StayState] = []
    for o in by_kind.get("stay", []):
        if not o.value.get("present", False):
            continue
        sid = o.subject
        prov = {"presence": _prov(o)}
        auth = of("medical_authorization", sid)
        logi = of("discharge_logistics", sid)
        ready = of("readiness_estimate", sid)
        planned = of("planned_departure", sid)
        for name, items in (("medical_authorization", auth), ("discharge_logistics", logi),
                            ("readiness_estimate", ready), ("planned_departure", planned)):
            if items:
                prov[name] = _prov(items[-1])
        care = tuple(
            CareProfile.model_validate({k: v for k, v in c.value.items() if k != "stay_id"})
            for c in of("care_profile", sid)
        )
        tasks = tuple(
            CareTask.model_validate(
                {"task_id": t.subject, **{k: v for k, v in t.value.items() if k != "stay_id"}}
            )
            for t in of("care_task", sid)
        )
        obstacles = tuple(
            str(b.value["code"]) for b in of("obstacle", sid) if b.value.get("active", True)
        )
        stays.append(
            StayState(
                stay_id=sid,
                bed_id=o.value.get("bed_id"),
                medical_authorization=auth[-1].value["status"] if auth else "unknown",
                destination=logi[-1].value.get("destination", "unknown") if logi else "unknown",
                transport_need=logi[-1].value.get("transport_need", "unknown")
                if logi
                else "unknown",
                transport_lead=_dist(logi[-1].value.get("transport_lead_hours")) if logi else None,
                ready_earliest=ready[-1].value.get("earliest") if ready else None,
                ready_delay=_dist(ready[-1].value.get("delay_hours")) if ready else None,
                planned_departure=planned[-1].value.get("at") if planned else None,
                care=care,
                tasks=tasks,
                obstacles=obstacles,
                provenance=prov,
            )
        )
        if not any(c.skill == "IDE" for c in care):
            issues.append(f"care_profile_unknown:{sid}")
    admissions = [
        AdmissionRequest(request_id=o.subject, provenance=_prov(o), **o.value)
        for o in by_kind.get("admission_request", [])
        if not o.value.get("cancelled")
    ]
    shifts = [
        StaffShift(staff_id=o.subject, **o.value)
        for o in by_kind.get("staff_shift", [])
        if not o.value.get("cancelled")
    ]
    coverage = [RosterCoverage(**o.value) for o in by_kind.get("roster_coverage", [])]
    reinforcements = [
        ReinforcementOption(option_id=o.subject, **o.value)
        for o in by_kind.get("reinforcement_option", [])
        if not o.value.get("cancelled")
    ]
    teams = [TeamCapacity(**o.value) for o in by_kind.get("team_capacity", [])]

    # Contradictions are surfaced, never arbitrated silently.
    bed_ids = {b.bed_id: b for b in beds}
    claimed: dict[str, str] = {}
    for s in stays:
        if s.bed_id is None or s.bed_id not in bed_ids:
            issues.append(f"stay_without_known_bed:{s.stay_id}")
            continue
        if s.bed_id in claimed:
            issues.append(f"bed_claimed_twice:{s.bed_id}:{claimed[s.bed_id]}:{s.stay_id}")
        claimed[s.bed_id] = s.stay_id
        if bed_ids[s.bed_id].status != "occupied":
            issues.append(f"bed_state_contradicts_presence:{s.bed_id}")
    for b in beds:
        if b.status == "occupied" and b.bed_id not in claimed:
            issues.append(f"occupied_bed_without_stay:{b.bed_id}")
        if b.status in {"dirty", "cleaning"} and b.cleaning is None:
            issues.append(f"cleaning_duration_unknown:{b.bed_id}")
    limits = profile["limits"]
    if len(stays) > limits["max_present_stays"]:
        issues.append(f"stays_exceed_supported_bound:{len(stays)}>{limits['max_present_stays']}")

    unit = UnitInfo(
        unit_id=profile["unit_id"], profile_id=profile["profile_id"],
        profile_version=profile["version"],
    )
    body = {
        "as_of": utc(as_of).isoformat(),
        "unit": unit.model_dump(mode="json"),
        "stays": [s.model_dump(mode="json") for s in stays],
        "beds": [b.model_dump(mode="json") for b in beds],
        "admissions": [a.model_dump(mode="json") for a in admissions],
        "shifts": [s.model_dump(mode="json") for s in shifts],
        "roster_coverage": [c.model_dump(mode="json") for c in coverage],
        "reinforcements": [r.model_dump(mode="json") for r in reinforcements],
        "teams": [t.model_dump(mode="json") for t in teams],
        "issues": sorted(issues),
    }
    fingerprint = sha(body)
    return PublicSnapshot(
        snapshot_id=f"snap-{fingerprint[:12]}",
        fingerprint=fingerprint,
        as_of=as_of,
        unit=unit,
        stays=tuple(stays),
        beds=tuple(beds),
        admissions=tuple(admissions),
        shifts=tuple(shifts),
        roster_coverage=tuple(coverage),
        reinforcements=tuple(reinforcements),
        teams=tuple(teams),
        issues=tuple(sorted(issues)),
        excluded_observations=excluded,
    )


def load_profile(path: Path | str | None = None) -> dict[str, Any]:
    return load_json(path or CONFIG_DIR / "UNIT_PROFILE.json")


def load_fixture_public(path: Path | str) -> tuple[dict[str, Any], list[Observation], datetime]:
    """Load only the public part of a fixture. ``private_truth`` is deliberately ignored."""
    raw = load_json(path)
    if raw.get("synthetic") is not True:
        raise ValueError("Only synthetic fixtures are accepted in this prototype")
    meta = {k: v for k, v in raw.items() if k not in {"observations", "private_truth"}}
    observations = [Observation.model_validate(o) for o in raw["observations"]]
    return meta, observations, utc(datetime.fromisoformat(raw["as_of"]))


def snapshot_from_fixture(
    path: Path | str, as_of: datetime | None = None, profile: Mapping[str, Any] | None = None
) -> PublicSnapshot:
    meta, observations, fixture_as_of = load_fixture_public(path)
    return build_snapshot(observations, as_of or fixture_as_of, profile or load_profile())
