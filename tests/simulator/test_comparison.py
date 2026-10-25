"""Paired execution, independent scoring, coupling and API isolation checks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from hospitalos.simulator import comparison
from hospitalos.simulator.comparison import ComparisonRequest, ComparisonResult, compare, replay
from hospitalos.simulator.evaluation import evaluate
from hospitalos.simulator.session import DemoSession
from services.api import simulator_app


@pytest.fixture(scope="module")
def accepted() -> ComparisonResult:
    return compare(ComparisonRequest(horizon_minutes=60))


def test_real_planner_changes_order_not_primitives_and_scorer_is_independent(
    accepted: ComparisonResult,
) -> None:
    a0, a1 = accepted.a0, accepted.a1
    assert a0.evaluation.waiting_patient_minutes == 67
    assert a1.evaluation.waiting_patient_minutes == 62
    assert accepted.waiting_patient_minutes_saved == 5
    assert accepted.waiting_patient_hours_saved == pytest.approx(5 / 60)
    assert not accepted.physical_trajectories_identical
    assert a0.installed_during_episode == a1.installed_during_episode == 2
    assert a0.evaluation.coordination_tasks == 0
    assert a1.evaluation.coordination_tasks == 1
    assert a1.solicitation_seconds_requested == 30
    assert a1.commands[0].status == "executed"
    assert a1.decisions[0].action == "prioritize_cleaning"
    assert a1.decisions[0].bed_id == "G02"
    assert [d.second for d in a1.decisions] == list(range(30, 3600, 300))
    for episode in (a0, a1):
        assert evaluate(episode.truth_journal, 3600) == episode.evaluation
        starts = {e.bed: e.second for e in episode.truth_journal if e.kind == "cleaning_started"}
        for event in episode.truth_journal:
            if event.kind == "cleaning_finished":
                key = f"demo-world-1|7|cleaning|{event.bed}|0"
                assert (
                    event.second - starts[event.bed] == accepted.manifest.exogenous_primitives[key]
                )


def test_disabled_policy_is_strictly_identical_through_maximum_horizon() -> None:
    result = compare(ComparisonRequest(seed=9, policy="disabled"))
    assert result.a0 == result.a1
    assert result.physical_trajectories_identical
    assert result.waiting_patient_minutes_saved == 0
    assert not result.a1.commands and not result.a1.decisions
    assert result.a1.evaluation.coordination_tasks == 0
    assert (result.manifest.ends_at - result.manifest.starts_at).total_seconds() == 10800


def test_refusals_cost_time_without_applying_actions(accepted: ComparisonResult) -> None:
    result = compare(ComparisonRequest(horizon_minutes=60, policy="refuse"))
    assert result.a0 == accepted.a0
    assert result.a1.commands and all(c.status == "refused" for c in result.a1.commands)
    assert result.a1.evaluation.coordination_tasks == len(result.a1.commands)
    assert result.a1.solicitation_seconds_requested == 30 * len(result.a1.commands)
    assert not any(e.kind == "cleaning_prioritized" for e in result.a1.truth_journal)
    # This scenario has no overlapping assignment at refusal time. No universal gain/sign claim.
    assert result.waiting_patient_minutes_saved == 0


def test_negative_effect_is_preserved() -> None:
    result = compare(ComparisonRequest(seed=0, horizon_minutes=60))
    assert result.waiting_patient_minutes_saved == -5
    assert (
        result.a1.evaluation.waiting_patient_minutes > result.a0.evaluation.waiting_patient_minutes
    )


def test_terminal_wait_and_initial_stock_are_counted() -> None:
    result = compare(ComparisonRequest(horizon_minutes=1, policy="disabled"))
    for episode in (result.a0, result.a1):
        assert episode.evaluation.waiting_patient_minutes == 1
        assert episode.evaluation.waiting_at_end == 1
        assert episode.installed_during_episode == 0
        assert episode.evaluation.admitted_at_end == 1
        assert episode.evaluation.patients_total == 2


def test_complete_export_replays_deterministically(accepted: ComparisonResult) -> None:
    exported = ComparisonResult.model_validate_json(accepted.model_dump_json())
    reproduced = replay(exported)
    assert reproduced == exported  # Includes decisions, outcomes, journals, metrics and content ID.
    assert exported.manifest.source_sha256["simulator/engine.py"]
    assert exported.manifest.source_sha256["hybrid/planning.py"]
    assert exported.manifest.runtime_versions["simpy"]


def test_replay_rejects_changed_code_or_dependencies(accepted: ComparisonResult) -> None:
    for key in ("source_sha256", "runtime_versions"):
        changed = accepted.model_copy(deep=True)
        getattr(changed.manifest, key)["changed"] = "different"
        with pytest.raises(ValueError, match="diffère|diffèrent"):
            replay(changed)


def test_running_server_rejects_code_changed_since_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(comparison, "source_hashes", lambda: {})
    session = DemoSession(monotonic=lambda: 0)
    try:
        with TestClient(simulator_app.create_app(session)) as client:
            response = client.post("/demo/compare", json={"horizon_minutes": 1})
            assert response.status_code == 503
            assert response.json()["detail"] == "comparison_environment_changed_restart_required"
    finally:
        session.close()


@pytest.mark.parametrize("completed", [False, True])
def test_api_is_isolated_from_interactive_state_and_rejects_invalid_inputs(completed: bool) -> None:
    session = DemoSession(monotonic=lambda: 0)
    try:
        session.engine.advance(600)
        if completed:
            session.engine.advance(10800 - session.engine.second)
            session.completed = True
        before = session.view()
        journal = tuple(session.engine.journal)
        with TestClient(simulator_app.create_app(session)) as client:
            response = client.post("/demo/compare", json={"horizon_minutes": 1})
            assert response.status_code == 200
            result = ComparisonResult.model_validate(response.json())
            assert result.a0.evaluation.waiting_patient_minutes == 1
            assert session.view() == before
            assert tuple(session.engine.journal) == journal
            invalid_inputs: tuple[dict[str, object], ...] = (
                {"seed": True},
                {"seed": -1},
                {"seed": 2**31},
                {"horizon_minutes": 181},
                {"horizon_minutes": 0},
                {"horizon_minutes": 1.5},
                {"policy": "oracle"},
                {"truth": {}},
            )
            for invalid in invalid_inputs:
                assert client.post("/demo/compare", json=invalid).status_code == 422
            assert (
                client.post(
                    "/demo/compare", json={}, headers={"Origin": "https://example.com"}
                ).status_code
                == 403
            )
    finally:
        session.close()


def test_only_one_pair_runs_and_lock_is_released_after_error(
    monkeypatch: pytest.MonkeyPatch,
    accepted: ComparisonResult,
) -> None:
    entered, release = Event(), Event()

    def blocked(config: ComparisonRequest) -> ComparisonResult:
        entered.set()
        assert release.wait(10)
        raise RuntimeError("deliberate_failure")

    monkeypatch.setattr(simulator_app, "compare", blocked)
    session = DemoSession(monotonic=lambda: 0)
    try:
        with TestClient(simulator_app.create_app(session), raise_server_exceptions=False) as client:
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(client.post, "/demo/compare", json={})
                try:
                    assert entered.wait(10)
                    assert client.post("/demo/compare", json={}).status_code == 429
                    assert client.get("/demo/session").status_code == 200
                finally:
                    release.set()
                assert first.result().status_code == 500
            monkeypatch.setattr(simulator_app, "compare", lambda config: accepted)
            assert client.post("/demo/compare", json={}).status_code == 200
    finally:
        session.close()
