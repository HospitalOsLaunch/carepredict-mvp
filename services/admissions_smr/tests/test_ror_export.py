from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.admissions_smr.domain.ror import (
    ForecastDay,
    PoolSnapshot,
    available_beds,
    closure_type,
    tension_of,
    unit_export,
)
from services.admissions_smr.models import AuditEntry, BedPool, CapacityChange, Group, Site
from services.admissions_smr.tests.conftest import TODAY
from services.admissions_smr.tests.test_api import new_request

Login = Callable[[str], dict[str, str]]
MakeGroup = Callable[[str], Group]


def _snapshot(**kw: Any) -> PoolSnapshot:
    base: dict[str, Any] = {
        "site_id": 1,
        "site_name": "SMR Test",
        "finess": "590000000",
        "mention": "geriatrie",
        "mention_label": "Gériatrie",
        "beds_installed": 30,
        "beds_open": 26,
        "closure_reason": "personnel",
        "occupied": 20,
        "reserved_24h": 2,
        "forecast": [
            ForecastDay(TODAY + timedelta(days=k), 4.0 + k - 5.0, -3 + k, 6 + k) for k in range(8)
        ],
        "last_movement_at": datetime(2026, 10, 25, 7, 0, tzinfo=UTC),
    }
    base.update(kw)
    return PoolSnapshot(**base)


def _status(unit: dict[str, Any], code: str) -> int | None:
    count: int | None = next(c["nombre"] for c in unit["capacites"] if c["statut"]["code"] == code)
    return count


def test_available_beds_follow_the_ror_definition() -> None:
    assert available_beds(beds_open=26, occupied=20, reserved_24h=2) == 4
    assert available_beds(beds_open=10, occupied=11, reserved_24h=1) == 0  # never negative


def test_tension_levels_follow_the_liscop_legend() -> None:
    assert tension_of(0, 30).level == "critique"
    assert tension_of(5, 30).level == "tension"  # 16.7 % < 20 %
    assert tension_of(6, 30).level == "normal"  # exactly 20 %
    assert tension_of(0, 0).availability_rate is None


def test_closure_reasons_map_to_the_j191_vocabulary() -> None:
    assert closure_type("personnel") == ("01", "Réactivable")
    assert closure_type("saisonnier") == ("01", "Réactivable")
    assert closure_type("travaux") == ("02", "Non réactivable")
    assert closure_type("autre") == ("03", "Indéterminé")


def test_unit_export_lists_every_j188_status_and_clips_the_forecast() -> None:
    unit = unit_export(_snapshot(), TODAY)
    counts = {c.code: c.count for c in unit.capacities}
    assert counts == {"01": 30, "02": 4, "03": 20, "04": 2, "05": 4, "06": None}
    assert [(f.code, f.count) for f in unit.closures] == [("01", 4)]
    assert [f.horizon for f in unit.forecast] == ["J+1", "J+2", "J+7"]
    j1 = unit.forecast[0]
    assert j1.free_expected == 0.0 and j1.free_low == 0  # negative values are shown as zero
    assert unit.ror_unit_id is None and "Identifiant ROR de l'unité" in unit.missing


def test_unit_without_closed_beds_or_finess() -> None:
    unit = unit_export(_snapshot(beds_open=30, finess=None), TODAY)
    assert unit.closures == []
    assert "FINESS géographique du site" in unit.missing


def test_export_endpoint_is_read_only_and_consistent(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    group = make_group("g1")
    coord = login("coord@g1.fr")
    site_a = db.scalars(select(Site).where(Site.name == "g1 A")).one()
    pool = db.scalars(
        select(BedPool).where(BedPool.site_id == site_a.id, BedPool.mention == "geriatrie")
    ).one()
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
    direction = login("dir@g1.fr")  # logging in is audited: do it before counting
    audits_before = db.scalar(select(func.count()).select_from(AuditEntry))

    response = app_client.get("/api/ror/export", headers=direction)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["maquette"] is True and "rien n'est envoyé" in body["avertissement"]
    assert date.fromisoformat(body["date_situation"]) == TODAY
    assert len(body["unites"]) == 3

    unit = next(
        u for u in body["unites"] if u["site_id"] == site_a.id and u["mention"] == "geriatrie"
    )
    assert _status(unit, "01") == 10
    assert _status(unit, "03") == 8
    assert _status(unit, "04") == 1  # the admission promised for tomorrow
    assert _status(unit, "02") == 0  # 9 open - 8 present - 1 promised
    assert _status(unit, "05") == 1
    assert unit["fermetures"][0]["type_fermeture"]["code"] == "02"  # works: not reactivable
    assert unit["tension"]["niveau"] == "critique"
    assert [p["echeance"] for p in unit["previsionnel"]] == ["J+1", "J+2", "J+7"]
    for p in unit["previsionnel"]:
        low, high = p["fourchette_80"]
        assert 0 <= low <= high
    assert unit["dernier_mouvement_saisi"] is not None

    # Reading the export writes nothing.
    assert db.scalar(select(func.count()).select_from(AuditEntry)) == audits_before


def test_export_respects_site_scope_and_roles(
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
