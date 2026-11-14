"""Post-restoration check: run AFTER restore.sh in a fresh directory.

AUDIT_PACKAGE=/path/package AUDIT_RESTORED=/path/restored \
python -m pytest -q /path/test_v4_restoration_counter.py

The restored runtime must inherit the terminal history, not an older source-tree copy.
Subsequent test commands may add records; the terminal must remain an exact prefix.
"""
import json
import os
from pathlib import Path
import pytest


def test_restored_runtime_preserves_sealed_terminal_history():
    package = os.environ.get('AUDIT_PACKAGE')
    restored = os.environ.get('AUDIT_RESTORED')
    if not package or not restored:
        pytest.skip('Set AUDIT_PACKAGE and AUDIT_RESTORED after a real fresh restoration.')
    package = Path(package)
    restored = Path(restored)
    terminal = json.loads((package/'LEDGER_TERMINAL.json').read_text())
    expected = [json.loads(l) for l in (package/'ledger/BUDGET_LEDGER.jsonl').read_text().splitlines() if l.strip()]
    actual = [json.loads(l) for l in (restored/'evidence/decision_support/BUDGET_LEDGER.jsonl').read_text().splitlines() if l.strip()]
    assert len(actual) >= terminal['records'], (
        f"Restored {len(actual)} records, sealed terminal {terminal['records']}; lost consumed budget.")
    assert actual[:len(expected)] == expected
    assert round(sum(float(r.get('wall_seconds',0)) for r in actual),3) >= terminal['used_wall_seconds']
