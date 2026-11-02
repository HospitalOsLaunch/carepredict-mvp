"""Bed board API: reading by role and site scope, audited bed actions, tenant isolation."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.models import AuditEntry, Bed, BedPool, Group, Site, Stay
from services.admissions_smr.tests.conftest import NOW

MakeGroup = Callable[[str], Group]
Login = Callable[[str], dict[str, str]]


def add_beds(db: Session, group: Group) -> dict[str, int]:
    """Site A geriatrie: free isolation single, double room with a man, cleaning, blocked.
    Site B geriatrie: one free bed. Returns bed ids by label."""
    site_a, site_b = db.scalars(
        select(Site).where(Site.group_id == group.id).order_by(Site.name)
    ).all()
    pool_a = next(p for p in site_a.pools if p.mention == "geriatrie")
    pool_b = next(p for p in site_b.pools if p.mention == "geriatrie")
    man = db.scalars(
        select(Stay).where(Stay.site_id == site_a.id, Stay.discharge_date.is_(None))
    ).first()
    assert man is not None
    man.patient_sex = "M"

    def bed(pool: BedPool, room: str, label: str, status: str, **kw: object) -> Bed:
        b = Bed(
            group_id=group.id,
            site_id=pool.site_id,
            pool_id=pool.id,
            room=room,
            label=label,
            status=status,
            updated_at=NOW,
            **kw,
        )
        db.add(b)
        return b

    beds = [
        bed(pool_a, "A1", "A1", "libre", isolation=True),
        bed(pool_a, "A2", "A2a", "occupe", stay_id=man.id),
        bed(pool_a, "A2", "A2b", "libre"),
        bed(pool_a, "A3", "A3", "a_nettoyer"),
        bed(pool_a, "A4", "A4", "bloque", status_reason="Panne"),
        bed(pool_b, "B1", "B1", "libre"),
    ]
    db.commit()
    return {b.label: b.id for b in beds}


def test_board_lists_units_rooms_and_beds_with_accepted_sexes(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    add_beds(db, make_group("g1"))

    board = app_client.get("/api/beds", headers=login("dir@g1.fr"))

    assert board.status_code == 200, board.text
    sites = board.json()["sites"]
    assert [s["site_name"] for s in sites] == ["g1 A", "g1 B"]
    unit = sites[0]["units"][0]
    rooms = {r["room"]: r["beds"] for r in unit["rooms"]}
    assert [b["accepts"] for b in rooms["A2"]] == [[], ["M"]]
    assert rooms["A2"][0]["occupant_sex"] == "M"
    assert rooms["A3"][0]["usable"] is False
    a = unit["availability"]
    assert (a["usable"], a["male"], a["either"], a["isolation"], a["cleaning"]) == (2, 1, 1, 1, 1)
    assert "patient_ref" not in board.text and "encounter_ref" not in board.text


def test_availability_per_unit_and_site(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    add_beds(db, make_group("g1"))

    report = app_client.get("/api/beds/availability", headers=login("coord@g1.fr")).json()

    assert [(u["site_name"], u["code"]) for u in report["units"]] == [
        ("g1 A", "geriatrie"),
        ("g1 B", "geriatrie"),
    ]
    site_a = report["sites"][0]["availability"]
    assert (site_a["installed"], site_a["occupied"], site_a["blocked"]) == (5, 1, 1)
    assert site_a["tension"]["level"] == "normal"
    assert report["definitions"]


def test_site_scoped_coordinator_sees_only_their_site(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    group = make_group("g1")
    add_beds(db, group)
    siteb = login("siteb@g1.fr")
    site_a = db.scalars(select(Site).where(Site.name == "g1 A")).one()

    board = app_client.get("/api/beds", headers=siteb).json()
    forbidden = app_client.get(f"/api/beds?site_id={site_a.id}", headers=siteb)

    assert [s["site_name"] for s in board["sites"]] == ["g1 B"]
    assert forbidden.status_code == 403


def test_cleaned_bed_becomes_free_and_is_audited(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    ids = add_beds(db, make_group("g1"))

    done = app_client.patch(
        f"/api/beds/{ids['A3']}", json={"action": "nettoye"}, headers=login("coord@g1.fr")
    )

    assert done.status_code == 200, done.text
    assert (done.json()["status"], done.json()["usable"]) == ("libre", True)
    audit = db.scalars(select(AuditEntry).where(AuditEntry.action == "lit.nettoye")).one()
    assert (audit.entity_id, audit.detail) == (str(ids["A3"]), "a_nettoyer → libre")


def test_block_needs_a_coded_reason_then_unblock(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    ids = add_beds(db, make_group("g1"))
    coord = login("coord@g1.fr")
    url = f"/api/beds/{ids['A1']}"

    no_reason = app_client.patch(url, json={"action": "bloquer"}, headers=coord)
    free_text = app_client.patch(
        url, json={"action": "bloquer", "reason": "M. Dupont agité"}, headers=coord
    )
    too_long = app_client.patch(
        url, json={"action": "bloquer", "reason": "autre", "note": "x" * 81}, headers=coord
    )
    blocked = app_client.patch(
        url,
        json={"action": "bloquer", "reason": "equipement", "note": " Fuite d'eau "},
        headers=coord,
    )
    unblocked = app_client.patch(url, json={"action": "debloquer"}, headers=coord)

    assert (no_reason.status_code, free_text.status_code, too_long.status_code) == (422, 422, 422)
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["status"] == "bloque"
    assert blocked.json()["status_reason"] == "Équipement en panne : Fuite d'eau"
    assert (unblocked.json()["status"], unblocked.json()["status_reason"]) == ("libre", None)
    # The audit keeps the code, never the free note.
    audit = db.scalars(select(AuditEntry).where(AuditEntry.action == "lit.bloquer")).one()
    assert audit.detail == "libre → bloque (equipement)"
    assert "Fuite" not in " ".join(a.detail or "" for a in db.scalars(select(AuditEntry)))


def test_block_reasons_are_in_the_vocabulary(app_client: TestClient) -> None:
    vocabulary = app_client.get("/api/vocabulary").json()

    assert set(vocabulary["bed_block_reasons"]) == {
        "travaux",
        "equipement",
        "hygiene_isolement",
        "personnel",
        "autre",
    }


def test_reserve_and_cancel_a_reservation(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    ids = add_beds(db, make_group("g1"))
    admin = login("admin@g1.fr")
    url = f"/api/beds/{ids['B1']}"

    reserved = app_client.patch(
        url, json={"action": "reserver", "note": "Entrée programmée"}, headers=admin
    )
    again = app_client.patch(url, json={"action": "reserver"}, headers=admin)
    cancelled = app_client.patch(url, json={"action": "annuler_reservation"}, headers=admin)

    assert reserved.json()["status"] == "reserve"
    assert reserved.json()["status_reason"] == "Entrée programmée"
    audit = db.scalars(select(AuditEntry).where(AuditEntry.action == "lit.reserver")).one()
    assert audit.detail == "libre → reserve"
    assert again.status_code == 409
    assert cancelled.json()["status"] == "libre"


def test_an_occupied_bed_is_never_freed(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    ids = add_beds(db, make_group("g1"))
    coord = login("coord@g1.fr")

    for action in ("nettoye", "debloquer", "annuler_reservation"):
        r = app_client.patch(f"/api/beds/{ids['A2a']}", json={"action": action}, headers=coord)
        assert r.status_code == 409
    assert db.get(Bed, ids["A2a"]).status == "occupe"  # type: ignore[union-attr]


def test_bed_actions_respect_roles_and_scope(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    ids = add_beds(db, make_group("g1"))
    body = {"action": "nettoye"}

    direction = app_client.patch(f"/api/beds/{ids['A3']}", json=body, headers=login("dir@g1.fr"))
    other_site = app_client.patch(f"/api/beds/{ids['A3']}", json=body, headers=login("siteb@g1.fr"))
    unknown_action = app_client.patch(
        f"/api/beds/{ids['A3']}", json={"action": "liberer"}, headers=login("coord@g1.fr")
    )

    assert direction.status_code == 403
    assert other_site.status_code == 403
    assert unknown_action.status_code == 422


def test_another_tenant_cannot_see_or_touch_the_beds(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    ids = add_beds(db, make_group("g1"))
    make_group("g2")
    other = login("admin@g2.fr")
    site_a = db.scalars(select(Site).where(Site.name == "g1 A")).one()

    board = app_client.get("/api/beds", headers=other).json()
    by_site = app_client.get(f"/api/beds?site_id={site_a.id}", headers=other)
    patch = app_client.patch(f"/api/beds/{ids['A3']}", json={"action": "nettoye"}, headers=other)

    assert board["sites"] == []
    assert by_site.status_code == 404
    assert patch.status_code == 404


def test_availability_stays_within_the_tenant_and_site_scope(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    """T-13: /beds/availability."""
    add_beds(db, make_group("g1"))
    make_group("g2")
    site_a = db.scalars(select(Site).where(Site.name == "g1 A")).one()
    other, scoped = login("admin@g2.fr"), login("siteb@g1.fr")

    mine = app_client.get("/api/beds/availability", headers=login("dir@g1.fr")).json()
    theirs = app_client.get("/api/beds/availability", headers=other).json()
    by_site = app_client.get(f"/api/beds/availability?site_id={site_a.id}", headers=other)
    scoped_all = app_client.get("/api/beds/availability", headers=scoped).json()
    scoped_a = app_client.get(f"/api/beds/availability?site_id={site_a.id}", headers=scoped)

    assert {u["site_name"] for u in mine["units"]} == {"g1 A", "g1 B"}
    assert theirs["units"] == [] and theirs["sites"] == []
    assert by_site.status_code == 404
    assert {u["site_name"] for u in scoped_all["units"]} <= {"g1 B"}
    assert scoped_a.status_code == 403
