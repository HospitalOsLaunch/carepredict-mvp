"""The MCO demo (seed-demo-mco): realistic, consistent, pseudonymous, usable by every page."""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from services.admissions_smr import cli
from services.admissions_smr.clock import FrozenClock
from services.admissions_smr.config import Settings, get_settings
from services.admissions_smr.db import Base, make_engine, make_session_factory
from services.admissions_smr.domain.imports import _NIR_LIKE
from services.admissions_smr.main import create_app
from services.admissions_smr.migrate import upgrade
from services.admissions_smr.models import Bed, BedPool, EdVisit, Group, Site, Stay, User
from services.admissions_smr.seed_mco import GROUP_NAME, seed_demo_mco
from services.admissions_smr.tests.conftest import NOW
from services.admissions_smr.tests.conftest import test_database_url as database_url
from services.admissions_smr.vocab import UNIT_KINDS

PARIS = ZoneInfo("Europe/Paris")
PASSWORD = "mot-de-passe-demo"
HEX64 = re.compile(r"[0-9a-f]{64}")


@pytest.fixture(scope="module")
def engine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Engine]:
    engine = make_engine(database_url(tmp_path_factory.mktemp("mco")))
    upgrade(engine)
    with make_session_factory(engine)() as session:
        seed_demo_mco(session, NOW, PASSWORD, 1000)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with make_session_factory(engine)() as session:
        yield session


def local_day(at: datetime) -> date:
    return at.astimezone(PARIS).date()


def test_group_sites_and_units_follow_the_plan(db: Session) -> None:
    group = db.scalars(select(Group).where(Group.name == GROUP_NAME)).one()
    sites = db.scalars(select(Site).where(Site.group_id == group.id)).all()
    assert {s.name for s in sites} == {"CH Deux-Rivières", "SMR Les Saules"}
    assert {(s.departement, s.ght) for s in sites} == {("59", "GHT Hainaut-Fictif")}
    assert all(s.territory for s in sites)
    pools = db.scalars(select(BedPool).join(Site).where(Site.group_id == group.id)).all()
    assert {p.mention for p in pools} == set(UNIT_KINDS) | {"polyvalent", "geriatrie"}
    for pool in pools:
        expected = UNIT_KINDS.get(pool.mention, ("smr", "smr"))
        assert (pool.unit_type, pool.discipline) == expected
        assert pool.label and pool.uf_code


def test_rooms_and_beds_match_the_units(db: Session) -> None:
    beds = db.scalars(select(Bed)).all()
    assert 230 <= len(beds) <= 270
    by_pool = Counter(b.pool_id for b in beds)
    for pool in db.scalars(select(BedPool)):
        assert by_pool[pool.id] == pool.beds_installed
        isolation = sum(1 for b in beds if b.pool_id == pool.id and b.isolation)
        assert isolation == pool.isolation_rooms
    room_sizes = Counter(Counter((b.site_id, b.room) for b in beds).values())
    assert room_sizes[1] > 20 and room_sizes[2] > 40 and set(room_sizes) == {1, 2}
    sexes = Counter(b.sex_constraint for b in beds)
    assert sexes["X"] > len(beds) / 2 and sexes["F"] > 0 and sexes["M"] > 0


def test_beds_and_present_stays_point_at_each_other(db: Session) -> None:
    beds = db.scalars(select(Bed)).all()
    stays = {s.id: s for s in db.scalars(select(Stay))}
    present = {s.id for s in stays.values() if s.discharged_at is None}
    occupied = [b for b in beds if b.status == "occupe"]
    assert {b.stay_id for b in occupied} == present
    assert len(occupied) == len(present) > 150
    pools = {p.id: p for p in db.scalars(select(BedPool))}
    for bed in occupied:
        assert bed.stay_id is not None
        stay = stays[bed.stay_id]
        assert stay.bed_id == bed.id and stay.admitted_at and stay.admitted_at <= NOW
        assert (stay.site_id, stay.mention) == (bed.site_id, pools[bed.pool_id].mention)
        assert bed.sex_constraint in ("X", stay.patient_sex)
    assert all(b.stay_id is None for b in beds if b.status != "occupe")
    assert all(s.bed_id is None for s in stays.values() if s.id not in present)
    statuses = Counter(b.status for b in beds)
    assert statuses["a_nettoyer"] > 0 and statuses["bloque"] > 0 and statuses["libre"] > 0
    for pool in pools.values():
        in_pool = [b for b in beds if b.pool_id == pool.id]
        assert sum(b.status == "occupe" for b in in_pool) <= pool.beds_open
        assert sum(b.status == "bloque" for b in in_pool) >= pool.beds_installed - pool.beds_open


def test_stays_are_hl7_stays_with_coherent_dates(db: Session) -> None:
    stays = db.scalars(select(Stay)).all()
    assert len(stays) > 5000
    for stay in stays:
        assert stay.source == "hl7" and stay.admitted_at is not None
        assert stay.admission_date == local_day(stay.admitted_at)
        if stay.discharged_at is not None:
            assert stay.admitted_at < stay.discharged_at <= NOW
            assert stay.discharge_date == local_day(stay.discharged_at)
        else:
            assert stay.discharge_date is None
        assert stay.patient_sex in ("F", "M") and stay.patient_age is not None
    modes = Counter(s.admission_mode for s in stays)
    assert set(modes) == {"urgences", "programme", "mutation", "transfert"}


def test_emergency_history_has_seasonality_and_overnight_boarding(db: Session) -> None:
    visits = db.scalars(select(EdVisit)).all()
    per_day = Counter(local_day(v.arrived_at) for v in visits)
    full_days = [d for d in per_day if d < local_day(NOW)]
    assert 360 <= len(full_days) <= 366
    mean = statistics.mean(per_day[d] for d in full_days)
    assert 110 <= mean <= 130
    by_month: dict[int, list[int]] = defaultdict(list)
    by_weekday: dict[int, list[int]] = defaultdict(list)
    for d in full_days:
        by_month[d.month].append(per_day[d])
        by_weekday[d.weekday()].append(per_day[d])
    winter = statistics.mean(by_month[1] + by_month[2])
    summer = statistics.mean(by_month[6] + by_month[9])
    assert winter > summer * 1.08
    assert statistics.mean(by_weekday[0]) > statistics.mean(by_weekday[3])
    admitted = [v for v in visits if v.admit_decision_at is not None]
    assert 0.18 <= len(admitted) / len(visits) <= 0.28
    hospitalised = [v for v in admitted if v.outcome == "hospitalise"]
    assert all(v.target_pool_id is not None and v.left_at for v in hospitalised)
    overnight: set[date] = set()
    for v in admitted:
        assert v.admit_decision_at is not None
        decision = v.admit_decision_at.astimezone(PARIS)
        ten = datetime.combine(decision.date(), datetime.min.time(), PARIS).replace(hour=10)
        if decision.hour < 8 and (v.left_at is None or v.left_at > ten):
            overnight.add(decision.date())
    assert len(overnight) >= 15
    still_there = [v for v in visits if v.left_at is None]
    assert still_there and all(NOW - v.arrived_at < timedelta(days=3) for v in still_there)


def test_nothing_identifying_is_stored(db: Session) -> None:
    refs = [
        *db.execute(select(Stay.encounter_ref, Stay.patient_ref)),
        *db.execute(select(EdVisit.encounter_ref, EdVisit.patient_ref)),
    ]
    assert all(HEX64.fullmatch(e or "") and HEX64.fullmatch(p) for e, p in refs)
    for name in ("stays", "ed_visits", "beds", "bed_pools", "sites", "users"):
        for row in db.execute(select(Base.metadata.tables[name])).mappings():
            for column, value in row.items():
                assert not (isinstance(value, str) and _NIR_LIKE.match(value)), (name, column)
    names = {u.full_name for u in db.scalars(select(User).where(User.email.like("%ch-demo%")))}
    assert all("(démo)" in n or n.startswith("Agent") for n in names)


def test_existing_pages_work_on_the_mco_group(engine: Engine) -> None:
    settings = Settings(
        environment="test",
        database_url=engine.url.render_as_string(hide_password=False),
        secret_key="t" * 40,
        token_ttl_minutes=60,
        password_iterations=1000,
        timezone="Europe/Paris",
        cors_origins=(),
    )
    with TestClient(create_app(settings, FrozenClock(NOW))) as client:
        login = client.post(
            "/api/auth/login",
            json={"email": "bedmanager@ch-demo.hospitalos.fr", "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        for path in (
            "/api/sites",
            "/api/dashboard",
            "/api/stays",
            "/api/forecast",
            "/api/forecast/workload",
            "/api/staffing",
            "/api/ror/export",
        ):
            response = client.get(path, headers=headers)
            assert response.status_code == 200, (path, response.text)


def test_cli_seeds_once_and_refuses_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ADM_DATABASE_URL", database_url(tmp_path))
    monkeypatch.setenv("ADM_ENV", "development")
    monkeypatch.setenv("ADM_PASSWORD_ITERATIONS", "1000")
    get_settings.cache_clear()
    try:
        assert cli.main(["seed-demo-mco"]) == 0
        out = capsys.readouterr().out
        assert "bedmanager@" in out and "ch-demo.hospitalos.fr" in out
        assert cli.main(["seed-demo-mco"]) == 1
        assert "existe déjà" in capsys.readouterr().err
        monkeypatch.setenv("ADM_ENV", "production")
        monkeypatch.setenv("ADM_SECRET_KEY", "k" * 40)
        monkeypatch.setenv("ADM_PSEUDONYM_SECRET", "p" * 40)
        monkeypatch.setenv("ADM_DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/x")
        get_settings.cache_clear()
        # Refused before touching the database.
        assert cli.main(["seed-demo-mco"]) == 1
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("env", ["staging", "Production", "prod"])
@pytest.mark.parametrize("command", ["seed-demo", "seed-demo-mco"])
def test_cli_refuses_demo_seeds_outside_development_and_test(
    env: str,
    command: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REVIEW S-M3: known demo passwords never reach a non-development database."""
    monkeypatch.setenv("ADM_ENV", env)
    monkeypatch.setenv("ADM_SECRET_KEY", "k" * 40)
    monkeypatch.setenv("ADM_PSEUDONYM_SECRET", "p" * 40)
    monkeypatch.setenv("ADM_DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/x")
    get_settings.cache_clear()
    try:
        assert cli.main([command]) == 1  # refused before touching the (unreachable) database
        assert "ADM_ENV" in capsys.readouterr().err
    finally:
        get_settings.cache_clear()
