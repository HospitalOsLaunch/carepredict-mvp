"""Emergency department census, boarding at 10:00 and hosted patients."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from services.admissions_smr.domain.ed import (
    AdmittedStay,
    Declared,
    Visit,
    boarding_10h,
    census,
    daily_series,
    hosted_elsewhere,
)

PARIS = ZoneInfo("Europe/Paris")
DAY = date(2026, 11, 3)  # winter time: UTC+1


def paris(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=PARIS).astimezone(UTC)


def waiting(arrived: datetime, left: datetime | None = None) -> Visit:
    return Visit(
        arrived_at=arrived, admit_decision_at=arrived + timedelta(minutes=30), left_at=left
    )


def test_present_and_waiting_bed_at_an_instant() -> None:
    t = paris(DAY, 12)
    visits = [
        Visit(paris(DAY, 9), None, None),  # present, no decision
        Visit(paris(DAY, 8), paris(DAY, 11), None),  # waiting for a bed
        Visit(paris(DAY, 8), paris(DAY, 13), None),  # decision after t
        Visit(paris(DAY, 7), None, paris(DAY, 11)),  # left before t
        Visit(paris(DAY, 13), None, None),  # not arrived yet
    ]

    c = census(visits, t)

    assert (c.present, c.waiting_bed, c.longest_wait_hours) == (3, 1, 1.0)


def test_visit_left_exactly_at_t_is_gone() -> None:
    assert census([Visit(paris(DAY, 8), None, paris(DAY, 12))], paris(DAY, 12)).present == 0


def test_visit_without_departure_after_72_hours_is_stale() -> None:
    old = Visit(paris(DAY, 8) - timedelta(hours=72), None, None)

    assert census([old], paris(DAY, 8)).present == 0


def test_boarding_cutoff_arrived_0759_counts_0800_does_not() -> None:
    visits = [
        Visit(paris(DAY, 7, 59), paris(DAY, 9), None),
        Visit(paris(DAY, 8, 0), paris(DAY, 9), None),
    ]

    assert boarding_10h(visits, DAY, PARIS) == 1


def test_boarding_counts_the_night_before() -> None:
    visits = [waiting(paris(DAY - timedelta(days=1), 22))]

    assert boarding_10h(visits, DAY, PARIS) == 1


def test_boarding_needs_a_decision_by_10h_and_presence_at_10h() -> None:
    visits = [
        Visit(paris(DAY, 6), paris(DAY, 10, 1), None),  # decision after 10:00
        Visit(paris(DAY, 6), None, None),  # no decision
        Visit(paris(DAY, 6), paris(DAY, 7), paris(DAY, 10)),  # left at 10:00 sharp
        Visit(paris(DAY, 6), paris(DAY, 7), paris(DAY, 10, 1)),  # still there at 10:00
    ]

    assert boarding_10h(visits, DAY, PARIS) == 1


def test_boarding_on_daylight_saving_days_uses_local_time() -> None:
    spring, autumn = date(2026, 3, 29), date(2026, 10, 25)
    # 10:00 local is 08:00 UTC on the spring day, 09:00 UTC on the autumn day.
    left_spring = datetime(2026, 3, 29, 8, 0, tzinfo=UTC)
    left_autumn = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    arrived_spring = datetime(2026, 3, 29, 5, 59, tzinfo=UTC)  # 07:59 CEST
    arrived_autumn = datetime(2026, 10, 25, 6, 59, tzinfo=UTC)  # 07:59 CET

    assert boarding_10h([waiting(arrived_spring, left_spring)], spring, PARIS) == 0
    assert boarding_10h([waiting(arrived_spring)], spring, PARIS) == 1
    assert boarding_10h([waiting(arrived_autumn, left_autumn)], autumn, PARIS) == 0
    assert boarding_10h([waiting(arrived_autumn)], autumn, PARIS) == 1
    late = datetime(2026, 10, 25, 7, 0, tzinfo=UTC)  # 08:00 CET
    assert boarding_10h([waiting(late)], autumn, PARIS) == 0


def test_hosted_elsewhere_only_when_disciplines_differ_and_are_known() -> None:
    t = paris(DAY, 10)
    admitted = paris(DAY, 2)
    stays = [
        AdmittedStay(admitted, None, "chirurgie", "medecine"),  # hosted
        AdmittedStay(admitted, None, "medecine", "medecine"),
        AdmittedStay(admitted, None, "chirurgie", None),  # target unknown
        AdmittedStay(admitted, paris(DAY, 9), "chirurgie", "medecine"),  # discharged
    ]

    assert hosted_elsewhere(stays, t) == 1


def test_daily_series_reads_each_day_at_10h() -> None:
    days = [DAY - timedelta(days=1), DAY]
    visits = [waiting(paris(DAY, 6))]

    series = daily_series(visits, [], days, PARIS)

    assert [(p.day, p.boarding, p.source) for p in series] == [
        (days[0], 0, "calcul"),
        (DAY, 1, "calcul"),
    ]
    assert series[1].waiting_bed == 1 and series[1].present == 1


def test_latest_declaration_of_the_day_replaces_the_computed_values() -> None:
    visits = [waiting(paris(DAY, 6))]
    declarations = [
        Declared(paris(DAY, 10, 5), 40, 9, 6, 2),
        Declared(paris(DAY, 11), 41, 10, 7, 3),
    ]

    [point] = daily_series(visits, [], [DAY], PARIS, declarations)

    assert (point.boarding, point.computed_boarding, point.source) == (7, 1, "declaration")
    assert (point.present, point.waiting_bed, point.hosted_elsewhere) == (41, 10, 3)


def test_before_10h_the_count_is_provisional_at_the_given_instant() -> None:
    visits = [waiting(paris(DAY, 6), left=paris(DAY, 9, 30)), waiting(paris(DAY, 7))]

    assert boarding_10h(visits, DAY, PARIS, as_of=paris(DAY, 9)) == 2
    assert boarding_10h(visits, DAY, PARIS) == 1
