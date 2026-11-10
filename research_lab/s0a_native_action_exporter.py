"""S0a: same-world native synthetic decision export, never an RS-JEPA action mapping.

The source of truth is the VERIFIED immutable synthetic run's DECISION events.
No simulation, inference or model training is invoked.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

NATIVE_SCHEMA = "hospitalos.synthetic_native_decisions_v1"
LEVIERS = (
    "anticipation_sorties", "lits_supplementaires",
    "renfort_soignant", "acceleration_aval",
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_native_intervals(
    events: list[dict[str, Any]], *,
    hospital_id: str, units: tuple[str, ...],
    days: int, warmup_hours: int,
) -> list[dict[str, Any]]:
    """Extract every native daily decision, fail on missing/duplicate unit-days.

    DECISION at hour h is applied at the start of [h,h+1). The ledger's
    interval_end is h+1; action knowledge is conservatively h+1. For other
    hours the all-zero vector is only justified by the simulator's explicit
    daily 09:00 decision policy. This is not a real clinical action feed.
    """
    if not hospital_id or not units or len(set(units)) != len(units):
        raise ValueError("Invalid hospital or unit membership")
    if type(days) is not int or days <= 0 or type(warmup_hours) is not int:
        raise ValueError("Invalid simulation time range")
    if warmup_hours < 0 or warmup_hours % 24:
        raise ValueError("Warmup must be whole days")
    if len(LEVIERS) != 4:
        raise AssertionError("Native decision catalog changed")
    decision: dict[tuple[str, int], tuple[int, ...]] = {}
    for row in events:
        if row.get("type") != "DECISION":
            continue
        h = row.get("h")
        if (row.get("hospital_id") != hospital_id or row.get("unit_id") not in units
                or type(h) is not int):
            raise ValueError("Unknown source decision identity or hour")
        if h < 0 or h >= days * 24:
            continue  # warmup/after-end decisions are not this exported interval
        if h % 24 != 9:
            raise ValueError("Decision recorded outside native 09:00 policy")
        payload = row.get("payload")
        if not isinstance(payload, dict) or set(payload) != set(LEVIERS):
            raise ValueError("Decision must preserve the four original levers")
        if any(type(payload[name]) is not int or payload[name] not in (0, 1)
               for name in LEVIERS):
            raise ValueError("Native decision must be binary per lever")
        key = (row["unit_id"], h)
        if key in decision:
            raise ValueError("Duplicate decision for unit and day")
        decision[key] = tuple(payload[name] for name in LEVIERS)
    expected = {(unit, 24 * day + 9) for unit in units for day in range(days)}
    if set(decision) != expected:
        raise ValueError("Native decision journal does not cover every unit/day at 09:00")
    output = []
    for unit in units:
        for h in range(days * 24):
            native = decision.get((unit, h), (0, 0, 0, 0))
            output.append({
                "schema": NATIVE_SCHEMA,
                "event_id": f"{hospital_id}:decision:{unit}:{h}",
                "version": 1,
                "hospital_id": hospital_id,
                "unit_id": unit,
                "hour": h,
                "interval_start_h": h,
                "interval_end_h": h + 1,
                "available_h": h + 1,
                "values": dict(zip(LEVIERS, native, strict=True)),
                "source": "native_simulator_decision",
                "synthetic_only": True,
                "is_policy_decision_hour": h % 24 == 9,
            })
    return output


def export_native(source: Path, output: Path) -> dict[str, Any]:
    """Export from existing truth artifacts only; no synthetic rerun."""
    if output.exists():
        raise FileExistsError("S0a output already exists")
    if (source / "OVERLAY.json").exists():
        raise ValueError("Runtime overlay is not an immutable source")
    # Existing source validator checks source config and immutable truth hashes.
    from hospitalos.synthetic.learning import _events, verify_source

    config, source_manifest_sha256 = verify_source(source)
    if config.partition == "test":
        raise PermissionError("Reserved synthetic test source cannot be opened")
    # _events verifies only the manifest hash via verify_source above.
    rows = build_native_intervals(
        list(_events(source)),
        hospital_id=config.hospital_id,
        units=tuple(u.unit_id for u in config.units),
        days=config.days,
        warmup_hours=config.warmup_days * 24,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".s0a-", dir=output.parent) as temp:
        staging = Path(temp) / "native"
        target = staging / "actions" / "native_unit_intervals.jsonl.gz"
        target.parent.mkdir(parents=True)
        with gzip.open(target, "wt", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
        manifest = {
            "schema": NATIVE_SCHEMA,
            "status": "complete",
            "synthetic_only": True,
            "data_role": "native_policy_decisions_not_rs_jepa_deltas",
            "source_manifest_sha256": source_manifest_sha256,
            "source_clock": "fixed_utc_plus_01_no_dst",
            "partition": config.partition,
            "hospital_id": config.hospital_id,
            "days": config.days,
            "units": sorted(u.unit_id for u in config.units),
            "native_levers": list(LEVIERS),
            "time_convention": "decision h starts interval [h,h+1); known at h+1",
            "assumed_policy": "all four decisions per unit at 09:00; zero at other hours",
            "training_input_approved": False,
            "rs_jepa_two_channel_compatible": False,
            "future_policy_known_at_origin": False,
            "source_event_count": len(rows),
            "files_sha256": {"actions/native_unit_intervals.jsonl.gz": digest(target)},
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.rename(output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="S0a native synthetic actions only")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metadata = export_native(args.source, args.output)
    print(json.dumps({
        "status": "NATIVE_SYNTHETIC_ACTION_EXPORT_ONLY",
        "events": metadata["source_event_count"],
        "training_input_approved": False,
        "rs_jepa_two_channel_compatible": False,
    }))


if __name__ == "__main__":
    main()
