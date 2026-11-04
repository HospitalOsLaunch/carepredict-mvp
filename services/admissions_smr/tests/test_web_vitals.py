"""Core Web Vitals of real visits (règle 30): sent to the group's API, nothing personal kept."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from services.admissions_smr.api.routes_web_vitals import p75, rating
from services.admissions_smr.models import Group, WebVital

from .conftest import TODAY


def vital(
    metric: str, value: float, page: str = "/plan-des-lits", device: str = "mobile"
) -> dict[str, object]:
    return {"metric": metric, "value": value, "page": page, "device": device, "connection": "4g"}


def test_each_persona_reports_and_the_administrator_reads_the_75th_percentile(
    app_client: TestClient,
    make_group: Callable[[str], Group],
    login: Callable[[str], dict[str, str]],
) -> None:
    make_group("g1")
    for email, values in (("coord@g1.fr", [900, 1200]), ("dir@g1.fr", [3100, 5200])):
        response = app_client.post(
            "/api/web-vitals",
            json={"vitals": [vital("LCP", v) for v in values] + [vital("CLS", 0.02)]},
            headers=login(email),
        )
        assert response.status_code == 204, response.text

    summary = app_client.get("/api/web-vitals", headers=login("admin@g1.fr")).json()
    rows = {(r["page"], r["metric"]): r for r in summary["rows"]}
    assert rows[("/plan-des-lits", "LCP")] == {
        "page": "/plan-des-lits",
        "metric": "LCP",
        "p75": 3100,
        "samples": 4,
        "rating": "a_ameliorer",
    }
    assert rows[("/plan-des-lits", "CLS")]["rating"] == "bon"
    assert summary["samples"] == 6

    # Only the administrator reads them; the agent's service account does not report.
    assert app_client.get("/api/web-vitals", headers=login("coord@g1.fr")).status_code == 403
    assert (
        app_client.post(
            "/api/web-vitals", json={"vitals": [vital("LCP", 1)]}, headers=login("agent@g1.fr")
        ).status_code
        == 403
    )
    assert app_client.post("/api/web-vitals", json={"vitals": [vital("LCP", 1)]}).status_code == 401


def test_a_measure_keeps_nothing_that_ties_it_to_a_person(
    app_client: TestClient,
    db: Session,
    make_group: Callable[[str], Group],
    login: Callable[[str], dict[str, str]],
) -> None:
    make_group("g1")
    # A screen the browser could not reduce to a template (an id in it) is stored as « autre ».
    app_client.post(
        "/api/web-vitals",
        json={
            "vitals": [vital("INP", 180, page="/demandes/4512"), vital("TTFB", 210, page="/lits")]
        },
        headers=login("coord@g1.fr"),
    )
    columns = {c["name"] for c in inspect(db.get_bind()).get_columns("web_vitals")}
    assert columns == {
        "id",
        "group_id",
        "recorded_on",
        "page",
        "metric",
        "value",
        "device",
        "connection",
    }
    pages = set(db.scalars(select(WebVital.page)))
    assert pages == {"autre", "/lits"}


def test_reports_are_bounded_and_groups_do_not_see_each_other(
    app_client: TestClient,
    make_group: Callable[[str], Group],
    login: Callable[[str], dict[str, str]],
) -> None:
    make_group("g1")
    make_group("g2")
    coord = login("coord@g1.fr")
    too_many = {"vitals": [vital("LCP", 1000)] * 21}
    assert app_client.post("/api/web-vitals", json=too_many, headers=coord).status_code == 422
    assert (
        app_client.post(
            "/api/web-vitals", json={"vitals": [vital("CLS", 60)]}, headers=coord
        ).status_code
        == 422
    )
    assert (
        app_client.post(
            "/api/web-vitals", json={"vitals": [vital("FID", 10)]}, headers=coord
        ).status_code
        == 422
    )
    app_client.post("/api/web-vitals", json={"vitals": [vital("LCP", 1000)]}, headers=coord)
    assert app_client.get("/api/web-vitals", headers=login("admin@g2.fr")).json()["rows"] == []


def test_measures_older_than_ninety_days_are_purged(
    app_client: TestClient,
    db: Session,
    make_group: Callable[[str], Group],
    login: Callable[[str], dict[str, str]],
) -> None:
    group = make_group("g1")
    for age in (91, 89):
        db.add(
            WebVital(
                group_id=group.id,
                recorded_on=TODAY - timedelta(days=age),
                page="/lits",
                metric="LCP",
                value=1000,
                device="bureau",
                connection="4g",
            )
        )
    db.commit()
    app_client.post(
        "/api/web-vitals", json={"vitals": [vital("LCP", 800)]}, headers=login("coord@g1.fr")
    )
    db.expire_all()
    ages = sorted((TODAY - d).days for d in db.scalars(select(WebVital.recorded_on)))
    assert ages == [0, 89]


def test_percentile_and_rating() -> None:
    assert p75([1, 2, 3, 4]) == 3
    assert p75([10]) == 10
    assert p75([5, 1, 9, 7, 3, 2, 8, 4]) == 7
    assert rating("INP", 200) == "bon" and rating("INP", 201) == "a_ameliorer"
    assert rating("CLS", 0.3) == "mauvais"
