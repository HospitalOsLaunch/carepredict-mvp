"""Error-path tests for the review findings P5L-01..03 (development seeds, doubles/mocks).

No committed partition is generated: the pilot tests use small fixed development seeds and a
temporary output directory; the runner tests use a temporary ledger and a Popen that must not
be called.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ds_budget_run as base  # noqa: E402
import p5_budget_run as runner  # noqa: E402

from hospitalos.decision_support.planner import Settings  # noqa: E402
from hospitalos.decision_support.snapshot import load_profile  # noqa: E402
from hospitalos.p5 import integrity  # noqa: E402
from hospitalos.p5 import pilot as P  # noqa: E402
from hospitalos.p5 import truth as T  # noqa: E402
from hospitalos.p5.eval_adapter import Outcome  # noqa: E402
from hospitalos.p5.generator import GeneratorError, check_offer_keys_unique, generate_candidate  # noqa: E402

VENV_PY = str(runner.DEFAULT_VENV / "bin" / "python")
DEV_SEED = 21


# ---------------------------------------------------------------- runner: refuse before launch


@pytest.fixture()
def tmp_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "L.jsonl"
    monkeypatch.setattr(runner, "LEDGER", ledger)
    monkeypatch.setattr(runner, "LOGS", tmp_path / "logs")
    base.append(ledger, {"kind": "genesis", "lot": "P5.0", "wall_seconds": 0.0})

    def forbidden(*a, **k):
        raise AssertionError("Popen must not be called for a refused command")

    monkeypatch.setattr(runner.subprocess, "Popen", forbidden)
    return ledger


def test_program_of_skips_env_assignments():
    assert runner.program_of(["env", "PYTHONPATH=src:.", VENV_PY, "-m", "pytest"]) == VENV_PY
    assert runner.program_of([VENV_PY, "-I", "x.py"]) == VENV_PY
    assert runner.program_of(["/usr/bin/python3.11", "-c", "1"]) == "/usr/bin/python3.11"


def test_wrong_interpreter_refused_before_launch(tmp_ledger):
    code = runner.run(["env", "PYTHONPATH=src", "/usr/bin/python3.11", "-c", "print(1)"], "P5.1", "t")
    assert code == 5
    last = base.read_ledger(tmp_ledger)[-1]
    assert last["kind"] == "refused" and last["reason"].startswith("interpreter_not_authorised")
    assert last["wall_seconds"] == 0.0


def test_modified_dependency_freeze_refused(tmp_ledger, monkeypatch):
    monkeypatch.setattr(runner, "environment", lambda venv=None: {"freeze_sha256": "0" * 64, "python": "3.11.18"})
    assert runner.run([VENV_PY, "-c", "print(1)"], "P5.1", "t") == 5
    assert base.read_ledger(tmp_ledger)[-1]["reason"].startswith("environment_not_approved")


def test_post_install_pair_accepted_only_when_recorded_with_python(tmp_ledger, monkeypatch):
    fake = {"freeze_sha256": "a" * 64, "python": "3.11.18"}
    monkeypatch.setattr(runner, "environment", lambda venv=None: fake)
    assert runner.launch_refusal([VENV_PY], base.read_ledger(tmp_ledger))[0] is not None
    # a note without a Python version never changes Python implicitly: ignored
    base.append(tmp_ledger, {"kind": "environment_approved", "lot": "P5.I", "payload": {"freeze_sha256": "a" * 64}, "wall_seconds": 0.0})
    assert runner.launch_refusal([VENV_PY], base.read_ledger(tmp_ledger))[0] is not None
    base.append(tmp_ledger, {"kind": "environment_approved", "lot": "P5.I", "payload": {"python": "3.11.18", "freeze_sha256": "a" * 64}, "wall_seconds": 0.0})
    assert runner.launch_refusal([VENV_PY], base.read_ledger(tmp_ledger))[0] is None
    assert (runner.D3_PYTHON, runner.D3_FREEZE_SHA256) in runner.approved_environments(base.read_ledger(tmp_ledger))


def test_same_freeze_wrong_python_refused_and_conforming_pair_passes(tmp_ledger, monkeypatch):
    wrong = {"freeze_sha256": runner.D3_FREEZE_SHA256, "python": "3.11.9"}
    monkeypatch.setattr(runner, "environment", lambda venv=None: wrong)
    assert runner.run([VENV_PY, "-c", "1"], "P5.1", "t") == 5
    last = base.read_ledger(tmp_ledger)[-1]
    assert last["kind"] == "refused" and "python=3.11.9" in last["reason"]
    good = {"freeze_sha256": runner.D3_FREEZE_SHA256, "python": "3.11.18"}
    monkeypatch.setattr(runner, "environment", lambda venv=None: good)
    assert runner.launch_refusal([VENV_PY], base.read_ledger(tmp_ledger))[0] is None


def test_in_process_runtime_check():
    approved = {(runner.D3_PYTHON, runner.D3_FREEZE_SHA256)}
    with pytest.raises(P.RuntimeRefused):
        P.check_runtime({"python": "3.11.9", "freeze_sha256": runner.D3_FREEZE_SHA256}, approved)
    with pytest.raises(P.RuntimeRefused):
        P.check_runtime({"python": "3.11.18", "freeze_sha256": "b" * 64}, approved)
    P.check_runtime({"python": "3.11.18", "freeze_sha256": runner.D3_FREEZE_SHA256}, approved)


def test_unauthorised_lot_refusal_is_logged_at_zero_seconds(tmp_ledger):
    assert runner.run([VENV_PY, "-c", "1"], "P5.4", "t") == 4
    last = base.read_ledger(tmp_ledger)[-1]
    assert last["kind"] == "refused" and last["reason"] == "lot_not_authorised:P5.4"
    assert last["wall_seconds"] == 0.0 and last["lot"] == "P5.4"


def test_missing_or_corrupt_ledger_blocks_and_never_restarts_genesis(tmp_path, monkeypatch):
    ledger = tmp_path / "absent.jsonl"
    monkeypatch.setattr(runner, "LEDGER", ledger)
    with pytest.raises(base.LedgerError):
        runner.run([VENV_PY, "-c", "1"], "P5.1", "t")
    assert not ledger.exists()
    base.append(ledger, {"kind": "genesis", "lot": "P5.0", "wall_seconds": 0.0})
    lines = ledger.read_text().splitlines()
    ledger.write_text(lines[0].replace('"P5.0"', '"P5.X"') + "\n")
    with pytest.raises(base.LedgerError):
        runner.run([VENV_PY, "-c", "1"], "P5.4", "t")


def test_unauthorised_lot_refused_without_launch(tmp_ledger):
    assert runner.run([VENV_PY, "-c", "1"], "P5.4", "t") == 4


def test_static_tool_allowed_by_exact_path():
    assert runner.program_of(["/root/.local/bin/ruff", "check"]) in runner.ALLOWED_TOOLS
    assert runner.launch_refusal(["ruff", "check"], [])[0].startswith("interpreter_not_authorised")


# ---------------------------------------------------------------- integrity of the effective commitment


def _commitment_from_disk(paths):
    return {
        "stage": "TEST",
        "code_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
        "seeds": {"commitment_id": "test"},
        "seeds_file_sha256": None,
    }


CODE = ["src/hospitalos/p5/generator.py", "src/hospitalos/p5/pilot.py", "scripts/p5_pilot.py"]


def test_source_identical_to_commitment_passes_and_v6_checked():
    out = integrity.verify(_commitment_from_disk(CODE))
    assert out["commitment_id"] == "test"


def test_source_different_from_commitment_refused():
    c = _commitment_from_disk(CODE)
    c["code_sha256"]["scripts/p5_pilot.py"] = "0" * 64
    with pytest.raises(integrity.IntegrityError, match="code_differs_from_commitment:scripts/p5_pilot.py"):
        integrity.verify(c, check_v6=False)


def test_sealed_seeds_mismatch_refused():
    c = _commitment_from_disk(CODE)
    c["seeds_file_sha256"] = "0" * 64
    with pytest.raises(integrity.IntegrityError, match="sealed_seeds_differ"):
        integrity.verify(c, check_v6=False)


def test_effective_commitment_is_the_last_recorded(tmp_path):
    ledger = tmp_path / "L.jsonl"
    base.append(ledger, {"kind": "genesis", "wall_seconds": 0.0})
    base.append(ledger, {"kind": "commitment", "payload": {"stage": "E0"}, "wall_seconds": 0.0})
    base.append(ledger, {"kind": "commitment", "payload": {"stage": "E1"}, "wall_seconds": 0.0})
    assert integrity.effective_commitment(ledger)["stage"] == "E1"
    with pytest.raises(integrity.IntegrityError):
        integrity.effective_commitment(tmp_path / "absent.jsonl")


# ---------------------------------------------------------------- pilot identity, resume and stops


@pytest.fixture(scope="module")
def profile():
    return load_profile()


@pytest.fixture(scope="module")
def settings():
    return Settings.default()


def _identity(k=2, n_parents=2):
    commitment = {"stage": "TEST", "commitment_id": "test-commitment", "code_sha256": {"x": "y"}}
    env = {"python": "3.11.18", "freeze_sha256": runner.D3_FREEZE_SHA256}
    return P.run_identity(commitment, "TEST_dev", [DEV_SEED], n_parents, k, ("R1",), env, "pilot-sha")


def _run(tmp_path, profile, settings, **kw):
    ident = kw.pop("identity", _identity())
    return ident, P.run_pilot(out_dir=tmp_path, identity=ident, seeds=[DEV_SEED], profile=profile, settings=settings, **kw)


def test_pilot_run_records_identity_and_resumes_without_duplicates(tmp_path, profile, settings):
    ident, summary = _run(tmp_path, profile, settings)
    path = tmp_path / "runs" / ident["run_id"] / "pilot_parents.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert len(rows) == 2 and all(r["run_id"] == ident["run_id"] for r in rows)
    assert all(len(r["structure_id"]) == 16 and str(DEV_SEED) not in r["structure_id"] for r in rows)
    before = path.read_text()
    _run(tmp_path, profile, settings, identity=ident)
    assert path.read_text() == before


def test_other_identity_never_mixed_and_old_records_kept(tmp_path, profile, settings):
    ident, _ = _run(tmp_path, profile, settings)
    run_dir = tmp_path / "runs" / ident["run_id"]
    old = (run_dir / "pilot_parents.jsonl").read_text()
    with (run_dir / "pilot_parents.jsonl").open("a") as fh:
        fh.write(json.dumps({"run_id": "another", "structure_id": "s", "parent_index": 9}) + "\n")
    with pytest.raises(P.ResumeRefused):
        _run(tmp_path, profile, settings, identity=ident)
    (run_dir / "pilot_parents.jsonl").write_text(old)
    ident_file = run_dir / "RUN_IDENTITY.json"
    ident_file.write_text(json.dumps({**ident, "K": 99}))
    with pytest.raises(P.ResumeRefused):
        _run(tmp_path, profile, settings, identity=ident)
    assert (run_dir / "pilot_parents.jsonl").read_text() == old
    other = _identity(k=3)
    assert other["run_id"] != ident["run_id"]
    _run(tmp_path, profile, settings, identity=other)
    assert (run_dir / "pilot_parents.jsonl").read_text() == old


def test_violation_stops_with_receipt(tmp_path, profile, settings):
    def bad_outcome(*a, **k):
        return Outcome(0, 0, 0, 0, 0, 0, 0, ("injected_violation",))

    ident = _identity()
    with pytest.raises(P.PilotStop, match="invariant_or_admissibility_violation"):
        _run(tmp_path, profile, settings, identity=ident, outcome_fn=bad_outcome)
    receipt = json.loads((tmp_path / "runs" / ident["run_id"] / "FAILURE_RECEIPT.json").read_text())
    assert receipt["detail"]["violations"] == ["injected_violation"]
    assert not (tmp_path / "runs" / ident["run_id"] / "pilot_parents.jsonl").exists()
    with pytest.raises(P.ResumeRefused):
        _run(tmp_path, profile, settings, identity=ident)


def test_plan_outside_universe_stops_not_silent_habitual(tmp_path, profile, settings):
    def fake_recommend(snapshot, settings):
        return SimpleNamespace(status="RECOMMENDATION_READY", primary_plan_id="plan-not-in-universe")

    with pytest.raises(P.PilotStop, match="recommended_plan_outside_public_universe"):
        _run(tmp_path, profile, settings, recommend_fn=fake_recommend)


def test_habitual_invariant_failure_is_a_stop_not_an_abstention(tmp_path, profile, settings):
    def infeasible(snapshot, settings):
        return SimpleNamespace(status="INFEASIBLE", primary_plan_id=None, reasons=("habitual_practice_invariant_failure",))

    with pytest.raises(P.PilotStop, match="habitual_practice_invariant_failure"):
        _run(tmp_path, profile, settings, recommend_fn=infeasible)


def test_genuine_abstention_evaluated_as_habitual(tmp_path, profile, settings):
    def abstain(snapshot, settings):
        return SimpleNamespace(status="INSUFFICIENT_DATA", primary_plan_id=None)

    ident, _ = _run(tmp_path, profile, settings, recommend_fn=abstain)
    rows = [json.loads(x) for x in (tmp_path / "runs" / ident["run_id"] / "pilot_parents.jsonl").read_text().splitlines()]
    assert all(r["abstention_as_habitual"] and r["chosen_index"] == 0 for r in rows)


def test_universe_change_stops(tmp_path, profile, settings, monkeypatch):
    original = T.realise

    def mutating(ep, regime, rep, commitment):
        if len(ep.plans) > 1:
            object.__setattr__(ep, "plans", ep.plans[:-1])
        return original(ep, regime, rep, commitment)

    monkeypatch.setattr(P.T, "realise", mutating)
    with pytest.raises(P.PilotStop, match="universe_changed_across_realisations"):
        _run(tmp_path, profile, settings)


# ---------------------------------------------------------------- offer identity


def test_duplicate_offer_key_is_a_generator_stop(profile):
    cand = generate_candidate("TEST_dev", 11, 0, profile, twins=False)
    spec = cand.episodes["A"].spec
    if not spec.offers:
        cand = next(c for c in (generate_candidate("TEST_dev", 11, p, profile, False) for p in range(1, 30))
                    if c.excluded is None and c.episodes["A"].spec.offers)
        spec = cand.episodes["A"].spec
    check_offer_keys_unique(spec)
    dup = replace(spec, offers=(spec.offers[0], replace(spec.offers[0], option_id="DUP")))
    with pytest.raises(GeneratorError, match="duplicate offer_key"):
        check_offer_keys_unique(dup)


def test_real_effective_commitment_verifies_against_disk():
    eff = integrity.effective_commitment()
    out = integrity.verify(eff)
    assert out["stage"] == eff["stage"] and out["stage"].startswith("E") and out["stage"][1:].isdigit()
    assert out["commitment_id"].startswith("276d965d")
