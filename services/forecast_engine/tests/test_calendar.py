"""French public holidays and zone B school holidays."""

from __future__ import annotations

from datetime import date

from services.forecast_engine.calendar import (
    SCHOOL_HOLIDAYS_ZONE_B,
    day_kinds,
    is_school_holiday,
    public_holidays,
)


def test_public_holidays_are_the_french_ones() -> None:
    days = public_holidays([2026])

    assert days[date(2026, 7, 14)] == "Fête nationale"
    assert date(2026, 5, 25) in days  # lundi de Pentecôte
    assert date(2026, 12, 26) not in days  # Alsace-Moselle only


def test_school_holidays_end_the_day_before_classes_resume() -> None:
    assert is_school_holiday(date(2026, 1, 4)) is True
    assert is_school_holiday(date(2026, 1, 5)) is False


def test_school_holidays_are_unknown_outside_the_table() -> None:
    assert is_school_holiday(date(2024, 12, 25)) is None


def test_school_table_is_ordered_and_disjoint() -> None:
    for (_, end, _), (start, _, _) in zip(
        SCHOOL_HOLIDAYS_ZONE_B, SCHOOL_HOLIDAYS_ZONE_B[1:], strict=False
    ):
        assert end <= start
    assert all(s.weekday() in (2, 5) for s, _, _ in SCHOOL_HOLIDAYS_ZONE_B)  # Wed or Sat
    term_breaks = [e for _, e, label in SCHOOL_HOLIDAYS_ZONE_B if "été" not in label]
    assert all(e.weekday() == 0 for e in term_breaks)  # classes resume on a Monday


def test_day_kinds_label_each_day() -> None:
    kinds = day_kinds(date(2026, 11, 1), date(2026, 11, 3))

    assert kinds == {
        date(2026, 11, 1): "ferie",
        date(2026, 11, 2): "ordinaire",
        date(2026, 11, 3): "ordinaire",
    }
