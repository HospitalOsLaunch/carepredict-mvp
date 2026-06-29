"""Step-1 isolation checks."""

from __future__ import annotations

from pathlib import Path


def test_gate_python_stays_isolated_from_application_and_tft_branch() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden = (
        "import " + "care" + "predict",
        "postgresql" + "://",
        "timescale" + "db",
        "tft" + "-agnostic",
    )
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if ".venv" in path.parts:
            continue
        text = path.read_text(encoding="utf-8").lower()
        if any(token in text for token in forbidden):
            offenders.append(str(path.relative_to(root)))
    assert offenders == []
