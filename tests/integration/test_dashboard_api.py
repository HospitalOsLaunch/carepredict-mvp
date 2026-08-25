"""Dashboard/API contract smoke test."""

from __future__ import annotations

from pathlib import Path


def test_dashboard_api_client_exists() -> None:
    client_path = Path("services/dashboard/src/api/client.ts")
    real_client_path = Path("services/dashboard/src/api/real/client.ts")

    assert client_path.exists()
    assert real_client_path.exists()
    assert "fetchChargePrediction" in client_path.read_text(encoding="utf-8")
    assert "/predict/charge" in real_client_path.read_text(encoding="utf-8")
