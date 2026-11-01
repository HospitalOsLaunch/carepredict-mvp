"""MCO unit codes are accepted wherever a unit code is validated (pools, staffing)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.models import BedPool, Group

MakeGroup = Callable[[str], Group]
Login = Callable[[str], dict[str, str]]


def test_admin_creates_an_mco_unit_with_its_kind(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    admin = login("admin@g1.fr")
    site_id = app_client.get("/api/sites", headers=admin).json()[0]["id"]

    created = app_client.put(
        f"/api/sites/{site_id}/pools/cardiologie",
        json={"beds_installed": 20, "beds_open": 18, "reason": "personnel"},
        headers=admin,
    )

    assert created.status_code == 200, created.text
    pool = next(p for p in created.json()["pools"] if p["mention"] == "cardiologie")
    assert (pool["beds_installed"], pool["beds_open"]) == (20, 18)
    row = db.scalars(select(BedPool).where(BedPool.mention == "cardiologie")).one()
    assert (row.unit_type, row.discipline) == ("medecine", "medecine")


def test_unknown_unit_code_is_still_rejected(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    admin = login("admin@g1.fr")
    site_id = app_client.get("/api/sites", headers=admin).json()[0]["id"]

    response = app_client.put(
        f"/api/sites/{site_id}/pools/inconnue",
        json={"beds_installed": 1, "beds_open": 1, "reason": "ouverture"},
        headers=admin,
    )

    assert response.status_code == 422


def test_staffing_accepts_an_mco_unit(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    admin = login("admin@g1.fr")
    site_id = app_client.get("/api/sites", headers=admin).json()[0]["id"]
    app_client.put(
        f"/api/sites/{site_id}/pools/cardiologie",
        json={"beds_installed": 20, "beds_open": 20, "reason": "ouverture"},
        headers=admin,
    )

    weekly = app_client.put(
        f"/api/staffing/{site_id}/cardiologie/weekly", json={"hours": [80.0] * 7}, headers=admin
    )

    assert weekly.status_code == 200, weekly.text
