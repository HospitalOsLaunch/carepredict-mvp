"""Predeclared paired old-delay versus finite-SMR development experiment."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.learning import _digest

REGIMES = ("fluid", "strained", "saturated")


def audit_ledger(
    events: list[dict[str, Any]], resources: list[dict[str, str]], config: HospitalConfig
) -> int:
    """Reconstruct stocks from exported transitions, independently of allocator state."""
    by_hour: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        by_hour[e["h"]].append(e)
    hourly = {int(r["h"]): r for r in resources}
    requests: dict[str, dict[str, Any]] = {}
    slots: dict[int, str] = {}
    for h in range(-24 * config.warmup_days, 24 * config.days):
        departed, admitted = set(), set()
        for e in by_hour[h]:
            kind, p = e["type"], e["payload"]
            if kind == "SORTIE":
                if p["destination"] == "SMR":
                    departed.add(e["stay_id"])
                continue
            key = p["request_id"]
            if kind == "SMR_REQUESTED":
                if key in requests:
                    raise ValueError("Repeated SMR request identity")
                requests[key] = {**p, "status": "waiting", "bed": None}
                continue
            r = requests[key]
            if kind == "SMR_RESERVED":
                bed = p["bed"]
                if r["status"] != "waiting" or bed in slots or not 0 <= bed < config.smr.beds:
                    raise ValueError("Invalid SMR ledger reservation")
                if (r["oxygen"] and bed >= config.smr.oxygen_beds) or (
                    r["isolation"] and bed >= config.smr.isolation_beds
                ):
                    raise ValueError("Incompatible SMR ledger reservation")
                slots[bed], r["status"], r["bed"] = key, "reserved", bed
            elif kind == "SMR_ADMITTED":
                if r["status"] != "reserved" or slots.get(p["bed"]) != key:
                    raise ValueError("SMR admission without matching reservation")
                r["status"] = "occupied"
                if p["origin"] == "hospital":
                    admitted.add(e["stay_id"])
            elif kind in ("SMR_RELEASED", "SMR_RESERVATION_EXPIRED", "SMR_CANCELLED"):
                allowed = {
                    "SMR_RELEASED": ("occupied",),
                    "SMR_RESERVATION_EXPIRED": ("reserved",),
                    "SMR_CANCELLED": ("waiting", "reserved"),
                }[kind]
                if r["status"] not in allowed:
                    raise ValueError("Invalid SMR ledger release/cancellation")
                if kind != "SMR_CANCELLED" and p["bed"] != r["bed"]:
                    raise ValueError("SMR ledger release names a different bed")
                if r["bed"] is not None and slots.pop(r["bed"], None) != key:
                    raise ValueError("SMR ledger ownership mismatch")
                r["status"], r["bed"] = (
                    ("waiting" if kind == "SMR_RESERVATION_EXPIRED" else "ended"),
                    None,
                )
        if departed != admitted:
            raise ValueError("Hospital-to-SMR movement does not match ledger admission")
        if h in hourly:
            counts = Counter(r["status"] for r in requests.values())
            expected = {
                "smr_capacity": config.smr.beds,
                "smr_free": config.smr.beds - len(slots),
                "smr_reserved": counts["reserved"],
                "smr_occupied": counts["occupied"],
                "smr_waiting_internal": sum(
                    r["status"] == "waiting" and r["origin"] == "hospital"
                    for r in requests.values()
                ),
                "smr_waiting_external": sum(
                    r["status"] == "waiting" and r["origin"] == "external"
                    for r in requests.values()
                ),
            }
            if any(int(hourly[h][k]) != v for k, v in expected.items()):
                raise ValueError("SMR ledger and hourly stocks disagree")
    return len(hourly)


def configure(worlds: list[HospitalConfig], plan: dict[str, Any]) -> list[HospitalConfig]:
    if plan["variant"] not in ("legacy_delay", "finite_v1"):
        raise ValueError("Unknown SMR comparison arm")
    if len(plan["capacity_fractions"]) != 3:
        raise ValueError("Three predeclared SMR regimes required")
    counts: Counter[str] = Counter()
    output = []
    for cfg in worlds:
        i = counts[cfg.partition]
        counts[cfg.partition] += 1
        regime = (i + i // 3) % 3
        raw = cfg.model_dump(mode="json")
        # Stable identity and cohort in the paired arms, disjoint from lot 15's experiment.
        raw["hospital_id"] = raw["hospital_id"].replace("H15_", "H16_")
        for pole in raw["poles"]:
            pole["pole_id"] = pole["pole_id"].replace("H15_", "H16_")
            for unit in pole["units"]:
                unit["unit_id"] = unit["unit_id"].replace("H15_", "H16_")
        raw["clinical"] = {"destinations": "conditional_survival_v1"}
        if plan["variant"] == "finite_v1":
            nominal = sum(u.beds for u in cfg.units)
            beds = math.ceil(nominal * plan["capacity_fractions"][regime])
            raw["smr"] = {
                "mode": "finite_v1",
                "beds": beds,
                "oxygen_beds": beds,
                "isolation_beds": math.ceil(beds * 0.25),
                "external_arrivals_per_day": nominal * plan["external_arrivals_per_bed_day"],
                **plan["pool_parameters"],
            }
        output.append(HospitalConfig.model_validate(raw))
    return output


def measurements(source: Path) -> dict[str, Any]:
    """Completed and censored patients stay visible; no completed-only wait claim."""
    cfg = HospitalConfig.model_validate_json((source / "config.json").read_text())
    manifest = json.loads((source / "manifest.json").read_text())
    files = ["truth/events.jsonl.gz", "truth/shared_resources_hourly.csv", "truth/units_hourly.csv"]
    for name in files:
        if _digest(source / name) != manifest["files_sha256"][name]:
            raise ValueError("Changed physical evidence")
    counters: Counter[str] = Counter()
    request_h: dict[str, int] = {}
    waits = []
    ledger = []
    by_unit: dict[str, Counter[str]] = defaultdict(Counter)
    with gzip.open(source / files[0], "rt") as stream:
        for line in stream:
            e = json.loads(line)
            h, kind, payload = e["h"], e["type"], e["payload"]
            if kind.startswith("SMR_") or kind == "SORTIE":
                ledger.append(e)
            if kind == "SMR_REQUESTED":
                request_h[payload["request_id"]] = h
            if h < 0 or not kind.startswith("SMR_"):
                continue
            origin = payload["origin"]
            counters[f"{kind}_{origin}"] += 1
            if origin == "hospital":
                by_unit[e["unit_id"]][kind] += 1
            if kind == "SMR_ADMITTED" and origin == "hospital":
                waits.append(h - request_h[payload["request_id"]])
    resources = list(csv.DictReader((source / files[1]).open()))
    units = list(csv.DictReader((source / files[2]).open()))
    sums = {
        k: sum(float(r[k]) for r in units)
        for k in (
            "lits_occupes",
            "attente_urgences_nb",
            "sortants_medicaux_presents",
            "sorties_h",
            "charge_soins_min_h",
            "minutes_non_couvertes_h",
        )
    }
    for r in units:
        for k in ("lits_occupes", "attente_urgences_nb", "sortants_medicaux_presents"):
            by_unit[r["unit_id"]][k] += int(r[k])
    smr: dict[str, Any] = {}
    if cfg.smr.mode == "finite_v1":
        smr["independently_reconciled_hours"] = audit_ledger(ledger, resources, cfg)
        if any(
            int(r["smr_capacity"])
            != sum(int(r[k]) for k in ("smr_free", "smr_reserved", "smr_occupied"))
            for r in resources
        ):
            raise ValueError("SMR exported conservation failed")
        for k in ("smr_waiting_internal", "smr_waiting_external", "smr_waiting_capacity_internal"):
            smr[k + "_person_hours"] = sum(int(r[k]) for r in resources)
        smr["occupied_fraction"] = float(
            np.mean([int(r["smr_occupied"]) / max(1, int(r["smr_capacity"])) for r in resources])
        )
        smr["end_snapshot"] = {k: int(v) for k, v in resources[-1].items() if k.startswith("smr_")}
        smr["completed_request_to_departure_mean_h"] = float(np.mean(waits)) if waits else None
    return {
        "hospital_id": cfg.hospital_id,
        "partition": cfg.partition,
        "hours": cfg.days * 24,
        "nominal_beds": sum(u.beds for u in cfg.units),
        "smr_beds": cfg.smr.beds,
        "sums": sums,
        "smr": smr,
        "events": dict(counters),
        "per_unit": dict(by_unit),
    }


def compare(root: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    reports, physical = {}, {}
    for variant in ("legacy_delay", "finite_v1"):
        result_path = root / variant / "result"
        metadata = json.loads((result_path / "manifest.json").read_text())
        if metadata["status"] != "complete" or metadata["test_opened"]:
            raise ValueError("Only completed development results are allowed")
        if _digest(result_path / "report.json") != metadata["files_sha256"]["report.json"]:
            raise ValueError("Changed prediction results")
        reports[variant] = json.loads((result_path / "report.json").read_text())
        cohort = root / variant / "cohort"
        manifest = json.loads((cohort / "manifest.json").read_text())
        physical[variant] = [
            measurements(cohort / r["hospital_id"] / "truth") for r in manifest["worlds"]
        ]
    from .experiment import macro_scores

    by_regime: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for arm, report in reports.items():
        by_regime[arm] = {}
        for r in physical[arm]:
            i = int(r["hospital_id"].rsplit("_", 1)[-1])
            r["capacity_regime_hypothesis"] = REGIMES[(i + i // 3) % 3]
        for regime in REGIMES:
            ids = {
                r["hospital_id"] for r in physical[arm] if r["capacity_regime_hypothesis"] == regime
            }
            by_regime[arm][regime] = macro_scores(
                [r for r in report["per_entity"] if r["hospital_id"] in ids], 1501701
            )
    result = {
        "status": "exploratory_paired_development_comparison",
        "test_opened": False,
        "physical": physical,
        "macro_forecast": {k: v["macro"] for k, v in reports.items()},
        "forecast_by_capacity_regime": by_regime,
        "caveats": [
            "Capacity regimes are hypotheses, not empirically classified hospitals.",
            "Different targets in paired arms: lower MSE across arms does not mean a better model.",
            "Same model architecture, optimiser, budget and observed input fields; "
            "separate training in each arm.",
            "Mortality correction is held fixed in both arms. Legacy SMR percentage action "
            "is disabled in the finite arm.",
            "Changes reflect the whole SMR mechanism, not a causal estimate of additional beds.",
            "Two validation hospitals per regime; one model seed; "
            "no formal gate or real transfer claim.",
            "Finite horizon and 28-day warmup do not establish stationary queues.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compare(args.root, args.output)


if __name__ == "__main__":
    main()
