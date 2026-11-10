"""Bounded train/dev metadata checks. No files, models, simulator or network.

A successful consistency check is NEVER source qualification. The private
steward must still authenticate lineage/coverage and reconcile reserved roles.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import defaultdict
from typing import Any, cast

from .s0c_world_registry import SCHEMA as WORLD_SCHEMA
from .s0c_world_registry import validate_job_scope

SCHEMA = "hospitalos.s0d_cohort_metadata_v1"
ROLES = {"train", "development_temporal", "development_ood"}
MAX_ITEMS = 4096
SHA = re.compile(r"^[0-9a-f]{64}$")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class InvalidMetadata(ValueError):
    """Malformed or incomplete evidence; not evidence of independence."""


class Conflict(ValueError):
    """A demonstrated contradiction in the supplied metadata."""


def fingerprint(value: Any) -> str:
    """Canonical JSON commitment; pin independently of the supplied bundle."""
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _obj(value: Any, keys: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise InvalidMetadata("SCHEMA_FIELDS")
    return cast(dict[str, Any], value)


def _items(value: Any, *, empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or not (0 if empty else 1) <= len(value) <= MAX_ITEMS:
        raise InvalidMetadata("LIST_SIZE")
    return value


def _id(value: Any) -> str:
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise InvalidMetadata("IDENTITY")
    return value


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise InvalidMetadata("COMMITMENT_MISSING")
    return value


def _ids(value: Any, *, empty: bool = False) -> list[str]:
    result = [_id(x) for x in _items(value, empty=empty)]
    if len(set(result)) != len(result):
        raise InvalidMetadata("DUPLICATE_IDENTITY")
    return result


def _hour(value: Any, low: int = 0, high: int = 8760) -> int:
    if type(value) is not int or not low <= value <= high:
        raise InvalidMetadata("DURATION")
    return value


def _time(value: Any) -> dt.datetime:
    if not isinstance(value, str):
        raise InvalidMetadata("TIMESTAMP")
    try:
        stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            raise ValueError
        return stamp.astimezone(dt.UTC)
    except (ValueError, OverflowError) as exc:
        raise InvalidMetadata("TIMESTAMP") from exc


def _span(row: dict[str, Any]) -> tuple[dt.datetime, dt.datetime]:
    start, end = _time(row["start"]), _time(row["end_exclusive"])
    if start >= end:
        raise InvalidMetadata("SOURCE_BOUNDARIES")
    return start, end


def _table(rows: Any, keys: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for value in _items(rows):
        row = _obj(value, keys)
        ident = _id(row["id"])
        if ident in result:
            raise InvalidMetadata("DUPLICATE_IDENTITY")
        result[ident] = row
    return result


def _components(
    episodes: dict[str, dict[str, Any]],
    dependencies: Any,
) -> dict[str, str]:
    adjacency: dict[str, set[str]] = {k: set() for k in episodes}
    groups: dict[str, list[str]] = defaultdict(list)
    parents: dict[str, list[str]] = {}
    for ident, row in episodes.items():
        _span(row)
        if row["source_clock"] != "fixed_utc_plus_01_no_dst":
            raise InvalidMetadata("SOURCE_CLOCK")
        root = _id(row["root"])
        parent_ids = _ids(row["parents"], empty=True)
        if root not in episodes or any(p not in episodes for p in parent_ids):
            raise InvalidMetadata("UNRESOLVED_ANCESTOR")
        if episodes[root]["root"] != root or episodes[root]["parents"]:
            raise InvalidMetadata("INVALID_ROOT")
        if not parent_ids and root != ident:
            raise InvalidMetadata("ROOT_NOT_REACHABLE")
        if any(episodes[p]["root"] != root for p in parent_ids):
            raise InvalidMetadata("ROOT_DISAGREEMENT")
        parents[ident] = parent_ids
        _sha(row["proof_sha256"])
        groups["root:" + root].append(ident)
        groups["realization:" + _sha(row["realization_sha256"])].append(ident)
        groups["initial:" + _id(row["initial_state_group"])].append(ident)
        for stream in _ids(row["rng_groups"]):
            groups["rng:" + stream].append(ident)
    # Iterative topological validation avoids recursion on long ancestry chains.
    remaining = set(episodes)
    while remaining:
        ready = {x for x in remaining if not (set(parents[x]) & remaining)}
        if not ready:
            raise InvalidMetadata("ANCESTRY_CYCLE")
        remaining -= ready
    seen: set[str] = set()
    for value in _items(dependencies, empty=True):
        row = _obj(value, "id kind members start end_exclusive proof_sha256")
        ident = _id(row["id"])
        if ident in seen:
            raise InvalidMetadata("DUPLICATE_DEPENDENCY")
        seen.add(ident)
        if row["kind"] not in (
            "transfer",
            "shared_shock",
            "shared_resource",
            "shared_staff",
            "shared_rng",
            "inherited_state",
        ):
            raise InvalidMetadata("DEPENDENCY_KIND")
        members = _ids(row["members"])
        if len(members) < 2 or any(x not in episodes for x in members):
            raise InvalidMetadata("UNRESOLVED_DEPENDENCY")
        start, end = _span(row)
        if any(start < _span(episodes[x])[0] or end > _span(episodes[x])[1] for x in members):
            raise InvalidMetadata("DEPENDENCY_COVERAGE")
        _sha(row["proof_sha256"])
        groups["edge:" + ident] = members
    # Keep coupling over the entire episode, even after an edge ends.
    for members in groups.values():
        for member in members[1:]:
            adjacency[members[0]].add(member)
            adjacency[member].add(members[0])
    components: dict[str, str] = {}
    for ident in sorted(episodes):
        if ident in components:
            continue
        pending = [ident]
        components[ident] = ident
        while pending:
            current = pending.pop()
            for other in adjacency[current]:
                if other not in components:
                    components[other] = ident
                    pending.append(other)
    return components


def _bindings(
    manifest: dict[str, Any],
    registry: dict[str, Any],
    index: dict[str, Any],
    episodes: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    bindings = _obj(manifest["bindings"], "world_registry_sha256 exposure_index_sha256")
    if _sha(bindings["world_registry_sha256"]) != fingerprint(registry) or _sha(
        bindings["exposure_index_sha256"]
    ) != fingerprint(index):
        raise Conflict("REGISTRY_COMMITMENT_MISMATCH")
    if registry.get("schema") != WORLD_SCHEMA or registry.get("registry_sha256") != fingerprint(
        {k: v for k, v in registry.items() if k != "registry_sha256"}
    ):
        raise Conflict("WORLD_REGISTRY_INTEGRITY")
    if (
        index.get("schema") != "hospitalos.synthetic_pretraining_registry_s0c_v1"
        or index.get("synthetic_only") is not True
        or any(
            index.get(k) is not False for k in ("training_allowed", "model_forward", "simulation")
        )
    ):
        raise InvalidMetadata("EXPOSURE_SCHEMA")
    partitions = _obj(index.get("partitions"), "train development_temporal development_ood")
    worlds = _table(
        manifest["worlds"],
        "id episode hospital_id canonical_partition registry_partition "
        "source_manifest_sha256 observation_manifest_sha256 action_manifest_sha256",
    )
    validate_job_scope(registry, list(worlds), "development_evaluation")
    rows = registry["readable_worlds"]
    archive_owners: set[tuple[str, str]] = set()
    seed_owners: dict[str, str] = {}
    for wid, world in worlds.items():
        if _id(world["episode"]) not in episodes:
            raise InvalidMetadata("UNRESOLVED_EPISODE")
        _id(world["hospital_id"])
        matches = [row for row in rows if row["world_id"] == wid]
        if len(matches) != 1:
            raise InvalidMetadata("AMBIGUOUS_WORLD")
        match = matches[0]
        seed = _id(match["seed_group"])
        if seed_owners.setdefault(seed, match["partition"]) != match["partition"]:
            raise Conflict("SEED_GROUP_CROSSES_ROLES")
        if (
            match["hospital_id"] != world["hospital_id"]
            or match["partition"] != world["registry_partition"]
        ):
            raise Conflict("WORLD_IDENTITY_MISMATCH")
        source = world["canonical_partition"]
        if source not in ("train", "validation"):
            raise PermissionError("RESERVED_SOURCE")
        if world["registry_partition"] != {"train": "train", "validation": "development"}[source]:
            raise Conflict("PARTITION_RELABEL")
        for key in (
            "source_manifest_sha256",
            "observation_manifest_sha256",
            "action_manifest_sha256",
        ):
            if _sha(world[key]) != match[key]:
                raise Conflict("ARCHIVE_BINDING_MISMATCH")
            if (key, world[key]) in archive_owners:
                raise Conflict("ARCHIVE_REUSED")
            archive_owners.add((key, world[key]))
        roles = ("train", "development_temporal") if source == "train" else ("development_ood",)
        exposures = []
        for role in roles:
            exposed = [r for r in _items(partitions[role]) if r["world_id"] == wid]
            if len(exposed) != 1 or exposed[0]["hospital_id"] != world["hospital_id"]:
                raise Conflict("EXPOSURE_BINDING_MISMATCH")
            if exposed[0]["mechanism_family"] != match["generator_family"]:
                raise Conflict("GENERATOR_BINDING_MISMATCH")
            ep_start, ep_end = _span(episodes[world["episode"]])
            if (ep_end - ep_start) != dt.timedelta(days=_hour(exposed[0]["days"], 1, 366)):
                raise Conflict("EPISODE_DURATION_MISMATCH")
            exposures.append({k: v for k, v in exposed[0].items() if k != "origin_hours"})
            span = _obj(exposed[0]["origin_hours"], "first_origin_h last_origin_h")
            if _hour(span["first_origin_h"]) > _hour(span["last_origin_h"]):
                raise InvalidMetadata("ORIGIN_RANGE")
        if any(e != exposures[0] for e in exposures[1:]):
            raise Conflict("TEMPORAL_WORLD_METADATA_MISMATCH")
        for role in ROLES - set(roles):
            if any(row["world_id"] == wid for row in _items(partitions[role])):
                raise Conflict("EXPOSURE_ROLE_REUSE")
    return worlds


def _check(
    manifest: Any,
    registry: dict[str, Any],
    index: dict[str, Any],
) -> dict[str, Any]:
    m = _obj(
        manifest,
        "schema scope mode bindings episodes dependencies worlds samples "
        "policy coverage preprocessing",
    )
    if m["schema"] != SCHEMA:
        raise InvalidMetadata("SCHEMA_VERSION")
    if m["scope"] != "train_dev_only":
        raise PermissionError("RESERVED_SCOPE")
    if m["mode"] not in ("independent_episode", "within_episode_temporal"):
        raise InvalidMetadata("EVALUATION_MODE")
    episodes = _table(
        m["episodes"],
        "id root parents realization_sha256 initial_state_group "
        "rng_groups proof_sha256 start end_exclusive source_clock",
    )
    components = _components(episodes, m["dependencies"])
    coverage = _obj(m["coverage"], "episodes start end_exclusive completeness proof_sha256")
    if (
        set(_ids(coverage["episodes"])) != set(episodes)
        or coverage["completeness"] != "declared_complete"
    ):
        raise InvalidMetadata("INCOMPLETE_DEPENDENCY_COVERAGE")
    start, end = _span(coverage)
    if any(start > _span(e)[0] or end < _span(e)[1] for e in episodes.values()):
        raise InvalidMetadata("INCOMPLETE_DEPENDENCY_COVERAGE")
    _sha(coverage["proof_sha256"])
    worlds = _bindings(m, registry, index, episodes)
    policy = _obj(
        m["policy"],
        "history_steps step_hours horizons_hours max_age_hours "
        "aggregation_lookback_hours recurrent_lookback_hours extra_embargo_hours "
        "bounds model_spec_sha256",
    )
    n = _hour(policy["history_steps"], 1, 2048)
    step = _hour(policy["step_hours"], 1, 24)
    horizons = [_hour(x, 1, 720) for x in _items(policy["horizons_hours"])]
    if sorted(set(horizons)) != horizons or any(h % step for h in horizons):
        raise InvalidMetadata("HORIZONS")
    if policy["bounds"] != "closed_conservative":
        raise InvalidMetadata("INTERVAL_CONVENTION")
    ip = index["policy"]
    if (
        _sha(policy["model_spec_sha256"]) != index["model_spec_sha256"]
        or n != ip["history_steps"]
        or max(horizons) != ip["max_horizon_hours"]
        or step != 1
    ):
        raise Conflict("MODEL_POLICY_MISMATCH")
    age = _hour(policy["max_age_hours"])
    aggregation = _hour(policy["aggregation_lookback_hours"])
    recurrent = _hour(policy["recurrent_lookback_hours"])
    embargo = dt.timedelta(hours=_hour(policy["extra_embargo_hours"]))
    if _hour(policy["extra_embargo_hours"]) < _hour(ip["embargo_hours"]):
        raise Conflict("EMBARGO_WEAKENED")
    # Age and rolling aggregation can compose; actions extend one whole interval.
    lookback = (n - 1) * step + max(age + aggregation, step, recurrent)
    samples = _table(
        m["samples"], "id world role origin label_cutoff support_start support_end uses"
    )
    if sum(len(_items(row["uses"])) for row in samples.values()) > 16384:
        raise InvalidMetadata("TOTAL_USAGE_LIMIT")
    preprocessing = _obj(m["preprocessing"], "fit_sample_ids proof_sha256")
    _sha(preprocessing["proof_sha256"])
    fit = _ids(preprocessing["fit_sample_ids"], empty=True)
    if any(s not in samples for s in fit):
        raise InvalidMetadata("UNRESOLVED_FIT_SAMPLE")
    if any(samples[s]["role"] != "train" for s in fit):
        raise Conflict("PREPROCESSING_LEAKAGE")
    frames: list[tuple[str, str, dt.datetime, dt.datetime, set[tuple[str, str]]]] = []
    selected: set[tuple[str, dt.datetime]] = set()
    referenced_worlds: set[str] = set()
    for row in samples.values():
        wid, role = _id(row["world"]), row["role"]
        if role not in ROLES:
            raise PermissionError("RESERVED_ROLE")
        if wid not in worlds:
            raise InvalidMetadata("UNRESOLVED_WORLD")
        world = worlds[wid]
        referenced_worlds.add(wid)
        source = world["canonical_partition"]
        if (role == "development_ood") != (source == "validation"):
            raise Conflict("PARTITION_RELABEL")
        ep = episodes[world["episode"]]
        ep_start, ep_end = _span(ep)
        origin, cutoff = _time(row["origin"]), _time(row["label_cutoff"])
        left, right = _time(row["support_start"]), _time(row["support_end"])
        if (wid, origin) in selected:
            raise Conflict("DUPLICATE_ORIGIN")
        selected.add((wid, origin))
        exposed = next(r for r in index["partitions"][role] if r["world_id"] == wid)
        offset = (origin - ep_start).total_seconds() / 3600
        span = exposed["origin_hours"]
        if offset % step or not span["first_origin_h"] <= offset <= span["last_origin_h"]:
            raise Conflict("ORIGIN_OUTSIDE_EXPOSURE")
        if left > origin - dt.timedelta(hours=lookback) or right < origin + dt.timedelta(
            hours=max(horizons)
        ):
            raise Conflict("UNDERSTATED_SOURCE_SUPPORT")
        if not ep_start <= left <= origin < right < ep_end or not right <= cutoff < ep_end:
            raise InvalidMetadata("SOURCE_BOUNDARIES")
        events: set[tuple[str, str]] = set()
        kinds: set[str] = set()
        for value in _items(row["uses"]):
            use = _obj(value, "lineage_id event_id version kind start end available_at")
            key = (_id(use["lineage_id"]), _id(use["event_id"]))
            _hour(use["version"], 1, 1000000)
            kind = use["kind"]
            if kind not in ("observation", "action", "label"):
                raise InvalidMetadata("SOURCE_KIND")
            kinds.add(kind)
            a, b, available = _time(use["start"]), _time(use["end"]), _time(use["available_at"])
            if not left <= a <= b <= right or available < b:
                raise InvalidMetadata("SOURCE_SUPPORT")
            if kind == "label":
                if a <= origin or available > cutoff:
                    raise Conflict("LABEL_CUTOFF")
            elif b > origin or available > origin:
                raise Conflict("ASOF_LEAKAGE")
            if key in events:
                raise InvalidMetadata("DUPLICATE_SOURCE_EVENT")
            events.add(key)
        if kinds != {"observation", "action", "label"}:
            raise InvalidMetadata("INCOMPLETE_USAGE")
        frames.append((components[world["episode"]], role, left, right, events))
    if referenced_worlds != set(worlds):
        raise InvalidMetadata("UNUSED_WORLD")
    if {r[1] for r in frames} - {"train"} == set() or not any(r[1] == "train" for r in frames):
        raise InvalidMetadata("MISSING_COMPARISON_ROLE")
    correlated = 0
    for i, (component, role, left, right, events) in enumerate(frames):
        for other, other_role, other_left, other_right, other_events in frames[i + 1 :]:
            overlap = left <= other_right and other_left <= right
            if role == other_role:
                correlated += int(component == other and overlap)
                continue
            if events & other_events:
                raise Conflict("REUSED_EVENT_ACROSS_ROLES")
            if component != other:
                continue
            if m["mode"] == "independent_episode":
                raise Conflict("DEPENDENCY_CROSSES_ROLES")
            if {role, other_role} != {"train", "development_temporal"}:
                raise Conflict("OOD_DEPENDENCY_CROSSES_ROLES")
            # Train must precede every temporal-dev frame in the component.
            train_end = right if role == "train" else other_right
            dev_start = other_left if role == "train" else left
            if dev_start <= train_end + embargo:
                raise Conflict("TEMPORAL_SUPPORT_OVERLAP")
    counts: dict[str, int] = {}
    for role in sorted({f[1] for f in frames}):
        counts[role] = len({f[0] for f in frames if f[1] == role})
    return {
        "policy_sha256": fingerprint(policy),
        "input_commitments": dict(m["bindings"]),
        "samples_checked": len(frames),
        "worlds_checked": len(worlds),
        "components_by_role": counts,
        "correlated_within_role_pairs": correlated,
    }


def audit_cohort_metadata(
    manifest: Any,
    *,
    world_registry: dict[str, Any],
    exposure_index: dict[str, Any],
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    """Check an independently pinned, in-memory train/dev projection only.

    No schema field can authorize execution or assert authenticated provenance.
    Error receipts contain fixed codes, never raw source identities or paths.
    """
    result: dict[str, Any] = {
        "schema": SCHEMA + ".receipt",
        "scope": "train_dev_only",
        "audit_execution_status": "COMPLETED",
        "metadata_status": "NOT_QUALIFIED",
        "separation_status": "NOT_QUALIFIED",
        "source_authenticity_verified": False,
        "coverage_authenticity_verified": False,
        "holdout_separation_status": "NOT_TESTED",
        "supervision_status": "NOT_QUALIFIED",
        "statistical_design_status": "NOT_QUALIFIED",
        "reserved_holdout_opened": False,
        "training_authorized": False,
        "model_forward_authorized": False,
        "simulation_authorized": False,
        "promotion_authorized": False,
        "reason_codes": [],
    }
    try:
        if fingerprint(manifest) != _sha(expected_manifest_sha256):
            raise Conflict("MANIFEST_PIN_MISMATCH")
        result["manifest_sha256"] = expected_manifest_sha256
        result.update(_check(manifest, world_registry, exposure_index))
        result["metadata_status"] = "CONSISTENT_METADATA_ONLY"
        result["reason_codes"] = ["SOURCE_AND_COVERAGE_ATTESTATION_REQUIRED"]
    except PermissionError:
        result["metadata_status"] = "ACCESS_REFUSED"
        result["reason_codes"] = ["RESERVED_SCOPE_OR_SELECTION"]
    except Conflict as exc:
        result["metadata_status"] = "REJECTED"
        result["separation_status"] = "REJECTED"
        result["reason_codes"] = [str(exc)]
    except InvalidMetadata as exc:
        result["reason_codes"] = [str(exc)]
    except (KeyError, TypeError, ValueError, OverflowError, StopIteration, RecursionError):
        result["reason_codes"] = ["MALFORMED_METADATA"]
    return result
