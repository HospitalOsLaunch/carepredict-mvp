"""MIMIC-IV demo loader placeholder."""

from __future__ import annotations

from pathlib import Path


def mimic_demo_available(path: Path) -> bool:
    """Return whether MIMIC-IV demo files are available locally."""
    return path.exists() and any(path.iterdir())


if __name__ == "__main__":
    raise SystemExit(
        "MIMIC-IV demo loader is scaffolded. Step 2 will add DUA-aware ingestion."
    )
