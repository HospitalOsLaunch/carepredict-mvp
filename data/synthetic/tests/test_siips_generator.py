"""Tests for SIIPS synthetic generator patterns."""

from __future__ import annotations

import statistics

from data.synthetic.siips_generator import DEFAULT_SERVICES, generate_dataset


def test_daily_peak_exceeds_night_mean() -> None:
    dataset = generate_dataset(months=1, services=[DEFAULT_SERVICES[1]], seed=123)
    morning_values = [
        record.siips_score for record in dataset.care_load if 8 <= record.measured_at.hour <= 11
    ]
    night_values = [
        record.siips_score for record in dataset.care_load if 0 <= record.measured_at.hour <= 5
    ]

    assert statistics.mean(morning_values) > statistics.mean(night_values) + 5.0


def test_weekday_siips_exceeds_weekend_siips() -> None:
    dataset = generate_dataset(months=1, services=[DEFAULT_SERVICES[0]], seed=456)
    weekday_values = [
        record.siips_score
        for record in dataset.care_load
        if record.measured_at.weekday() in (0, 1, 2, 3, 4)
    ]
    weekend_values = [
        record.siips_score for record in dataset.care_load if record.measured_at.weekday() in (5, 6)
    ]

    assert statistics.mean(weekday_values) > statistics.mean(weekend_values) + 5.0


def test_default_volume_exceeds_acceptance_thresholds() -> None:
    dataset = generate_dataset(months=24, seed=789)

    assert len(dataset.services) == 5
    assert len(dataset.care_load) >= 80_000
    assert len(dataset.staffing) >= 30_000
    assert len(dataset.admissions) >= 1_000
    assert len(dataset.discharges) >= 950
