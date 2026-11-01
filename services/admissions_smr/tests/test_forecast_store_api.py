"""GET /api/forecast/liscop: serves stored forecast runs, never computes them."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.models import BedPool, ForecastRun, ForecastValue, Group, Site
from services.admissions_smr.tests.conftest import NOW, TODAY

Login = Callable[[str], dict[str, str]]
MakeGroup = Callable[[str], Group]


def add_run(
    db: Session,
    group: Group,
    *,
    as_of: date = TODAY,
    created: datetime = NOW,
    status: str = "ok",
) -> ForecastRun:
    """A stored run with unit, site and group rows for J+0..J+7."""
    sites = db.scalars(select(Site).where(Site.group_id == group.id).order_by(Site.id)).all()
    pools = db.scalars(
        select(BedPool).where(BedPool.site_id.in_([s.id for s in sites])).order_by(BedPool.id)
    ).all()
    metrics = {
        "models_chosen": {"AutoETS": 2, "SeasonalNaive": 1},
        "fallback_series": [f"arrivals:{pools[-1].id}"],
        "common_shock_variance": 0.004,
        "series": {
            f"arrivals:{pools[0].id}": {"model": "AutoETS", "fallback": False},
            f"boarding_10h:{sites[0].id}": {"model": "AutoTheta", "fallback": False},
        },
        "recent_observed": {
            f"boarding_10h:{sites[0].id}": {(TODAY - timedelta(days=1)).isoformat(): 3.0}
        },
    }
    run = ForecastRun(
        group_id=group.id,
        created_at=created,
        as_of=as_of,
        model_version="test-1",
        horizon_days=8,
        status=status,
        params_json="{}",
        metrics_json=json.dumps(metrics),
    )
    db.add(run)
    db.flush()
    for k in range(8):
        day = as_of + timedelta(days=k)
        for pool in pools:
            for target in ("available_beds", "arrivals"):
                db.add(
                    ForecastValue(
                        run_id=run.id,
                        site_id=pool.site_id,
                        pool_id=pool.id,
                        scope="unit",
                        scope_key=f"pool:{pool.id}",
                        target=target,
                        day=day,
                        mean=4.0,
                        q10=2.0,
                        q50=4.0,
                        q90=6.0,
                        p_tension=0.3 if target == "available_beds" else None,
                        p_critique=0.1 if target == "available_beds" else None,
                    )
                )
        db.add(
            ForecastValue(
                run_id=run.id,
                site_id=sites[0].id,
                scope="site",
                scope_key=f"site:{sites[0].id}",
                target="boarding_10h",
                day=day,
                mean=5.0,
                q10=2.0,
                q50=5.0,
                q90=9.0,
            )
        )
        db.add(
            ForecastValue(
                run_id=run.id,
                scope="group",
                scope_key=f"group:{group.id}",
                target="available_beds",
                day=day,
                mean=12.0,
                q10=8.0,
                q50=12.0,
                q90=16.0,
                p_tension=0.5,
                p_critique=0.0,
            )
        )
    db.commit()
    return run


def test_no_run_yet_is_an_empty_answer(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("alpha")

    response = app_client.get("/api/forecast/liscop", headers=login("coord@alpha.fr"))

    assert response.status_code == 200
    body = response.json()
    assert body["run"] is None and body["series"] == [] and body["backtest"] is None
    assert body["synthetic"] is False
    assert any("Disponibles attendus" in note for note in body["notes"])


def test_latest_run_by_unit_with_freshness_models_and_horizons(
    app_client: TestClient, db: Session, make_group: MakeGroup, login: Login
) -> None:
    group = make_group("alpha")
    add_run(db, group, as_of=TODAY - timedelta(days=1), created=NOW - timedelta(days=1))
    latest = add_run(db, group)

    response = app_client.get(
        "/api/forecast/liscop",
        params={"scope": "unit", "target": "available_beds"},
        headers=login("coord@alpha.fr"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["id"] == latest.id
    assert body["run"]["stale"] is False and body["run"]["age_hours"] == 0.0
    assert body["run"]["models_chosen"] == {"AutoETS": 2, "SeasonalNaive": 1}
    assert {s["target"] for s in body["series"]} == {"available_beds"}
    assert len(body["series"]) == 3  # alpha A: geriatrie, polyvalent; alpha B: geriatrie
    first = body["series"][0]
    assert [v["horizon"] for v in first["values"]] == [f"J+{k}" for k in range(8)]
    assert first["values"][1] | {"day": None} == {
        "day": None,
        "horizon": "J+1",
        "mean": 4.0,
        "q10": 2.0,
        "q50": 4.0,
        "q90": 6.0,
        "p_tension": 0.3,
        "p_critique": 0.1,
    }
    assert first["beds_installed"] == 10 and first["label"] in ("geriatrie", "polyvalent")


def test_model_and_recent_history_come_with_the_series(
    app_client: TestClient, db: Session, make_group: MakeGroup, login: Login
) -> None:
    group = make_group("alpha")
    add_run(db, group)

    response = app_client.get(
        "/api/forecast/liscop",
        params={"scope": "site", "target": "boarding_10h"},
        headers=login("coord@alpha.fr"),
    )

    (series,) = response.json()["series"]
    assert series["label"] == "alpha A" and series["model"] == "AutoTheta"
    assert series["recent"] == [{"day": (TODAY - timedelta(days=1)).isoformat(), "value": 3.0}]


def test_site_scoped_users_only_see_their_site(
    app_client: TestClient, db: Session, make_group: MakeGroup, login: Login
) -> None:
    group = make_group("alpha")
    add_run(db, group)
    site_b = db.scalars(select(Site).where(Site.name == "alpha B")).one()
    headers = login("siteb@alpha.fr")

    units = app_client.get("/api/forecast/liscop", headers=headers).json()
    whole = app_client.get("/api/forecast/liscop", params={"scope": "group"}, headers=headers)

    assert units["restricted_to_site"] == site_b.id
    assert {s["site_id"] for s in units["series"]} == {site_b.id}
    assert whole.json()["series"] == []


def test_other_groups_runs_are_invisible(
    app_client: TestClient, db: Session, make_group: MakeGroup, login: Login
) -> None:
    add_run(db, make_group("alpha"))
    make_group("beta")

    body = app_client.get("/api/forecast/liscop", headers=login("coord@beta.fr")).json()

    assert body["run"] is None and body["series"] == []


def test_stale_run_failure_and_backtest_are_reported(
    app_client: TestClient, db: Session, make_group: MakeGroup, login: Login
) -> None:
    group = make_group("alpha")
    add_run(db, group, as_of=TODAY - timedelta(days=2), created=NOW - timedelta(days=2))
    db.add(
        ForecastRun(
            group_id=group.id,
            created_at=NOW - timedelta(hours=1),
            as_of=TODAY,
            model_version="test-1",
            horizon_days=8,
            status="failed",
            metrics_json='{"error": "boom"}',
        )
    )
    db.add(
        ForecastRun(
            group_id=group.id,
            created_at=NOW - timedelta(days=3),
            as_of=TODAY - timedelta(days=4),
            model_version="test-1",
            horizon_days=8,
            status="backtest",
            metrics_json=json.dumps(
                {
                    "gates": {"a_arrivals_mae_ratio": "réussi"},
                    "origins": 21,
                    "arrivals_mae_ratio": 0.8,
                }
            ),
        )
    )
    db.commit()

    body = app_client.get("/api/forecast/liscop", headers=login("dir@alpha.fr")).json()

    assert body["run"]["stale"] is True
    assert body["last_failure_at"] is not None
    assert body["backtest"]["gates"] == {"a_arrivals_mae_ratio": "réussi"}
    assert body["backtest"]["origins"] == 21


def test_unknown_scope_or_target_is_rejected(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("alpha")
    headers = login("coord@alpha.fr")

    scope = app_client.get("/api/forecast/liscop", params={"scope": "pays"}, headers=headers)
    target = app_client.get("/api/forecast/liscop", params={"target": "meteo"}, headers=headers)

    assert scope.status_code == 422 and target.status_code == 422


def test_reading_forecasts_needs_an_account(app_client: TestClient) -> None:
    assert app_client.get("/api/forecast/liscop").status_code == 401


def test_the_api_never_loads_the_forecasting_stack() -> None:
    code = (
        "import sys, services.admissions_smr.main;"
        "heavy = {'numpy', 'pandas', 'statsforecast', 'scipy'} & set(sys.modules);"
        "print(sorted(heavy)); sys.exit(1 if heavy else 0)"
    )

    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert result.returncode == 0, result.stdout + result.stderr
