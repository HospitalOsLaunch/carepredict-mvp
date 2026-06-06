"""Tests for SIIPS synthetic generator patterns."""

from __future__ import annotations

import statistics

from data.synthetic.siips_generator import DEFAULT_SERVICES, generate_dataset


def test_daily_peak_exceeds_night_mean() -> None:
    dataset = generate_dataset(months=1, services=[DEFAULT_SERVICES[1]], seed=123)
    morning_values = [
        record.siips_score
        for record in dataset.care_load
        if 8 <= record.measured_at.hour <= 11
    ]
    night_values = [
        record.siips_score
        for record in dataset.care_load
        if 0 <= record.measured_at.hour <= 5
    ]

    assert statistics.mean(morning_values) > statistics.mean(night_values) + 5.0


def test_monday_tuesday_weekly_cycle_is_detectable() -> None:
    dataset = generate_dataset(months=1, services=[DEFAULT_SERVICES[2]], seed=456)
    monday_tuesday = [
        record.siips_score
        for record in dataset.care_load
        if record.measured_at.weekday() in (0, 1)
    ]
    other_weekdays = [
        record.siips_score
        for record in dataset.care_load
        if record.measured_at.weekday() in (2, 3, 4)
    ]

    assert statistics.mean(monday_tuesday) > statistics.mean(other_weekdays) + 1.0


def test_default_volume_exceeds_acceptance_thresholds() -> None:
    dataset = generate_dataset(months=24, seed=789)

    assert len(dataset.services) == 5
    assert len(dataset.care_load) >= 80_000
    assert len(dataset.staffing) >= 30_000
    assert len(dataset.admissions) >= 1_000
    assert len(dataset.discharges) >= 950
