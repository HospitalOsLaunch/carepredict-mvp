"""ROR export: domain mapping (J188/J189/J190/J191), API, simulated send queue, unit settings."""

from __future__ import annotations

import hashlib
import inspect
import json
import socket
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.admissions_smr.api import routes_ror
from services.admissions_smr.domain.beds import Availability
from services.admissions_smr.domain.ror import (
    MODE_EXPECTED,
    MODE_NONE,
    MODE_RELEASED,
    ForecastPoint,
    ForecastSource,
    UnitSnapshot,
    available_beds,
    closure_type,
    closures,
    forecast_block,
    freshness,
    tension_of,
    unit_export,
)
from services.admissions_smr.models import (
    AuditEntry,
    BedPool,
    CapacityChange,
    Group,
    RorOutbox,
    Site,
)
from services.admissions_smr.tests.conftest import NOW, TODAY
from services.admissions_smr.tests.test_api import new_request
from services.admissions_smr.tests.test_beds_api import add_beds
from services.admissions_smr.tests.test_forecast_store_api import add_run

Login = Callable[[str], dict[str, str]]
MakeGroup = Callable[[str], Group]


def availability(**kw: int) -> Availability:
    base = dict.fromkeys(Availability.__dataclass_fields__, 0)
    base.update(installed=20, occupied=12, usable=5, female=1, male=2, either=2, isolation=1)
    base.update(kw)
    return Availability(**base)


def snapshot(**kw: Any) -> UnitSnapshot:
    base: dict[str, Any] = {
        "site_id": 1,
        "site_name": "CH Test",
        "finess": "590000000",
        "pool_id": 7,
        "code": "medecine_polyvalente",
        "label": "Médecine polyvalente",
        "unit_type": "medecine",
        "discipline": "medecine",
        "ror_unit_id": None,
        "beds_installed": 20,
        "beds_open": 17,
        "extra_beds": 2,
        "crisis_reserved_beds": 1,
        "closure_reason": "personnel",
        "availability": availability(closed=3, blocked=1, reserved=1),
    }
    base.update(kw)
    return UnitSnapshot(**base)


def points(start: date, n: int = 8) -> list[ForecastPoint]:
    return [
        ForecastPoint(start + timedelta(days=k), 4.0 + k, 2.0 + k, 6.4 + k, 0.3, 0.05)
        for k in range(n)
    ]


def records(unit: Any, status: str, temporality: str = "01") -> list[Any]:
    return [r for r in unit.records if r.status[0] == status and r.temporality[0] == temporality]


# --- domain ---------------------------------------------------------------------------------


def test_available_beds_and_tension_follow_the_definitions() -> None:
    assert available_beds(beds_open=26, occupied=20, reserved_24h=2) == 4
    assert available_beds(beds_open=10, occupied=11, reserved_24h=1) == 0
    assert tension_of(0, 30).level == "critique"
    assert tension_of(5, 30).level == "tension"
    assert tension_of(6, 30).level == "normal"


def test_gender_split_maps_to_j190_codes() -> None:
    unit = unit_export(snapshot(), TODAY)

    g = unit.gender
    assert (g.female, g.male, g.undetermined, g.total, g.isolation) == (1, 2, 2, 5, 1)
    assert g.level == "lit"
    by_gender = {r.gender: r.count for r in records(unit, "02")}
    assert by_gender == {("01", "Femme"): 1, ("02", "Homme"): 2, ("04", "Indéterminé"): 2}
    assert all(r.nature == ("01", "Lit") for r in unit.records)


def test_closures_are_typed_with_j191_by_reason_and_blocked_beds_are_undetermined() -> None:
    assert closure_type("personnel") == ("01", "Réactivable")
    assert closure_type("saisonnier") == ("01", "Réactivable")
    assert closure_type("travaux") == ("02", "Non réactivable")
    assert closure_type("autre") == ("03", "Indéterminé")

    lines = closures(declared_closed=1, reason="travaux", blocked=3)

    assert [(c.code, c.count, c.internal_reason) for c in lines] == [
        ("02", 1, "travaux"),
        ("03", 2, "lit_bloque"),
    ]
    assert closures(0, "personnel", 0) == []


def test_closed_beds_add_up_and_feed_the_operational_capacity() -> None:
    unit = unit_export(snapshot(), TODAY)  # 3 declared closures (staff), 1 blocked bed

    counts = {c.code: c.count for c in unit.capacities}
    assert counts == {"01": 20, "02": 5, "03": 12, "04": 1, "05": 3, "06": 2}
    assert sum(c.count for c in unit.closures) == counts["05"]
    op = unit.operational
    assert (op.in_service, op.reactivable, op.extra) == (17, 3, 2)
    assert unit.crisis_reserved == 1
    assert [(r.closing_type, r.count) for r in records(unit, "05")] == [(("01", "Réactivable"), 3)]
    assert records(unit, "06")[0].count == 2


def test_freshness_is_the_latest_change_and_says_where_it_came_from() -> None:
    early, late = datetime(2026, 10, 24, 7, tzinfo=UTC), datetime(2026, 10, 25, 6, tzinfo=UTC)

    fresh = freshness({"mouvement": early, "lit": late, "capacite": None})

    assert fresh is not None and (fresh.at, fresh.source) == (late, "lit")
    assert freshness({"lit": None}) is None
    unit = unit_export(snapshot(changes={"capacite": early}), TODAY)
    assert unit.freshness is not None and unit.freshness.source == "capacite"
    assert all(r.update_date == early for r in records(unit, "01"))


def test_stored_forecast_is_labelled_expected_and_becomes_j189_records() -> None:
    source = ForecastSource(
        MODE_EXPECTED, points(TODAY), "engine-1", TODAY, datetime(2026, 10, 25, 4, tzinfo=UTC)
    )

    unit = unit_export(snapshot(forecast=source), TODAY)

    block = unit.forecast
    assert block.mode == MODE_EXPECTED and block.label.startswith("Disponibles attendus")
    assert block.model == "engine-1" and block.as_of == TODAY
    assert [(f.horizon, f.temporality[0]) for f in block.lines] == [
        ("J+1", "03"),
        ("J+2", "04"),
        ("J+7", "05"),
    ]
    j1 = block.lines[0]
    assert (j1.mean, j1.low, j1.high, j1.p_tension, j1.p_critique) == (5.0, 3, 7, 0.3, 0.05)
    assert [r.count for r in unit.records if r.temporality[0] in ("03", "04", "05")] == [5, 6, 11]


def test_horizons_count_from_today_even_with_an_older_run() -> None:
    source = ForecastSource(MODE_EXPECTED, points(TODAY - timedelta(days=2)), "m", None, None)

    block = forecast_block(source, TODAY)

    assert [f.horizon for f in block.lines] == ["J+1", "J+2"]  # J+7 is beyond the old run


def test_discharge_fallback_is_labelled_and_never_sent_as_a_ror_availability() -> None:
    source = ForecastSource(MODE_RELEASED, points(TODAY), "sorties", TODAY, None)

    unit = unit_export(snapshot(forecast=source), TODAY)

    assert unit.forecast.mode == MODE_RELEASED
    assert unit.forecast.label.startswith("Libérés non promis")
    assert len(unit.forecast.lines) == 3
    assert not [r for r in unit.records if r.temporality[0] != "01"]
    assert unit_export(snapshot(), TODAY).forecast.mode == MODE_NONE


def test_unit_without_bed_rows_falls_back_to_pool_level() -> None:
    unit = unit_export(snapshot(availability=None, occupied=12, reserved_24h=2, finess=None), TODAY)

    counts = {c.code: c.count for c in unit.capacities}
    assert counts == {"01": 20, "02": 3, "03": 12, "04": 2, "05": 3, "06": 2}
    assert unit.gender.level == "unite" and unit.gender.female is None
    assert [r.gender for r in records(unit, "02")] == [None]
    assert "Plan des lits (disponibilité par genre et isolement)" in unit.missing
    assert "FINESS géographique du site" in unit.missing
    assert unit.tension.level == "tension"  # 3 / 20 = 15 %


# --- API ------------------------------------------------------------------------------------


def unit_of(body: dict[str, Any], site: str, code: str) -> dict[str, Any]:
    unit: dict[str, Any] = next(
        u for u in body["unites"] if u["etablissement"] == site and u["mention"] == code
    )
    return unit


def status_count(unit: dict[str, Any], code: str) -> int:
    count: int = next(c["nombre"] for c in unit["capacites"] if c["statut"]["code"] == code)
    return count


def test_export_uses_the_bed_plan_and_the_stored_forecast(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    group = make_group("g1")
    add_beds(db, group)
    add_run(db, group)
    direction = login("dir@g1.fr")
    audits_before = db.scalar(select(func.count()).select_from(AuditEntry))

    response = app_client.get("/api/ror/export", headers=direction)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["maquette"] is True and "rien n'est envoyé" in body["avertissement"]
    assert body["prevision"]["modele"] == "test-1" and body["prevision"]["perimee"] is False
    beds = unit_of(body, "g1 A", "geriatrie")
    g = beds["disponibles_par_genre"]
    assert (g["niveau"], g["homme"], g["indetermine"], g["isolement"]) == ("lit", 1, 1, 1)
    assert status_count(beds, "02") == 2
    assert beds["fermetures"][0]["type_fermeture"]["code"] == "03"  # the blocked bed
    assert beds["previsionnel_nature"]["nature"] == "disponibles_attendus"
    assert [p["echeance"] for p in beds["previsionnel"]] == ["J+1", "J+2", "J+7"]
    assert beds["previsionnel"][0]["p_tension"] == 0.3
    assert beds["fraicheur"]["source"] in ("lit", "capacite", "saisie")
    assert beds["dernier_mouvement_saisi"] == beds["fraicheur"]["le"]
    statuses = {
        (r["capacityStatus"]["code"], r["temporalityCapacity"]["code"])
        for r in beds["ror_capacites"]
    }
    assert ("02", "05") in statuses
    pool_level = unit_of(body, "g1 A", "polyvalent")
    assert pool_level["disponibles_par_genre"]["niveau"] == "unite"
    assert "patient_ref" not in response.text and "encounter_ref" not in response.text
    # Reading the export writes nothing.
    assert db.scalar(select(func.count()).select_from(AuditEntry)) == audits_before


def test_without_a_run_the_discharge_forecast_is_labelled_as_such(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    group = make_group("g1")
    coord = login("coord@g1.fr")
    site_a = db.scalars(select(Site).where(Site.name == "g1 A")).one()
    pool = next(p for p in site_a.pools if p.mention == "geriatrie")
    pool.beds_open = 9
    db.add(
        CapacityChange(
            group_id=group.id,
            site_id=site_a.id,
            mention="geriatrie",
            effective_date=TODAY - timedelta(days=3),
            beds_installed=10,
            beds_open=9,
            reason="travaux",
            created_at=NOW,
        )
    )
    db.commit()
    created = app_client.post("/api/requests", json=new_request(), headers=coord).json()
    accord = app_client.post(
        f"/api/requests/{created['id']}/accord",
        json={"site_id": site_a.id, "proposed_date": (TODAY + timedelta(days=1)).isoformat()},
        headers=coord,
    )
    assert accord.status_code == 200, accord.text

    body = app_client.get("/api/ror/export", headers=login("dir@g1.fr")).json()

    assert body["prevision"] is None
    unit = unit_of(body, "g1 A", "geriatrie")
    assert (status_count(unit, "01"), status_count(unit, "03")) == (10, 8)
    assert (status_count(unit, "04"), status_count(unit, "02")) == (1, 0)
    assert unit["fermetures"][0]["type_fermeture"]["code"] == "02"  # works
    assert unit["operationnel"] == {"en_service": 9, "reactivables": 0, "supplementaires": 0}
    assert unit["tension"]["niveau"] == "critique"
    assert unit["previsionnel_nature"]["nature"] == "liberes_non_promis"
    for p in unit["previsionnel"]:
        low, high = p["fourchette_80"]
        assert 0 <= low <= high and p["p_tension"] is None
    assert {r["temporalityCapacity"]["code"] for r in unit["ror_capacites"]} == {"01"}


def test_export_respects_site_scope_roles_and_tenants(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    make_group("g2")
    scoped = login("siteb@g1.fr")
    units = app_client.get("/api/ror/export", headers=scoped).json()["unites"]
    assert {u["etablissement"] for u in units} == {"g1 B"}
    site_a = db.scalars(select(Site).where(Site.name == "g1 A")).one()
    assert app_client.get(f"/api/ror/export?site_id={site_a.id}", headers=scoped).status_code == 403
    other = db.scalars(select(Site).where(Site.name == "g2 A")).one()
    admin = login("admin@g1.fr")
    assert app_client.get(f"/api/ror/export?site_id={other.id}", headers=admin).status_code == 404
    assert app_client.get("/api/ror/export", headers=login("agent@g1.fr")).status_code == 403


def test_simulated_send_stores_a_digest_audits_and_never_opens_a_socket(
    app_client: TestClient,
    make_group: MakeGroup,
    login: Login,
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_group("g1")
    admin = login("admin@g1.fr")
    calls: list[object] = []

    def no_network(*args: object, **kwargs: object) -> None:
        calls.append(args)
        raise AssertionError("network access during a simulated send")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    first = app_client.post("/api/ror/outbox", headers=admin)
    second = app_client.post("/api/ror/outbox", headers=admin)

    assert first.status_code == 201, first.text
    assert calls == []
    out = first.json()
    assert out["statut"] == "simulated" and out["type"] == "ror_capacity"
    assert out["unites"] == 3 and out["contenu"]["maquette"] is True
    row = db.get(RorOutbox, out["id"])
    assert row is not None
    assert row.digest == hashlib.sha256(row.payload_json.encode("utf-8")).hexdigest()
    assert out["empreinte_sha256"] == row.digest
    assert second.json()["empreinte_sha256"] == row.digest  # same state, same digest
    assert json.loads(row.payload_json)["unites"][0]["site_id"]
    audit = db.scalars(select(AuditEntry).where(AuditEntry.action == "ror.envoi_simule")).all()
    assert len(audit) == 2 and "aucun envoi" in (audit[0].detail or "")
    history = app_client.get("/api/ror/outbox", headers=admin).json()
    assert [h["id"] for h in history] == [second.json()["id"], out["id"]]
    assert history[0]["prepare_par"] == "admin@g1.fr" and history[0]["contenu"] is None


def test_the_export_module_has_no_way_to_reach_the_network() -> None:
    source = inspect.getsource(routes_ror)
    for client in ("httpx", "requests", "urllib", "socket", "aiohttp", "smtplib"):
        assert f"import {client}" not in source and f"from {client}" not in source


def test_simulated_send_and_history_are_for_administrators_only(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    for email in ("coord@g1.fr", "dir@g1.fr", "agent@g1.fr"):
        headers = login(email)
        assert app_client.post("/api/ror/outbox", headers=headers).status_code == 403
        assert app_client.get("/api/ror/outbox", headers=headers).status_code == 403
    assert db.scalar(select(func.count()).select_from(RorOutbox)) == 0


def test_history_is_per_tenant(app_client: TestClient, make_group: MakeGroup, login: Login) -> None:
    make_group("g1")
    make_group("g2")
    assert app_client.post("/api/ror/outbox", headers=login("admin@g1.fr")).status_code == 201
    assert app_client.get("/api/ror/outbox", headers=login("admin@g2.fr")).json() == []


def test_unit_settings_are_validated_audited_and_exported(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    make_group("g2")
    admin = login("admin@g1.fr")
    site_a = db.scalars(select(Site).where(Site.name == "g1 A")).one()
    pool = next(p for p in site_a.pools if p.mention == "geriatrie")
    url = f"/api/ror/units/{pool.id}"

    ok = app_client.put(
        url,
        json={"ror_unit_id": "UO-59.001", "extra_beds": 2, "crisis_reserved_beds": 3},
        headers=admin,
    )

    assert ok.status_code == 200, ok.text
    assert ok.json() == {
        "pool_id": pool.id,
        "ror_unit_id": "UO-59.001",
        "extra_beds": 2,
        "crisis_reserved_beds": 3,
    }
    audit = db.scalars(select(AuditEntry).where(AuditEntry.action == "ror.unite")).one()
    assert audit.entity_id == str(pool.id) and "UO-59.001" in (audit.detail or "")
    unit = unit_of(app_client.get("/api/ror/export", headers=admin).json(), "g1 A", "geriatrie")
    assert unit["identifiant_unite_ror"] == "UO-59.001"
    assert status_count(unit, "06") == 2 and unit["reserves_crise_sse"] == 3
    assert unit["operationnel"]["supplementaires"] == 2
    assert "Identifiant ROR de l'unité" not in unit["a_completer"]
    for bad in (
        {"ror_unit_id": "<script>"},
        {"ror_unit_id": "x" * 65},
        {"extra_beds": -1},
        {"crisis_reserved_beds": 50},  # more than installed + extra
        {"extra_beds": None},
        {"unknown": 1},
        {},
    ):
        assert app_client.put(url, json=bad, headers=admin).status_code == 422, bad
    cleared = app_client.put(url, json={"ror_unit_id": None}, headers=admin)
    assert cleared.json()["ror_unit_id"] is None
    assert (
        app_client.put(url, json={"extra_beds": 1}, headers=login("coord@g1.fr")).status_code == 403
    )
    other = db.scalars(select(BedPool).join(Site).where(Site.name == "g2 A")).first()
    assert other is not None
    assert (
        app_client.put(
            f"/api/ror/units/{other.id}", json={"extra_beds": 1}, headers=admin
        ).status_code
        == 404
    )
