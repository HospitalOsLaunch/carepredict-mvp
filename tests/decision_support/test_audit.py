"""Audit — archive integrity, budget stop, provenance, no hard-coded product figures."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from hospitalos.decision_support.audit import (
    ArchiveIntegrityError,
    ProvenanceError,
    check_result_claim,
    resolve_pointer,
    verify_archive,
    verify_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
PRIMARY = "a7bf5dcc63fcc2391636b20ed3ac1726c7bcf796b8293beb6dc25003c71f9475"
DETACHED = "db72732e55d237bea7a0e6fa3714e7d3627e0469add996ead25bb5e8254b387b"


def _budget():
    spec = importlib.util.spec_from_file_location("ds_budget_run", ROOT / "scripts/ds_budget_run.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_t01_altered_archive_stops_restoration(tmp_path):
    good = tmp_path / "a.txt"
    good.write_text("payload")
    import hashlib

    digest = hashlib.sha256(b"payload").hexdigest()
    verify_archive(good, digest)
    manifest = tmp_path / "SHA256SUMS"
    manifest.write_text(f"{digest}  a.txt\n")
    assert verify_manifest(tmp_path, manifest) == []
    good.write_text("payload-altered")
    with pytest.raises(ArchiveIntegrityError):
        verify_archive(good, digest)
    assert verify_manifest(tmp_path, manifest) == ["altered:a.txt"]


def test_t29_budget_stop_is_clean_and_never_resets(tmp_path):
    b = _budget()
    ledger, logs = tmp_path / "ledger.jsonl", tmp_path / "logs"
    quick = [sys.executable, "-c", "import time; time.sleep(0.25)"]
    # the timeout is capped by the remaining cumulative budget: the command is killed at 0.2 s
    assert b.run(quick, lot="T", label="1", ledger=ledger, logs=logs, limit=0.2) == 124
    assert b.run(quick, lot="T", label="2", ledger=ledger, logs=logs, limit=0.2) == 3
    state = b.status(ledger, 0.2)
    assert state["stopped"] is True and state["commands"] == 1
    assert b.run(quick, lot="T", label="3", ledger=ledger, logs=logs, limit=999) == 3  # no reset
    slow = [sys.executable, "-c", "import time; time.sleep(30)"]
    other = tmp_path / "ledger2.jsonl"
    assert b.run(slow, lot="T", label="slow", ledger=other, logs=logs, per_command=0.5) == 124
    record = [json.loads(x) for x in other.read_text().splitlines()][-1]
    assert record["timed_out"] is True and record["wall_seconds"] < 5
    lines = ledger.read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["wall_seconds"] = 0.0
    ledger.write_text("\n".join([json.dumps(tampered, sort_keys=True), *lines[1:]]) + "\n")
    with pytest.raises(b.LedgerError):
        b.read_ledger(ledger)


def test_t31_primary_result_cannot_be_passed_off_as_detached():
    assert check_result_claim({"archive_sha256": DETACHED, "mode": "A_detached", "updates": 2000})
    with pytest.raises(ProvenanceError):  # 6000 PRIMARY copied as the fallback result
        check_result_claim({"archive_sha256": DETACHED, "mode": "A_detached", "updates": 6000})
    with pytest.raises(ProvenanceError):
        check_result_claim({"archive_sha256": PRIMARY, "mode": "A_detached", "updates": 6000})
    with pytest.raises(ProvenanceError):  # unattested final != scientific failure
        check_result_claim({"archive_sha256": DETACHED, "mode": "A_detached", "updates": 2000,
                            "status": "SCIENTIFIC_FAILURE"})
    assert check_result_claim({"archive_sha256": PRIMARY, "mode": "primary", "updates": 6000})[
        "status"] == "COMPLETED_CRITERIA_FAILED"


def test_t32_no_hard_coded_product_figures_in_engine_or_cockpit():
    sources = [*ROOT.glob("src/hospitalos/decision_support/*.py"),
               *ROOT.glob("web/decision/*.ts"), *ROOT.glob("web/decision/*.html")]
    assert sources
    forbidden = re.compile(r"\b2\s*IDE\b|\b9\s*/\s*10\b|\b4\s*/\s*10\b|9/10\s*->\s*4/10", re.I)
    offenders = [str(p) for p in sources if forbidden.search(p.read_text())]
    assert offenders == []


def test_json_pointer_resolution():
    doc = {"a": [{"b/c": 3}]}
    assert resolve_pointer(doc, "/a/0/b~1c") == 3
