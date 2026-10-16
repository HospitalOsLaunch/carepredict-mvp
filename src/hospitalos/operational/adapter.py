"""Export synthetic observations through the source-independent operational contract."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import tempfile
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from hospitalos.synthetic.config import HospitalConfig, load_config
from hospitalos.synthetic.generate import _jsonl
from hospitalos.synthetic.learning import _digest, _events, verify_source
from hospitalos.synthetic.observations import Delivery, observe_snapshots

from .contract import SCHEMA, Cursor, Node, Observation, Topology

MAPPING = {
    "occupancy": "lits_occupes",
    "open_beds": "lits_ouverts",
    "ed_waiting": "attente_urgences_nb",
    "medically_ready": "sortants_medicaux_presents",
    "nurse_count": "ide_presents",
    "aide_count": "as_presents",
    "care_workload_proxy": "charge_soins_min_h",
}
LEGACY_CLOCK = dt.timezone(dt.timedelta(hours=1))


def boundary(config: HospitalConfig, hour: float = 0) -> dt.datetime:
    start = dt.datetime.combine(config.start, dt.time(), LEGACY_CLOCK)
    return (start + dt.timedelta(hours=hour)).astimezone(dt.UTC)


def topology_from_config(config: HospitalConfig) -> Topology:
    activity = {
        "MED_POLY": "medicine",
        "CSG": "geriatrics",
        "CARDIO": "cardiology",
        "PNEUMO": "respiratory",
    }
    nodes: list[dict[str, Any]] = []
    for pole in config.poles:
        nodes.append(
            {
                "entity_id": pole.pole_id,
                "level": "pole",
                "parent_id": config.hospital_id,
                "capacity_beds": float(sum(u.beds for u in pole.units)),
            }
        )
        for unit in pole.units:
            nodes.append(
                {
                    "entity_id": unit.unit_id,
                    "level": "unit",
                    "parent_id": pole.pole_id,
                    "capacity_beds": float(unit.beds),
                    "isolation_beds": float(unit.isolation_beds),
                    "oxygen_beds": float(unit.oxygen_beds),
                    "activity": activity[unit.template],
                }
            )
    nodes.append(
        {
            "entity_id": config.hospital_id,
            "level": "hospital",
            "capacity_beds": float(sum(u.beds for u in config.units)),
        }
    )
    start = boundary(config, -config.warmup_days * 24)
    return Topology(
        topology_id=f"{config.hospital_id}:structure",
        valid_from=start,
        available_at=start,
        nodes=tuple(Node.model_validate(n) for n in nodes),
    )


def convert(
    deliveries: Iterable[Delivery],
    config: HospitalConfig,
    topology: Topology,
    entities: tuple[str, ...],
) -> list[Observation]:
    """Sum observed snapshots at the SAME event time, only after every member arrived.

    This emulates an aggregate feed with inherited omissions/delays. It does not
    assert that real aggregate feeds are generated this way. Fine observations
    are not present in the resulting aggregate-only stream.
    """
    selected = topology.frontier(entities)
    leaves = {u.unit_id for u in config.units}
    membership = {n.entity_id: topology.descendants(n.entity_id) & leaves for n in selected}
    owner = {u: n.entity_id for n in selected for u in membership[n.entity_id]}
    nodes = {n.entity_id: n for n in selected}
    states: dict[tuple[str, float], dict[str, Delivery]] = defaultdict(dict)
    versions: dict[tuple[str, float], int] = defaultdict(int)
    identities: dict[tuple[str, int], str] = {}
    result = []
    for row in sorted(
        deliveries, key=lambda r: (r.available_h, r.event_id, r.event_version, r.delivery_id)
    ):
        key = (row.event_id, row.event_version)
        content = row.content_key()
        if key in identities:
            if identities[key] != content:
                raise ValueError("Conflicting source version")
            continue
        identities[key] = content
        entity = owner[row.unit_id]
        slot = (entity, row.event_h)
        old = states[slot].get(row.unit_id)
        if old is not None and old.event_version >= row.event_version:
            continue
        states[slot][row.unit_id] = row
        if states[slot].keys() != membership[entity]:
            continue
        versions[slot] += 1
        members = list(states[slot].values())
        result.append(
            Observation(
                event_id=f"{config.hospital_id}:{entity}:{row.event_h:g}",
                version=versions[slot],
                entity_id=entity,
                level=nodes[entity].level,
                source_system="synthetic_observed",
                event_time=boundary(config, row.event_h),
                recorded_at=boundary(config, max(r.recorded_h for r in members)),
                ingested_at=boundary(config, max(r.ingested_h for r in members)),
                available_at=boundary(config, max(r.available_h for r in members)),
                values={
                    name: sum(getattr(r.values, field) for r in members)
                    for name, field in MAPPING.items()
                },
            )
        )
    return sorted(result, key=lambda r: (r.available_at, r.event_id, r.version))


def export(source: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    if load_config(source / "config.json").partition == "test":
        raise ValueError("Reserved test cannot be opened by the development adapter")
    if (source / "OVERLAY.json").exists():
        raise ValueError("Runtime overlays are not accepted")
    config, source_hash = verify_source(source)
    topology = topology_from_config(config)
    delivered = observe_snapshots(_events(source), config)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".operational-", dir=output.parent) as temp:
        staging = Path(temp) / "dataset"
        (staging / "observations").mkdir(parents=True)
        (staging / "topology.json").write_text(topology.model_dump_json(indent=2) + "\n")
        modes: dict[str, Any] = {}
        for level in ("unit", "pole", "hospital"):
            frontier = tuple(n.entity_id for n in topology.nodes if n.level == level)
            stream = convert(delivered, config, topology, frontier)
            # The same generic real/synthetic consumer validates the complete stream.
            cursor = Cursor(LEGACY_CLOCK)
            cursor.advance(boundary(config, config.days * 24), stream, topology)
            name = f"observations/{level}.jsonl.gz"
            _jsonl(staging / name, (r.model_dump(mode="json") for r in stream))
            modes[level] = {"frontier": frontier, "path": name, "observations": len(stream)}
        manifest = {
            "schema_version": SCHEMA,
            "status": "complete",
            "data_role": "operational_observations_no_targets",
            "synthetic_only": True,
            "hospital_id": config.hospital_id,
            "partition": config.partition,
            "start": boundary(config).isoformat(),
            "end_exclusive": boundary(config, config.days * 24).isoformat(),
            "source_manifest_sha256": source_hash,
            "source_clock": "fixed_utc_plus_01_no_dst",
            "wire_clock": "UTC_instants",
            "modes": modes,
            "code_sha256": {
                p.name: _digest(p)
                for p in (Path(__file__), Path(__file__).with_name("contract.py"))
            },
            "files_sha256": {
                str(p.relative_to(staging)): _digest(p) for p in staging.rglob("*") if p.is_file()
            },
            "claims": {
                "real_connector_validated": False,
                "engine_europe_paris": False,
                "ght_dynamics": False,
            },
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        staging.rename(output)
    return manifest


def load_observed(path: Path, mode: str) -> tuple[Topology, list[Observation], dict[str, Any]]:
    metadata: dict[str, Any] = json.loads((path / "manifest.json").read_text())
    if metadata.get("partition") == "test":
        raise ValueError("Reserved test cannot be inspected")
    if (
        metadata.get("status") != "complete"
        or metadata.get("data_role") != "operational_observations_no_targets"
        or metadata.get("schema_version") != SCHEMA
    ):
        raise ValueError("Invalid operational dataset")
    name = metadata["modes"][mode]["path"]
    if name != f"observations/{mode}.jsonl.gz":
        raise ValueError("Unexpected observation path")
    for relative in ("topology.json", name):
        if _digest(path / relative) != metadata["files_sha256"].get(relative):
            raise ValueError("Operational dataset checksum mismatch")
    topology = Topology.model_validate_json((path / "topology.json").read_text())
    topology.frontier(metadata["modes"][mode]["frontier"])
    with gzip.open(path / name, "rt") as stream:
        observations = [Observation.model_validate_json(line) for line in stream]
    return topology, observations, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    metadata = export(args.source, args.output)
    print(json.dumps({"status": metadata["status"], "modes": metadata["modes"]}))


if __name__ == "__main__":
    main()
