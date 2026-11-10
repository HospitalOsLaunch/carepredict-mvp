"""Guarded synthetic experiment queue. No model runs without an external signed permit.

The queue is an execution control plane, NOT a scheduler, a GPU sandbox, or a
provider billing limit. Keep its files and training outputs private.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "hospitalos.synthetic-experiment.v1"
RUN_ID = re.compile(r"^[a-z][a-z0-9-]{5,63}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
SHA1 = re.compile(r"^[a-f0-9]{40}$")
RUNNERS = frozenset(("offline_manifest_verify", "rs_jepa_stage1"))
CONFIGS = frozenset(("configs/phaseA.yaml", "configs/phaseA_actioned.yaml"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def within(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Only nonempty relative paths are admitted")
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("Path escapes the allowed repository")
    return candidate


def validate(spec: dict[str, Any], repo: Path) -> dict[str, Any]:
    required = {"schema", "run_id", "runner", "source_commit", "config_path",
                "config_sha256", "synthetic_only", "limits"}
    if not isinstance(spec, dict) or set(spec) != required:
        raise ValueError("Experiment spec must have exactly the declared keys")
    if spec["schema"] != SCHEMA or spec["synthetic_only"] is not True:
        raise ValueError("Only the versioned synthetic-only protocol is accepted")
    if not isinstance(spec["run_id"], str) or not RUN_ID.fullmatch(spec["run_id"]):
        raise ValueError("Invalid run ID")
    if spec["runner"] not in RUNNERS:
        raise ValueError("Runner is not registered (full-model runner unavailable)")
    if not isinstance(spec["source_commit"], str) or not SHA1.fullmatch(spec["source_commit"]):
        raise ValueError("Source commit must be pinned")
    if not isinstance(spec["config_sha256"], str) or not SHA256.fullmatch(spec["config_sha256"]):
        raise ValueError("Configuration hash must be pinned")
    if spec["runner"] == "rs_jepa_stage1" and spec["config_path"] not in CONFIGS:
        raise ValueError("The training runner only accepts its two fixed synthetic configs")
    config = within(repo, spec["config_path"])
    if not config.is_file() or sha(config) != spec["config_sha256"]:
        raise ValueError("Configuration bytes differ from approved spec")
    limits = spec["limits"]
    if not isinstance(limits, dict) or set(limits) != {
        "wall_seconds", "max_epochs", "steps_per_epoch", "max_gpu_count"
    }:
        raise ValueError("Missing or unknown resource limits")
    for key, maximum in (("wall_seconds", 86400), ("max_epochs", 100),
                         ("steps_per_epoch", 500), ("max_gpu_count", 1)):
        value = limits[key]
        if type(value) is not int or not 0 < value <= maximum:
            raise ValueError(f"Invalid {key} resource bound")
    if spec["runner"] == "offline_manifest_verify" and limits["max_gpu_count"] != 1:
        raise ValueError("Invalid offline fixture device bound")
    return spec


def verify_permit(spec_file: Path, public_key: Path, approvals: Path) -> None:
    expected_fingerprint = os.environ.get("HOS_LAB_TRUSTED_PUBKEY_SHA256", "")
    if (not SHA256.fullmatch(expected_fingerprint) or not public_key.is_file()
            or sha(public_key) != expected_fingerprint):
        raise PermissionError("Operator-pinned public key fingerprint is required")
    signature = approvals / (spec_file.stem + ".sig")
    if not signature.is_file() or signature.is_symlink():
        raise PermissionError("A separate operator signature is missing")
    # Openssl verifies the exact raw bytes signed offline by a holder of the
    # private key. The model worker must NEVER receive that private key.
    try:
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-verify", str(public_key),
             "-signature", str(signature), str(spec_file)],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PermissionError("Signature verification could not run") from exc
    if result.returncode != 0 or "Verified OK" not in result.stdout:
        raise PermissionError("Human permit signature invalid")


def verify_journal(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    previous = "GENESIS"
    events = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        row = json.loads(line)
        expected = {k: v for k, v in row.items() if k != "hash"}
        if (row.get("seq") != n or row.get("prev") != previous or
                hashlib.sha256(stable_json(expected)).hexdigest() != row.get("hash")):
            raise ValueError("Experiment evidence journal was modified")
        previous = row["hash"]
        events.append(row)
    return events


def append(path: Path, entry: dict[str, Any]) -> None:
    rows = verify_journal(path)
    record = {"seq": len(rows) + 1, "prev": rows[-1]["hash"] if rows else "GENESIS",
              "at": datetime.now(UTC).isoformat(), "event": entry}
    record["hash"] = hashlib.sha256(stable_json(record)).hexdigest()
    with path.open("a", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def repo_commit(repo: Path) -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
                       text=True, timeout=10, check=False)
    if r.returncode != 0:
        raise RuntimeError("Private worker must use a Git checkout")
    return r.stdout.strip()


def require_clean_repo(repo: Path) -> None:
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                       cwd=repo, capture_output=True, text=True, timeout=10,
                       check=False)
    if r.returncode != 0 or r.stdout.strip():
        raise RuntimeError("Working tree modifications forbid a signed run")


def execute(spec: dict[str, Any], repo: Path, workspace: Path, permit_ok: bool) -> dict[str, Any]:
    if spec["runner"] == "offline_manifest_verify":
        return {"status": "COMPLETE_OFFLINE_METADATA_ONLY",
                "config_sha256": spec["config_sha256"], "model_forward": False}
    if not permit_ok:
        raise PermissionError("Training needs a separately signed approval")
    if os.environ.get("HOS_LAB_PRIVATE_SANDBOX") != "synthetic-only-v1":
        raise PermissionError("Private synthetic-only sandbox attestation missing")
    if repo_commit(repo) != spec["source_commit"]:
        raise RuntimeError("Worker Git commit differs from signed source commit")
    require_clean_repo(repo)
    # Training is restricted to the existing Stage-1 synthetic implementation.
    # The INTEGRATED FULL-MODEL runner has intentionally NOT been registered.
    limits = spec["limits"]
    ckpt = workspace / (spec["run_id"] + ".pt")
    command = [
        sys.executable, "-m", "rs_jepa.cli", "--stage", "1", "--config",
        spec["config_path"], "--max-epochs", str(limits["max_epochs"]),
        "--steps-per-epoch", str(limits["steps_per_epoch"]),
        "--save-checkpoint", str(ckpt),
    ]
    env = {k: v for k, v in os.environ.items()
           if k not in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY"}}
    env["CUDA_VISIBLE_DEVICES"] = "0"
    log = workspace / (spec["run_id"] + ".log")
    with log.open("xb") as output:
        try:
            result = subprocess.run(
                command, cwd=repo, env=env, stdout=output, stderr=subprocess.STDOUT,
                timeout=limits["wall_seconds"], check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Wall-time limit exceeded; subprocess terminated") from exc
    if result.returncode != 0:
        raise RuntimeError(f"Approved synthetic trainer failed: exit {result.returncode}")
    if not ckpt.is_file():
        raise RuntimeError("Trainer returned success without a checkpoint")
    return {"status": "COMPLETE_UNREVIEWED_SYNTHETIC_STAGE1",
            "checkpoint_sha256": sha(ckpt),
            "log_sha256": sha(log), "model_forward": True,
            "note": "No integrated world-model or independent scientific promotion"}


def inspect_queue(queue: Path, repo: Path, journal: Path) -> list[dict[str, Any]]:
    latest: dict[str, str] = {}
    for row in verify_journal(journal):
        ev = row["event"]
        if ev.get("type") in ("STARTED", "FINISHED", "FAILED"):
            latest[ev["run_id"]] = ev["type"]
    items = []
    for path in sorted(queue.glob("*.json")):
        try:
            if path.is_symlink():
                raise ValueError("Symlinked spec not allowed")
            spec = validate(json.loads(path.read_text()), repo)
            if path.stem != spec["run_id"]:
                raise ValueError("Run ID and filename must match")
            items.append({"run_id": spec["run_id"], "runner": spec["runner"],
                          "state": {"FINISHED": "COMPLETED", "FAILED": "FAILED_HALTED",
                                    "STARTED": "INTERRUPTED_NEEDS_REVIEW"}.get(
                                        latest.get(spec["run_id"], ""), "QUEUED")})
        except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
            items.append({"run_id": path.name, "state": "INVALID", "error": str(exc)})
    return items


def tick(queue: Path, repo: Path, workspace: Path, public_key: Path | None,
         approvals: Path | None, allow_training: bool) -> dict[str, Any]:
    queue = queue.resolve()
    repo = repo.resolve()
    if not queue.is_dir() or not repo.is_dir():
        raise ValueError("Queue and repository must already exist")
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = workspace / ".worker.lock"
    # Exclusive non-blocking lock: concurrent workers cannot double-bill a run.
    with lock.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "BLOCKED_WORKER_ALREADY_ACTIVE"}
        journal = workspace / "events.jsonl"
        status = inspect_queue(queue, repo, journal)
        invalid = [i for i in status if i["state"] == "INVALID"]
        if invalid:
            return {"status": "STOP_INVALID_QUEUE", "invalid": invalid}
        unresolved = [i for i in status if i["state"] in (
            "INTERRUPTED_NEEDS_REVIEW", "FAILED_HALTED")]
        if unresolved:
            return {"status": "HALTED_REQUIRES_HUMAN_REVIEW", "unresolved": unresolved}
        pending = next((i for i in status if i["state"] == "QUEUED"), None)
        if pending is None:
            return {"status": "IDLE", "completed_or_empty": True}
        file = queue / (pending["run_id"] + ".json")
        signed_bytes = file.read_bytes()
        spec = validate(json.loads(signed_bytes), repo)
        is_training = spec["runner"] != "offline_manifest_verify"
        if is_training and not allow_training:
            return {"status": "BLOCKED_G2_NO_EXECUTION_FLAG", "run_id": spec["run_id"]}
        if is_training:
            if public_key is None or approvals is None:
                return {"status": "BLOCKED_SIGNED_PERMIT_REQUIRED", "run_id": spec["run_id"]}
            try:
                verify_permit(file, public_key, approvals)
            except PermissionError:
                return {"status": "BLOCKED_PERMIT_INVALID", "run_id": spec["run_id"]}
        # Do not bind a signature to a different in-memory job after a file race.
        if file.read_bytes() != signed_bytes:
            return {"status": "BLOCKED_SPEC_CHANGED_DURING_PREFLIGHT",
                    "run_id": spec["run_id"]}
        append(journal, {"type": "STARTED", "run_id": spec["run_id"],
                         "spec_sha256": sha(file), "runner": spec["runner"]})
        try:
            result = execute(spec, repo, workspace, permit_ok=is_training)
            append(journal, {"type": "FINISHED", "run_id": spec["run_id"], "result": result})
            return {"run_id": spec["run_id"], **result}
        except Exception as exc:
            # Never automatically retry a failed/ambiguous experiment.
            append(journal, {"type": "FAILED", "run_id": spec["run_id"],
                             "error_type": type(exc).__name__})
            return {"status": "FAILED_NO_RETRY", "run_id": spec["run_id"],
                    "error_type": type(exc).__name__}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("inspect", "tick", "loop"))
    p.add_argument("--repo", type=Path, default=Path("."))
    p.add_argument("--queue", required=True, type=Path)
    p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--public-key", type=Path)
    p.add_argument("--approvals", type=Path)
    p.add_argument("--allow-training", action="store_true",
                   help="Still requires a signature and private sandbox per job")
    p.add_argument("--max-jobs", type=int, default=1,
                   help="Bounded queue loop, maximum 100 jobs per invocation")
    a = p.parse_args(argv)
    if not (1 <= a.max_jobs <= 100):
        p.error("--max-jobs must be between 1 and 100")
    try:
        if a.mode == "inspect":
            report = {"queue": inspect_queue(a.queue, a.repo, a.workspace / "events.jsonl"),
                      "execution": False}
        elif a.mode == "tick":
            report = tick(a.queue, a.repo, a.workspace, a.public_key,
                          a.approvals, a.allow_training)
        else:
            history = []
            for _ in range(a.max_jobs):
                result = tick(a.queue, a.repo, a.workspace, a.public_key,
                              a.approvals, a.allow_training)
                history.append(result)
                if result.get("status") not in (
                    "COMPLETE_OFFLINE_METADATA_ONLY",
                    "COMPLETE_UNREVIEWED_SYNTHETIC_STAGE1",
                ):
                    break
            report = {"mode": "bounded_loop", "results": history,
                      "note": "No adaptive model-agent planner or automatic permit grants"}
        print(json.dumps(report, indent=2))
        final = report.get("status") if a.mode != "loop" else history[-1].get("status")
        return 0 if final not in ("FAILED_NO_RETRY", "STOP_INVALID_QUEUE") else 2
    except (ValueError, PermissionError, RuntimeError, OSError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
