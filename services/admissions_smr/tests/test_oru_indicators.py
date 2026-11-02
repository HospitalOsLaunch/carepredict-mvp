"""ORU daily indicators: domain helpers, CSV format and GET /api/oru/indicators."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.domain import oru
from services.admissions_smr.domain.ed import DayPoint
from services.admissions_smr.models import Group, Site, TensionDeclaration, User
from services.admissions_smr.tests.conftest import NOW, TODAY
from services.admissions_smr.tests.test_ed_api import add_visit, utc, with_ed
from services.admissions_smr.tests.test_forecast_store_api import add_run

Login = Callable[[str], dict[str, str]]
MakeGroup = Callable[[str], Group]
PARIS = ZoneInfo("Europe/Paris")
YESTERDAY = TODAY - timedelta(days=1)


# --- domain ---------------------------------------------------------------------------------


def test_unit_level_at_the_end_of_the_day_follows_the_liscop_legend() -> None:
    capacity = {TODAY: (10, 9, "personnel")}

    assert oru.unit_levels({TODAY: 9}, capacity, TODAY) == (10, "critique")
    assert oru.unit_levels({TODAY: 8}, capacity, TODAY) == (10, "tension")
    assert oru.unit_levels({TODAY: 7}, capacity, TODAY) == (10, "normal")
    assert oru.unit_levels({}, {TODAY: (0, 0, "")}, TODAY) is None
    levels = oru.count_levels([(10, "critique"), None, (10, "tension"), (5, "normal")])
    assert (levels.units, levels.tension, levels.critique) == (3, 1, 1)


def test_declarations_active_during_the_local_day() -> None:
    def at(day: int, hour: int) -> datetime:
        return datetime(2026, 10, day, hour, tzinfo=UTC)

    declarations = [
        oru.Declaration("het", "niveau_1", at(20, 8), at(23, 22)),  # ended before the 24th
        oru.Declaration("het", "niveau_2", at(24, 15), None),
        oru.Declaration("plan_blanc", "alerte", at(25, 7), None),  # starts the next day
    ]

    assert oru.active_declarations(declarations, date(2026, 10, 24), PARIS) == {"het": "niveau_2"}
    assert oru.active_declarations(declarations, date(2026, 10, 23), PARIS) == {"het": "niveau_1"}
    assert oru.active_declarations(declarations, date(2026, 10, 25), PARIS) == {
        "het": "niveau_2",
        "plan_blanc": "alerte",
    }


def test_arrivals_are_counted_on_the_local_day() -> None:
    late = datetime(2026, 10, 24, 22, 30, tzinfo=UTC)  # 00:30 on the 25th in Paris (summer)
    counts = oru.arrivals_by_day([late, datetime(2026, 10, 24, 12, tzinfo=UTC)], PARIS)
    assert counts == {date(2026, 10, 25): 1, date(2026, 10, 24): 1}


def row(**kw: object) -> oru.OruDay:
    point = DayPoint(YESTERDAY, 30, 6, 4, 2, "declaration", 3)
    base = oru.oru_day(
        1,
        "=CH Test",
        YESTERDAY,
        TODAY,
        point,
        118,
        oru.UnitLevels(6, 2, 1),
        {"het": "niveau_1"},
        oru.BoardingForecast(4.25, 2.0, 7.5, YESTERDAY),
    )
    return oru.OruDay(**{**base.__dict__, **kw})


def test_a_declared_day_keeps_the_computed_boarding_next_to_it() -> None:
    r = row()
    assert (r.boarding_10h, r.computed_boarding_10h, r.boarding_source) == (4, 3, "declaration")
    assert r.complete is True and r.forecast_boarding_mean == 4.2
    empty = oru.oru_day(1, "S", TODAY, TODAY, None, None, None, {}, None)
    assert empty.present_10h is None and empty.boarding_source is None and not empty.complete
    assert empty.units is None


def test_csv_is_utf8_with_bom_semicolons_french_headers_and_no_formula() -> None:
    text = oru.to_csv([row()], {"niveau_1": "Niveau 1"})

    assert text.startswith("﻿")
    data = list(csv.reader(io.StringIO(text[1:]), delimiter=";"))
    header, line = data
    assert header[:4] == ["Date", "Identifiant site", "Site", "Jour complet"]
    assert "Lits brancards à 10 h (calculé)" in header and len(header) == len(line)
    values = dict(zip(header, line, strict=True))
    assert values["Site"] == "'=CH Test"  # neutralised spreadsheet formula
    assert values["Jour complet"] == "oui"
    assert values["Prévision lits brancards 10 h (moyenne)"] == "4,2"
    assert values["Hôpital en tension"] == "Niveau 1"
    assert values["Plan blanc"] == ""
    assert values["Source lits brancards"] == "declaration"
    assert text.encode("utf-8").decode("utf-8") == text


# --- API ------------------------------------------------------------------------------------


def test_indicators_per_site_and_day_with_declared_override_and_forecast(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    group = make_group("g1")
    site = with_ed(app_client, db, login)
    add_visit(db, site, utc(24, 5), utc(24, 6), None)  # yesterday: on a stretcher at 10:00
    add_visit(db, site, utc(24, 12), None, utc(24, 14))
    admin_user = db.scalars(select(User).where(User.email == "admin@g1.fr")).one()
    db.add(
        TensionDeclaration(
            group_id=group.id,
            site_id=None,
            kind="het",
            level="niveau_1",
            started_at=NOW - timedelta(days=2),
            declared_by=admin_user.id,
        )
    )
    db.commit()
    add_run(db, group)
    coord = login("coord@g1.fr")
    declared = app_client.post(
        "/api/ed/snapshots",
        json={
            "site_id": site.id,
            "at": "2026-10-24T09:00:00+00:00",
            "present": 20,
            "waiting_bed": 9,
            "boarding": 7,
            "hosted_elsewhere": 1,
        },
        headers=coord,
    )
    assert declared.status_code == 201, declared.text
    params = f"start={(TODAY - timedelta(days=3)).isoformat()}&end={(TODAY + timedelta(days=2))}"

    response = app_client.get(f"/api/oru/indicators?{params}", headers=login("dir@g1.fr"))

    assert response.status_code == 200, response.text
    body = response.json()
    days = [d for d in body["days"] if d["site_id"] == site.id]
    assert len(days) == 6
    by_day = {d["day"]: d for d in days}
    y = by_day[YESTERDAY.isoformat()]
    assert (y["boarding_10h"], y["computed_boarding_10h"], y["boarding_source"]) == (
        7,
        1,
        "declaration",
    )
    assert y["ed_arrivals"] == 2 and y["het"] == "niveau_1" and y["complete"] is True
    assert y["units"] >= 1
    today = by_day[TODAY.isoformat()]
    assert today["present_10h"] is None  # 10:00 not reached yet (09:30 in Paris)
    assert today["ed_arrivals"] == 3 and today["complete"] is False
    assert today["forecast_boarding_mean"] == 5.0
    future = by_day[(TODAY + timedelta(days=2)).isoformat()]
    assert future["ed_arrivals"] is None and future["forecast_boarding_high"] == 9.0
    assert future["units"] is None and future["units_critique"] is None
    site_b = next(d for d in body["days"] if d["site_name"] == "g1 B")
    assert site_b["ed_arrivals"] is None and site_b["present_10h"] is None


def test_indicators_as_csv(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    with_ed(app_client, db, login)
    start = (TODAY - timedelta(days=6)).isoformat()

    response = app_client.get(
        f"/api/oru/indicators?start={start}&end={TODAY.isoformat()}&format=csv",
        headers=login("dir@g1.fr"),
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    lines = response.content.decode("utf-8").splitlines()
    assert lines[0].startswith("﻿Date;Identifiant site;Site;")
    assert len(lines) == 1 + 7 * 2  # header + 7 days x 2 sites


def test_period_is_validated(app_client: TestClient, make_group: MakeGroup, login: Login) -> None:
    make_group("g1")
    headers = login("dir@g1.fr")

    def get(start: date, end: date, fmt: str = "json") -> int:
        url = f"/api/oru/indicators?start={start}&end={end}&format={fmt}"
        code: int = app_client.get(url, headers=headers).status_code
        return code

    assert get(TODAY, TODAY - timedelta(days=1)) == 422
    assert get(TODAY - timedelta(days=366), TODAY) == 422  # 367 days
    assert get(TODAY - timedelta(days=365), TODAY) == 200  # 366 days
    assert get(TODAY, TODAY + timedelta(days=8)) == 422
    assert get(TODAY, TODAY, "xml") == 422


def test_indicators_respect_scope_roles_and_tenants(
    app_client: TestClient, make_group: MakeGroup, login: Login, db: Session
) -> None:
    make_group("g1")
    make_group("g2")
    period = f"start={TODAY}&end={TODAY}"
    scoped = app_client.get(f"/api/oru/indicators?{period}", headers=login("siteb@g1.fr"))
    assert {d["site_name"] for d in scoped.json()["days"]} == {"g1 B"}
    other = db.scalars(select(Site).where(Site.name == "g2 A")).one()
    admin = login("admin@g1.fr")
    url = f"/api/oru/indicators?{period}&site_id={other.id}"
    assert app_client.get(url, headers=admin).status_code == 404
    agent = login("agent@g1.fr")
    assert app_client.get(f"/api/oru/indicators?{period}", headers=agent).status_code == 403
