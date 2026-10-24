"""Generate the cockpit's demonstration data by running the REAL hybrid planner.

    PYTHONPATH=src:. python web/dev/build_fixtures.py

Outputs web/src/fixtures/*.json. Nothing is hand-written: plans, readiness,
candidates, traces, live snapshots and quality reports come from the backend.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo_unit import (  # noqa: E402
    AT,
    SOURCE,
    UNIT,
    incomplete,
    live_batch,
    live_policy,
    nominal,
    perturbations,
)

from hospitalos.hybrid.live_models import PlanningOptions  # noqa: E402
from hospitalos.hybrid.live_store import LiveStore  # noqa: E402
from hospitalos.hybrid.models import Action  # noqa: E402
from hospitalos.hybrid.planning import PlanRequest, plan  # noqa: E402
from hospitalos.hybrid.scenarios import sample_future  # noqa: E402
from hospitalos.hybrid.scoring import score  # noqa: E402
from hospitalos.hybrid.shadow import summarize  # noqa: E402
from hospitalos.hybrid.simulation import simulate  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "src" / "fixtures"


def scenario(name: str, label: str, request: PlanRequest) -> dict[str, Any]:
    proposal = plan(request)
    state = request.state()
    traces: dict[str, Any] = {}
    if proposal.decision != "abstain":
        future = sample_future(state, request.future, request.seed, 0)
        for key, action in (("baseline", Action(kind="no_op")), ("selected", proposal.selected)):
            trajectory = simulate(
                state,
                action,
                request.assumptions,
                seed=request.seed,
                scenario=0,
                horizon_minutes=request.horizon_minutes,
                future=future,
                preparation=request.preparation,
            )
            traces[key] = {
                "trajectory": asdict(trajectory),
                "score": asdict(score(state, trajectory, expected_future=future)),
            }
    return {
        "id": name,
        "label": label,
        "source": "fixture",
        "request": request.model_dump(mode="json"),
        "state": state.model_dump(mode="json"),
        "plan": proposal.model_dump(mode="json"),
        "trace": traces or None,
    }


def live() -> dict[str, Any]:
    store = LiveStore(live_policy())
    try:
        store.ingest(live_batch(), AT)
        now = AT + timedelta(seconds=45)
        snapshot = store.snapshot(now)
        options = PlanningOptions(
            assumptions=nominal().assumptions, scenarios=16, horizon_minutes=480
        )
        episode = store.record_shadow(now, options)
        # A heartbeat without fresh confirmations: the next assessment must be gated.
        later = AT + timedelta(minutes=4)
        store.ingest(
            live_batch().model_copy(
                update={"batch_id": "demo-heartbeat", "events": (), "availability": ()}
            ),
            later,
        )
        stale = store.record_shadow(later, options)
        return {
            "snapshot": snapshot.model_dump(mode="json"),
            "episode": episode.model_dump(mode="json"),
            "stale_episode": stale.model_dump(mode="json"),
            "summary": summarize((episode, stale)),
        }
    finally:
        store.close()


def quality() -> dict[str, Any]:
    from hospitalos.hybrid.source_adapter import SourceAdapter
    from hospitalos.hybrid.source_contract import (
        KINDS,
        SourceProfile,
        TableMapping,
        expected_fields,
    )

    request = nominal()
    batch = live_batch()
    tables = tuple(
        TableMapping(
            kind=kind,
            table=f"export_{kind}",
            columns={key: f"col_{key.replace('.', '_')}" for key in sorted(expected_fields(kind))},
        )
        for kind in KINDS
    )
    profile = SourceProfile(
        profile_id="profil-fictif",
        version=1,
        source_schema="UNITE_FICTIVE_1",
        hospital_id=request.hospital_id,
        unit_id=UNIT,
        source=SOURCE,
        upstream_pseudonymized_ids=True,
        tables=tables,
    )
    rows: dict[str, list[dict[str, Any]]] = {t.table: [] for t in tables}
    for event in batch.events:
        table = next(t for t in tables if t.kind == event.fact.kind)
        canonical = event.model_dump(mode="json")
        rows[table.table].append(
            {
                source: canonical["fact"][target.removeprefix("fact.")]
                if target.startswith("fact.")
                else canonical[target]
                for target, source in table.columns.items()
            }
        )
    availability = next(t for t in tables if t.kind == "availability")
    for item in batch.availability:
        values = item.model_dump(mode="json")
        rows[availability.table].append(
            {source: values[target] for target, source in availability.columns.items()}
        )
    export = {
        "schema_version": "UNIT_SOURCE_EXPORT_1",
        "source_schema": profile.source_schema,
        "export_id": "export-demo-0830",
        "hospital_id": request.hospital_id,
        "unit_id": UNIT,
        "source": SOURCE,
        "exported_at": AT.isoformat(),
        "manifest_version": 1,
        "expected_entities": batch.expected_entities,
        "tables": rows,
    }
    store = LiveStore(live_policy())
    try:
        received = AT + timedelta(seconds=40)
        result = SourceAdapter(store, profile, clock=lambda: received).receive(
            json.dumps(export).encode()
        )
        return result.model_dump(mode="json")
    finally:
        store.close()


def _deterministic_ids() -> None:
    """Episode ids are random UUIDs in the store; pin them so CI can diff fixtures."""
    import itertools
    import uuid

    import hospitalos.hybrid.live_store as live_store

    counter = itertools.count(1)
    live_store.uuid = type(  # type: ignore[attr-defined]
        "PinnedUuid", (), {"uuid4": staticmethod(lambda: uuid.UUID(int=next(counter)))}
    )


def main() -> None:
    _deterministic_ids()
    OUT.mkdir(parents=True, exist_ok=True)
    scenarios = (
        scenario("nominal", "Matinée ordinaire", nominal()),
        scenario("perturbations", "Transport coupé, vague des urgences", perturbations()),
        scenario("incomplete", "Données incomplètes", incomplete()),
    )
    for item in scenarios:
        (OUT / f"scenario-{item['id']}.json").write_text(json.dumps(item, indent=1) + "\n")
        print(
            item["id"], item["plan"]["decision"], item["plan"]["selected"], item["plan"]["reasons"]
        )
    (OUT / "live.json").write_text(json.dumps(live(), indent=1) + "\n")
    (OUT / "quality.json").write_text(json.dumps(quality(), indent=1) + "\n")
    print("ok", sorted(p.name for p in OUT.glob("*.json")))


if __name__ == "__main__":
    main()
