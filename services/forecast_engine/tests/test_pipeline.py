"""End to end: compute a run, store it, and the command line."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from sqlalchemy import Engine, inspect, select
from sqlalchemy.orm import Session

from services.admissions_smr.db import make_engine, make_session_factory
from services.admissions_smr.migrate import upgrade
from services.admissions_smr.models import (
    BedPool,
    EdVisit,
    ForecastRun,
    ForecastValue,
    Group,
    Site,
    Stay,
)
from services.admissions_smr.seed_mco import GROUP_NAME
from services.admissions_smr.service import build_forecast, plan_history
from services.admissions_smr.tests.conftest import test_database_url as database_url
from services.admissions_smr.vocab import FORECAST_SCOPES, FORECAST_TARGETS
from services.forecast_engine.__main__ import SCHEMA_BEHIND, main
from services.forecast_engine.data import load_history
from services.forecast_engine.pipeline import compute, discharge_model
from services.forecast_engine.store import save_run

PARIS = ZoneInfo("Europe/Paris")
AS_OF = date(2026, 3, 31)
NOW = datetime(2026, 3, 31, 5, 0, tzinfo=UTC)


def tiny_hospital(session: Session) -> int:
    """Thirty days of a 10-bed unit and its emergency department: too short for CV."""
    group = Group(name="Mini", created_at=NOW)
    session.add(group)
    session.flush()
    site = Site(group_id=group.id, name="CH Mini", ght="GHT Mini", departement="80", created_at=NOW)
    session.add(site)
    session.flush()
    pool = BedPool(
        site_id=site.id,
        mention="medecine_polyvalente",
        beds_installed=10,
        beds_open=10,
        unit_type="medecine",
        discipline="medecine",
        updated_at=NOW,
    )
    session.add(pool)
    session.flush()
    for i in range(30):
        day = AS_OF - timedelta(days=30 - i)
        noon = datetime.combine(day, datetime.min.time(), tzinfo=PARIS) + timedelta(hours=12)
        session.add(
            EdVisit(
                group_id=group.id,
                site_id=site.id,
                encounter_ref=f"E{i}",
                patient_ref=f"P{i}",
                arrived_at=noon.astimezone(UTC),
                left_at=(noon + timedelta(hours=3)).astimezone(UTC),
                outcome="sortie",
                source="hl7",
            )
        )
        discharged = day + timedelta(days=4)
        session.add(
            Stay(
                group_id=group.id,
                site_id=site.id,
                mention="medecine_polyvalente",
                patient_ref=f"S{i}",
                admission_date=day,
                admitted_at=noon.astimezone(UTC),
                discharge_date=discharged if discharged < AS_OF else None,
                admission_mode="urgences",
                created_at=NOW,
                updated_at=NOW,
            )
        )
    session.commit()
    return group.id


@pytest.fixture
def tiny(tmp_path: Path) -> Iterator[tuple[str, int]]:
    url = database_url(tmp_path)
    engine = make_engine(url)
    upgrade(engine)
    with make_session_factory(engine)() as session:
        group_id = tiny_hospital(session)
    engine.dispose()
    yield url, group_id


def test_a_run_has_every_scope_and_consistent_bounds(tiny: tuple[str, int]) -> None:
    url, group_id = tiny
    engine = make_engine(url)
    with make_session_factory(engine)() as session:
        history = load_history(session, group_id, AS_OF - timedelta(days=1), "Europe/Paris")

        result = compute(session, history, AS_OF, use_current_plans=True, draws=300)
    engine.dispose()

    assert {v.scope for v in result.values} == set(FORECAST_SCOPES)
    beds = [v for v in result.values if v.target == "available_beds"]
    assert {v.day for v in beds} == {AS_OF + timedelta(days=k) for k in range(8)}
    for v in beds:
        assert 0 <= v.q10 <= v.q50 <= v.q90 <= 10
        assert v.p_tension is not None and v.p_critique is not None
        assert 0 <= v.p_critique <= v.p_tension <= 1
    unit = {v.day: v.mean for v in beds if v.scope == "unit"}
    site = {v.day: v.mean for v in beds if v.scope == "site"}
    assert unit == pytest.approx(site)  # one unit: the site is the unit
    assert result.metrics["fallback_series"]  # 30 days: too short for cross-validation
    targets = {v.target for v in result.values}
    assert {"arrivals", "discharges", "tension_prob", "boarding_10h", "ed_arrivals"} <= targets
    assert targets == set(FORECAST_TARGETS)  # what the API accepts, from the shared vocabulary


def test_discharge_model_is_the_one_of_build_forecast(demo_engine: Engine) -> None:
    """The engine skips build_forecast's per-pool work but keeps its hazards and slip."""
    as_of = date(2026, 10, 25)
    with make_session_factory(demo_engine)() as session:
        group_id = session.scalars(select(Group.id).where(Group.name == GROUP_NAME)).one()
        sites = list(session.scalars(select(Site).where(Site.group_id == group_id)))
        fitted = build_forecast(session, group_id, sites, as_of, 8)

        plans = plan_history(session, group_id)
        model, slip = discharge_model(session, group_id, as_of, plans)

    assert model == fitted.model
    assert slip == fitted.slip.weights


def test_saved_run_reads_back(tiny: tuple[str, int]) -> None:
    url, group_id = tiny
    engine = make_engine(url)
    with make_session_factory(engine)() as session:
        history = load_history(session, group_id, AS_OF - timedelta(days=1), "Europe/Paris")
        result = compute(session, history, AS_OF, use_current_plans=True, draws=200)

        run = save_run(session, group_id, result, NOW)

        stored = session.scalars(select(ForecastValue).where(ForecastValue.run_id == run.id)).all()
        assert run.status == "ok" and run.as_of == AS_OF and run.horizon_days == 8
        assert len(stored) == len(result.values)
        assert json.loads(run.metrics_json)["series"]
        assert json.loads(run.params_json)["draws"] == 200
    engine.dispose()


def test_command_line_runs_and_stores_a_forecast(
    tiny: tuple[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    url, group_id = tiny
    monkeypatch.setenv("ADM_DATABASE_URL", url)
    # The engine reads no secret: even "production" without them is fine (S-M4).
    monkeypatch.setenv("ADM_ENV", "production")
    monkeypatch.delenv("ADM_SECRET_KEY", raising=False)
    monkeypatch.delenv("ADM_PSEUDONYM_SECRET", raising=False)

    code = main(["run", "--group", str(group_id), "--as-of", AS_OF.isoformat()])
    missing = main(["run", "--group", "999"])

    assert (code, missing) == (0, 1)
    engine = make_engine(url)
    with make_session_factory(engine)() as session:
        runs = session.scalars(select(ForecastRun)).all()
        assert [r.status for r in runs] == ["ok"]
    engine.dispose()


def test_command_line_refuses_a_schema_that_is_not_migrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    monkeypatch.setenv("ADM_DATABASE_URL", url)

    code = main(["run", "--all"])

    assert code == SCHEMA_BEHIND
    assert "migrations" in caplog.text
    engine = make_engine(url)
    assert inspect(engine).get_table_names() == []  # nothing created: no migration run
    engine.dispose()


@pytest.mark.slow
def test_demo_run_aggregates_units_into_the_group(demo_engine: Engine) -> None:
    with make_session_factory(demo_engine)() as session:
        group_id = session.scalars(select(Group.id).where(Group.name == GROUP_NAME)).one()
        as_of = date(2026, 10, 25)
        history = load_history(session, group_id, as_of - timedelta(days=1), "Europe/Paris")

        result = compute(session, history, as_of, use_current_plans=True, draws=500)

    def means(scope: str, target: str) -> dict[date, float]:
        out: dict[date, float] = {}
        for v in result.values:
            if v.scope == scope and v.target == target:
                out[v.day] = out.get(v.day, 0.0) + v.mean
        return out

    for target in ("available_beds", "arrivals", "discharges"):
        units, group = means("unit", target), means("group", target)
        if target == "arrivals":  # units: model forecast; group: sum of the draws
            assert np.allclose(list(units.values()), list(group.values()), rtol=0.15, atol=1)
        else:
            assert units == pytest.approx(group, abs=0.01)
    assert means("ght", "available_beds") == pytest.approx(means("group", "available_beds"))
    assert set(result.metrics["models_chosen"]) <= {"SeasonalNaive", "AutoETS", "AutoTheta", "MSTL"}
    boarding = {v.scope_key for v in result.values if v.target == "boarding_10h"}
    assert len([k for k in boarding if k.startswith("site:")]) == 1  # the SMR site has no ED
