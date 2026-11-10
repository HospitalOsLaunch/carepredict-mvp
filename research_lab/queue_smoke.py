"""Zero-ML, zero-network demonstration of the experimental queue.

Runs in an isolated temporary directory. No simulator, model or paid API calls.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .experimental_autonomy import SCHEMA, inspect_queue, sha, tick, verify_journal


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hos-exp-queue-smoke-") as directory:
        temp = Path(directory)
        repo = temp / "fixture_repo"
        queue = temp / "queue"
        work = temp / "private_outputs"
        cfg = repo / "configs" / "phaseA.yaml"
        cfg.parent.mkdir(parents=True)
        cfg.write_text("synthetic_fixture: true\n", encoding="utf-8")
        queue.mkdir()
        run_id = "fixture-run-001"
        spec = {
            "schema": SCHEMA,
            "run_id": run_id,
            "runner": "offline_manifest_verify",
            "source_commit": "0" * 40,
            "config_path": "configs/phaseA.yaml",
            "config_sha256": sha(cfg),
            "synthetic_only": True,
            "limits": {"wall_seconds": 10, "max_epochs": 1,
                       "steps_per_epoch": 1, "max_gpu_count": 1},
        }
        (queue / f"{run_id}.json").write_text(json.dumps(spec), encoding="utf-8")
        result = tick(queue, repo, work, None, None, allow_training=False)
        statuses = inspect_queue(queue, repo, work / "events.jsonl")
        second = tick(queue, repo, work, None, None, allow_training=False)
        evidence = verify_journal(work / "events.jsonl")
        assert result["status"] == "COMPLETE_OFFLINE_METADATA_ONLY"
        assert statuses == [{"run_id": run_id, "runner": "offline_manifest_verify",
                             "state": "COMPLETED"}]
        assert second["status"] == "IDLE" and len(evidence) == 2
        print(json.dumps({
            "status": "PASS_OFFLINE_QUEUE_SMOKE",
            "jobs": 1,
            "verified_events": len(evidence),
            "model_forward": False,
            "training": False,
            "simulator": False,
            "network": False,
            "gpu_spend": 0,
            "full_model_pretrained": False,
        }, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
