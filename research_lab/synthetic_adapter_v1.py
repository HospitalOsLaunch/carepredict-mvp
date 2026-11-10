"""Synthetic adapter v1: versioned observations + same-run action ledger -> windows.

PURE STDLIB; NO torch, simulator, training, network, or model forward.
Every batch here is development-only, not a blind test sample.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import math
from collections import defaultdict
from typing import Any

from .integrated_full_model_v1_contract import fingerprint, validate_spec

SCHEMA = "hospitalos.synthetic_adapter_v1"
ACTION_SCHEMA = "hospitalos.synthetic_action_ledger_v1"
CLOCK = dt.UTC
METRICS = frozenset((
    "ed_waiting", "occupancy", "open_beds", "medically_ready",
    "nurse_count", "aide_count", "care_workload_proxy", "siips_score",
))
ACTIONS = ("staffing_delta", "discharge_delta")
V041_ACTIONS = (
    "anticipation_sorties", "lits_supplementaires",
    "renfort_soignant", "acceleration_aval",
)
FEATURE_SOURCES = {
    "observed_value": "operational_observed",
    "observation_mask": "observed_mask",
    "observation_age": "observed_age",
}


def instant(raw: str) -> dt.datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Missing timestamp")
    stamp = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("All source timestamps require an explicit UTC offset")
    return stamp.astimezone(CLOCK)


def ns(value: dt.datetime) -> int:
    value = value.astimezone(CLOCK)
    return calendar.timegm(value.timetuple()) * 1_000_000_000 + value.microsecond * 1_000


def _order(event: dt.datetime, recorded: dt.datetime | None,
           ingested: dt.datetime | None, available: dt.datetime) -> None:
    clocks = [event, recorded, ingested, available]
    present = [x for x in clocks if x is not None]
    if present != sorted(present):
        raise ValueError("event <= recorded <= ingested <= available must hold")


def _positive_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _action_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _optional_clock(raw: Any) -> dt.datetime | None:
    return None if raw is None else instant(raw)


def validate_observations(rows: list[dict[str, Any]],
                          entity_id: str) -> list[dict[str, Any]]:
    """Validate and normalize the existing OPERATIONAL_V2_RESEARCH_1 event schema."""
    expected = {
        "schema_version", "event_id", "version", "entity_id", "level",
        "source_system", "event_time", "recorded_at", "ingested_at",
        "available_at", "values",
    }
    seen: dict[tuple[str, int], bytes] = {}
    identity: dict[str, tuple[str, str, str]] = {}
    out = []
    for row in rows:
        if not isinstance(row, dict) or not expected.issubset(row):
            raise ValueError("Malformed operational observation row")
        if set(row) - expected:
            raise ValueError("Unknown observation field; source format changed")
        if (row["schema_version"] != "OPERATIONAL_V2_RESEARCH_1"
                or row["source_system"] != "synthetic_observed"
                or row["entity_id"] != entity_id or row["level"] != "hospital"):
            raise ValueError("Incorrect synthetic-only source or observation level")
        if (not isinstance(row["event_id"], str) or not row["event_id"]
                or type(row["version"]) is not int or row["version"] < 1):
            raise ValueError("Invalid event identity or version")
        event = instant(row["event_time"])
        rec = _optional_clock(row["recorded_at"])
        ingest = _optional_clock(row["ingested_at"])
        available = instant(row["available_at"])
        _order(event, rec, ingest, available)
        if not isinstance(row["values"], dict) or not row["values"]:
            raise ValueError("Observation values must be a nonempty mapping")
        for key, value in row["values"].items():
            if key not in METRICS or (value is not None and not _positive_number(value)):
                raise ValueError("Unknown, negative or nonfinite observable value")
        sig = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
        k = (row["event_id"], row["version"])
        if k in seen:
            if seen[k] != sig:
                raise ValueError("Conflicting retransmission of the same event version")
            continue
        seen[k] = sig
        triple = (row["entity_id"], row["source_system"], row["event_time"])
        if row["event_id"] in identity and identity[row["event_id"]] != triple:
            raise ValueError("Event identity changed across versions")
        identity[row["event_id"]] = triple
        out.append({
            "event_id": row["event_id"], "version": row["version"],
            "event": event, "available": available, "values": row["values"],
        })
    return out


def validate_action_ledger(
    rows: list[dict[str, Any]], entity_id: str, step_hours: int,
    channels: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Every interval is explicit, including true zeros. Never impute absent actions."""
    if channels not in (ACTIONS, V041_ACTIONS):
        raise ValueError("Unsupported action channel semantics")
    expected = {
        "schema", "event_id", "version", "entity_id", "source_system",
        "interval_start", "interval_end", "recorded_at", "available_at",
        "values", "synthetic_only",
    }
    seen: dict[tuple[str, int], bytes] = {}
    identity: dict[str, tuple[str, str, str]] = {}
    out = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected:
            raise ValueError("Malformed synthetic action interval")
        if (row["schema"] != ACTION_SCHEMA or row["synthetic_only"] is not True
                or row["source_system"] != "synthetic_action_observed"
                or row["entity_id"] != entity_id):
            raise ValueError("Actions must come from the same approved synthetic-only interface")
        if (not isinstance(row["event_id"], str) or not row["event_id"]
                or type(row["version"]) is not int or row["version"] < 1):
            raise ValueError("Invalid action event identity/version")
        start = instant(row["interval_start"])
        end = instant(row["interval_end"])
        recorded = instant(row["recorded_at"])
        available = instant(row["available_at"])
        if (end - start != dt.timedelta(hours=step_hours)
                or not (start <= end <= recorded <= available)):
            raise ValueError("Bad action interval or availability order")
        if (not isinstance(row["values"], dict)
                or set(row["values"]) != set(channels)
                or not all(_action_number(v) for v in row["values"].values())):
            raise ValueError("Action channels must match one exact synthetic contract")
        if (channels == V041_ACTIONS and any(
                type(row["values"][name]) is not int or row["values"][name] < 0
                for name in channels)):
            raise ValueError("Native V0.4.1 lever counts must be nonnegative integers")
        sig = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
        key = (row["event_id"], row["version"])
        if key in seen:
            if sig != seen[key]:
                raise ValueError("Conflicting action version retransmission")
            continue
        seen[key] = sig
        triple = (row["entity_id"], row["interval_start"], row["interval_end"])
        if row["event_id"] in identity and identity[row["event_id"]] != triple:
            raise ValueError("Action identity changed across versions")
        identity[row["event_id"]] = triple
        out.append({
            "event_id": row["event_id"], "version": row["version"],
            "start": start, "end": end, "available": available,
            "values": row["values"],
        })
    return out


def _latest_versions(rows: list[dict[str, Any]],
                     cutoff: dt.datetime) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["available"] > cutoff:
            continue
        old = latest.get(row["event_id"])
        if old is None or row["version"] > old["version"]:
            latest[row["event_id"]] = row
    return list(latest.values())


def _slots_unique(rows: list[dict[str, Any]], key: str) -> dict[dt.datetime, dict[str, Any]]:
    slots: dict[dt.datetime, dict[str, Any]] = {}
    for row in rows:
        stamp = row[key]
        if stamp in slots and slots[stamp]["event_id"] != row["event_id"]:
            raise ValueError("Multiple source events for a time slot need explicit reconciliation")
        slots[stamp] = row
    return slots


def _topology_capacity(topology: dict[str, Any], entity_id: str,
                       origin: dt.datetime) -> float:
    if (not isinstance(topology, dict)
            or topology.get("schema_version") != "OPERATIONAL_V2_RESEARCH_1"):
        raise ValueError("Invalid operational topology schema")
    start = instant(topology["valid_from"])
    available = instant(topology["available_at"])
    end = _optional_clock(topology.get("valid_to"))
    if available > origin or start > origin or (end is not None and origin >= end):
        raise ValueError("Topology unavailable or invalid at decision origin")
    nodes = topology.get("nodes")
    if not isinstance(nodes, list):
        raise ValueError("Missing topology nodes")
    matches = [n for n in nodes if n.get("entity_id") == entity_id
               and n.get("level") == "hospital"]
    if len(matches) != 1:
        raise ValueError("The hospital entity must have one source topology node")
    cap = matches[0].get("capacity_beds")
    if not _positive_number(cap) or cap <= 0:
        raise ValueError("Hospital bed capacity unknown or invalid")
    return float(cap)


def _feature_metric(entry: dict[str, str]) -> str:
    name = entry["name"]
    kind = entry["kind"]
    if kind not in FEATURE_SOURCES or entry["source"] != FEATURE_SOURCES[kind]:
        raise ValueError("Adapter v1 only supports explicitly sourced value/mask/age")
    suffix = {
        "observed_value": "_observed",
        "observation_mask": "_missing",
        "observation_age": "_age_hours",
    }[kind]
    if not name.endswith(suffix):
        raise ValueError("Feature suffix does not match its declared meaning")
    metric = name[:-len(suffix)]
    if metric not in METRICS:
        raise ValueError("No approved operational measurement mapping")
    return metric


def _spec_metrics(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    metrics: dict[str, dict[str, str]] = defaultdict(dict)
    for f in spec["observation_features"]:
        metric = _feature_metric(f)
        if f["kind"] in metrics[metric]:
            raise ValueError("Repeated feature of same metric and type")
        metrics[metric][f["kind"]] = f["name"]
    if any(set(kinds) != set(FEATURE_SOURCES) for kinds in metrics.values()):
        raise ValueError("Each observed metric needs value, missingness and age features")
    if spec["static_features"] != ["bed_capacity"]:
        raise ValueError("Only known as-of topology capacity may be a static v1 feature")
    if spec["action_features"] not in (list(ACTIONS), list(V041_ACTIONS)):
        raise ValueError("Incompatible synthetic action semantics")
    if any(t["name"] not in METRICS for t in spec["targets"]):
        raise ValueError("Only target measurements actually provided by observations allowed")
    return dict(metrics)


def build_window(
    *,
    spec: dict[str, Any],
    observations: list[dict[str, Any]],
    action_intervals: list[dict[str, Any]],
    topology: dict[str, Any],
    entity_id: str,
    origin: str,
    label_cutoff: str,
    partition: str,
    max_age_hours: int,
) -> dict[str, Any]:
    """Create one deterministic train/dev sample, no truth, inference or training.

    \`label_cutoff\` is strictly later than decision origin. Future observed
    labels never enter feature tensors. Source rows need to have been validated.
    """
    spec = validate_spec(spec)
    if partition not in ("train", "development", "validation"):
        raise PermissionError("Only synthetic train/development may be assembled")
    if type(max_age_hours) is not int or not 0 < max_age_hours <= 168:
        raise ValueError("Max observation age must be explicitly bounded")
    _spec_metrics(spec)
    D = instant(origin)
    L = instant(label_cutoff)
    step = dt.timedelta(hours=spec["step_hours"])
    max_h = max(spec["horizons_hours"])
    if D + dt.timedelta(hours=max_h) > L:
        raise ValueError("Labels not mature at requested cutoff")
    if not entity_id or not isinstance(entity_id, str):
        raise ValueError("Hospital entity ID required")
    static = [_topology_capacity(topology, entity_id, D)]
    obs = validate_observations(observations, entity_id)
    channels = tuple(spec["action_features"])
    acts = validate_action_ledger(
        action_intervals, entity_id, spec["step_hours"], channels
    )
    sources = _latest_versions(obs, D)
    obs_slots = _slots_unique(sources, "event")
    action_slots = _slots_unique(_latest_versions(acts, D), "end")
    grid = [D - step * (spec["history_steps"] - 1 - i)
            for i in range(spec["history_steps"])]
    x: list[list[float]] = []
    event_ns: list[int] = []
    available_ns: list[int] = []
    actions_context: list[list[float]] = []
    action_available_ns: list[int] = []
    masks = 0
    ages = []
    for timestamp in grid:
        eligible = [row for t, row in obs_slots.items() if t <= timestamp]
        last = max(eligible, key=lambda row: row["event"]) if eligible else None
        if last is not None:
            age = (timestamp - last["event"]).total_seconds() / 3600.0
            if age > max_age_hours:
                last = None
        age = 0.0 if last is None else (timestamp - last["event"]).total_seconds() / 3600.0
        row_values = []
        for feature in spec["observation_features"]:
            metric = _feature_metric(feature)
            value = None if last is None else last["values"].get(metric)
            missing = value is None
            if feature["kind"] == "observed_value":
                row_values.append(0.0 if value is None else float(value))
            elif feature["kind"] == "observation_mask":
                row_values.append(float(missing))
                masks += int(missing)
            else:
                row_values.append(0.0 if missing else age)
        x.append(row_values)
        ages.append(age if last is not None else None)
        event_ns.append(ns(last["event"]) if last is not None else ns(timestamp))
        available_ns.append(ns(last["available"]) if last is not None else ns(timestamp))
        action = action_slots.get(timestamp)
        if (action is None or action["start"] != timestamp - step
                or action["end"] != timestamp):
            raise ValueError("Missing complete synthetic action interval; never impute zero")
        actions_context.append([float(action["values"][k]) for k in channels])
        action_available_ns.append(ns(action["available"]))
    # Future targets are frozen separately, under a later label maturity cutoff.
    labels = _slots_unique(_latest_versions(obs, L), "event")
    target_values: list[list[float]] = []
    target_masks: list[list[int]] = []
    for horizon in spec["horizons_hours"]:
        target_at = D + dt.timedelta(hours=horizon)
        row = labels.get(target_at)
        values, present = [], []
        for target in spec["targets"]:
            value = None if row is None else row["values"].get(target["name"])
            values.append(0.0 if value is None else float(value))
            present.append(0 if value is None else 1)
        target_values.append(values)
        target_masks.append(present)
    return {
        "schema": SCHEMA,
        "model_spec_sha256": fingerprint(spec),
        "partition": partition,
        "entity_id": entity_id,
        "origin": D.isoformat(),
        "label_cutoff": L.isoformat(),
        "max_age_hours": max_age_hours,
        "x": [x],
        "static": [static],
        "actions_context": [actions_context],
        "action_available_ns": [action_available_ns],
        "origin_ns": [ns(D)],
        "event_ns": [event_ns],
        "available_ns": [available_ns],
        "action_mode": "no_op",
        "future_actions": None,
        "future_actions_available_ns": None,
        "training_targets": [target_values],
        "training_target_mask": [target_masks],
        "supervision_alignment": {
            "labels_are_factual_future_observations": True,
            "future_intervention_schedule_known_at_origin": False,
            "no_op_forecast_can_be_scored_against_labels": False,
            "training_loss_authorized": False,
            "reason": "Factual labels may include post-origin actions; the no-op "
                      "scenario is not a factual policy forecast.",
        },
        "provenance": {
            "observed_versions_at_origin": len(sources),
            "action_versions_at_origin": len(action_slots),
            "missing_feature_values": masks,
            "max_selected_age_hours": max((a for a in ages if a is not None), default=None),
            "labels_are_future_supervision_not_features": True,
            "future_action_trajectory_is_not_inferred": True,
            "synthetic_only": True,
        },
        "forward_executed": False,
        "training_executed": False,
    }
