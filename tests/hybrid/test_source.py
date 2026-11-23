"""Read-only import qualification without real hospital data or outward side effects."""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hospitalos.hybrid.live_models import PlanningOptions
from hospitalos.hybrid.live_store import LiveStore
from hospitalos.hybrid.source_adapter import MAX_BYTES, SourceAdapter, check_columns
from hospitalos.hybrid.source_cli import main
from hospitalos.hybrid.source_contract import ColumnManifest, SourceProfile, timestamp
from hospitalos.hybrid.source_demo import fixture

AT = datetime.fromisoformat(fixture()[2]["exported_at"])


def encode(export: dict[str, Any]) -> bytes:
    return json.dumps(export).encode()


@pytest.fixture
def source() -> Iterator[tuple[LiveStore, SourceAdapter, dict[str, Any]]]:
    policy, profile, export = fixture()
    store = LiveStore(policy)
    yield store, SourceAdapter(store, profile, clock=lambda: AT), export
    store.close()


def test_default_is_quality_only_without_simulation_or_commands(
    source: tuple[LiveStore, SourceAdapter, dict[str, Any]],
) -> None:
    store, adapter, export = source
    result = adapter.receive(encode(export))
    assert result.report.status == "OBSERVATION_ONLY" and result.report.state_ready
    assert result.current_state_assessed
    assert result.episode_id is None and not result.report.shadow_episode_created
    assert result.report.expected_entities == result.report.delivered_entities == 7
    assert result.report.records_by_kind["availability"] == 4
    for table in ("live_episodes", "live_proposals", "live_transitions", "live_holds"):
        assert store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_explicit_shadow_import_and_receipt_are_atomic(tmp_path: Path) -> None:
    policy, profile, export = fixture()
    profile = profile.model_copy(update={"evaluation_mode": "shadow"})
    path = str(tmp_path / "shadow.sqlite")
    store = LiveStore(policy, path)
    adapter = SourceAdapter(store, profile, clock=lambda: AT)
    first = adapter.receive(encode(export), PlanningOptions(scenarios=4))
    assert first.report.status == "SHADOW_EVALUATED"
    assert first.episode_id and store.episode(first.episode_id).commands_emitted == 0
    store.close()
    store = LiveStore(policy, path)
    try:
        duplicate = SourceAdapter(store, profile, clock=lambda: AT + timedelta(minutes=10)).receive(
            encode(export)
        )
        assert duplicate.duplicate and not duplicate.current_state_assessed
        assert duplicate.report == first.report and duplicate.episode_id == first.episode_id
        assert store.db.execute("SELECT COUNT(*) FROM live_episodes").fetchone()[0] == 1
    finally:
        store.close()


def test_late_file_is_stamped_at_actual_receipt_and_reported(
    source: tuple[LiveStore, SourceAdapter, dict[str, Any]],
) -> None:
    store, adapter, export = source
    adapter.clock = lambda: AT + timedelta(seconds=121)
    result = adapter.receive(encode(export))
    assert not result.report.state_ready
    assert result.report.max_resource_age_seconds == 121
    assert result.report.export_transfer_seconds == 121
    assert result.report.state_gate_counts["stale_confirmation"] == 4
    assert all(
        e.available_at == AT + timedelta(seconds=121)
        for e in store.snapshot(AT + timedelta(seconds=121)).events
    )


@pytest.mark.parametrize(
    "raw", [b'{"tables":{},"tables":{}}', b'{"x":NaN}', b'{"x":Infinity}', b"{", b"\xff"]
)
def test_invalid_json_is_redacted_and_creates_no_facts(
    source: tuple[LiveStore, SourceAdapter, dict[str, Any]], raw: bytes
) -> None:
    store, adapter, _ = source
    result = adapter.receive(raw)
    assert result.report.issues[0].code == "invalid_json"
    assert store.db.execute("SELECT COUNT(*) FROM live_facts").fetchone()[0] == 0


def test_large_export_is_bounded(source: tuple[LiveStore, SourceAdapter, dict[str, Any]]) -> None:
    _, adapter, _ = source
    result = adapter.receive(b" " * (MAX_BYTES + 1))
    assert result.report.issues[0].code == "export_too_large"


@pytest.mark.parametrize(
    "defect",
    [
        "column",
        "missing",
        "table",
        "hospital",
        "schema",
        "clock",
        "future",
        "numeric_time",
        "naive_time",
        "bool_string",
        "count_string",
        "duplicate",
        "missing_entity",
        "missing_resource",
    ],
)
def test_faults_reject_entire_export_without_echoing_values(
    source: tuple[LiveStore, SourceAdapter, dict[str, Any]], defect: str
) -> None:
    store, adapter, export = source
    row = export["tables"]["demo_patient"][0]
    secret = "PRIVATE_TEST_VALUE_NEVER_PRINT"
    if defect == "column":
        row["PatientName"] = secret
    elif defect == "missing":
        del row["col_fact_medically_cleared"]
    elif defect == "table":
        export["tables"][secret] = [{"note": secret}]
    elif defect == "hospital":
        export["hospital_id"] = secret
    elif defect == "schema":
        export["source_schema"] = secret
    elif defect == "clock":
        row["col_available_at"] = (AT - timedelta(seconds=1)).isoformat()
    elif defect == "future":
        row["col_available_at"] = (AT + timedelta(seconds=1)).isoformat()
    elif defect == "numeric_time":
        row["col_event_time"] = 1234567890
    elif defect == "naive_time":
        row["col_event_time"] = "2026-10-24T08:00:00"
    elif defect == "bool_string":
        row["col_fact_medically_cleared"] = "False"
    elif defect == "count_string":
        export["tables"]["demo_unit"][0]["col_fact_staffed_beds"] = "1"
    elif defect == "duplicate":
        export["tables"]["demo_patient"].append(row.copy())
    elif defect == "missing_entity":
        export["tables"]["demo_patient"].pop()
    elif defect == "missing_resource":
        export["tables"]["demo_availability"].pop()
    result = adapter.receive(encode(export))
    assert result.report.status == "REJECTED"
    assert secret not in result.model_dump_json() and "outgoing" not in result.model_dump_json()
    assert store.db.execute("SELECT COUNT(*) FROM live_facts").fetchone()[0] == 0
    assert store.db.execute("SELECT COUNT(*) FROM source_imports").fetchone()[0] == 0


def test_missing_rows_never_reuse_previous_snapshot_silently(
    source: tuple[LiveStore, SourceAdapter, dict[str, Any]],
) -> None:
    store, adapter, export = source
    assert adapter.receive(encode(export)).report.state_ready
    _, _, incomplete = fixture(1)
    incomplete["tables"]["demo_patient"].pop()
    adapter.clock = lambda: AT + timedelta(seconds=1)
    result = adapter.receive(encode(incomplete))
    assert "missing_entities" in {i.code for i in result.report.issues}
    snapshot = store.snapshot(AT + timedelta(seconds=1))
    assert "source_import_rejected:fictional_feed" in snapshot.issues
    assert all(e.event_time == AT for e in snapshot.events)
    assert store.record_shadow(AT + timedelta(seconds=1)).assessment.plan is None


def test_rejected_feed_requires_new_post_incident_observations(
    source: tuple[LiveStore, SourceAdapter, dict[str, Any]],
) -> None:
    store, adapter, export = source
    adapter.receive(encode(export))
    adapter.clock = lambda: AT + timedelta(seconds=10)
    adapter.receive(b"invalid")
    old = adapter.receive(encode(export))
    assert old.duplicate and not old.current_state_assessed
    # New envelope identity alone cannot heal a faulty feed.
    export["export_id"] = "new-envelope-old-observations"
    delayed = adapter.receive(encode(export))
    assert not delayed.report.state_ready
    _, _, fresh = fixture(11)
    adapter.clock = lambda: AT + timedelta(seconds=11)
    assert adapter.receive(encode(fresh)).report.state_ready
    assert not store.snapshot(AT + timedelta(seconds=11)).issues


def test_fault_block_survives_restart(tmp_path: Path) -> None:
    policy, profile, export = fixture()
    path = str(tmp_path / "source.sqlite")
    store = LiveStore(policy, path)
    adapter = SourceAdapter(store, profile, clock=lambda: AT)
    adapter.receive(encode(export))
    adapter.receive(b"bad-source")
    store.close()
    store = LiveStore(policy, path)
    try:
        assert "source_import_rejected:fictional_feed" in store.snapshot(AT).issues
    finally:
        store.close()


def test_same_export_id_with_different_content_is_not_overwritten(
    source: tuple[LiveStore, SourceAdapter, dict[str, Any]],
) -> None:
    store, adapter, export = source
    first = adapter.receive(encode(export))
    export["tables"]["demo_availability"][0]["col_available"] = 1
    conflict = adapter.receive(encode(export))
    assert conflict.report.issues[0].code == "export_identity_conflict"
    stored = store.db.execute("SELECT body FROM source_imports").fetchone()[0]
    assert json.loads(stored)["report"]["content_fingerprint"] == first.report.content_fingerprint


def test_correction_keeps_source_identity_and_late_availability(
    source: tuple[LiveStore, SourceAdapter, dict[str, Any]],
) -> None:
    store, adapter, export = source
    adapter.receive(encode(export))
    export["export_id"] = "correction"
    row = export["tables"]["demo_discharge"][0]
    row["col_version"] = 2
    row["col_fact_documents_ready"] = False
    adapter.clock = lambda: AT + timedelta(seconds=10)
    result = adapter.receive(encode(export))
    assert result.report.status == "OBSERVATION_ONLY"
    state = store.snapshot(AT + timedelta(seconds=10))
    assert state.state.discharges[0].documents_ready is False
    corrected = next(e for e in state.events if e.fact.kind == "discharge")
    assert corrected.available_at == AT + timedelta(seconds=10) and corrected.event_time == AT


def test_unknown_is_counted_and_never_converted_to_zero(
    source: tuple[LiveStore, SourceAdapter, dict[str, Any]],
) -> None:
    _, adapter, export = source
    export["tables"]["demo_availability"][1]["col_available"] = None
    result = adapter.receive(encode(export))
    assert result.report.missing_values_by_field["availability.available"] == 1
    assert not result.report.state_ready
    assert result.report.state_gate_counts["unknown_availability"] == 1


def test_codes_need_explicit_mapping_and_unknown_codes_reject() -> None:
    policy, profile, export = fixture()
    payload = profile.model_dump(mode="json")
    table = next(t for t in payload["tables"] if t["kind"] == "patient")
    table["value_maps"] = {"fact.medically_cleared": {"Y": True, "N": False}}
    profile = SourceProfile.model_validate(payload)
    export["tables"]["demo_patient"][0]["col_fact_medically_cleared"] = "Y"
    store = LiveStore(policy)
    try:
        adapter = SourceAdapter(store, profile, clock=lambda: AT)
        assert adapter.receive(encode(export)).report.state_ready
        export["export_id"] = "bad-code"
        export["tables"]["demo_patient"][0]["col_fact_medically_cleared"] = "MAYBE"
        assert adapter.receive(encode(export)).report.issues[0].code == "unknown_code"
    finally:
        store.close()


def test_timezone_offsets_are_distinct_and_naive_clocks_reject() -> None:
    early = timestamp("2026-10-25T02:30:00+02:00")
    late = timestamp("2026-10-25T02:30:00+01:00")
    assert (late - early).total_seconds() == 3600
    with pytest.raises(ValueError, match="timezone"):
        timestamp("2026-10-25T02:30:00")


def test_preflight_is_metadata_only_and_rejects_unexpected_columns() -> None:
    _, profile, _ = fixture()
    manifest = ColumnManifest(
        source_schema=profile.source_schema,
        tables={t.table: list(t.columns.values()) for t in profile.tables},
    )
    assert not check_columns(profile, manifest)
    manifest.tables["demo_patient"].append("PatientName")
    issues = check_columns(profile, manifest)
    assert {i.code for i in issues} == {"unexpected_columns", "forbidden_columns"}
    assert "PatientName" not in json.dumps([i.model_dump() for i in issues])


@pytest.mark.parametrize("defect", ["missing", "same_clock", "pii", "expression"])
def test_mapping_itself_fails_closed(defect: str) -> None:
    _, profile, _ = fixture()
    payload = profile.model_dump(mode="json")
    table = payload["tables"][0]
    if defect == "missing":
        del table["columns"]["fact.id"]
    elif defect == "same_clock":
        table["columns"]["available_at"] = table["columns"]["event_time"]
    elif defect == "pii":
        table["columns"]["fact.id"] = "PatientName"
    else:
        table["columns"]["fact.id"] = "eval(system())"
    with pytest.raises(ValidationError):
        SourceProfile.model_validate(payload)


def test_mapping_is_immutable_after_registration(
    source: tuple[LiveStore, SourceAdapter, dict[str, Any]],
) -> None:
    store, _, _ = source
    _, profile, _ = fixture()
    profile = profile.model_copy(update={"version": 2})
    with pytest.raises(ValueError, match="immutable"):
        SourceAdapter(store, profile)


def test_shadow_failure_rolls_back_facts_episode_and_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    policy, profile, export = fixture()
    store = LiveStore(policy)
    profile = profile.model_copy(update={"evaluation_mode": "shadow"})
    try:
        adapter = SourceAdapter(store, profile, clock=lambda: AT)

        original_record = store._record_shadow

        def fail(_now: datetime, _options: PlanningOptions | None = None) -> None:
            original_record(_now, _options)
            raise ValueError("simulated failure after episode persistence")

        monkeypatch.setattr(store, "_record_shadow", fail)
        assert adapter.receive(encode(export)).report.issues[0].code == "journal_rejected"
        for table in (
            "live_facts",
            "live_batches",
            "live_resources",
            "live_episodes",
            "source_imports",
        ):
            assert store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        store.close()


def test_cli_redacts_invalid_input_and_reads_export_without_modification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    policy, profile, export = fixture()

    def adapter_at_known_receipt(store: LiveStore, profile: SourceProfile) -> SourceAdapter:
        return SourceAdapter(store, profile, clock=lambda: AT)

    monkeypatch.setattr("hospitalos.hybrid.source_cli.SourceAdapter", adapter_at_known_receipt)
    profile_file, policy_file, export_file = (
        tmp_path / n for n in ("profile.json", "policy.json", "export.json")
    )
    profile_file.write_text(profile.model_dump_json())
    policy_file.write_text(policy.model_dump_json())
    raw = encode(export)
    export_file.write_bytes(raw)
    code = main(
        [
            "--profile",
            str(profile_file),
            "--policy",
            str(policy_file),
            "--import-export",
            str(export_file),
            "--db",
            str(tmp_path / "local.sqlite"),
        ]
    )
    assert code == 0
    assert export_file.read_bytes() == raw
    printed = capsys.readouterr().out
    assert "outgoing" not in printed and "fictional-hospital" not in printed
    export_file.write_text('{"bad":"PRIVATE_VALUE"')
    code = main(
        [
            "--profile",
            str(profile_file),
            "--policy",
            str(policy_file),
            "--import-export",
            str(export_file),
            "--db",
            str(tmp_path / "local.sqlite"),
        ]
    )
    assert code == 20 and "PRIVATE_VALUE" not in capsys.readouterr().out


def test_concurrent_reception_creates_one_batch_and_one_episode(tmp_path: Path) -> None:
    policy, profile, export = fixture()
    profile = profile.model_copy(update={"evaluation_mode": "shadow"})
    path = str(tmp_path / "concurrent.sqlite")
    one, two = LiveStore(policy, path), LiveStore(policy, path)
    try:
        adapters = (
            SourceAdapter(one, profile, clock=lambda: AT),
            SourceAdapter(two, profile, clock=lambda: AT),
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda a: a.receive(encode(export), PlanningOptions(scenarios=2)), adapters
                )
            )
        assert sorted(r.duplicate for r in results) == [False, True]
        for table in ("source_imports", "live_batches", "live_episodes"):
            assert one.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
    finally:
        one.close()
        two.close()


def test_source_adapter_rejects_sandbox_mode() -> None:
    policy, profile, _ = fixture()
    store = LiveStore(policy.model_copy(update={"mode": "sandbox"}))
    try:
        with pytest.raises(ValueError, match="shadow-mode"):
            SourceAdapter(store, profile)
    finally:
        store.close()
