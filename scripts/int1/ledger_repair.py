#!/usr/bin/env python3
"""INT-1 ledger repair after a concurrent-append race (incident logged, nothing deleted).

The broken file and its anchor are archived verbatim; the chain is rebuilt in the ORIGINAL order (records 1-36
unchanged and identical; the two racing 'command_started' records re-chained), then an 'incident' record cites the
original hashes and three 'command' completion records are RECONSTRUCTED for the commands whose final append failed
(wall from their run logs; CPU unknown -> conservative estimate wall x declared concurrency; flagged)."""
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ds_budget_run as base  # noqa: E402

LED = ROOT / "evidence/howm_int1/LEDGER_INT1.jsonl"
ANC = LED.with_name(LED.stem + ".anchor.json")
lines = [json.loads(x) for x in LED.read_text().splitlines() if x.strip()]
arch = LED.with_name("LEDGER_INT1.broken_at_line38.jsonl")
shutil.copy(LED, arch)
shutil.copy(ANC, arch.with_name("LEDGER_INT1.broken_at_line38.anchor.json"))
orig = [(r.get("sequence"), r["kind"], r.get("label"), r.get("previous_sha256"), r.get("record_sha256")) for r in lines[36:]]
LED.unlink()
ANC.unlink()
for r in lines:
    body = {k: v for k, v in r.items() if k not in ("sequence", "previous_sha256", "record_sha256")}
    base.append(LED, body)
now = datetime.now(UTC).isoformat()
base.append(LED, {"kind": "incident", "at_utc": now, "lot": "INT.L0", "label": "ledger concurrent-append race at line 38 (repaired, archived)",
                  "payload": {"archived_file": str(arch.relative_to(ROOT)), "original_records_37_38": orig,
                              "cause": "two runner processes appended 'command_started' concurrently (no file lock); later appends refused",
                              "fix": "fcntl lock around every append in scripts/howm_int1_run.py; chain rebuilt in original order"},
                  "wall_seconds": 0.0})
recon = [("INT.DATA", "Corpus VAL: INT_VAL 0-299, K=4 common futures (cmd 1) [RECONSTRUCTED completion]", "evidence/howm_int1/runlogs/0036_INT.DATA_20261117T163523039346Z.log", 494.5, 4),
         ("INT.L0", "Training cost pilot W-S [RECONSTRUCTED completion; failed: K-size concat bug]", "evidence/howm_int1/runlogs/0037_INT.L0_20261117T163924331491Z.log", 10.5, 1),
         ("INT.L0", "Training cost pilot W-M [RECONSTRUCTED completion; failed: K-size concat bug]", "evidence/howm_int1/runlogs/0037_INT.L0_20261117T163924333082Z.log", 10.5, 1)]
for lot, label, log, wall, conc in recon:
    base.append(LED, {"kind": "command", "at_utc": now, "lot": lot, "label": label, "log": log, "wall_seconds": wall,
                      "cpu_seconds": round(wall * conc, 3), "cpu_estimated_conservative": True, "reconstructed": True, "concurrency_declared": conc})
print(len(base.read_ledger(LED)), "records; chain ok")
