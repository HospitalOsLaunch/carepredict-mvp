"""Offline, no-network tests of the guarded experimental queue."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from research_lab import experimental_autonomy as lab


def fixture(tmp_path: Path, runner: str = "offline_manifest_verify") -> tuple[
    Path, Path, Path, dict[str, object]
]:
    repo = tmp_path / "repo"
    queue = tmp_path / "queue"
    workspace = tmp_path / "private-output"
    repo.mkdir()
    queue.mkdir()
    (repo / "configs").mkdir()
    config = repo / "configs" / "phaseA.yaml"
    config.write_text("synthetic_only: true\n", encoding="utf-8")
    spec: dict[str, object] = {
        "schema": lab.SCHEMA,
        "run_id": "test-run-001",
        "runner": runner,
        "source_commit": "a" * 40,
        "config_path": "configs/phaseA.yaml",
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "synthetic_only": True,
        "limits": {"wall_seconds": 10, "max_epochs": 1,
                   "steps_per_epoch": 1, "max_gpu_count": 1},
    }
    (queue / "test-run-001.json").write_text(json.dumps(spec))
    return repo, queue, workspace, spec


def test_metadata_job_runs_once_and_journal_verifies(tmp_path: Path) -> None:
    repo, queue, work, _ = fixture(tmp_path)
    first = lab.tick(queue, repo, work, None, None, allow_training=False)
    assert first["status"] == "COMPLETE_OFFLINE_METADATA_ONLY"
    assert first["model_forward"] is False
    assert lab.inspect_queue(queue, repo, work / "events.jsonl")[0]["state"] == "COMPLETED"
    assert lab.tick(queue, repo, work, None, None, False)["status"] == "IDLE"
    events = lab.verify_journal(work / "events.jsonl")
    assert [event["event"]["type"] for event in events] == ["STARTED", "FINISHED"]


def test_tampered_journal_refuses_execution(tmp_path: Path) -> None:
    repo, queue, work, _ = fixture(tmp_path)
    lab.tick(queue, repo, work, None, None, False)
    journal = work / "events.jsonl"
    journal.write_text(journal.read_text().replace("FINISHED", "STARTED"))
    with pytest.raises(ValueError, match="modified"):
        lab.tick(queue, repo, work, None, None, False)


def test_training_requires_flag_then_external_signature(tmp_path: Path) -> None:
    repo, queue, work, _ = fixture(tmp_path, "rs_jepa_stage1")
    assert lab.tick(queue, repo, work, None, None, False)["status"] == "BLOCKED_G2_NO_EXECUTION_FLAG"
    assert lab.tick(queue, repo, work, None, None, True)["status"] == "BLOCKED_SIGNED_PERMIT_REQUIRED"
    assert lab.tick(queue, repo, work, repo / "fake.pem", queue, True)["status"] == "BLOCKED_PERMIT_INVALID"
    assert not (work / "events.jsonl").exists()


def test_invalid_runner_schema_and_config_fails_closed(tmp_path: Path) -> None:
    repo, queue, work, spec = fixture(tmp_path)
    for key, value in [
        ("runner", "integrated_full_model"),
        ("synthetic_only", False),
        ("config_path", "../secrets.txt"),
        ("config_sha256", "b" * 64),
    ]:
        altered = dict(spec)
        altered[key] = value
        (queue / "test-run-001.json").write_text(json.dumps(altered))
        assert lab.tick(queue, repo, work, None, None, False)["status"] == "STOP_INVALID_QUEUE"
    assert not (work / "events.jsonl").exists()


def test_configuration_change_detected(tmp_path: Path) -> None:
    repo, queue, work, _ = fixture(tmp_path)
    (repo / "configs" / "phaseA.yaml").write_text("synthetic_only: false\n")
    report = lab.tick(queue, repo, work, None, None, False)
    assert report["status"] == "STOP_INVALID_QUEUE"
    assert "Configuration bytes" in report["invalid"][0]["error"]


def test_aborted_run_is_not_automatically_retried(tmp_path: Path) -> None:
    repo, queue, work, _ = fixture(tmp_path)
    work.mkdir()
    lab.append(work / "events.jsonl", {"type": "STARTED", "run_id": "test-run-001"})
    assert lab.inspect_queue(queue, repo, work / "events.jsonl")[0]["state"] == "INTERRUPTED_NEEDS_REVIEW"
    assert lab.tick(queue, repo, work, None, None, False)["status"] == "HALTED_REQUIRES_HUMAN_REVIEW"


def test_failure_halts_queue_without_running_next_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, queue, work, spec = fixture(tmp_path)
    extra = dict(spec)
    extra["run_id"] = "test-run-002"
    (queue / "test-run-002.json").write_text(json.dumps(extra))
    def fail(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("offline fixture failure")
    monkeypatch.setattr(lab, "execute", fail)
    assert lab.tick(queue, repo, work, None, None, False)["status"] == "FAILED_NO_RETRY"
    assert lab.tick(queue, repo, work, None, None, False)["status"] == "HALTED_REQUIRES_HUMAN_REVIEW"
    items = lab.inspect_queue(queue, repo, work / "events.jsonl")
    assert {x["run_id"]: x["state"] for x in items} == {
        "test-run-001": "FAILED_HALTED", "test-run-002": "QUEUED"}


def test_one_active_worker_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, queue, work, _ = fixture(tmp_path)
    def locked(*_args: object) -> None:
        raise BlockingIOError("already locked")
    monkeypatch.setattr(lab.fcntl, "flock", locked)
    assert lab.tick(queue, repo, work, None, None, False)["status"] == "BLOCKED_WORKER_ALREADY_ACTIVE"
    assert not (work / "events.jsonl").exists()


def test_actual_signed_permit_validation_and_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if shutil.which("openssl") is None:
        pytest.skip("OpenSSL unavailable")
    repo, queue, _work, spec = fixture(tmp_path, "rs_jepa_stage1")
    priv, pub = tmp_path / "operator-private.pem", tmp_path / "operator-public.pem"
    sign = queue / "test-run-001.sig"
    spec_path = queue / "test-run-001.json"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA",
                    "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(priv)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["openssl", "pkey", "-in", str(priv),
                    "-pubout", "-out", str(pub)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(priv),
                    "-out", str(sign), str(spec_path)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with pytest.raises(PermissionError, match="pinned"):
        lab.verify_permit(spec_path, pub, queue)
    monkeypatch.setenv("HOS_LAB_TRUSTED_PUBKEY_SHA256", lab.sha(pub))
    lab.verify_permit(spec_path, pub, queue)
    updated = dict(spec)
    updated["source_commit"] = "b" * 40
    spec_path.write_text(json.dumps(updated))
    with pytest.raises(PermissionError, match="invalid"):
        lab.verify_permit(spec_path, pub, queue)
