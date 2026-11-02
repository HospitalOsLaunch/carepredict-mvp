"""Emergency census, boarding series, manual declarations, tension status and HET API."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import count

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.models import AuditEntry, EdVisit, Group, Site
from services.admissions_smr.tests.conftest import NOW
from services.admissions_smr.tests.test_beds_api import add_beds

MakeGroup = Callable[[str], Group]
Login = Callable[[str], dict[str, str]]
# NOW is 2026-10-25 08:30 UTC = 09:30 in Paris (winter time): 10:00 is not reached yet.
_refs = count(1)


def utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def with_ed(app_client: TestClient, db: Session, login: Login, name: str = "g1") -> Site:
    """Gives site A an emergency department and three visits of today."""
    site = db.scalars(select(Site).where(Site.name == f"{name} A")).one()
    created = app_client.put(
        f"/api/sites/{site.id}/pools/urgences",
        json={"beds_installed": 0, "beds_open": 0, "reason": "ouverture"},
        headers=login(f"admin@{name}.fr"),
    )
    assert created.status_code == 200, created.text
    for arrived, decision, left in (
        (utc(25, 6), utc(25, 7), None),  # 07:00 Paris, waiting for a bed
        (utc(25, 8), None, None),  # present, no decision
        (utc(25, 5), None, utc(25, 7)),  # gone
    ):
        add_visit(db, site, arrived, decision, left)
    db.commit()
    return site


def add_visit(
    db: Session, site: Site, arrived: datetime, decision: datetime | None, left: datetime | None
) -> None:
    db.add(
        EdVisit(
            group_id=site.group_id,
            site_id=site.id,
            encounter_ref=f"enc-{next(_refs)}",
            patient_ref="p",
            arrived_at=arrived,
            admit_decision_at=decision,
            left_at=left,
            source="hl7",
        )
    )


def test_census_now_and_provisional_boarding_before_10h(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    site = with_ed(app_client, db, login)

    census = app_client.get("/api/ed/census", headers=login("dir@g1.fr"))

    assert census.status_code == 200, census.text
    body = census.json()
    assert body["site_id"] == site.id and body["ed_sites"] == [{"id": site.id, "name": "g1 A"}]
    now = body["now"]
    assert (now["present"], now["waiting_bed"], now["longest_wait_hours"]) == (2, 1, 1.5)
    today = body["today_10h"]
    assert (today["reached"], today["boarding"], today["source"]) == (False, 1, "calcul")
    assert body["latest_declaration"] is None and body["definitions"]


def test_manual_declaration_takes_over_today_and_is_audited(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    site = with_ed(app_client, db, login)
    coord = login("coord@g1.fr")

    posted = app_client.post(
        "/api/ed/snapshots",
        json={"site_id": site.id, "present": 30, "waiting_bed": 8, "boarding": 4},
        headers=coord,
    )
    census = app_client.get("/api/ed/census", headers=coord).json()

    assert posted.status_code == 201, posted.text
    today = census["today_10h"]
    assert (today["boarding"], today["computed_boarding"], today["source"]) == (
        4,
        1,
        "declaration",
    )
    assert census["latest_declaration"]["boarding"] == 4
    assert db.scalars(select(AuditEntry).where(AuditEntry.action == "urgences.declaration")).one()
    history = app_client.get("/api/ed/snapshots", headers=coord).json()
    assert [s["boarding"] for s in history] == [4]


def test_manual_declaration_is_validated_and_role_checked(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    site = with_ed(app_client, db, login)
    ok = {"site_id": site.id, "present": 10, "waiting_bed": 5, "boarding": 2}

    incoherent = app_client.post(
        "/api/ed/snapshots", json={**ok, "boarding": 6}, headers=login("coord@g1.fr")
    )
    future = app_client.post(
        "/api/ed/snapshots",
        json={**ok, "at": (NOW + timedelta(hours=2)).isoformat()},
        headers=login("coord@g1.fr"),
    )
    negative = app_client.post(
        "/api/ed/snapshots", json={**ok, "present": -1}, headers=login("coord@g1.fr")
    )
    direction = app_client.post("/api/ed/snapshots", json=ok, headers=login("dir@g1.fr"))
    other_site = app_client.post("/api/ed/snapshots", json=ok, headers=login("siteb@g1.fr"))

    assert (incoherent.status_code, future.status_code, negative.status_code) == (422, 422, 422)
    assert (direction.status_code, other_site.status_code) == (403, 403)


def test_boarding_series_ends_yesterday_before_10h(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    site = with_ed(app_client, db, login)
    # 24 Oct (summer time, UTC+2): arrived 07:00, still there at 10:00 → boarding.
    add_visit(db, site, utc(24, 5), utc(24, 6), utc(24, 12))
    db.commit()
    admin = login("admin@g1.fr")

    series = app_client.get("/api/ed/boarding?days=3", headers=admin)

    assert series.status_code == 200, series.text
    days = series.json()["days"]
    assert [d["day"] for d in days] == ["2026-10-22", "2026-10-23", "2026-10-24"]
    assert [d["boarding"] for d in days] == [0, 0, 1]
    assert app_client.get("/api/ed/boarding?days=0", headers=admin).status_code == 422
    assert app_client.get("/api/ed/boarding?days=400", headers=admin).status_code == 422


def test_no_emergency_department_is_a_404(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")

    response = app_client.get("/api/ed/census", headers=login("admin@g1.fr"))

    assert response.status_code == 404


def test_tension_status_lists_units_and_the_het_aid(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    add_beds(db, make_group("g1"))
    with_ed(app_client, db, login)

    status = app_client.get("/api/tension/status", headers=login("dir@g1.fr"))

    assert status.status_code == 200, status.text
    body = status.json()
    assert {(u["site_name"], u["code"]) for u in body["units"]} == {
        ("g1 A", "geriatrie"),
        ("g1 B", "geriatrie"),
    }
    aid = body["aid"]
    assert aid["level"] == "aucun"
    assert {c["code"] for c in aid["criteria"]} == {
        "boarding_10h",
        "waiting_bed",
        "longest_wait_hours",
        "critical_units_share",
    }
    assert "décision de la direction" in aid["notice"]


def test_het_declaration_lifecycle(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    site = with_ed(app_client, db, login)
    coord = login("coord@g1.fr")
    body = {"site_id": site.id, "kind": "het", "level": "niveau_1", "comment": "Afflux"}

    created = app_client.post("/api/tension/declarations", json=body, headers=coord)
    duplicate = app_client.post("/api/tension/declarations", json=body, headers=coord)
    active = app_client.get("/api/tension/status", headers=coord).json()["active_declarations"]
    raised = app_client.patch(
        f"/api/tension/declarations/{created.json()['id']}",
        json={"level": "niveau_2"},
        headers=coord,
    )
    ended = app_client.patch(
        f"/api/tension/declarations/{created.json()['id']}",
        json={"ended_at": NOW.isoformat()},
        headers=coord,
    )
    closed_again = app_client.patch(
        f"/api/tension/declarations/{created.json()['id']}",
        json={"level": "niveau_1"},
        headers=coord,
    )

    assert created.status_code == 201, created.text
    assert created.json()["declared_by"] == "coord@g1.fr"
    assert duplicate.status_code == 409
    assert [d["level"] for d in active] == ["niveau_1"]
    assert raised.json()["level"] == "niveau_2"
    assert ended.json()["ended_at"] is not None
    assert closed_again.status_code == 409
    assert app_client.get("/api/tension/declarations?active=true", headers=coord).json() == []
    actions = db.scalars(
        select(AuditEntry.action).where(AuditEntry.entity == "tension_declaration")
    )
    assert sorted(actions) == ["tension.declaration", "tension.update", "tension.update"]


def test_declarations_are_validated_and_role_checked(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    site = with_ed(app_client, db, login)
    body = {"site_id": site.id, "kind": "plan_blanc", "level": "declenche"}

    bad_level = app_client.post(
        "/api/tension/declarations",
        json={**body, "level": "niveau_1"},
        headers=login("coord@g1.fr"),
    )
    bad_kind = app_client.post(
        "/api/tension/declarations", json={**body, "kind": "orsan"}, headers=login("coord@g1.fr")
    )
    direction = app_client.post("/api/tension/declarations", json=body, headers=login("dir@g1.fr"))
    scoped_other_site = app_client.post(
        "/api/tension/declarations", json=body, headers=login("siteb@g1.fr")
    )
    scoped_establishment = app_client.post(
        "/api/tension/declarations", json={**body, "site_id": None}, headers=login("siteb@g1.fr")
    )
    establishment = app_client.post(
        "/api/tension/declarations", json={**body, "site_id": None}, headers=login("admin@g1.fr")
    )

    assert (bad_level.status_code, bad_kind.status_code) == (422, 422)
    assert direction.status_code == 403
    assert (scoped_other_site.status_code, scoped_establishment.status_code) == (403, 403)
    assert establishment.status_code == 201, establishment.text


def test_another_tenant_sees_nothing(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    site = with_ed(app_client, db, login)
    declared = app_client.post(
        "/api/tension/declarations",
        json={"site_id": site.id, "kind": "het", "level": "niveau_1"},
        headers=login("coord@g1.fr"),
    ).json()
    make_group("g2")
    other = login("admin@g2.fr")

    census = app_client.get(f"/api/ed/census?site_id={site.id}", headers=other)
    snapshot = app_client.post(
        "/api/ed/snapshots",
        json={"site_id": site.id, "present": 1, "waiting_bed": 0, "boarding": 0},
        headers=other,
    )
    patch = app_client.patch(
        f"/api/tension/declarations/{declared['id']}", json={"level": "niveau_2"}, headers=other
    )

    assert (census.status_code, snapshot.status_code, patch.status_code) == (404, 404, 404)
    assert app_client.get("/api/tension/declarations", headers=other).json() == []
    assert app_client.get("/api/tension/status", headers=other).json()["aid"] is None


def test_boarding_series_and_snapshots_stay_within_the_tenant_and_site_scope(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    """T-13: /ed/boarding and GET /ed/snapshots."""
    make_group("g1")
    site = with_ed(app_client, db, login)
    declared = app_client.post(
        "/api/ed/snapshots",
        json={"site_id": site.id, "present": 5, "waiting_bed": 2, "boarding": 1},
        headers=login("coord@g1.fr"),
    )
    assert declared.status_code == 201, declared.text
    make_group("g2")
    other = login("admin@g2.fr")
    scoped = login("siteb@g1.fr")  # coordinator restricted to site B, which has no ED

    for path in ("/api/ed/boarding", "/api/ed/snapshots"):
        assert app_client.get(f"{path}?site_id={site.id}", headers=other).status_code == 404
        assert app_client.get(path, headers=other).status_code == 404  # no ED of their own
        assert app_client.get(f"{path}?site_id={site.id}", headers=scoped).status_code == 403
        assert app_client.get(path, headers=scoped).status_code == 404
    mine = app_client.get("/api/ed/snapshots", headers=login("dir@g1.fr")).json()
    assert [s["id"] for s in mine] == [declared.json()["id"]]
