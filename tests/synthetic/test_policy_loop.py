"""Live temporal boundary, actor separation, execution failures and immutable evidence."""

from __future__ import annotations

import gzip
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from hospitalos.synthetic import policy_loop as loop
from hospitalos.synthetic.asof import AsOfCursor
from hospitalos.synthetic.cohort import _sha
from hospitalos.synthetic.config import HospitalConfig
from hospitalos.synthetic.engine import _RUN, simulate
from hospitalos.synthetic.policy import (
    NoRecommendationPolicy,
    ObservedRulePolicy,
    PolicyContext,
    RecommendationBatch,
    UnitRecommendation,
)
from hospitalos.synthetic.v041 import observation

EXAMPLE = Path("configs/synthetic/hospital_two_poles.json")
_OBS: Any = observation
PARENT = "4d0e4f975456c369ac7dffc2ab41239604a0af83"


@pytest.fixture
def config() -> HospitalConfig:
    value = json.loads(EXAMPLE.read_text())
    value.update(days=4, warmup_days=4, start="2025-09-28")
    return HospitalConfig.model_validate(value)


def ready(config: HospitalConfig) -> loop.PolicyEnvironment:
    env = loop.PolicyEnvironment(config, ObservedRulePolicy().descriptor)
    env.reset()
    for _ in range(9):
        env.advance()
    return env


def batch_for(env: loop.PolicyEnvironment, q: float = 1.0) -> RecommendationBatch:
    context = env.observe()
    assert context is not None
    return RecommendationBatch(
        descriptor=env.descriptor,
        decision_h=context.decision_h,
        context_sha256=context.fingerprint,
        units=tuple(
            UnitRecommendation(
                unit_id=u.unit_id, probabilities=(q, q, q, q), reason="controlled_test"
            )
            for u in env.config.units
        ),
    )


def finish(env: loop.PolicyEnvironment) -> loop.PolicyEnvironment:
    current = env.observe()
    policy = ObservedRulePolicy()
    policy.reset(env.site)
    while current is not None:
        if current.decision_h % 24 == 9:
            env.act(policy.recommend(current))
        current = env.advance()
    return env


def load_previous(name: str, path: str, directory: Path) -> Any:
    source = subprocess.check_output(["git", "show", f"{PARENT}:{path}"], text=True)
    file = directory / f"{name.rsplit('.', 1)[-1]}.py"
    file.write_text(source)
    spec = importlib.util.spec_from_file_location(name, file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_batch_observer_unchanged_against_published_parent(
    config: HospitalConfig, tmp_path: Path
) -> None:
    previous = load_previous(
        "previous_observer", "src/hospitalos/synthetic/v041/observation.py", tmp_path
    )
    result = simulate(config)
    sim = result.simulation
    events = _RUN.evenements(result.journal, [u.unit_id for u in config.units], sim.x.H)
    before = previous.observer(events, sim.x, config.seed, None)
    after = _OBS.observer(events, sim.x, config.seed, None)
    assert before == after
    assert len(after[0]) > 100


def test_online_cursor_matches_previous_replay(config: HospitalConfig, tmp_path: Path) -> None:
    previous = load_previous(
        "hospitalos.synthetic.previous_asof", "src/hospitalos/synthetic/asof.py", tmp_path
    )
    env = finish(ready(config))
    old = previous.replay(env.stream.delivered, config, run_id=env.run_id)
    assert all(a.model_dump() == b.model_dump() for a, b in zip(env.features, old, strict=True))
    assert loop.validate_run(env)["online_replay_equal"]


def test_future_delivery_is_rejected_without_changing_current_context(
    config: HospitalConfig,
) -> None:
    env = ready(config)
    context = env.observe()
    assert context is not None
    later = min((entry[-1] for entry in env.stream.pending), key=lambda d: d.available_h)
    assert later.available_h > context.decision_h
    with pytest.raises(ValueError, match="future delivery"):
        env.cursor.advance(env.hour, (later,))
    assert env.observe() == context
    assert all(
        s.available_h <= context.decision_h for row in context.observations for s in row.sources
    )
    assert all(s.event_h < context.decision_h for row in context.observations for s in row.sources)


def test_policy_receives_only_immutable_observations_and_site(config: HospitalConfig) -> None:
    env = ready(config)
    policy = ObservedRulePolicy()
    policy.reset(env.site)
    context = env.observe()
    assert context is not None
    first = policy.recommend(context)
    # Alter simulator-only future staffing, hidden cadre information and true states.
    env.sim.x.z_cache[:] = 999
    env.sim.x.u_renfort[:] = 1
    env.state.ratio[:] = [999.0] * env.sim.U
    assert policy.recommend(context) == first
    assert set(env.site.model_dump()) == {"hospital_id", "start", "clock", "units"}
    assert "hidden_z" not in context.model_dump_json()
    assert "ready_h" not in context.model_dump_json()
    with pytest.raises(ValueError):
        context.decision_h = 10
    row = next(r for r in context.observations if r.values is not None)
    with pytest.raises(ValueError):
        assert row.values is not None
        row.values.lits_occupes = 999


def test_stale_or_missing_observation_abstains(config: HospitalConfig) -> None:
    env = ready(config)
    context = env.observe()
    assert context is not None
    empty = AsOfCursor(config, run_id="EMPTY").advance(9, ())
    missing = PolicyContext(decision_h=9, timestamp=context.timestamp, observations=empty)
    assert all(
        r.probabilities == (0, 0, 0, 0) for r in ObservedRulePolicy().recommend(missing).units
    )
    stale = context.model_copy(
        update={
            "observations": tuple(
                r.model_copy(update={"stale": True}) for r in context.observations
            )
        }
    )
    assert all(r.probabilities == (0, 0, 0, 0) for r in ObservedRulePolicy().recommend(stale).units)


@pytest.mark.parametrize(
    "mutation", ["time", "context", "version", "duplicate", "missing", "unknown", "nan"]
)
def test_invalid_batch_rejected_before_any_execution(config: HospitalConfig, mutation: str) -> None:
    env = ready(config)
    batch = batch_for(env)
    data = batch.model_dump()
    if mutation == "time":
        data["decision_h"] = 8
    elif mutation == "context":
        data["context_sha256"] = "0" * 64
    elif mutation == "version":
        data["descriptor"]["version"] = "forged"
    else:
        units = list(data["units"])
        if mutation == "duplicate":
            units[1] = units[0]
        elif mutation == "missing":
            units.pop()
        elif mutation == "unknown":
            units[-1]["unit_id"] = "UNKNOWN"
        else:
            # Deliberately bypass constructor; the gateway must revalidate plugin output.
            corrupted = batch.units[0].model_copy(
                update={"probabilities": (float("nan"), 0.0, 0.0, 0.0)}
            )
            batch = batch.model_copy(update={"units": (corrupted, *batch.units[1:])})
        data["units"] = units
    if mutation != "nan":
        batch = RecommendationBatch.model_validate(data)
    state = (list(env.state.surge_until), dict(env.state.renfort), len(env.journal.actions))
    with pytest.raises(ValueError):
        env.act(batch)
    assert (env.state.surge_until, env.state.renfort, len(env.journal.actions)) == state
    assert not env.ledger


def test_exact_retry_is_idempotent_and_changed_retry_is_rejected(config: HospitalConfig) -> None:
    env = ready(config)
    batch = batch_for(env)
    first = env.act(batch)
    state = (list(env.state.surge_until), dict(env.state.renfort), len(env.journal.events))
    assert env.act(batch) == first
    assert len(env.ledger) == len(first)
    assert (env.state.surge_until, env.state.renfort, len(env.journal.events)) == state
    with pytest.raises(ValueError, match="already committed"):
        env.act(batch_for(env, q=0.0))


def test_decision_clock_cannot_be_skipped_or_rewound(config: HospitalConfig) -> None:
    env = loop.PolicyEnvironment(config, ObservedRulePolicy().descriptor)
    with pytest.raises(ValueError, match="Reset"):
        env.observe()
    env.reset()
    with pytest.raises(ValueError, match="09:00"):
        env.act(batch_for(env))
    for _ in range(9):
        env.advance()
    count = len(env.features)
    assert env.observe() == env.observe()
    assert len(env.features) == count
    with pytest.raises(ValueError, match="abstention"):
        env.advance()
    with pytest.raises(ValueError, match="forward"):
        env.cursor.advance(8, ())


def test_refused_recommendations_do_not_execute(config: HospitalConfig) -> None:
    env = ready(config)
    env.sim.x.u_expo[:] = 0
    env.sim.x.u_politique[:] = 1
    records = env.act(batch_for(env))
    assert all(r.recommended and r.exposed and r.approval == "rejected" for r in records)
    assert all(not r.requested and r.execution == "not_requested" for r in records)


def test_unexposed_recommendations_are_distinct_from_cadre_initiatives(
    config: HospitalConfig,
) -> None:
    env = ready(config)
    env.sim.x.u_expo[:] = 1
    env.sim.x.u_politique[:] = 0
    records = env.act(batch_for(env))
    assert all(r.approval == "not_presented" for r in records)
    assert any(r.requested for r in records)
    assert all(r.action_origin == "cadre_initiative" for r in records if r.requested)


def test_no_recommendation_is_not_no_cadre_action(config: HospitalConfig) -> None:
    env = ready(config)
    env.sim.x.u_politique[:] = 0
    records = env.act(batch_for(env, q=0.0))
    assert all(not r.recommended and r.approval == "not_recommended" for r in records)
    assert any(r.action_origin == "cadre_initiative" for r in records)


@pytest.mark.parametrize("filled,status", [(0, "failed"), (1, "partially_applied"), (2, "applied")])
def test_staffing_failure_partial_and_complete_confirmations(
    config: HospitalConfig,
    filled: int,
    status: str,
) -> None:
    env = ready(config)
    env.sim.x.u_expo[:] = 0
    env.sim.x.u_politique[:] = 0
    env.sim.x.u_renfort[:] = 1
    absolute_day = (env.hour + env.sim.h0_rec) // 24
    slots = (3 * absolute_day + 2, 3 * (absolute_day + 1) + 1)
    for slot in slots[:filled]:
        env.sim.x.u_renfort[:, slot] = 0
    records = env.act(batch_for(env))
    staff = [r for r in records if r.lever == "renfort_soignant"]
    assert all(r.approval == "approved" and r.execution == status for r in staff)
    assert all(r.affected_count == filled for r in staff)
    assert all(r.confirmed_shift_starts_h == (15, 31)[:filled] for r in staff)
    for _ in range(6):
        env.advance()
    if filled:
        pres, sid = env.sim.presents(env.state, 0, env.hour + env.sim.h0_rec)
        baseline = (
            env.sim.x.prevus[0, sid] - env.sim.x.absents[0, sid] + env.sim.x.remplaces[0, sid]
        )
        assert pres == baseline + 1


def test_extra_beds_already_active_report_no_effect(config: HospitalConfig) -> None:
    env = ready(config)
    env.sim.x.u_expo[:] = 0
    env.sim.x.u_politique[:] = 0
    env.state.surge_until[:] = [env.sim.h0_rec + 100] * env.sim.U
    rows = [r for r in env.act(batch_for(env)) if r.lever == "lits_supplementaires"]
    assert all(r.execution == "not_applicable" and r.affected_count == 0 for r in rows)


@pytest.mark.parametrize("family", ["v041", "local_v1", "hybrid_v1"])
def test_policy_loop_works_with_each_resource_family(config: HospitalConfig, family: str) -> None:
    changed = HospitalConfig.model_validate({**config.model_dump(), "mechanism_family": family})
    env = finish(ready(changed))
    checks = loop.validate_run(env)
    assert checks["online_replay_equal"]
    assert all(v == 0 for k, v in checks["physical"].items() if k != "heures_controlees")
    assert checks["decision_records"] == config.days * len(config.units) * 4
    assert all(d.available_h <= config.days * 24 for d in env.stream.delivered)
    with pytest.raises(ValueError, match="finished"):
        env.advance()


@pytest.mark.parametrize("mutation", ["missing", "context", "identity", "probability", "count"])
def test_ledger_mutations_rejected(config: HospitalConfig, mutation: str) -> None:
    env = finish(ready(config))
    if mutation == "missing":
        env.ledger.pop()
    else:
        pos = next(
            i
            for i, r in enumerate(env.ledger)
            if r.execution == "applied" and r.lever != "renfort_soignant"
        )
        record = env.ledger[pos]
        options: dict[str, dict[str, Any]] = {
            "context": {"context_sha256": "0" * 64},
            "identity": {"hospital_id": "OTHER"},
            "probability": {"recommendation_probability": 0.001},
            "count": {"affected_count": record.affected_count + 1},
        }
        env.ledger[pos] = record.model_copy(update=options[mutation])
    with pytest.raises(ValueError):
        loop.validate_run(env)


def test_export_reproducible_and_receipts_not_renoised(
    config: HospitalConfig, tmp_path: Path
) -> None:
    a = loop.run_policy(config, ObservedRulePolicy(), tmp_path / "a")
    b = loop.run_policy(config, ObservedRulePolicy(), tmp_path / "b")
    assert a == b
    for name, digest in a["files_sha256"].items():
        assert _sha(tmp_path / "a" / name) == _sha(tmp_path / "b" / name) == digest
    assert not a["test_opened"]
    with gzip.open(tmp_path / "a/decisions/contexts.jsonl.gz", "rt") as stream:
        contexts = [json.loads(line) for line in stream]
    assert len(contexts) == config.days
    assert all(
        s["available_h"] <= c["decision_h"]
        for c in contexts
        for r in c["observations"]
        for s in r["sources"]
    )
    assert a["checks"]["online_replay_equal"]
    with pytest.raises(FileExistsError):
        loop.run_policy(config, ObservedRulePolicy(), tmp_path / "a")


def test_test_partition_rejected_before_simulation(
    config: HospitalConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(_: HospitalConfig) -> Any:
        pytest.fail("Test simulation must not start")

    monkeypatch.setattr(loop, "build_simulation", forbidden)
    reserved = HospitalConfig.model_validate({**config.model_dump(), "partition": "test"})
    with pytest.raises(ValueError, match="reserved test"):
        loop.PolicyEnvironment(reserved, ObservedRulePolicy().descriptor)


def test_plugin_failure_publishes_no_partial_run(config: HospitalConfig, tmp_path: Path) -> None:
    class Broken(NoRecommendationPolicy):
        def recommend(self, context: PolicyContext) -> RecommendationBatch:
            raise RuntimeError("plugin failed")

    with pytest.raises(RuntimeError, match="plugin failed"):
        loop.run_policy(config, Broken(), tmp_path / "result")
    assert not (tmp_path / "result").exists()


@pytest.mark.parametrize("shape", ["one_unit", "three_poles"])
def test_loop_supports_unit_and_larger_hospital(config: HospitalConfig, shape: str) -> None:
    raw = config.model_dump(mode="json")
    if shape == "one_unit":
        raw["poles"] = [raw["poles"][0]]
        raw["poles"][0]["units"] = [raw["poles"][0]["units"][0]]
    else:
        extra = json.loads(json.dumps(raw["poles"][0]))
        extra["pole_id"] = "EXTRA_POLE"
        for index, unit in enumerate(extra["units"]):
            unit["unit_id"] = f"EXTRA_U{index}"
        raw["poles"].append(extra)
    changed = HospitalConfig.model_validate(raw)
    env = finish(ready(changed))
    assert loop.validate_run(env)["decision_records"] == changed.days * len(changed.units) * 4


def test_reset_restores_same_context_and_clears_actions(config: HospitalConfig) -> None:
    env = ready(config)
    before = env.observe()
    receipts = env.act(batch_for(env))
    env.reset()
    for _ in range(9):
        env.advance()
    assert env.observe() == before
    assert not env.ledger
    assert env.act(batch_for(env)) == receipts
