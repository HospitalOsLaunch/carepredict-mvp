"""Engines and routing set from the Agents screen: a model sees identifiable screens only on
a stated basis, written in the audit; movements stay with the script."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from services.admissions_smr.models import Group


def policy(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    body: dict[str, Any] = client.get("/api/agent/status", headers=headers).json()["policy"]
    return body


def audit(client: TestClient, headers: dict[str, str]) -> list[str]:
    return [
        e["detail"]
        for e in client.get("/api/audit", headers=headers).json()
        if e["action"] == "agent.donnees_identifiantes"
    ]


def test_a_model_sees_identifiable_screens_only_on_a_stated_basis(
    app_client: TestClient,
    make_group: Callable[[str], Group],
    login: Callable[[str], dict[str, str]],
) -> None:
    make_group("g1")
    admin = login("admin@g1.fr")
    p = policy(app_client, admin)

    p["engines"]["closed_fast"].update(enabled=True, identifiable_data_allowed=True)
    refused = app_client.put("/api/agent/policy", headers=admin, json=p)
    assert refused.status_code == 422
    assert "indiquez sur quoi repose l'autorisation" in refused.json()["detail"]

    p["engines"]["closed_fast"].update(
        identifiable_basis="contrat", identifiable_reference="CT-2026-14"
    )
    saved = app_client.put("/api/agent/policy", headers=admin, json=p)
    assert saved.status_code == 200, saved.text
    assert saved.json()["engines"]["closed_fast"]["identifiable_basis"] == "contrat"
    assert audit(app_client, admin) == [
        "closed_fast autorisé (contrat couvrant les données de santé : CT-2026-14)"
    ]

    # Saving again unchanged writes nothing new; withdrawing clears the basis and is written.
    assert app_client.put("/api/agent/policy", headers=admin, json=p).status_code == 200
    p["engines"]["closed_fast"]["identifiable_data_allowed"] = False
    withdrawn = app_client.put("/api/agent/policy", headers=admin, json=p).json()
    assert withdrawn["engines"]["closed_fast"]["identifiable_basis"] is None
    assert withdrawn["engines"]["closed_fast"]["identifiable_reference"] is None
    assert audit(app_client, admin) == [
        "closed_fast n'est plus autorisé",
        "closed_fast autorisé (contrat couvrant les données de santé : CT-2026-14)",
    ]


def test_movements_stay_with_the_script_and_only_the_administrator_sets_engines(
    app_client: TestClient,
    make_group: Callable[[str], Group],
    login: Callable[[str], dict[str, str]],
) -> None:
    make_group("g1")
    admin = login("admin@g1.fr")
    p = policy(app_client, admin)
    assert p["routes"]["sync_movements"] == ["playbook"]

    p["routes"]["sync_movements"] = ["playbook", "closed_fast"]
    refused = app_client.put("/api/agent/policy", headers=admin, json=p)
    assert refused.status_code == 422
    assert refused.json()["detail"] == "La relève des mouvements se fait par script seulement"

    p["routes"]["sync_movements"] = ["playbook"]
    assert (
        app_client.put("/api/agent/policy", headers=login("coord@g1.fr"), json=p).status_code == 403
    )
