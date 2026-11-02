"""Beds, emergency census and tension on the MCO demo: plausible values, every page works."""

from __future__ import annotations

import statistics
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.admissions_smr.clock import FrozenClock
from services.admissions_smr.config import Settings
from services.admissions_smr.db import make_engine, make_session_factory
from services.admissions_smr.main import create_app
from services.admissions_smr.migrate import upgrade
from services.admissions_smr.seed_mco import seed_demo_mco
from services.admissions_smr.tests.conftest import NOW
from services.admissions_smr.tests.conftest import test_database_url as database_url

PASSWORD = "mot-de-passe-demo"


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[TestClient, dict[str, str]]]:
    url = database_url(Path(tmp_path_factory.mktemp("mco-beds")))
    engine = make_engine(url)
    upgrade(engine)
    with make_session_factory(engine)() as session:
        seed_demo_mco(session, NOW, PASSWORD, 1000)
    engine.dispose()
    settings = Settings(
        environment="test",
        database_url=url,
        secret_key="t" * 40,
        token_ttl_minutes=60,
        password_iterations=1000,
        timezone="Europe/Paris",
        cors_origins=(),
    )
    with TestClient(create_app(settings, FrozenClock(NOW))) as c:
        token = c.post(
            "/api/auth/login",
            json={"email": "bedmanager@ch-demo.hospitalos.fr", "password": PASSWORD},
        ).json()["token"]
        yield c, {"Authorization": f"Bearer {token}"}


def get(client: tuple[TestClient, dict[str, str]], path: str) -> Any:
    c, headers = client
    response = c.get(path, headers=headers)
    assert response.status_code == 200, (path, response.text)
    return response.json()


def test_availability_is_plausible_and_adds_up(client: tuple[TestClient, dict[str, str]]) -> None:
    report = get(client, "/api/beds/availability")

    assert len(report["units"]) == 8  # 6 MCO wards with beds + 2 SMR units
    for unit in report["units"]:
        a = unit["availability"]
        assert a["female"] + a["male"] + a["either"] == a["usable"]
        assert 0 <= a["isolation"] <= a["usable"] <= a["installed"]
        assert a["occupied"] + a["usable"] + a["cleaning"] + a["reserved"] <= a["installed"]
        assert a["sex_conflict"] == 0
    total = sum(s["availability"]["installed"] for s in report["sites"])
    usable = sum(s["availability"]["usable"] for s in report["sites"])
    assert 230 <= total <= 270
    assert 1 <= usable <= 0.3 * total


def test_board_shows_every_bed_once(client: tuple[TestClient, dict[str, str]]) -> None:
    board = get(client, "/api/beds")

    beds = [b for s in board["sites"] for u in s["units"] for r in u["rooms"] for b in r["beds"]]
    assert len({b["id"] for b in beds}) == len(beds)
    assert {b["status"] for b in beds} >= {"libre", "occupe", "a_nettoyer", "bloque"}


def test_emergency_census_and_history_are_plausible(
    client: tuple[TestClient, dict[str, str]],
) -> None:
    census = get(client, "/api/ed/census")
    year = get(client, "/api/ed/boarding?days=366")["days"]

    assert 5 <= census["now"]["present"] <= 150
    assert 0 <= census["now"]["waiting_bed"] <= census["now"]["present"]
    boarding = [d["boarding"] for d in year]
    assert len(boarding) == 366
    assert max(boarding) > 0  # the winter wave fills the wards
    assert statistics.mean(boarding) < 15
    assert all(d["boarding"] <= d["waiting_bed"] <= d["present"] for d in year)


def test_tension_status_on_the_demo(client: tuple[TestClient, dict[str, str]]) -> None:
    status = get(client, "/api/tension/status")

    assert len(status["units"]) == 8
    assert {u["tension"]["level"] for u in status["units"]} <= {"normal", "tension", "critique"}
    assert status["aid"]["level"] in {"aucun", "vigilance", "het_suggere"}
    critical = next(c for c in status["aid"]["criteria"] if c["code"] == "critical_units_share")
    assert critical["value"] is not None
