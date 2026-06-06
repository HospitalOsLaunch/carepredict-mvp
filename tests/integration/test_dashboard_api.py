"""Dashboard/API contract smoke test."""

from __future__ import annotations

from pathlib import Path


def test_dashboard_api_client_exists() -> None:
    client_path = Path("services/dashboard/src/api/client.ts")

    assert client_path.exists()
    assert "/predict/charge" in client_path.read_text(encoding="utf-8")
