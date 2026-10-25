from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from fastapi.testclient import TestClient

from services.admissions_smr.models import Group
from services.admissions_smr.tests.conftest import TODAY

Login = Callable[[str], dict[str, str]]
MakeGroup = Callable[[str], Group]


def _first_present(client: TestClient, h: dict[str, str]) -> dict[str, object]:
    stays = client.get("/api/stays", headers=h).json()
    assert stays
    first: dict[str, object] = stays[0]
    return first


def test_planned_dates_are_historised(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    h = login("coord@g1.fr")
    stay = _first_present(app_client, h)
    for day in (5, 7, 7):
        planned = (TODAY + timedelta(days=day)).isoformat()
        r = app_client.patch(
            f"/api/stays/{stay['id']}", json={"planned_discharge_date": planned}, headers=h
        )
        assert r.status_code == 200, r.text
    assert r.json()["plan_changes"] == 2  # the repeated date is not a new plan
    cleared = app_client.patch(
        f"/api/stays/{stay['id']}", json={"clear_planned": True}, headers=h
    ).json()
    assert cleared["plan_changes"] == 3 and cleared["planned_discharge_date"] is None
    level = app_client.patch(f"/api/stays/{stay['id']}", json={"care_level": 4}, headers=h).json()
    assert level["care_level"] == 4


def test_staffing_drives_workload_tension(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    admin, coord = login("admin@g1.fr"), login("coord@g1.fr")
    site_id = app_client.get("/api/sites", headers=admin).json()[0]["id"]
    workload = app_client.get(f"/api/forecast/workload?site_id={site_id}", headers=coord).json()
    pool = next(p for p in workload["pools"] if p["mention"] == "geriatrie")
    assert not pool["staffing_configured"]
    assert {d["tension"] for d in pool["days"]} == {"inconnue"}

    weekly = app_client.put(
        f"/api/staffing/{site_id}/geriatrie/weekly", json={"hours": [100.0] * 7}, headers=coord
    )
    assert weekly.status_code == 200, weekly.text
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    app_client.put(
        f"/api/staffing/{site_id}/geriatrie/days/{tomorrow}",
        json={"care_hours": 1.0},
        headers=coord,
    )
    staffing = next(
        p
        for p in app_client.get("/api/staffing", headers=coord).json()
        if p["site_id"] == site_id and p["mention"] == "geriatrie"
    )
    assert staffing["weekly_hours"] == [100.0] * 7 and staffing["overrides"] == {tomorrow: 1.0}

    pool = next(
        p
        for p in app_client.get(f"/api/forecast/workload?site_id={site_id}", headers=coord).json()[
            "pools"
        ]
        if p["mention"] == "geriatrie"
    )
    by_day = {d["day"]: d for d in pool["days"]}
    assert pool["staffing_configured"]
    assert by_day[TODAY.isoformat()]["staff_minutes"] == 6000.0
    assert by_day[TODAY.isoformat()]["tension"] == "normale"
    assert by_day[tomorrow]["tension"] == "tension"
    assert by_day[tomorrow]["prob_over_capacity"] == 1.0

    removed = app_client.put(
        f"/api/staffing/{site_id}/geriatrie/days/{tomorrow}",
        json={"care_hours": None},
        headers=coord,
    )
    assert next(p for p in removed.json() if p["mention"] == "geriatrie")["overrides"] == {}
    assert (
        app_client.put(
            f"/api/staffing/{site_id}/geriatrie/weekly",
            json={"hours": [1.0] * 7},
            headers=login("dir@g1.fr"),
        ).status_code
        == 403
    )


def test_care_minutes_are_group_settings(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    admin = login("admin@g1.fr")
    assert app_client.get("/api/settings", headers=admin).json()["care_minutes"]["4"] == 240.0
    bad = app_client.put("/api/settings", json={"care_minutes": {"5": 10}}, headers=admin)
    assert bad.status_code == 422
    ok = app_client.put(
        "/api/settings", json={"care_minutes": {"4": 300, "entree": 90}}, headers=admin
    ).json()
    assert ok["care_minutes"]["4"] == 300.0 and ok["care_minutes"]["1"] == 45.0
    assert (
        app_client.get("/api/forecast/workload", headers=admin).json()["care_minutes"]["entree"]
        == 90.0
    )


def test_workload_backtest_runs(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    result = app_client.get("/api/metrics/backtest/workload", headers=login("dir@g1.fr")).json()
    assert result["points"] and result["coverage_80"] is not None
