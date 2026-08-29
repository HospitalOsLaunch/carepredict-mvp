"""Conformance tests for the executable six-hour Tier-A aggregation spec."""

from __future__ import annotations

import pytest

from hfwm.m3d.aggregation import (
    aggregate_census_intervals,
    apply_disclosure_eligibility_mask,
    apply_whole_row_disclosure_mask,
)


def test_six_hour_aggregation_is_half_open_and_filters_future_correction() -> None:
    events = [
        {
            "event_id": "admission-1",
            "event_time": "2026-01-01T01:00:00Z",
            "available_at": "2026-01-01T01:05:00Z",
            "event_type": "external_entry",
        },
        {
            "event_id": "transfer-out-1",
            "event_time": "2026-01-01T06:00:00Z",
            "available_at": "2026-01-01T06:02:00Z",
            "event_type": "internal_outbound_transfer",
        },
        {
            "event_id": "future-correction",
            "event_time": "2026-01-01T05:00:00Z",
            "available_at": "2026-01-03T00:00:00Z",
            "event_type": "other_signed_census_adjustment",
            "signed_delta": -1,
        },
    ]
    rows = aggregate_census_intervals(
        initial_census_count=10,
        interval_start="2026-01-01T00:00:00Z",
        bucket_hours=6,
        bucket_count=2,
        events=events,
        as_of="2026-01-01T12:00:00Z",
    )
    assert rows == [
        {
            "bucket_start": "2026-01-01T00:00:00Z",
            "bucket_end": "2026-01-01T06:00:00Z",
            "patient_census_count_start": 10,
            "patient_census_count_end": 11,
            "applied_event_ids": ["admission-1"],
        },
        {
            "bucket_start": "2026-01-01T06:00:00Z",
            "bucket_end": "2026-01-01T12:00:00Z",
            "patient_census_count_start": 11,
            "patient_census_count_end": 10,
            "applied_event_ids": ["transfer-out-1"],
        },
    ]


def test_same_inputs_produce_same_aggregate() -> None:
    arguments = {
        "initial_census_count": 4,
        "interval_start": "2026-01-01T00:00:00Z",
        "bucket_hours": 6,
        "bucket_count": 1,
        "events": [
            {
                "event_id": "birth-1",
                "event_time": "2026-01-01T00:30:00Z",
                "available_at": "2026-01-01T00:31:00Z",
                "event_type": "external_entry",
            }
        ],
        "as_of": "2026-01-01T06:00:00Z",
    }
    assert aggregate_census_intervals(**arguments) == aggregate_census_intervals(**arguments)


def test_disclosure_suppresses_the_whole_row_and_reports_reason() -> None:
    rows = [
        {
            "hospital_site_id": "s1",
            "unit_id": "u1",
            "bucket_start": "2026-01-01T00:00:00Z",
            "patient_census_count_end": 12,
            "external_entries_count": 2,
        },
        {
            "hospital_site_id": "s1",
            "unit_id": "u1",
            "bucket_start": "2026-01-01T06:00:00Z",
            "patient_census_count_end": 13,
            "external_entries_count": 1,
        },
    ]
    released, gaps, counts = apply_whole_row_disclosure_mask(
        rows,
        absence_by_row={("s1", "u1", "2026-01-01T06:00:00Z"): "DISCLOSURE_SUPPRESSED"},
    )
    assert released == [{**rows[0], "row_absence_reason": None}]
    assert gaps == [
        {
            "hospital_site_id": "s1",
            "unit_id": "u1",
            "bucket_start": "2026-01-01T06:00:00Z",
            "row_absence_reason": "DISCLOSURE_SUPPRESSED",
        }
    ]
    assert counts["disclosure_suppressed_rows"] == 1
    assert counts["disclosure_suppression_rate"] == 0.5


def test_disclosure_rejects_partial_or_unknown_suppression_and_creates_gap() -> None:
    row = {
        "hospital_site_id": "s1",
        "unit_id": "u1",
        "bucket_start": "2026-01-01T00:00:00Z",
        "patient_census_count_end": 12,
    }
    with pytest.raises(ValueError, match="unsupported row_absence_reason"):
        apply_whole_row_disclosure_mask(
            [row],
            absence_by_row={("s1", "u1", "2026-01-01T00:00:00Z"): "PARTIAL_FIELD"},
        )
    episodes = [
        {
            "episode_id": "e1",
            "required_intervals": [row],
        },
        {
            "episode_id": "e2",
            "required_intervals": [
                {
                    "hospital_site_id": "s1",
                    "unit_id": "u1",
                    "bucket_start": "2026-01-01T06:00:00Z",
                }
            ],
        },
    ]
    masked = apply_disclosure_eligibility_mask(
        episodes,
        gap_keys={("s1", "u1", "2026-01-01T00:00:00Z")},
    )
    assert masked[0]["eligible"] is False
    assert masked[0]["ineligibility_reason"] == "DISCLOSURE_SUPPRESSED_INTERVAL"
    assert masked[1]["eligible"] is True


def test_disclosure_metadata_has_all_absence_categories() -> None:
    rows = [
        {
            "hospital_site_id": "s1",
            "unit_id": "u1",
            "bucket_start": f"2026-01-01T{index * 6:02d}:00:00Z",
        }
        for index in range(4)
    ]
    reasons = {
        ("s1", "u1", "2026-01-01T00:00:00Z"): "DISCLOSURE_SUPPRESSED",
        ("s1", "u1", "2026-01-01T06:00:00Z"): "SOURCE_OUTAGE",
        ("s1", "u1", "2026-01-01T12:00:00Z"): "UNIT_CLOSED",
        ("s1", "u1", "2026-01-01T18:00:00Z"): "NOT_APPLICABLE",
    }
    released, gaps, counts = apply_whole_row_disclosure_mask(rows, absence_by_row=reasons)
    assert released == []
    assert len(gaps) == 4
    assert counts == {
        "expected_rows": 4,
        "released_rows": 0,
        "disclosure_suppressed_rows": 1,
        "source_outage_rows": 1,
        "unit_closed_rows": 1,
        "not_applicable_rows": 1,
        "disclosure_suppression_rate": 0.25,
    }
