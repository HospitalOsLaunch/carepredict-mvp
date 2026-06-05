"""CSV fallback connector entrypoint."""

from __future__ import annotations

from pathlib import Path


def mapping_exists(mapping_path: Path) -> bool:
    """Return true when a CSV mapping file exists."""
    return mapping_path.exists() and mapping_path.is_file()
