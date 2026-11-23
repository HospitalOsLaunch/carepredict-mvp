"""Read-only access to the HOWM-1 ledger notes (for guards)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LEDGER = Path(__file__).resolve().parents[3] / "evidence" / "howm1" / "BUDGET_LEDGER_HOWM1.jsonl"


def notes() -> list[dict[str, Any]]:
    if not LEDGER.exists():
        return []
    return [json.loads(line) for line in LEDGER.read_text().splitlines() if line.strip()]


def last_note(kind: str) -> dict[str, Any] | None:
    out = [r for r in notes() if r.get("kind") == kind]
    return out[-1] if out else None
