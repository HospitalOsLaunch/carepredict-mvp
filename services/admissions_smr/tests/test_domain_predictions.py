from __future__ import annotations

from datetime import date, timedelta

import pytest

from services.admissions_smr.domain.forecast import (
    DEFAULT_PLAN_SLIP,
    MIN_SLIP_SAMPLES,
    StayRecord,
    discharge_cdf,
    estimate_plan_slip,
    fit_hazard,
    plan_known_at,
)
from services.admissions_smr.domain.workload import (
    Arrival,
    CareMinutes,
    forecast_workload,
    realized_care_minutes,
    tension_of,
)

TODAY = date(2026, 10, 25)
MINUTES = CareMinutes.from_settings(
    {"1": 60, "2": 120, "3": 180, "4": 240, "entree": 30, "sortie": 15}
)


def test_plan_known_at_uses_the_latest_entry_strictly_before_the_morning() -> None:
    history = [(date(2026, 10, 1), date(2026, 10, 10)), (date(2026, 10, 5), date(2026, 10, 12))]
    assert plan_known_at(history, date(2026, 10, 5)) == date(2026, 10, 10)
    assert plan_known_at(history, date(2026, 10, 6)) == date(2026, 10, 12)
    assert plan_known_at(history, date(2026, 9, 30)) is None


def _discharged_with_plan(
    n: int, slip: int
) -> tuple[list[StayRecord], dict[int, list[tuple[date, date | None]]]]:
    stays: list[StayRecord] = []
    plans: dict[int, list[tuple[date, date | None]]] = {}
    for i in range(n):
        discharge = TODAY - timedelta(days=5 + i)
        stays.append(StayRecord(i, 1, "geriatrie", discharge - timedelta(days=20), discharge))
        plans[i] = [(discharge - timedelta(days=4), discharge - timedelta(days=slip))]
    return stays, plans


def test_slip_is_a_prior_until_enough_discharges_then_measured() -> None:
    stays, plans = _discharged_with_plan(MIN_SLIP_SAMPLES - 1, slip=2)
    assert estimate_plan_slip(stays, plans, TODAY).weights == DEFAULT_PLAN_SLIP
    stays, plans = _discharged_with_plan(MIN_SLIP_SAMPLES, slip=2)
    measured = estimate_plan_slip(stays, plans, TODAY)
    assert measured.measured and measured.samples == MIN_SLIP_SAMPLES
    assert measured.weights == {2: 1.0}


def test_a_plan_typed_on_the_discharge_day_is_not_counted() -> None:
    stays = [
        StayRecord(i, 1, "g", TODAY - timedelta(days=30), TODAY - timedelta(days=3))
        for i in range(40)
    ]
    plans = {i: [(TODAY - timedelta(days=3), TODAY - timedelta(days=3))] for i in range(40)}
    assert not estimate_plan_slip(stays, plans, TODAY).measured


def test_patients_without_a_plan_use_the_landmark_model() -> None:
    """Teams plan the discharges that are near: patients with no plan leave less often."""
    stays, plans = [], {}
    sid = 0
    for d in range(0, 300):
        admit = TODAY - timedelta(days=330 - d)
        # Short stays (10 d) always get a plan 4 days ahead; long stays (60 d) never do.
        for los, planned in ((10, True), (60, False)):
            discharge = admit + timedelta(days=los)
            stays.append(
                StayRecord(sid, 1, "geriatrie", admit, discharge if discharge < TODAY else None)
            )
            if planned:
                plans[sid] = [(discharge - timedelta(days=4), discharge)]
            sid += 1
    unconditional = fit_hazard(stays, TODAY)
    conditional = fit_hazard(stays, TODAY, plans=plans)
    patient = StayRecord(99_999, 1, "geriatrie", TODAY - timedelta(days=8))  # 8 days in, no plan
    naive = discharge_cdf(patient, TODAY, 7, unconditional)[6]
    aware = discharge_cdf(patient, TODAY, 7, conditional)[6]
    assert naive > 0.4  # half the cohort leaves at day 10
    assert aware < 0.05  # but those are the planned ones; an unplanned patient stays


def test_workload_counts_presence_discharges_promises_and_staff() -> None:
    stays = [
        StayRecord(
            i,
            1,
            "geriatrie",
            TODAY - timedelta(days=200 + i),
            TODAY - timedelta(days=190 + i),
            None,
            2,
        )
        for i in range(40)
    ]
    model = fit_hazard(stays, TODAY)  # every stay lasts exactly 10 days
    present = [
        StayRecord(
            100, 1, "geriatrie", TODAY - timedelta(days=9), None, None, 4
        ),  # leaves tomorrow
        StayRecord(101, 1, "geriatrie", TODAY - timedelta(days=2), None, None, 1),
    ]
    staff = {TODAY: 400.0, TODAY + timedelta(days=1): 250.0}
    days = forecast_workload(
        present,
        10,
        TODAY,
        3,
        model,
        MINUTES,
        arrivals=[Arrival(TODAY + timedelta(days=1), 3)],
        staff_minutes=staff,
    )
    assert days[0].care_minutes_expected == pytest.approx(240 + 60)
    # Day 1: patient 100 is cared for and leaves (240 + 15), 101 stays (60), arrival (180 + 30).
    assert days[1].care_minutes_expected == pytest.approx(240 + 15 + 60 + 180 + 30)
    assert days[1].known_admissions == 1
    assert days[0].tension == "normale" and days[1].tension == "tension"
    assert days[1].load_ratio == pytest.approx(525 / 250, abs=1e-3)
    assert days[2].staff_minutes is None and days[2].tension == "inconnue"


def test_unknown_admissions_fill_only_free_beds() -> None:
    stays = [
        StayRecord(
            i, 1, "g", TODAY - timedelta(days=200 + i), TODAY - timedelta(days=150 + i), None, 2
        )
        for i in range(40)
    ]
    model = fit_hazard(stays, TODAY)  # 50-day stays: nobody leaves within the horizon
    present = [
        StayRecord(200 + i, 1, "g", TODAY - timedelta(days=1), None, None, 2) for i in range(9)
    ]
    days = forecast_workload(
        present, 10, TODAY, 4, model, MINUTES, admission_rate=dict.fromkeys(range(7), 3.0)
    )
    assert sum(d.expected_new_admissions for d in days) == pytest.approx(1.0)
    assert days[-1].census_expected == pytest.approx(10.0)


def test_realized_minutes_and_tension_thresholds() -> None:
    stays = [
        StayRecord(1, 1, "g", TODAY, None, None, 3),
        StayRecord(2, 1, "g", TODAY - timedelta(days=5), TODAY, None, 1),
        StayRecord(3, 1, "g", TODAY - timedelta(days=5), TODAY - timedelta(days=1), None, 4),
    ]
    assert realized_care_minutes(stays, TODAY, MINUTES) == 180 + 30 + 60 + 15
    assert [tension_of(r) for r in (None, 0.5, 0.95, 1.2)] == [
        "inconnue",
        "normale",
        "vigilance",
        "tension",
    ]
