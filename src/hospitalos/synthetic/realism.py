"""Descriptive truth diagnostics, with explicit windows and no realism pass/fail claim."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import platform
import tempfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from .config import HospitalConfig, load_config
from .learning import _digest, _events, verify_source

VERSION = "REALISM_MEASURES_V1"
TERMINALS = {"ORIENTATION_HORS_PERIMETRE", "DEPROGRAMMATION", "TRANSFERT_REFUSE"}
MOVEMENTS = {"DEMANDE_ADMISSION", "ADMISSION", "SORTIE", "TRANSFERT_INTERNE", "SORTANT_MEDICAL"}
HOURLY = (
    "lits_physiques",
    "lits_fermes",
    "lits_ouverts",
    "lits_occupes",
    "attente_urgences_nb",
    "patients_heberges_presents",
    "sortants_medicaux_presents",
    "en_attente_aval",
    "soignants_prevus",
    "soignants_presents",
    "ide_presents",
    "charge_soins_min_h",
    "minutes_non_couvertes_h",
)


@dataclass
class Stay:
    requested: int
    target: str
    mode: str
    age: int
    admitted: int | None = None
    admission_unit: str | None = None
    departed: int | None = None
    discharge_unit: str | None = None
    destination: str | None = None
    ready: int | None = None
    terminal: str | None = None
    terminal_h: int | None = None
    active_unit: str | None = None
    segment_start: int | None = None
    segments: list[tuple[str, int, int]] = field(default_factory=list)


def ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0 else None


def distribution(values: Iterable[float]) -> dict[str, int | float | None]:
    array = np.asarray(list(values), dtype=float)
    if not np.isfinite(array).all():
        raise ValueError("Nonfinite diagnostic value")
    return {
        "n": len(array),
        "mean": float(array.mean()) if len(array) else None,
        "p50": float(np.quantile(array, 0.5)) if len(array) else None,
        "p90": float(np.quantile(array, 0.9)) if len(array) else None,
        "p99": float(np.quantile(array, 0.99)) if len(array) else None,
    }


def overlap(start: int, stop: int, end: int) -> int:
    return max(0, min(stop, end) - max(start, 0))


def _close_segment(stay: Stay, hour: int) -> None:
    if stay.active_unit is None or stay.segment_start is None or hour < stay.segment_start:
        raise ValueError("Movement without a consistent active segment")
    stay.segments.append((stay.active_unit, stay.segment_start, hour))


def reconstruct(config: HospitalConfig, events: Iterable[dict[str, Any]]) -> list[Stay]:
    """Warm-up initializes prevalence; future events and impossible paths fail closed."""
    end = config.days * 24
    units = config.unit_poles
    stays: dict[str, Stay] = {}
    last_hour = -config.warmup_days * 24
    for event in events:
        hour = event["h"]
        if type(hour) is not int or not last_hour <= hour < end:
            raise ValueError("Events must be chronological and inside the simulation window")
        last_hour = hour
        if event["hospital_id"] != config.hospital_id or event["unit_id"] not in units:
            raise ValueError("Event belongs to an unknown hospital/unit")
        kind, sid, unit = event["type"], event.get("stay_id"), event["unit_id"]
        if kind not in MOVEMENTS | TERMINALS:
            continue
        if not isinstance(sid, str) or not sid.startswith(config.hospital_id + ":"):
            raise ValueError("Missing or foreign stay identifier")
        payload = event["payload"]
        if kind == "DEMANDE_ADMISSION":
            if sid in stays:
                raise ValueError("Duplicate admission request")
            age = payload["age"]
            mode = payload["mode_entree"]
            if (
                type(age) is not int
                or not 0 <= age <= 120
                or mode not in {"urgences", "programme", "transfert_entrant"}
            ):
                raise ValueError("Invalid request population")
            stays[sid] = Stay(hour, unit, mode, age)
            continue
        if sid not in stays:
            raise ValueError("Missing admission request, including warm-up history")
        stay = stays[sid]
        if kind == "ADMISSION":
            if stay.admitted is not None or stay.terminal is not None:
                raise ValueError("Duplicate admission or admission after terminal outcome")
            if payload["attente_h"] != hour - stay.requested:
                raise ValueError("Admission delay contradicts its request")
            stay.admitted = stay.segment_start = hour
            stay.active_unit = stay.admission_unit = unit
        elif kind in TERMINALS:
            if stay.admitted is not None or stay.terminal is not None:
                raise ValueError("Invalid non-admission outcome")
            stay.terminal, stay.terminal_h = kind, hour
        elif kind == "SORTANT_MEDICAL":
            if stay.active_unit != unit or stay.ready is not None:
                raise ValueError("Invalid or repeated readiness event")
            stay.ready = hour
        elif kind == "TRANSFERT_INTERNE":
            if stay.active_unit != payload["depuis"] or unit == stay.active_unit:
                raise ValueError("Transfer does not match the patient's current unit")
            _close_segment(stay, hour)
            stay.active_unit, stay.segment_start = unit, hour
        elif kind == "SORTIE":
            if stay.active_unit != unit:
                raise ValueError("Discharge does not match the patient's current unit")
            _close_segment(stay, hour)
            stay.departed, stay.discharge_unit = hour, unit
            stay.destination = str(payload["destination"])
            stay.active_unit = stay.segment_start = None
    for stay in stays.values():
        if stay.active_unit is not None:
            _close_segment(stay, end)
    return list(stays.values())


def _grid(
    config: HospitalConfig, rows: Iterable[dict[str, Any]]
) -> dict[str, dict[str, NDArray[np.float64]]]:
    end, members = config.days * 24, config.unit_poles
    result = {u: {key: np.zeros(end) for key in HOURLY} for u in members}
    seen: set[tuple[int, str]] = set()
    for row in rows:
        hour, unit = int(row["h"]), str(row["unit_id"])
        if (
            unit not in members
            or not 0 <= hour < end
            or (hour, unit) in seen
            or row["hospital_id"] != config.hospital_id
            or row["pole_id"] != members[unit]
        ):
            raise ValueError("Invalid or duplicate hourly state")
        seen.add((hour, unit))
        for key in HOURLY:
            value = float(row[key])
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Invalid nonnegative state: {key}")
            result[unit][key][hour] = value
        r = result[unit]
        if (
            r["lits_physiques"][hour] != r["lits_fermes"][hour] + r["lits_ouverts"][hour]
            or r["lits_occupes"][hour] > r["lits_ouverts"][hour]
            or r["patients_heberges_presents"][hour] > r["lits_occupes"][hour]
            or r["sortants_medicaux_presents"][hour] > r["lits_occupes"][hour]
            or r["en_attente_aval"][hour] > r["sortants_medicaux_presents"][hour]
            or r["ide_presents"][hour] > r["soignants_presents"][hour]
        ):
            raise ValueError("Inconsistent capacity, presence or staffing state")
    if len(seen) != end * len(members):
        raise ValueError("Incomplete hourly grid")
    return result


def _histogram(values: Iterable[str | int]) -> dict[str, int]:
    return dict(sorted(Counter(str(x) for x in values).items()))


def _stays_summary(stays: list[Stay], end: int) -> dict[str, Any]:
    admissions = [s for s in stays if s.admitted is not None and 0 <= s.admitted < end]
    discharges = [s for s in stays if s.departed is not None and 0 <= s.departed < end]
    paired = [s for s in admissions if s.departed is not None]
    ready_completed = [s for s in discharges if s.ready is not None]
    ready_censored = [s for s in stays if s.ready is not None and s.departed is None]
    return {
        "admissions_in_window": len(admissions),
        "discharges_in_window": len(discharges),
        "admitted_and_discharged_in_window": len(paired),
        "prewindow_admissions_discharged_in_window": sum(
            s.admitted is not None and s.admitted < 0 for s in discharges
        ),
        "admissions_in_window_still_present_at_end": sum(s.departed is None for s in admissions),
        "all_stays_present_at_end": sum(s.active_unit is not None for s in stays),
        "age_of_admissions": distribution(s.age for s in admissions),
        "admissions_age_75plus": sum(s.age >= 75 for s in admissions),
        "admission_modes": _histogram(s.mode for s in admissions),
        "hospital_los_days_discharges_in_window": distribution(
            (s.departed - s.admitted) / 24
            for s in discharges
            if s.departed is not None and s.admitted is not None
        ),
        "hospital_los_days_admitted_and_discharged_in_window": distribution(
            (s.departed - s.admitted) / 24
            for s in paired
            if s.departed is not None and s.admitted is not None
        ),
        "discharge_destinations": _histogram(s.destination for s in discharges if s.destination),
        "first_ready_to_exit_h_completed": distribution(
            s.departed - s.ready
            for s in ready_completed
            if s.departed is not None and s.ready is not None
        ),
        "first_ready_to_exit_h_by_final_destination_completed": {
            destination: distribution(
                s.departed - s.ready
                for s in ready_completed
                if s.destination == destination and s.departed is not None and s.ready is not None
            )
            for destination in sorted({s.destination for s in ready_completed if s.destination})
        },
        "discharges_without_readiness_event": len(discharges) - len(ready_completed),
        "first_ready_to_end_h_censored_lower_bounds": distribution(
            end - s.ready for s in ready_censored if s.ready is not None
        ),
        "completed_readiness_wait_is_conditional_not_survival_estimate": True,
    }


def _ed_summary(stays: list[Stay], end: int) -> dict[str, Any]:
    requests = [s for s in stays if s.mode == "urgences" and 0 <= s.requested < end]
    admitted = [s for s in requests if s.admitted is not None]
    pending = [s for s in requests if s.admitted is None and s.terminal is None]
    durations = [s.admitted - s.requested for s in admitted if s.admitted is not None]
    return {
        "request_cohort_n": len(requests),
        "admitted_n": len(admitted),
        "nonadmitted_terminal_outcomes": _histogram(s.terminal for s in requests if s.terminal),
        "pending_at_end_n": len(pending),
        "decision_to_admission_h_conditional_on_admission": distribution(durations),
        "admitted_wait_gt4h_share": ratio(sum(h > 4 for h in durations), len(durations)),
        "nonadmitted_terminal_wait_h": distribution(
            s.terminal_h - s.requested for s in requests if s.terminal_h is not None
        ),
        "pending_wait_h_censored_lower_bounds": distribution(end - s.requested for s in pending),
        "decision_08_12_h_conditional_on_admission": distribution(
            s.admitted - s.requested
            for s in admitted
            if s.admitted is not None and 8 <= s.requested % 24 < 12
        ),
        "decision_16_20_h_conditional_on_admission": distribution(
            s.admitted - s.requested
            for s in admitted
            if s.admitted is not None and 16 <= s.requested % 24 < 20
        ),
        "age_75plus_wait_h_conditional_on_admission": distribution(
            s.admitted - s.requested for s in admitted if s.admitted is not None and s.age >= 75
        ),
    }


def _hourly_summary(r: dict[str, NDArray[np.float64]]) -> dict[str, Any]:
    occupied, opened = r["lits_occupes"], r["lits_ouverts"]
    available = opened > 0
    present, planned = r["soignants_presents"], r["soignants_prevus"]
    total = {key: float(value.sum()) for key, value in r.items()}
    return {
        "hours": len(occupied),
        "zero_open_capacity_hours": int((~available).sum()),
        "occupied_bed_hours": total["lits_occupes"],
        "open_bed_hours": total["lits_ouverts"],
        "occupancy_open_capacity_weighted": ratio(total["lits_occupes"], total["lits_ouverts"]),
        "occupancy_hourly_distribution": distribution(occupied[available] / opened[available]),
        "hours_at_full_open_capacity_share": ratio(
            int(((occupied >= opened) & available).sum()), int(available.sum())
        ),
        "closed_bed_hours_share": ratio(total["lits_fermes"], total["lits_physiques"]),
        "hosted_patient_hours": total["patients_heberges_presents"],
        "ed_queue_patient_hours": total["attente_urgences_nb"],
        "medically_ready_present_hours": total["sortants_medicaux_presents"],
        "ready_with_smr_ehpad_destination_hours": total["en_attente_aval"],
        "patients_per_present_nurse_hour_weighted": ratio(
            total["lits_occupes"], total["ide_presents"]
        ),
        "staff_hours_planned": total["soignants_prevus"],
        "staff_hours_present": total["soignants_presents"],
        "net_staff_deficit_signed_share": (
            1 - total["soignants_presents"] / total["soignants_prevus"]
            if total["soignants_prevus"]
            else None
        ),
        "staff_hours_below_plan": float(np.maximum(planned - present, 0).sum()),
        "staff_hours_above_plan": float(np.maximum(present - planned, 0).sum()),
        "gross_absenteeism": None,
        "gross_absenteeism_status": "unmeasurable_from_net_presence_export",
        "care_proxy_minutes_per_patient_day": ratio(
            total["charge_soins_min_h"] * 24, total["lits_occupes"]
        ),
        "uncovered_minutes_hours_share": float((r["minutes_non_couvertes_h"] > 0).mean()),
        "capacity_caused_downstream_blocked_hours": None,
        "capacity_caused_downstream_blocked_hours_status": "not_identified_by_readiness_alone",
        "coordination_minutes": None,
        "coordination_minutes_status": "not_instrumented",
    }


def measure(
    config: HospitalConfig,
    events: Iterable[dict[str, Any]],
    rows: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Pure measurement: truth may score the simulator, never become learner features."""
    if config.partition == "test":
        raise ValueError("Reserved test worlds cannot be inspected by this development scorecard")
    end = config.days * 24
    stays, grid = reconstruct(config, events), _grid(config, rows)
    stock = {u: np.zeros(end + 1, dtype=np.int64) for u in grid}
    ed_queue = {u: np.zeros(end + 1, dtype=np.int64) for u in grid}
    ready_hours: Counter[str] = Counter()
    ready_excess: Counter[str] = Counter()
    for stay in stays:
        for unit, start, stop in stay.segments:
            left, right = max(0, start), min(end, stop)
            if left < right:
                stock[unit][left] += 1
                stock[unit][right] -= 1
                if stay.ready is not None:
                    ready_hours[unit] += overlap(max(start, stay.ready), stop, end)
                    ready_excess[unit] += overlap(max(start, stay.ready + 24), stop, end)
        if stay.mode == "urgences":
            queue_stop = stay.admitted if stay.admitted is not None else stay.terminal_h
            left, right = (
                max(0, stay.requested),
                min(end, queue_stop if queue_stop is not None else end),
            )
            if left < right:
                ed_queue[stay.target][left] += 1
                ed_queue[stay.target][right] -= 1
    for unit in grid:
        if not np.array_equal(np.cumsum(stock[unit])[:-1], grid[unit]["lits_occupes"]):
            raise ValueError(f"Event/hourly occupancy reconciliation failed: {unit}")
        if not np.array_equal(np.cumsum(ed_queue[unit])[:-1], grid[unit]["attente_urgences_nb"]):
            raise ValueError(f"Event/hourly ED queue reconciliation failed: {unit}")
    members = {u: [u] for u in grid}
    members.update({p.pole_id: [u.unit_id for u in p.units] for p in config.poles})
    members[config.hospital_id] = list(grid)
    entities: dict[str, Any] = {}
    for entity, units in members.items():
        aggregated = {k: sum((grid[u][k] for u in units), np.zeros(end)) for k in HOURLY}
        summary = _hourly_summary(aggregated)
        summary.update(
            first_ready_present_hours=sum(ready_hours[u] for u in units),
            first_ready_beyond_24h_present_hours=sum(ready_excess[u] for u in units),
            first_ready_beyond_24h_bed_hours_share=ratio(
                sum(ready_excess[u] for u in units), summary["occupied_bed_hours"]
            ),
        )
        months: dict[str, list[int]] = {}
        for hour in range(end):
            month = (config.start + dt.timedelta(days=hour // 24)).strftime("%Y-%m")
            months.setdefault(month, []).append(hour)
        summary["monthly"] = {
            month: {
                "occupied_bed_hours": float(aggregated["lits_occupes"][indices].sum()),
                "open_bed_hours": float(aggregated["lits_ouverts"][indices].sum()),
                "occupancy": ratio(
                    float(aggregated["lits_occupes"][indices].sum()),
                    float(aggregated["lits_ouverts"][indices].sum()),
                ),
            }
            for month, indices in months.items()
        }
        entities[entity] = {
            "level": "unit"
            if entity in grid
            else ("hospital" if entity == config.hospital_id else "pole"),
            "units": units,
            "hourly": summary,
            "admissions_by_actual_admission_unit": sum(
                s.admission_unit in units and s.admitted is not None and 0 <= s.admitted < end
                for s in stays
            ),
            "admissions_by_requested_unit": sum(
                s.target in units and s.admitted is not None and 0 <= s.admitted < end
                for s in stays
            ),
            "discharges_by_actual_discharge_unit": sum(
                s.discharge_unit in units and s.departed is not None and 0 <= s.departed < end
                for s in stays
            ),
            "ed_by_requested_unit": _ed_summary([s for s in stays if s.target in units], end),
        }
    discharges = [s for s in stays if s.departed is not None and 0 <= s.departed < end]
    return {
        "protocol_id": VERSION,
        "status": "descriptive_only_external_realism_not_validated",
        "synthetic_only": True,
        "data_role": "simulation_truth_diagnostics_not_training_inputs",
        "hospital_id": config.hospital_id,
        "partition": config.partition,
        "window": {
            "start": config.start.isoformat(),
            "end_exclusive": (config.start + dt.timedelta(days=config.days)).isoformat(),
            "hours": end,
            "clock": "fixed UTC+01:00; no DST",
        },
        "checks": {
            "occupancy_reconciled_each_unit_hour": True,
            "ed_queue_reconciled_each_unit_hour": True,
        },
        "stays": _stays_summary(stays, end),
        "case_mix_by_requested_template": {
            template: _stays_summary(
                [
                    s
                    for s in stays
                    if s.target in {u.unit_id for u in config.units if u.template == template}
                ],
                end,
            )
            for template in sorted({u.template for u in config.units})
        },
        "discharge_hour_counts": _histogram(
            s.departed % 24 for s in discharges if s.departed is not None
        ),
        "discharge_weekday_counts": _histogram(
            (config.start + dt.timedelta(days=s.departed // 24)).weekday()
            for s in discharges
            if s.departed is not None
        ),
        "entities": entities,
        "limits": [
            "Discharge LOS is hospital elapsed time, not residence time in a requested unit.",
            "Admission-cohort completed LOS is reported separately and is selection-biased.",
            "ED waiting concerns requests to this perimeter, not the whole emergency department.",
            "Nonadmitted/unresolved requests remain visible; their waiting time is not zero.",
            "ORIENTATION_HORS_PERIMETRE does not establish an inter-hospital transfer.",
            "First readiness and SMR/EHPAD destination do not identify a causal capacity blockage.",
            "Complete-case waiting quantiles are not censoring-adjusted population estimates.",
            "Care minutes are synthetic proxies, not SIIPS or measured staff work.",
            "Staff presence after replacements/extra staff cannot identify gross absenteeism.",
            "No empirical acceptance bands or real hospital performance claims are implied.",
        ],
    }


def score_run(source: Path) -> tuple[dict[str, Any], str]:
    # Reject even checksum reads of a declared reserved test's truth files.
    if load_config(source / "config.json").partition == "test":
        raise ValueError("Reserved test worlds cannot be inspected")
    overlay = source / "OVERLAY.json"
    if (
        overlay.exists()
        and json.loads(overlay.read_text()).get("experimental_overlay") is not False
    ):
        raise ValueError(
            "Runtime overlay is not versioned in HospitalConfig; provenance is incomplete"
        )
    config, manifest_hash = verify_source(source)
    with (source / "truth/units_hourly.csv").open(newline="", encoding="utf-8") as stream:
        report = measure(config, _events(source), csv.DictReader(stream))
    return report, manifest_hash


def load_references(path: Path) -> dict[str, Any]:
    """This provisional registry cannot silently introduce an empirical acceptance gate."""
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") != "provisional_context_not_acceptance_bands":
        raise ValueError("Unsupported reference registry status")
    entries = data.get("references", [])
    ids = [entry["id"] for entry in entries]
    if not entries or len(ids) != len(set(ids)):
        raise ValueError("Empty or duplicate reference registry")
    for entry in entries:
        if (
            entry.get("acceptance_band") is not None
            or entry.get("evaluation_role") != "context_only"
        ):
            raise ValueError("Provisional references cannot become pass/fail acceptance bands")
        for key in ("indicator", "definition", "population", "comparability", "source_status"):
            if not entry.get(key):
                raise ValueError(f"Incomplete reference definition: {key}")
    return data


def publish(source: Path, output: Path, references: Path | None = None) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    report, manifest_hash = score_run(source)
    if references is not None:
        report["external_references"] = load_references(references)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".realism-", dir=output.parent) as temp:
        staging = Path(temp) / "report"
        staging.mkdir()
        path = staging / "scorecard.json"
        path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
        manifest = {
            "status": "complete",
            "protocol_id": VERSION,
            "source_manifest_sha256": manifest_hash,
            "measurement_source_sha256": _digest(Path(__file__)),
            "runtime": {"python": platform.python_version(), "numpy": np.__version__},
            "files_sha256": {"scorecard.json": _digest(path)},
            "external_realism_validated": False,
            "references_sha256": _digest(references) if references is not None else None,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        staging.rename(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--references", type=Path)
    args = parser.parse_args()
    report = publish(args.source, args.output, args.references)
    print(
        json.dumps({"protocol_id": VERSION, "status": report["status"], "output": str(args.output)})
    )


if __name__ == "__main__":
    main()
