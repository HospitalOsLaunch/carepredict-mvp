"""Annual documentary variants: physical invariance, message contracts and reservations."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from hospitalos.synthetic.cohort import freeze
from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.counterfactual import exogenous_fingerprint
from hospitalos.synthetic.engine import SimulationResult, simulate
from hospitalos.synthetic.generate import export_result, source_hashes
from hospitalos.synthetic.learning import _events
from hospitalos.synthetic.patient_care import CARE_TYPES, CareDelivery, OnlineCare, observe_care
from hospitalos.synthetic.registry import CohortPlan

CASES: dict[str, dict[str, str]] = {
    "reference": {},
    "admission_prior": {"staff_forecasts": "admission_prior_v1"},
    "milestones": {"staff_forecasts": "milestones_v1"},
    "request_delay": {"downstream_confirmation": "request_delay_v1"},
    "review_capacity": {"downstream_confirmation": "review_capacity_v1"},
    "composed": {
        "staff_forecasts": "milestones_v1",
        "downstream_confirmation": "review_capacity_v1",
    },
}


def digest_rows(rows: Any) -> str:
    value = hashlib.sha256()
    for row in rows:
        value.update(json.dumps(row, sort_keys=True, default=int, allow_nan=False).encode())
        value.update(b"\n")
    return value.hexdigest()


def physics(result: SimulationResult) -> dict[str, str]:
    j = result.journal
    return {
        "exogenous": exogenous_fingerprint(result.simulation.x),
        **{key: digest_rows(getattr(j, key)) for key in ("etats", "actions", "cadre", "sejours")},
        "tasks": digest_rows(sorted(j.taches.items())),
        "physical_events": digest_rows(e for e in j.events if e["type"] not in CARE_TYPES),
        "resources": digest_rows(result.resources),
        "resource_pools": digest_rows(result.resource_pools),
    }


def diagnostics(result: SimulationResult, config: HospitalConfig) -> dict[str, Any]:
    j, offset = result.journal, config.warmup_days * 24
    end = offset + config.days * 24
    exits = {s["pid"]: s["exit_h"] for s in j.sejours if s["admit_h"] >= 0}
    events: Counter[str] = Counter()
    requests: dict[int, tuple[int, str, bool]] = {}
    confirmation_hours: Counter[int] = Counter()
    errors, gaps = [], []
    after_cutoff = pending_forecasts = 0
    matched_confirmations = 0
    for e in j.events:
        h, kind, pid, payload = e["h"], e["type"], e["pid"], e["payload"]
        recorded = offset <= h < end
        if recorded and kind in CARE_TYPES:
            events[kind] += 1
        if kind == "DEMANDE_AVAL":
            requests[pid] = (h, payload["type_aval"], False)
        elif kind == "DEMANDE_AVAL_ANNULEE":
            requests.pop(pid, None)
        elif kind == "PLACE_AVAL_CONFIRMEE":
            request = requests.get(pid)
            if config.documentary.downstream_confirmation != "v041":
                assert request is not None and not request[2]
                assert request[0] < h and request[1] == payload["type_aval"]
                assert result.simulation.x.ouvre[h // 24]
                if config.documentary.downstream_confirmation == "review_capacity_v1":
                    assert h % 24 == 14 and h - request[0] >= 24
                else:
                    assert 9 <= h % 24 < 17
                requests[pid] = (request[0], request[1], True)
                matched_confirmations += 1
                confirmation_hours[h] += 1
            if recorded and pid in exits:
                gap = exits[pid] - h
                assert gap >= 0
                gaps.append(gap)
        elif kind == "DATE_SORTIE_PREVISIONNELLE" and recorded:
            planned = (dt.date.fromisoformat(payload["date_prevue"]) - config.start).days
            assert planned >= (h - offset) // 24
            after_cutoff += planned >= config.days
            if pid in exits:
                errors.append(planned - (exits[pid] - offset) // 24)
            else:
                pending_forecasts += 1
    if config.documentary.downstream_confirmation == "review_capacity_v1":
        assert max(confirmation_hours.values(), default=0) <= max(1, len(config.units) // 2)
    return {
        "source_events_recorded": dict(events),
        "linked_confirmations_checked_including_warmup": matched_confirmations,
        "maximum_confirmations_per_hour": max(confirmation_hours.values(), default=0)
        if config.documentary.downstream_confirmation != "v041"
        else None,
        "forecast_announcements_beyond_extraction": after_cutoff,
        "forecast_announcements_without_observed_exit": pending_forecasts,
        "forecast_diagnostics_on_announcements_with_observed_exit": {
            "n": len(errors),
            "mae_days": float(np.mean(np.abs(errors))) if errors else None,
            "mean_signed_error_days": float(np.mean(errors)) if errors else None,
        },
        "confirmation_to_exit_hours_with_observed_exit": {
            "n": len(gaps),
            "quantiles_10_50_90": np.quantile(gaps, [0.1, 0.5, 0.9]).tolist() if gaps else [],
            "exactly_18h": sum(g == 18 for g in gaps),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    raw = json.loads(
        (root / "configs/synthetic/hospital_observation_intermittent_v1.json").read_text()
    )
    reference = None
    records = []
    for name, documentary in CASES.items():
        config = HospitalConfig.model_validate(
            {**raw, "partition": "development", "documentary": documentary}
        )
        result = simulate(config)
        physical = physics(result)
        if reference is None:
            reference = physical
        assert physical == reference, f"Documentary change altered physics: {name}"
        measures = diagnostics(result, config)
        destination = args.output / name
        manifest = export_result(config, result, destination)
        del result
        for relative, expected in manifest["files_sha256"].items():
            file = destination / relative
            assert hashlib.sha256(file.read_bytes()).hexdigest() == expected
            if file.suffix == ".gz":
                with gzip.open(file, "rb") as stream:
                    while stream.read(1024 * 1024):
                        pass
        deliveries = observe_care(_events(destination), config)
        batches: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for event in _events(destination):
            batches[event["h"]].append(event)
        online = OnlineCare(config)
        incremental: list[CareDelivery] = []
        for hour in range(-config.warmup_days * 24, config.days * 24):
            online.push(hour, batches.pop(hour, []))
            incremental.extend(online.receive(hour + 1))
        assert incremental == deliveries
        record = {
            "case": name,
            "documentary": config.documentary.model_dump(),
            "config_sha256": config.fingerprint,
            "physical_sha256": physical,
            "checks": manifest["checks"],
            "files_verified": len(manifest["files_sha256"]),
            "manifest_sha256": hashlib.sha256(
                (destination / "manifest.json").read_bytes()
            ).hexdigest(),
            "care_receipts_checked": len(deliveries),
            "care_receipts_by_kind": dict(Counter(r.payload.kind for r in deliveries)),
            "online_offline_equal": True,
            **measures,
        }
        records.append(record)
        print(json.dumps(record), flush=True)
        del incremental, deliveries, batches
    registries = {}
    for axis in ("staff_forecasts", "downstream_confirmation"):
        plan = CohortPlan.model_validate_json(
            (root / f"configs/synthetic/cohort_{axis}_v1.json").read_text()
        )
        registry = freeze(plan, args.output / f"registry_{axis}")
        registries[axis] = {"sha256": registry.fingerprint, **registry.summary()}
    report = {
        "status": "complete",
        "synthetic_only": True,
        "test_opened": False,
        "purpose": "development mechanism diagnostics, not clinical accuracy or generalization",
        "days_per_case": raw["days"],
        "warmup_days": raw["warmup_days"],
        "source_sha256": source_hashes(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cases": records,
        "reserved_registries": registries,
        "limits": [
            "Documentary confirmations do not allocate beds or constrain physical discharge.",
            "Forecast diagnostics exclude censored outcomes and weight announcements, not stays.",
            "Variants are inspected on development fixtures; reservation is not blind evaluation.",
            "Global journal event numbering can alter observation noise keys across variants.",
            "No trained model, final test, real data, clinical calibration or transfer claim.",
        ],
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
