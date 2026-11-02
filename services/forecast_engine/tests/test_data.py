"""Daily series read from the database."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from services.admissions_smr.db import make_engine, make_session_factory
from services.admissions_smr.migrate import upgrade
from services.admissions_smr.models import BedPool, EdVisit, Group, Site, Stay
from services.admissions_smr.seed_mco import GROUP_NAME
from services.admissions_smr.tests.conftest import test_database_url as database_url
from services.forecast_engine.data import load_history

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 3, 4, 8, 0, tzinfo=UTC)


def paris(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, minute, tzinfo=PARIS).astimezone(UTC)


@pytest.fixture
def small(tmp_path: Path) -> Iterator[tuple[Session, int, int]]:
    """Three days of a tiny hospital, with every case of the definitions spelled out."""
    engine = make_engine(database_url(tmp_path))
    upgrade(engine)
    session = make_session_factory(engine)()
    group = Group(name="Petit", created_at=NOW)
    session.add(group)
    session.flush()
    site = Site(group_id=group.id, name="Site", ght="GHT", departement="59", created_at=NOW)
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

    def stay(ref: str, admitted: datetime, discharged: datetime | None, mode: str) -> None:
        session.add(
            Stay(
                group_id=group.id,
                site_id=site.id,
                mention="medecine_polyvalente",
                patient_ref=ref,
                admission_date=admitted.astimezone(PARIS).date(),
                admitted_at=admitted,
                discharge_date=discharged.astimezone(PARIS).date() if discharged else None,
                discharged_at=discharged,
                admission_mode=mode,
                created_at=NOW,
                updated_at=NOW,
            )
        )

    stay("A", paris(1, 10), paris(3, 14), "urgences")
    stay("B", paris(2, 9), None, "programme")
    stay("C", datetime(2026, 2, 20, 12, tzinfo=UTC), paris(2, 11), "mutation")

    def visit(ref: str, arrived: datetime, decision: datetime | None, left: datetime | None,
              outcome: str | None, target: int | None) -> None:  # fmt: skip
        session.add(
            EdVisit(
                group_id=group.id,
                site_id=site.id,
                encounter_ref=ref,
                patient_ref=ref,
                arrived_at=arrived,
                admit_decision_at=decision,
                left_at=left,
                outcome=outcome,
                target_pool_id=target,
                source="hl7",
            )
        )

    # Boards at 10:00 on the 2nd and the 3rd: arrived the evening before, decided at night.
    visit("V1", paris(1, 23), paris(2, 2), paris(3, 11), "hospitalise", pool.id)
    # Arrived after 08:00: never counted that day; gone before the next 10:00.
    visit("V2", paris(2, 9), paris(2, 9, 30), paris(2, 15), "hospitalise", pool.id)
    # Decided after 10:00, gone before 10:00 the next day.
    visit("V3", paris(1, 6), paris(1, 10, 30), paris(2, 9), "transfert", None)
    session.commit()
    yield session, group.id, pool.id
    session.close()
    engine.dispose()


def test_unit_series_count_arrivals_discharges_and_occupancy(
    small: tuple[Session, int, int],
) -> None:
    session, group_id, pool_id = small

    h = load_history(session, group_id, date(2026, 3, 3), "Europe/Paris")

    assert (h.first_day, h.last_day) == (date(2026, 3, 1), date(2026, 3, 3))
    assert h.unit_series["arrivals"][pool_id].tolist() == [1, 1, 0]
    assert h.unit_series["arrivals_urgences"][pool_id].tolist() == [1, 0, 0]
    assert h.unit_series["arrivals_programme"][pool_id].tolist() == [0, 1, 0]
    assert h.unit_series["discharges"][pool_id].tolist() == [0, 1, 1]
    assert h.unit_series["occupancy"][pool_id].tolist() == [2, 2, 1]


def test_site_series_count_emergency_flows_and_boarding(small: tuple[Session, int, int]) -> None:
    session, group_id, _ = small

    h = load_history(session, group_id, date(2026, 3, 3), "Europe/Paris")

    site_id = next(iter(h.sites))
    assert h.site_series["ed_arrivals"][site_id].tolist() == [2, 1, 0]
    assert h.site_series["ed_admissions"][site_id].tolist() == [0, 1, 1]
    assert h.site_series["boarding_10h"][site_id].tolist() == [0, 1, 1]


def test_present_stays_and_waiting_patients_at_a_point_in_time(
    small: tuple[Session, int, int],
) -> None:
    session, group_id, pool_id = small
    h = load_history(session, group_id, date(2026, 3, 3), "Europe/Paris")

    present = h.present_at_start(date(2026, 3, 2))
    waiting = h.ed_waiting(paris(2, 5))

    assert sorted(s.stay_id for s in present[pool_id]) == [1, 3]
    assert waiting[pool_id] == 1


def test_demo_series_are_consistent(demo_engine: Engine) -> None:
    with make_session_factory(demo_engine)() as session:
        group_id = session.scalars(select(Group.id).where(Group.name == GROUP_NAME)).one()
        last_day = date(2026, 10, 24)

        h = load_history(session, group_id, last_day, "Europe/Paris")

    assert 360 <= h.n_days <= 367
    ed = next(s for s in h.site_series["ed_arrivals"].values() if s.sum() > 0)
    assert 100 < ed.mean() < 150
    beds = {p: u for p, u in h.units.items() if u.installed > 0}
    for pool_id, unit in beds.items():
        occupancy = h.unit_series["occupancy"][pool_id]
        assert occupancy.min() >= 0 and occupancy.max() <= unit.installed
        modes = sum(
            h.unit_series[f"arrivals_{m}"][pool_id]
            for m in ("urgences", "programme", "mutation", "transfert", "autre")
        )
        assert np.array_equal(modes, h.unit_series["arrivals"][pool_id])
        # Occupancy integrates the flows.
        flow = np.diff(occupancy)
        net = (h.unit_series["arrivals"][pool_id] - h.unit_series["discharges"][pool_id])[1:]
        assert np.array_equal(flow, net)
    boarding = next(iter(h.site_series["boarding_10h"].values()))
    assert boarding.max() > 0
    assert h.capacity_on(next(iter(beds)), last_day - timedelta(days=400))[0] > 0
