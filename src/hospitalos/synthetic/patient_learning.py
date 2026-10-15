"""Stream patient features and separate truth targets from a verified synthetic run."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import tempfile
from collections import Counter
from collections.abc import Iterable
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import StrictBool, model_validator

from .config import FrozenConfig, HospitalConfig
from .generate import _jsonl, source_hashes
from .learning import _digest, _events, verify_source
from .patient_asof import PatientRow, replay_patients
from .patient_observations import (
    Admission,
    Departure,
    NotAdmitted,
    Request,
    Transfer,
    observe_patients,
    patient_profile,
    source_movement,
)


class TruthStay(FrozenConfig):
    """Outcome file only. No projected/latent discharge or medical-ready date."""

    stay_id: str
    requested_h: float
    admission_h: float | None
    departure_h: float | None
    closed_h: float | None
    termination: Literal["open", "departed", "not_admitted"]
    followup_end_h: float
    right_censored: StrictBool

    @model_validator(mode="after")
    def frozen_followup(self) -> Self:
        times = [self.requested_h, self.followup_end_h]
        times.extend(
            h for h in (self.admission_h, self.departure_h, self.closed_h) if h is not None
        )
        if any(not float("-inf") < h <= self.followup_end_h < float("inf") for h in times):
            raise ValueError("Truth stay contains future or nonfinite dates")
        if self.right_censored != (self.termination == "open"):
            raise ValueError("Censoring disagrees with termination")
        if (self.closed_h is None) != self.right_censored:
            raise ValueError("Open stay cannot reveal a future closure")
        if self.admission_h is not None and self.admission_h < self.requested_h:
            raise ValueError("Admission precedes request")
        if self.termination == "departed":
            if (
                self.admission_h is None
                or self.departure_h is None
                or not self.admission_h <= self.departure_h == self.closed_h
            ):
                raise ValueError("Invalid hospital departure")
        elif self.departure_h is not None:
            raise ValueError("Only departed stays can reveal a departure date")
        if self.termination == "not_admitted" and self.admission_h is not None:
            raise ValueError("Nonadmission cannot follow admission")
        if self.closed_h is not None and self.closed_h < self.requested_h:
            raise ValueError("Closure precedes request")
        return self


def build_patient_truth(
    events: Iterable[dict[str, Any]], config: HospitalConfig
) -> dict[str, TruthStay]:
    movements = [row for event in events if (row := source_movement(event, config)) is not None]
    movements.sort(key=lambda r: (r.event_h, r.event_order, r.event_id))
    states: dict[str, dict[str, Any]] = {}
    seen = set()
    for row in movements:
        if row.event_id in seen:
            raise ValueError("Duplicate patient truth event")
        seen.add(row.event_id)
        if isinstance(row.payload, Request):
            if row.stay_id in states:
                raise ValueError("Duplicate patient request")
            states[row.stay_id] = {
                "stay_id": row.stay_id,
                "requested_h": row.event_h,
                "admission_h": None,
                "departure_h": None,
                "closed_h": None,
                "termination": "open",
                "followup_end_h": float(config.days * 24),
                "right_censored": True,
            }
            continue
        state = states.get(row.stay_id)
        if state is None or state["termination"] != "open":
            raise ValueError("Movement without open requested stay")
        if isinstance(row.payload, Admission):
            if state["admission_h"] is not None:
                raise ValueError("Duplicate admission")
            state["admission_h"] = row.event_h
        elif isinstance(row.payload, Transfer):
            if state["admission_h"] is None:
                raise ValueError("Transfer before admission")
        elif isinstance(row.payload, Departure):
            state.update(
                departure_h=row.event_h,
                closed_h=row.event_h,
                termination="departed",
                right_censored=False,
            )
        elif isinstance(row.payload, NotAdmitted):
            state.update(closed_h=row.event_h, termination="not_admitted", right_censored=False)
    return {stay: TruthStay.model_validate(state) for stay, state in states.items()}


def patient_target(row: PatientRow, truth: dict[str, TruthStay]) -> dict[str, Any]:
    stay = truth.get(row.stay_id)
    if stay is None or not row.decision_h < stay.followup_end_h:
        raise ValueError("Patient feature lacks valid follow-up truth")
    hour = row.decision_h
    present = (
        stay.admission_h is not None
        and stay.admission_h <= hour
        and (stay.departure_h is None or hour < stay.departure_h)
    )
    result: dict[str, Any] = {
        "sample_id": row.sample_id,
        "run_id": row.run_id,
        "hospital_id": row.hospital_id,
        "stay_id": row.stay_id,
        "partition": row.partition,
        "decision_h": hour,
        "at_risk": present,
        "remaining_stay_h": (stay.departure_h - hour)
        if present and stay.departure_h is not None
        else None,
        "remaining_stay_censored": present and stay.departure_h is None,
        "observed_followup_h": (
            min(stay.departure_h or stay.followup_end_h, stay.followup_end_h) - hour
        )
        if present
        else None,
    }
    for horizon in (24, 48, 72):
        positive = (
            present and stay.departure_h is not None and hour < stay.departure_h <= hour + horizon
        )
        censored = present and not positive and hour + horizon > stay.followup_end_h
        result[f"departure_{horizon}h"] = None if not present or censored else bool(positive)
        result[f"departure_{horizon}h_censored"] = censored
    return result


def prepare_patient_run(
    source: Path, output: Path, *, stale_after_h: float = 96.0
) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    if source.resolve() in output.resolve().parents:
        raise ValueError("Patient output must be outside immutable truth run")
    if not 0 < stale_after_h < float("inf"):
        raise ValueError("Invalid patient staleness threshold")
    config, input_hash = verify_source(source)
    settings = {
        "adapter": "patient_movements_v1",
        "profile": patient_profile(config).model_dump(mode="json"),
        "stale_after_h": stale_after_h,
        "horizons_h": [24, 48, 72],
    }
    hashes = source_hashes()
    runtime = {
        "python": platform.python_version(),
        **{name: version(name) for name in ("numpy", "pandas", "pydantic")},
    }
    run_id = hashlib.sha256(
        json.dumps(
            {"input": input_hash, "settings": settings, "source": hashes, "runtime": runtime},
            sort_keys=True,
        ).encode()
    ).hexdigest()[:24]
    deliveries = observe_patients(_events(source), config)
    truth = build_patient_truth(_events(source), config)
    counts: Counter[str] = Counter()
    counts.update(
        features=0,
        targets=0,
        stale_rows=0,
        bed_conflict_rows=0,
        admission_missing_rows=0,
        request_missing_rows=0,
        not_at_risk_rows=0,
        censored_24h_rows=0,
        censored_48h_rows=0,
        censored_72h_rows=0,
        deliveries=len(deliveries),
        truth_stays=len(truth),
        right_censored_stays=sum(s.right_censored for s in truth.values()),
        right_censored_admitted_stays=sum(
            s.right_censored and s.admission_h is not None for s in truth.values()
        ),
        unique_events=len({r.event_id for r in deliveries}),
        revisions=sum(r.event_version > 1 for r in deliveries),
        duplicates=len(deliveries) - len({(r.event_id, r.event_version) for r in deliveries}),
    )
    observed_stays: set[str] = set()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".patients-", dir=output.parent) as temp:
        staging = Path(temp) / "run"
        for name in ("observed", "features", "targets"):
            (staging / name).mkdir(parents=True)
        _jsonl(
            staging / "observed/movements.jsonl.gz", (r.model_dump(mode="json") for r in deliveries)
        )
        _jsonl(
            staging / "targets/stays.jsonl.gz",
            (s.model_dump(mode="json") for _, s in sorted(truth.items())),
        )

        # Stream features and labels in separate passes; no truth object enters replay.
        def features() -> Iterable[dict[str, Any]]:
            for row in replay_patients(
                deliveries, config, run_id=run_id, stale_after_h=stale_after_h
            ):
                counts["features"] += 1
                counts["stale_rows"] += row.stale
                counts["bed_conflict_rows"] += row.bed_conflict
                counts["admission_missing_rows"] += row.admission_missing
                counts["request_missing_rows"] += row.request_missing
                observed_stays.add(row.stay_id)
                yield row.model_dump(mode="json")

        _jsonl(staging / "features/patients_asof.jsonl.gz", features())

        def targets() -> Iterable[dict[str, Any]]:
            with gzip.open(staging / "features/patients_asof.jsonl.gz", "rt") as stream:
                for line in stream:
                    row = PatientRow.model_validate_json(line)
                    target = patient_target(row, truth)
                    counts["targets"] += 1
                    counts["not_at_risk_rows"] += not target["at_risk"]
                    for horizon in (24, 48, 72):
                        counts[f"censored_{horizon}h_rows"] += target[
                            f"departure_{horizon}h_censored"
                        ]
                    yield target

        _jsonl(staging / "targets/departures.jsonl.gz", targets())
        counts["feature_stays"] = len(observed_stays)
        (staging / "config.json").write_text(config.model_dump_json(indent=2) + "\n")
        manifest = {
            "schema_version": "0.1",
            "status": "complete",
            "synthetic_only": True,
            "data_role": "patient_observations_features_targets_separated",
            "run_id": run_id,
            "input_manifest_sha256": input_hash,
            "source_sha256": hashes,
            "runtime": runtime,
            "settings": settings,
            "hospital_id": config.hospital_id,
            "partition": config.partition,
            "counts": dict(counts),
            "clock": (
                "fixed UTC+01:00; movements during [h,h+1) become facts at h+1; horizon (t,t+H]"
            ),
            "scope": "movement-only; no clinical notes, learned encoder or patient-based policy",
            "files_sha256": {
                str(p.relative_to(staging)): _digest(p)
                for p in sorted(staging.rglob("*"))
                if p.is_file()
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
        staging.rename(output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stale-after-hours", type=float, default=96.0)
    args = parser.parse_args()
    try:
        result = prepare_patient_run(args.source, args.output, stale_after_h=args.stale_after_hours)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Patient preparation failed: {exc}\n")
    print(json.dumps({"output": str(args.output), "counts": result["counts"]}))


if __name__ == "__main__":
    main()
