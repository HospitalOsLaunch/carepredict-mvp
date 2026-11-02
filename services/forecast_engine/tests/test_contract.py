"""Engine → database → API contract (T-9) and the failure path of a scheduled run (T-10)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.clock import FrozenClock
from services.admissions_smr.config import Settings
from services.admissions_smr.db import make_engine, make_session_factory
from services.admissions_smr.main import create_app
from services.admissions_smr.models import ForecastRun, Group, User
from services.admissions_smr.security import hash_password
from services.forecast_engine import __main__ as cli
from services.forecast_engine.data import load_history
from services.forecast_engine.pipeline import compute
from services.forecast_engine.store import save_run
from services.forecast_engine.tests.conftest import AS_OF, NOW, tiny_hospital

PASSWORD = "mot-de-passe-solide"


def add_admin(session: Session, group_id: int) -> str:
    email = f"admin{group_id}@mini.fr"
    session.add(
        User(
            group_id=group_id,
            email=email,
            full_name="Admin Mini",
            role="admin_groupe",
            password_hash=hash_password(PASSWORD, 1000),
            created_at=NOW,
        )
    )
    session.commit()
    return email


@pytest.fixture
def api(tiny: tuple[str, int]) -> Iterator[tuple[TestClient, Session, int]]:
    """The API on the engine's database, at the engine's "now" (J+0 = AS_OF)."""
    url, group_id = tiny
    settings = Settings(
        environment="test",
        database_url=url,
        secret_key="t" * 40,
        token_ttl_minutes=60,
        password_iterations=1000,
        timezone="Europe/Paris",
        cors_origins=(),
    )
    engine = make_engine(url)
    session = make_session_factory(engine)()
    with TestClient(create_app(settings, FrozenClock(NOW))) as client:
        yield client, session, group_id
    session.close()
    engine.dispose()


def headers(client: TestClient, email: str) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_a_computed_run_is_what_the_forecast_page_and_the_ror_export_serve(
    api: tuple[TestClient, Session, int],
) -> None:
    client, session, group_id = api
    auth = headers(client, add_admin(session, group_id))
    history = load_history(session, group_id, AS_OF - timedelta(days=1), "Europe/Paris")
    result = compute(session, history, AS_OF, use_current_plans=True, draws=300)
    run = save_run(session, group_id, result, NOW)
    expected = {
        v.day: v for v in result.values if v.scope == "unit" and v.target == "available_beds"
    }

    page = client.get(
        "/api/forecast/liscop", params={"target": "available_beds"}, headers=auth
    ).json()
    export = client.get("/api/ror/export", headers=auth).json()

    assert page["run"]["id"] == run.id and page["run"]["stale"] is False
    (series,) = page["series"]
    assert [v["horizon"] for v in series["values"]] == [f"J+{k}" for k in range(8)]
    for v in series["values"]:
        stored = expected[AS_OF + timedelta(days=int(v["horizon"][2:]))]
        assert (v["mean"], v["q10"], v["q90"]) == (stored.mean, stored.q10, stored.q90)
        assert v["p_tension"] == stored.p_tension
    assert export["prevision"]["id"] == run.id and export["prevision"]["perimee"] is False
    (unit,) = export["unites"]
    assert unit["previsionnel_nature"]["nature"] == "disponibles_attendus"
    assert unit["previsionnel_nature"]["modele"] == result.model_version
    lines = {p["echeance"]: p for p in unit["previsionnel"]}
    assert list(lines) == ["J+1", "J+2", "J+7"]
    for k in (1, 2, 7):
        stored = expected[AS_OF + timedelta(days=k)]
        assert lines[f"J+{k}"]["moyenne"] == round(max(0.0, stored.mean), 1)
        assert lines[f"J+{k}"]["p_critique"] == stored.p_critique
    forecast_records = {
        r["temporalityCapacity"]["code"]
        for r in unit["ror_capacites"]
        if r["temporalityCapacity"]["code"] != "01"
    }
    assert forecast_records == {"03", "04", "05"}


def test_a_failed_run_is_recorded_the_last_good_one_served_and_other_groups_still_run(
    api: tuple[TestClient, Session, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session, failing = api
    other = tiny_hospital(session)
    auth = headers(client, add_admin(session, failing))
    monkeypatch.setenv(
        "ADM_DATABASE_URL", session.get_bind().engine.url.render_as_string(hide_password=False)
    )
    as_of = ["--as-of", AS_OF.isoformat()]
    assert cli.main(["run", "--group", str(failing), *as_of]) == 0
    good = session.scalars(select(ForecastRun).where(ForecastRun.group_id == failing)).one()

    def compute_or_fail(session: Session, history: Any, *args: Any, **kwargs: Any) -> Any:
        if history.group_id == failing:
            raise RuntimeError("panne simulée")
        return compute(session, history, *args, **kwargs)

    monkeypatch.setattr(cli, "compute", compute_or_fail)

    code = cli.main(["run", "--all", *as_of])

    assert code == 1
    session.expire_all()
    runs = {
        (r.group_id, r.status): r
        for r in session.scalars(select(ForecastRun).order_by(ForecastRun.id))
    }
    assert set(runs) == {(failing, "ok"), (failing, "failed"), (other, "ok")}
    assert "panne simulée" in runs[(failing, "failed")].metrics_json
    assert session.get(Group, other) is not None
    page = client.get("/api/forecast/liscop", headers=auth).json()
    assert page["run"]["id"] == good.id
    assert page["last_failure_at"] is not None
