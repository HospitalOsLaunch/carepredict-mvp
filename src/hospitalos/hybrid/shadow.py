"""Local shadow replay; timestamps in a replay file are simulation inputs only.

A real adapter must supply its own trusted receipt clock. No replay artifact,
patient data, fitted model or generated metric table is published by this CLI.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import field_validator

from hospitalos.operational.contract import Closed, instant

from .demo import pathway_request
from .live_models import (
    Availability,
    LivePolicy,
    ObservationBatch,
    PlanningOptions,
    Resource,
    ShadowEpisode,
)
from .live_store import LiveStore


class ReplayReceipt(Closed):
    received_at: datetime
    batch: ObservationBatch

    @field_validator("received_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return instant(value)


def summarize(episodes: tuple[ShadowEpisode, ...]) -> dict[str, Any]:
    reasons = Counter(reason for e in episodes for reason in e.assessment.gate_reasons)
    decisions = Counter(
        e.assessment.plan.decision for e in episodes if e.assessment.plan is not None
    )
    return {
        "schema_version": "SHADOW_SUMMARY_1",
        "episodes": len(episodes),
        "blocked_episodes": sum(bool(e.assessment.gate_reasons) for e in episodes),
        "planner_decisions": dict(sorted(decisions.items())),
        "gate_reason_counts": dict(sorted(reasons.items())),
        "commands_emitted": 0,
        "causal_effect_established": False,
        "interpretation": (
            "Observation quality and hypothetical decisions only; no clinical gain estimate."
        ),
    }


def demo() -> dict[str, Any]:
    request = pathway_request()
    policy = LivePolicy(
        hospital_id=request.hospital_id, unit_id="medicine", sources=("fictional_feed",)
    )
    capacities: tuple[tuple[Resource, str, int], ...] = (
        ("staffed", "medicine", 0),
        ("cleaning", "medicine", 1),
        ("transport", "transport", 1),
        ("downstream", "smr", 1),
    )
    availability = tuple(
        Availability(
            resource=kind,
            target_id=target,
            available=count,
            source="fictional_feed",
            observed_at=request.at,
            evidence_ref=f"fictional:{kind}",
        )
        for kind, target, count in capacities
    )
    batch = ObservationBatch(
        batch_id="fictional-initial",
        hospital_id=request.hospital_id,
        source="fictional_feed",
        manifest_version=1,
        expected_entities=request.expected_entities,
        events=request.events,
        availability=availability,
    )
    store = LiveStore(policy)
    try:
        store.ingest(batch, request.at)
        options = PlanningOptions(assumptions=request.assumptions, scenarios=8)
        first = store.record_shadow(request.at, options)
        # A heartbeat is received, but contains NO new availability observation.
        later = request.at + timedelta(seconds=121)
        store.ingest(
            batch.model_copy(
                update={
                    "batch_id": "fictional-heartbeat",
                    "events": (),
                    "availability": (),
                }
            ),
            later,
        )
        second = store.record_shadow(later, options)
        return summarize((first, second))
    finally:
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--batches", type=Path, help="JSONL ReplayReceipt records in receipt order")
    parser.add_argument(
        "--db", type=Path, help="Private local SQLite path; immutable shadow policy"
    )
    args = parser.parse_args()
    if args.demo:
        if args.policy or args.batches or args.db:
            parser.error("--demo cannot be combined with replay inputs")
        result = demo()
    else:
        if not args.policy or not args.batches or not args.db:
            parser.error("Supply --demo or all of --policy, --batches and --db")
        policy = LivePolicy.model_validate_json(args.policy.read_text())
        if policy.mode != "shadow":
            parser.error("Replay is restricted to shadow mode")
        store = LiveStore(policy, str(args.db))
        episodes: list[ShadowEpisode] = []
        try:
            with args.batches.open() as source:
                for line in source:
                    if line.strip():
                        receipt = ReplayReceipt.model_validate_json(line)
                        if store.ingest(receipt.batch, receipt.received_at):
                            episodes.append(store.record_shadow(receipt.received_at))
            result = summarize(tuple(episodes))
        finally:
            store.close()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
