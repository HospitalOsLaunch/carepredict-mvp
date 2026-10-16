from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

import pytest

from hospitalos.operational.experiment import configs
from hospitalos.operational.smr_experiment import REGIMES, audit_ledger, measurements
from hospitalos.synthetic.engine import build_simulation
from hospitalos.synthetic.generate import generate


def test_paired_design_holds_case_mix_clinical_fix_and_topology_constant() -> None:
    plans = [
        json.loads(Path(f"configs/operational/{name}").read_text())
        for name in ("smr_legacy_delay_v1.json", "smr_finite_v1.json")
    ]
    old, finite = [configs(p) for p in plans]
    assert len(old) == len(finite) == 20
    for a, b in zip(old, finite, strict=True):
        assert a.model_dump(exclude={"smr"}) == b.model_dump(exclude={"smr"})
        assert b.smr.mode == "finite_v1"
        assert b.clinical.destinations == "conditional_survival_v1"
    val = [c for c in finite if c.partition == "validation"]
    regimes = [REGIMES[(i + i // 3) % 3] for i in range(len(val))]
    assert all(regimes.count(r) == 2 for r in REGIMES)
    # No old-delay waits can leak into the finite SMR physical schedule.
    a = build_simulation(finite[0])
    p = type("Patient", (), {"pid": 0, "ready_h": 41, "aide_h": -1})()
    a.p_dest[0] = 1
    a.x.pat["aval_j"][0] = 1000
    assert a.planifier(p) == 42


def test_measurement_uses_pending_stock_and_detects_corruption(tmp_path: Path) -> None:
    plan = json.loads(Path("configs/operational/smr_finite_v1.json").read_text())
    plan.update(days=3, warmup_days=7)
    cfg = configs(plan)[0]
    generate(cfg, tmp_path / "source")
    report = measurements(tmp_path / "source")
    assert report["hours"] == 72
    assert "smr_waiting_internal" in report["smr"]["end_snapshot"]
    with gzip.open(tmp_path / "source/truth/events.jsonl.gz", "rt") as stream:
        events = [json.loads(line) for line in stream]
    ledger = [e for e in events if e["type"].startswith("SMR_") or e["type"] == "SORTIE"]
    with (tmp_path / "source/truth/shared_resources_hourly.csv").open() as stream:
        resources = list(csv.DictReader(stream))
    reserved = next(e for e in ledger if e["type"] == "SMR_RESERVED")
    reserved["payload"]["bed"] = cfg.smr.beds
    with pytest.raises(ValueError, match="ledger reservation"):
        audit_ledger(ledger, resources, cfg)
    path = tmp_path / "source/truth/shared_resources_hourly.csv"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="physical evidence"):
        measurements(tmp_path / "source")
