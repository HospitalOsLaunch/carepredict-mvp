"""Fictional source schema for exercising mappings, never a hospital integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from .demo import pathway_request
from .live_models import LivePolicy
from .source_contract import KINDS, SourceProfile, TableMapping, expected_fields


def fixture(seconds: int = 0) -> tuple[LivePolicy, SourceProfile, dict[str, Any]]:
    request = pathway_request()
    at = request.at + timedelta(seconds=seconds)
    tables = tuple(
        TableMapping(
            kind=kind,
            table=f"demo_{kind}",
            columns={key: f"col_{key.replace('.', '_')}" for key in sorted(expected_fields(kind))},
        )
        for kind in KINDS
    )
    profile = SourceProfile(
        profile_id="fictional-source",
        version=1,
        source_schema="FICTIONAL_UNIT_1",
        hospital_id=request.hospital_id,
        unit_id="medicine",
        source="fictional_feed",
        upstream_pseudonymized_ids=True,
        tables=tables,
    )
    rows: dict[str, list[dict[str, Any]]] = {t.table: [] for t in tables}
    for event in request.events:
        table = next(t for t in tables if t.kind == event.fact.kind)
        canonical = event.model_dump(mode="json")
        canonical.update(
            event_id=f"fixture-{seconds}:{event.fact.kind}:{event.fact.id}",
            event_time=at.isoformat(),
            available_at=at.isoformat(),
        )
        rows[table.table].append(
            {
                source: canonical["fact"][target.removeprefix("fact.")]
                if target.startswith("fact.")
                else canonical[target]
                for target, source in table.columns.items()
            }
        )
    table = next(t for t in tables if t.kind == "availability")
    for resource, target, count in (
        ("staffed", "medicine", 0),
        ("cleaning", "medicine", 1),
        ("transport", "transport", 1),
        ("downstream", "smr", 1),
    ):
        values: dict[str, Any] = {
            "resource": resource,
            "target_id": target,
            "available": count,
            "observed_at": at.isoformat(),
            "evidence_ref": f"fictional-{seconds}:{resource}",
        }
        rows[table.table].append(
            {source: values[target] for target, source in table.columns.items()}
        )
    export = {
        "schema_version": "UNIT_SOURCE_EXPORT_1",
        "source_schema": profile.source_schema,
        "export_id": f"fictional-export-{seconds}",
        "hospital_id": request.hospital_id,
        "unit_id": "medicine",
        "source": profile.source,
        "exported_at": at.isoformat(),
        "manifest_version": 1,
        "expected_entities": request.expected_entities,
        "tables": rows,
    }
    policy = LivePolicy(
        hospital_id=request.hospital_id, unit_id="medicine", sources=(profile.source,)
    )
    return policy, profile, export
