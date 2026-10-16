"""Reproducible truth-only exports. No learning view is emitted by this first lot."""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import platform
import tempfile
from collections.abc import Iterable
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .config import HospitalConfig
from .documentary import documentary_assumptions
from .engine import SimulationResult, simulate

# Ratios are recomputed after aggregation, never summed or averaged unweighted.
ADDITIVE_FIELDS = (
    "lits_physiques",
    "lits_fermes",
    "lits_ouverts",
    "lits_occupes",
    "lits_sales_ou_nettoyage",
    "lits_propres_libres",
    "lits_supplementaires_actifs",
    "patients_heberges_presents",
    "attente_urgences_nb",
    "attente_urgences_4h_plus",
    "programmes_en_attente",
    "transferts_entrants_en_attente",
    "entrees_h",
    "sorties_h",
    "transferts_internes_entrants_h",
    "transferts_internes_sortants_h",
    "sortants_medicaux_presents",
    "en_attente_aval",
    "en_attente_transport",
    "en_attente_imagerie",
    "en_attente_avis",
    "en_attente_aide_domicile",
    "charge_soins_min_h",
    "capacite_soins_min_h",
    "minutes_non_couvertes_h",
    "soignants_prevus",
    "soignants_presents",
    "ide_presents",
    "as_presents",
    "ei_attendus_h",
    "ei_observes_h",
)


def source_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.py"))
    }


def timestamp(config: HospitalConfig, hour: int) -> str:
    # Explicitly retain the reference engine's fixed UTC+1, without DST.
    start = dt.datetime.combine(config.start, dt.time(), dt.timezone(dt.timedelta(hours=1)))
    return (start + dt.timedelta(hours=hour)).isoformat()


def aggregate(rows: list[dict[str, Any]], level: str) -> list[dict[str, Any]]:
    key_name = f"{level}_id"
    groups: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["h"], row[key_name])
        if key not in groups:
            groups[key] = {
                "hospital_id": row["hospital_id"],
                "h": row["h"],
                "timestamp": row["timestamp"],
                key_name: row[key_name],
                **dict.fromkeys(ADDITIVE_FIELDS, 0),
            }
        for field in ADDITIVE_FIELDS:
            groups[key][field] += row[field]
    for group in groups.values():
        capacity = group["capacite_soins_min_h"]
        group["ratio_charge"] = (
            round(group["charge_soins_min_h"] / capacity, 4) if capacity else None
        )
        group["taux_occupation"] = (
            round(group["lits_occupes"] / group["lits_ouverts"], 6)
            if group["lits_ouverts"]
            else None
        )
        for field in ("charge_soins_min_h", "capacite_soins_min_h", "minutes_non_couvertes_h"):
            group[field] = round(group[field], 2)
        group["ei_attendus_h"] = round(group["ei_attendus_h"], 5)
    return list(groups.values())


def _csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Empty hourly export: {path.name}")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    payload = stream.getvalue().encode("utf-8")
    # A checksum of a truncated file is still a valid checksum. Verify the write
    # against the intended payload before producing a "complete" manifest.
    if path.write_bytes(payload) != len(payload) or path.read_bytes() != payload:
        raise RuntimeError(f"Incomplete CSV write: {path.name}")


def _jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    # Pin gzip metadata too: byte-identical runs, not just identical decompressed content.
    with (
        path.open("wb") as binary,
        gzip.GzipFile(filename="", fileobj=binary, mode="wb", mtime=0) as compressed,
        io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as stream,
    ):
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=int))
            stream.write("\n")


def generate(config: HospitalConfig, output: Path) -> dict[str, Any]:
    """Publish a complete run only after all invariants and writes have succeeded."""
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    return export_result(config, simulate(config), output)


def export_result(
    config: HospitalConfig,
    result: SimulationResult,
    output: Path,
    *,
    policy_description: str = "inherited v0.4.1 policy with privileged simulator information",
) -> dict[str, Any]:
    """Export a completed simulation without re-running it."""
    if output.exists():
        raise FileExistsError(output)
    h0 = config.warmup_days * 24
    units = [unit.unit_id for unit in config.units]
    poles = config.unit_poles
    rows = []
    for original in result.journal.etats:
        if original["h"] < h0:
            continue
        row = dict(original)
        unit_id = units[row.pop("u")]
        row["h"] -= h0
        rows.append(
            {
                "hospital_id": config.hospital_id,
                "pole_id": poles[unit_id],
                "unit_id": unit_id,
                "timestamp": timestamp(config, row["h"]),
                **row,
            }
        )
    shared = [
        {"hospital_id": config.hospital_id, "timestamp": timestamp(config, row["h"]), **row}
        for row in result.resources
    ]

    def events() -> Iterable[dict[str, Any]]:
        # Warm-up events remain available to initialize later as-of reconstruction (negative h).
        for index, event in enumerate(result.journal.events):
            unit_id = units[event["u"]]
            hour = event["h"] - h0
            pid = event["pid"]
            yield {
                "event_id": f"{config.hospital_id}:E{index:09d}",
                "hospital_id": config.hospital_id,
                "pole_id": poles[unit_id],
                "unit_id": unit_id,
                "stay_id": f"{config.hospital_id}:S{pid:06d}" if pid is not None else None,
                "h": hour,
                "timestamp": timestamp(config, hour),
                "type": event["type"],
                "payload": event["payload"],
            }

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".synthetic-", dir=output.parent) as temporary:
        staging = Path(temporary) / "run"
        truth = staging / "truth"
        truth.mkdir(parents=True)
        _csv(truth / "units_hourly.csv", rows)
        _csv(truth / "poles_hourly.csv", aggregate(rows, "pole"))
        _csv(truth / "hospital_hourly.csv", aggregate(rows, "hospital"))
        _csv(truth / "shared_resources_hourly.csv", shared)
        if result.resource_pools:
            _csv(truth / "resource_pools_hourly.csv", result.resource_pools)
        _jsonl(truth / "events.jsonl.gz", events())
        if config.changes:
            _jsonl(
                truth / "changes.jsonl.gz",
                (e for e in events() if e["type"] == "ORGANISATION_CHANGE"),
            )
        (staging / "config.json").write_text(
            config.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        files = {
            str(path.relative_to(staging)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        }
        manifest = {
            "schema_version": "0.1",
            "status": "complete",
            "synthetic_only": True,
            "data_role": "simulation_truth_not_training_inputs",
            "hospital_id": config.hospital_id,
            "partition": config.partition,
            "mechanism_family": config.mechanism_family,
            "dynamics": config.dynamics.model_dump(mode="json"),
            "documentary": config.documentary.model_dump(mode="json"),
            "clinical": config.clinical.model_dump(mode="json"),
            "smr": config.smr.model_dump(mode="json"),
            "observation": {
                "profile": config.observation.model_dump(mode="json"),
                "role": "observation_generator_only_not_policy_inputs",
            },
            "organisation_changes": {
                "count": len(config.changes),
                "schedule_role": "truth_only_not_policy_inputs",
                "windows": "start_inclusive_end_exclusive; fixed UTC+01:00",
            },
            "config_sha256": config.fingerprint,
            "source_sha256": source_hashes(),
            "runtime": {
                "python": platform.python_version(),
                **{name: version(name) for name in ("numpy", "pandas", "pydantic")},
            },
            "counts": {
                "poles": len(config.poles),
                "units": len(config.units),
                "recorded_hours": config.days * 24,
                "unit_hour_rows": len(rows),
                "events_including_warmup": len(result.journal.events),
                "resource_pool_hour_rows": len(result.resource_pools),
            },
            "checks": result.checks,
            "files_sha256": files,
            "assumptions": {
                "clock": "fixed UTC+01:00; no daylight saving",
                "resources": {
                    "v041": "hospital-wide shared queues",
                    "local_v1": "all four resources reserved by pole, same total capacity",
                    "hybrid_v1": "local cleaning/transport; hospital imaging/specialist",
                }[config.mechanism_family],
                "hosting": {
                    "v041": "all hospital units with compatible available beds",
                    "local_v1": "compatible beds within the home pole only",
                    "hybrid_v1": "home pole first, then allowed poles after configured delay",
                }[config.mechanism_family],
                "poles": "resource/routing boundaries for local_v1 and hybrid_v1",
                "arrivals": "template rates times arrival_scale; no occupancy calibration",
                "policy": policy_description,
                "family": config.mechanism_family,
                "dynamics": "versioned engineering assumptions; not calibrated to real data",
                "documentary": documentary_assumptions(config),
                "smr": (
                    "Finite shared SMR beds; current ready scenario need, oxygen/isolation "
                    "compatibility; weekday FIFO offers, expiring reservations, transport, "
                    "occupied stays, outside demand. SMR acceleration has no implemented effect. "
                    "EHPAD/home retain legacy rules. SMR ledger is truth only; not a calibrated "
                    "clinical eligibility or territorial model."
                    if config.smr.mode == "finite_v1"
                    else "legacy sampled delay; no finite SMR beds"
                ),
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.rename(output)
    return manifest
