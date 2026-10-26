from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.models import AuditEntry, Group, Site, Stay
from services.admissions_smr.tests.conftest import NOW, TODAY

Login = Callable[[str], dict[str, str]]
MakeGroup = Callable[[str], Group]


def new_request(**kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source": "viatrajectoire",
        "external_ref": "VT-1",
        "received_at": (NOW - timedelta(hours=5)).isoformat(),
        "referrer_facility": "CH des Monts",
        "referrer_unit": "Médecine",
        "patient_ref": "PAT-42",
        "patient_age": 84,
        "mention_requested": "geriatrie",
        "care_level": 3,
        "special_needs": ["oxygene"],
        "desired_date": (TODAY + timedelta(days=2)).isoformat(),
    }
    body.update(kw)
    return body


def test_login_rejects_bad_password_and_requires_token(
    app_client: TestClient, make_group: MakeGroup
) -> None:
    make_group("g1")
    assert (
        app_client.post(
            "/api/auth/login", json={"email": "admin@g1.fr", "password": "nope-nope-nope"}
        ).status_code
        == 401
    )
    assert app_client.get("/api/requests").status_code == 401
    assert (
        app_client.get("/api/requests", headers={"Authorization": "Bearer x.y"}).status_code == 401
    )


def test_full_admission_workflow(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    h = login("coord@g1.fr")
    created = app_client.post("/api/requests", json=new_request(), headers=h)
    assert created.status_code == 201, created.text
    req = created.json()
    assert req["status"] == "nouvelle"
    assert req["best"] is not None and req["best"]["eligible"]
    assert {s["site_name"] for s in req["suggestions"]} == {"g1 A", "g1 B"}

    queue = app_client.get("/api/requests", headers=h).json()
    assert [r["id"] for r in queue] == [req["id"]]

    site_id = req["best"]["site_id"]
    proposed = (TODAY + timedelta(days=2)).isoformat()
    accord = app_client.post(
        f"/api/requests/{req['id']}/accord",
        json={"site_id": site_id, "proposed_date": proposed},
        headers=h,
    )
    assert accord.status_code == 200, accord.text
    body = accord.json()
    assert body["status"] == "accord"
    assert body["first_response_at"] is not None
    assert body["waiting_hours"] == 5.0
    assert "Entrée proposée" in body["draft_message"]

    # The promised bed is reserved in the forecast.
    fc = app_client.get(f"/api/forecast?site_id={site_id}", headers=h).json()
    pool = next(p for p in fc["pools"] if p["mention"] == "geriatrie")
    assert pool["days"][2]["reserved"] == 1

    assert (
        app_client.post(f"/api/requests/{req['id']}/confirm", json={}, headers=h).json()["status"]
        == "confirmee"
    )
    admitted = app_client.post(
        f"/api/requests/{req['id']}/admit", json={"admission_date": TODAY.isoformat()}, headers=h
    )
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["status"] == "admise"
    assert admitted.json()["stay_id"] is not None
    stay = db.get(Stay, admitted.json()["stay_id"])
    assert stay is not None and stay.patient_ref == "PAT-42" and stay.request_id == req["id"]

    kinds = [e["kind"] for e in admitted.json()["events"]]
    assert kinds == ["recue", "accord", "confirmation", "admission"]
    actions = set(db.scalars(select(AuditEntry.action)))
    assert {"demande.create", "demande.accord", "demande.admission", "sejour.create"} <= actions


def test_invalid_transition_is_rejected(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    h = login("coord@g1.fr")
    rid = app_client.post("/api/requests", json=new_request(), headers=h).json()["id"]
    response = app_client.post(
        f"/api/requests/{rid}/admit", json={"admission_date": TODAY.isoformat()}, headers=h
    )
    assert response.status_code == 409


def test_refusal_then_reorientation_resets_to_study(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    h = login("coord@g1.fr")
    sites = {s["name"]: s["id"] for s in app_client.get("/api/sites", headers=h).json()}
    rid = app_client.post(
        "/api/requests", json=new_request(site_id=sites["g1 A"]), headers=h
    ).json()["id"]
    refused = app_client.post(
        f"/api/requests/{rid}/refuse", json={"reason": "pas_de_lit"}, headers=h
    ).json()
    assert refused["status"] == "refusee"
    assert "Motif : pas de lit" in refused["draft_message"]
    moved = app_client.post(
        f"/api/requests/{rid}/reorient", json={"site_id": sites["g1 B"]}, headers=h
    ).json()
    assert moved["status"] == "en_etude"
    assert moved["site_name"] == "g1 B"
    assert moved["refusal_reason"] is None


def test_reorientation_to_site_without_mention_is_refused(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    h = login("coord@g1.fr")
    sites = {s["name"]: s["id"] for s in app_client.get("/api/sites", headers=h).json()}
    rid = app_client.post(
        "/api/requests", json=new_request(mention_requested="polyvalent"), headers=h
    ).json()["id"]
    response = app_client.post(
        f"/api/requests/{rid}/reorient", json={"site_id": sites["g1 B"]}, headers=h
    )
    assert response.status_code == 409


def test_tenants_are_isolated(app_client: TestClient, make_group: MakeGroup, login: Login) -> None:
    make_group("g1")
    make_group("g2")
    h1, h2 = login("coord@g1.fr"), login("coord@g2.fr")
    rid = app_client.post("/api/requests", json=new_request(), headers=h1).json()["id"]
    assert app_client.get(f"/api/requests/{rid}", headers=h2).status_code == 404
    assert app_client.get("/api/requests", headers=h2).json() == []
    g1_sites = {s["id"] for s in app_client.get("/api/sites", headers=h1).json()}
    g2_sites = {s["id"] for s in app_client.get("/api/sites", headers=h2).json()}
    assert not g1_sites & g2_sites
    some_g1_site = next(iter(g1_sites))
    assert (
        app_client.post(
            f"/api/requests/{rid}/reorient", json={"site_id": some_g1_site}, headers=h2
        ).status_code
        == 404
    )


def test_site_scoped_coordinator_sees_only_its_site(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    admin, scoped = login("admin@g1.fr"), login("siteb@g1.fr")
    site_a = db.scalar(select(Site.id).where(Site.name == "g1 A"))
    rid = app_client.post("/api/requests", json=new_request(site_id=site_a), headers=admin).json()[
        "id"
    ]
    assert app_client.get(f"/api/requests/{rid}", headers=scoped).status_code == 404
    assert [s["name"] for s in app_client.get("/api/sites", headers=scoped).json()] == ["g1 B"]
    unassigned = app_client.post(
        "/api/requests", json=new_request(external_ref="VT-2"), headers=admin
    ).json()["id"]
    assert [r["id"] for r in app_client.get("/api/requests", headers=scoped).json()] == [unassigned]


def test_roles_are_enforced(app_client: TestClient, make_group: MakeGroup, login: Login) -> None:
    make_group("g1")
    direction, agent = login("dir@g1.fr"), login("agent@g1.fr")
    assert app_client.get("/api/dashboard", headers=direction).status_code == 200
    assert (
        app_client.post("/api/requests", json=new_request(), headers=direction).status_code == 403
    )
    assert app_client.get("/api/requests", headers=agent).status_code == 403
    assert app_client.get("/api/users", headers=login("coord@g1.fr")).status_code == 403


def test_ingestion_is_idempotent(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    agent = login("agent@g1.fr")
    first = app_client.post("/api/ingest/requests", json=new_request(), headers=agent).json()
    second = app_client.post("/api/ingest/requests", json=new_request(), headers=agent).json()
    assert first["created"] is True and second == {"id": first["id"], "created": False}
    missing_ref = app_client.post(
        "/api/ingest/requests", json=new_request(external_ref=None), headers=agent
    )
    assert missing_ref.status_code == 422


def test_pool_update_logs_capacity_change_and_closure_reason(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    admin, coord = login("admin@g1.fr"), login("coord@g1.fr")
    site_id = app_client.get("/api/sites", headers=admin).json()[0]["id"]
    ok = app_client.put(
        f"/api/sites/{site_id}/pools/geriatrie",
        json={"beds_installed": 10, "beds_open": 8, "reason": "personnel"},
        headers=coord,
    )
    assert ok.status_code == 200, ok.text
    assert next(p for p in ok.json()["pools"] if p["mention"] == "geriatrie")["beds_open"] == 8
    forbidden = app_client.put(
        f"/api/sites/{site_id}/pools/geriatrie",
        json={"beds_installed": 12, "beds_open": 8, "reason": "ouverture"},
        headers=coord,
    )
    assert forbidden.status_code == 403
    invalid = app_client.put(
        f"/api/sites/{site_id}/pools/geriatrie",
        json={"beds_installed": 10, "beds_open": 11, "reason": "ouverture"},
        headers=admin,
    )
    assert invalid.status_code == 422
    metrics = app_client.get(
        f"/api/metrics/pilot?start={TODAY}&end={TODAY}&site_id={site_id}", headers=admin
    ).json()
    assert metrics["occupancy"]["closed_bed_days_by_reason"] == {"personnel": 2}


def test_imports_dry_run_then_commit_all_or_nothing(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    admin = login("admin@g1.fr")
    bad = (
        "site;mention;patient_ref;date_entree\n"
        "g1 A;geriatrie;PAT-1;01/10/2026\n"
        "Inconnu;geriatrie;PAT-2;01/10/2026\n"
    )
    result = app_client.post(
        "/api/imports/sejours", json={"csv_text": bad, "dry_run": False}, headers=admin
    ).json()
    assert result["committed"] is False
    assert result["errors"][0]["line"] == 3
    assert db.scalar(select(Stay.id).where(Stay.patient_ref == "PAT-1")) is None

    good = "site;mention;patient_ref;date_entree\ng1 A;geriatrie;PAT-1;01/10/2026\n"
    dry = app_client.post(
        "/api/imports/sejours", json={"csv_text": good, "dry_run": True}, headers=admin
    ).json()
    assert dry == {**dry, "committed": False, "created": 1, "errors": []}
    assert db.scalar(select(Stay.id).where(Stay.patient_ref == "PAT-1")) is None
    done = app_client.post(
        "/api/imports/sejours", json={"csv_text": good, "dry_run": False}, headers=admin
    ).json()
    assert done["committed"] is True
    db.expire_all()
    assert db.scalar(select(Stay.id).where(Stay.patient_ref == "PAT-1")) is not None
    template = app_client.get("/api/imports/templates/demandes")
    assert template.status_code == 200 and "etablissement_adresseur" in template.text


def test_baseline_freeze_locks_contract_parameters(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    admin = login("admin@g1.fr")
    start, end = (TODAY - timedelta(days=120)).isoformat(), (TODAY - timedelta(days=60)).isoformat()
    assert (
        app_client.put(
            "/api/settings/baseline", json={"start": start, "end": end}, headers=admin
        ).status_code
        == 200
    )
    assert (
        app_client.put(
            "/api/settings",
            json={"value_per_bed_day": 160, "success_fee_rate": 0.15},
            headers=admin,
        ).status_code
        == 200
    )
    frozen = app_client.post("/api/settings/baseline/freeze", headers=admin).json()
    assert frozen["baseline"]["frozen_at"] is not None
    assert (
        app_client.put("/api/settings", json={"value_per_bed_day": 200}, headers=admin).status_code
        == 409
    )
    assert (
        app_client.put(
            "/api/settings/baseline", json={"start": start, "end": end}, headers=admin
        ).status_code
        == 409
    )
    assert (
        app_client.post(
            "/api/settings/baseline/unfreeze", json={"reason": "court"}, headers=admin
        ).status_code
        == 422
    )
    unfrozen = app_client.post(
        "/api/settings/baseline/unfreeze",
        json={"reason": "Erreur de période signalée par la direction"},
        headers=admin,
    )
    assert unfrozen.status_code == 200 and unfrozen.json()["baseline"]["frozen_at"] is None
    log = app_client.get("/api/audit", headers=admin).json()
    assert {"reference.freeze", "reference.unfreeze"} <= {e["action"] for e in log}


def test_dashboard_and_pilot_metrics_shapes(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    h = login("dir@g1.fr")
    dash = app_client.get("/api/dashboard", headers=h).json()
    assert dash["beds_open"] == 30 and dash["occupied"] == 16
    assert len(dash["daily_free_beds"]) == 14
    metrics = app_client.get("/api/metrics/pilot", headers=h).json()
    assert metrics["north_star"] is None
    assert metrics["north_star_unavailable_reason"] == "Aucune période de référence définie."
    backtest = app_client.get("/api/metrics/backtest", headers=h).json()
    assert backtest["horizon_days"] == 7 and backtest["points"]
