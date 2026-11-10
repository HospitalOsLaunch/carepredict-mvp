"""S0a: export native V0.4.1 actions from a VERIFIED existing synthetic truth run.

No simulator, GPU, model forward, or training. The exported four levers are
aggregated *requested decisions*, NOT RS-JEPA Phase-A staffing/discharge deltas
and NOT causal effects or confirmed downstream execution outcomes.

A conservative observed clock makes each action interval [h, h+1) available
at its END h+1, aligned to the operational unit snapshot for the same hour.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import tempfile
from pathlib import Path
from typing import Any

from .synthetic_adapter_v1 import ACTION_SCHEMA

LEVER_CHANNELS = (
    "anticipation_sorties",
    "lits_supplementaires",
    "renfort_soignant",
    "acceleration_aval",
)
CLOCK = dt.timezone(dt.timedelta(hours=1))
FILE = "actions/intervals.jsonl.gz"
SOURCE_EVENT_FILE = "truth/events.jsonl.gz"
MAX_COMPRESSED = 128 * 1024 * 1024
MAX_DECOMPRESSED = 512 * 1024 * 1024
MAX_EVENTS = 8_000_000
MAX_DAYS = 1096


def _sha(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _file(root: Path, name: str) -> Path:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Source must be a regular synthetic run directory")
    path = root / name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Source file missing, symlinked or outside truth archive")
    if path.stat().st_size > MAX_COMPRESSED:
        raise ValueError("Synthetic source exceeds read limit")
    return path


def _json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 256 * 1024:
        raise ValueError("Metadata document too large")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Expected JSON object metadata")
    return result


def _start(config: dict[str, Any]) -> dt.datetime:
    date = dt.date.fromisoformat(config["start"])
    return dt.datetime.combine(date, dt.time(), tzinfo=CLOCK)


def _time(start: dt.datetime, h: int) -> str:
    return (start + dt.timedelta(hours=h)).isoformat()


def _read_events(path: Path, expected_count: int) -> list[dict[str, Any]]:
    rows = []
    decompressed = 0
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            decompressed += len(line.encode("utf-8"))
            if decompressed > MAX_DECOMPRESSED or len(rows) >= MAX_EVENTS:
                raise ValueError("Source event log exceeds bounded extraction")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("Malformed truth event")
            rows.append(row)
    if len(rows) != expected_count:
        raise ValueError("Truth event-count mismatch; source not complete")
    return rows


def build_ledger(
    *, truth: dict[str, Any], config: dict[str, Any],
    events: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Pure mapping from already recorded decisions to hourly hospital vectors."""
    if truth.get("synthetic_only") is not True or truth.get("status") != "complete":
        raise ValueError("Only completed existing synthetic truth is admissible")
    if truth.get("data_role") != "simulation_truth_not_training_inputs":
        raise ValueError("Unexpected source role")
    partition = truth.get("partition")
    if partition not in ("train", "development", "validation"):
        raise PermissionError("Reserved test partition is forbidden")
    if config.get("partition") != partition:
        raise ValueError("Configuration partition does not match truth manifest")
    hospital = config.get("hospital_id")
    if not isinstance(hospital, str) or not hospital:
        raise ValueError("Hospital identity is required")
    if truth.get("hospital_id") != hospital:
        raise ValueError("Truth and configuration hospital mismatch")
    days = config.get("days")
    if type(days) is not int or not 1 <= days <= MAX_DAYS:
        raise ValueError("Unexpected simulated days count")
    poles = config.get("poles")
    if not isinstance(poles, list):
        raise ValueError("Missing unit hierarchy")
    units = [
        u.get("unit_id") for pole in poles for u in pole.get("units", [])
    ]
    if (not units or any(not isinstance(u, str) or not u for u in units)
            or len(set(units)) != len(units)):
        raise ValueError("Invalid unique synthetic unit registry")
    # Reference engine exposes the 4 lever decisions once daily at 09:00.
    # A full grid of events is mandatory. Absence on decision hours is an error.
    clock = _start(config)
    by_day_unit: dict[tuple[int, str], dict[str, int]] = {}
    seen_ids: set[str] = set()
    for row in events:
        if row.get("type") != "DECISION":
            continue
        if row.get("hospital_id") != hospital:
            raise ValueError("Action event from another hospital")
        h = row.get("h")
        u = row.get("unit_id")
        if type(h) is not int:
            raise ValueError("Action event hour must be an integer")
        if h < 0:
            continue  # existing warm-up; not part of released training period
        if h >= days * 24 or h % 24 != 9:
            raise ValueError("Unexpected decision time")
        if u not in units or row.get("timestamp") != _time(clock, h):
            raise ValueError("Decision time/unit disagrees with source clock")
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or not event_id or event_id in seen_ids:
            raise ValueError("Duplicate or missing decision event identity")
        seen_ids.add(event_id)
        payload = row.get("payload")
        if (not isinstance(payload, dict) or set(payload) != set(LEVER_CHANNELS)
                or any(type(payload[c]) is not int or payload[c] not in (0, 1)
                       for c in LEVER_CHANNELS)):
            raise ValueError("Unknown, missing or nonbinary physical decision lever")
        slot = (h, u)
        if slot in by_day_unit:
            raise ValueError("Duplicate decision for one unit and day")
        by_day_unit[slot] = {name: payload[name] for name in LEVER_CHANNELS}
    expected = {
        (day * 24 + 9, unit) for day in range(days) for unit in units
    }
    if set(by_day_unit) != expected:
        raise ValueError("Incomplete daily decision coverage; cannot infer zero actions")
    out = []
    nonzero = 0
    for h in range(days * 24):
        values = {
            name: sum(by_day_unit[(h, unit)][name] for unit in units)
            if h % 24 == 9 else 0
            for name in LEVER_CHANNELS
        }
        if any(values.values()):
            nonzero += 1
        end = _time(clock, h + 1)
        out.append({
            "schema": ACTION_SCHEMA,
            "event_id": f"{hospital}:policy_decisions:{h:09d}",
            "version": 1,
            "entity_id": hospital,
            "source_system": "synthetic_action_observed",
            "interval_start": _time(clock, h),
            "interval_end": end,
            "recorded_at": end,
            "available_at": end,
            "values": values,
            "synthetic_only": True,
        })
    return out, {
        "unit_count": len(units),
        "decision_events": len(by_day_unit),
        "hour_intervals": len(out),
        "hours_with_nonzero_action": nonzero,
        "channels": list(LEVER_CHANNELS),
        "clock_mapping": "decision_at_hour_h_recorded_conservatively_at_h_plus_1",
        "zero_proof": "full_09h_daily_unit_decision_grid_verified",
        "action_semantics": "hospital_count_of_requested_levers_not_execution_effect",
        "asof_qualification": "synthetic_synchronous_decision_conservative_end_hour",
    }


def _write_gzip(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("wb") as sink:
        with gzip.GzipFile(filename="", fileobj=sink, mode="wb", mtime=0) as packed:
            with io.TextIOWrapper(packed, encoding="utf-8", newline="\n") as stream:
                for row in rows:
                    stream.write(json.dumps(
                        row, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                    ) + "\n")


def export_existing_truth(source: Path, destination: Path) -> dict[str, Any]:
    """Versioned action export; DOES NOT call a simulator or alter source files."""
    source = source.resolve(strict=True)
    if destination.exists():
        raise FileExistsError("Immutable destination already exists")
    if destination.resolve().is_relative_to(source):
        raise ValueError("Output must not be inside source truth directory")
    manifest_file = _file(source, "manifest.json")
    truth = _json(manifest_file)
    # Reject reserved test before reading event contents.
    if truth.get("partition") not in ("train", "development", "validation"):
        raise PermissionError("Reserved test source cannot be inspected")
    config_file = _file(source, "config.json")
    events_file = _file(source, SOURCE_EVENT_FILE)
    hashes = truth.get("files_sha256")
    if (not isinstance(hashes, dict)
            or _sha(config_file) != hashes.get("config.json")
            or _sha(events_file) != hashes.get(SOURCE_EVENT_FILE)):
        raise ValueError("Truth source files differ from frozen manifest")
    cfg = _json(config_file)
    expected_count = truth.get("counts", {}).get("events_including_warmup")
    if type(expected_count) is not int or expected_count < 1:
        raise ValueError("Missing complete-event count")
    rows = _read_events(events_file, expected_count)
    ledger, coverage = build_ledger(truth=truth, config=cfg, events=rows)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".s0a-", dir=destination.parent) as tmp:
        stage = Path(tmp) / "action-export"
        (stage / "actions").mkdir(parents=True)
        _write_gzip(stage / FILE, ledger)
        result = {
            "schema": ACTION_SCHEMA,
            "status": "complete",
            "synthetic_only": True,
            "partition": truth["partition"],
            "entity_id": truth["hospital_id"],
            "entity_level": "hospital",
            "source_manifest_sha256": _sha(manifest_file),
            "source_clock": "fixed_utc_plus_01_no_dst",
            "file": FILE,
            "files_sha256": {FILE: _sha(stage / FILE)},
            "source_files_sha256": {
                "config.json": _sha(config_file),
                SOURCE_EVENT_FILE: _sha(events_file),
            },
            "coverage": coverage,
            "training": False,
            "model_forward": False,
            "simulator_executed": False,
        }
        (stage / "manifest.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        stage.rename(destination)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="S0a export from an EXISTING verified synthetic truth archive; no simulation."
    )
    parser.add_argument("--truth", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    receipt = export_existing_truth(args.truth, args.output)
    print(json.dumps({
        "status": "S0A_ACTION_EXPORT_COMPLETE_UNTRAINED",
        "source_manifest_sha256": receipt["source_manifest_sha256"],
        "action_channels": receipt["coverage"]["channels"],
        "hour_intervals": receipt["coverage"]["hour_intervals"],
        "simulation": False, "forward": False, "training": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
