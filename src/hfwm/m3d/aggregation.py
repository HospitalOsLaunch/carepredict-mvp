"""Executable Tier-A census aggregation contract for synthetic conformance tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

EVENT_DELTAS = {
    "external_entry": 1,
    "internal_inbound_transfer": 1,
    "external_exit": -1,
    "internal_outbound_transfer": -1,
}

ROW_ABSENCE_REASONS = frozenset(
    {
        "DISCLOSURE_SUPPRESSED",
        "SOURCE_OUTAGE",
        "UNIT_CLOSED",
        "NOT_APPLICABLE",
    }
)


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    values = tuple(row.get(field) for field in ("hospital_site_id", "unit_id", "bucket_start"))
    if not all(isinstance(value, str) and value for value in values):
        raise ValueError("each row requires site, unit and bucket_start identifiers")
    return values  # type: ignore[return-value]


def apply_whole_row_disclosure_mask(
    rows: Sequence[Mapping[str, Any]],
    *,
    absence_by_row: Mapping[tuple[str, str, str], str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, int | float]]:
    """Suppress complete Tier-A rows and expose only non-sensitive metadata.

    A suppressed row is removed as a whole, never partially masked. Its identity and
    absence reason are retained solely to create an explicit analytical gap.
    """
    unknown_reasons = set(absence_by_row.values()) - ROW_ABSENCE_REASONS
    if unknown_reasons:
        raise ValueError(f"unsupported row_absence_reason: {sorted(unknown_reasons)}")
    expected = len(rows)
    released: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    counts: dict[str, int | float] = {
        "expected_rows": expected,
        "released_rows": 0,
        "disclosure_suppressed_rows": 0,
        "source_outage_rows": 0,
        "unit_closed_rows": 0,
        "not_applicable_rows": 0,
    }
    seen: set[tuple[str, str, str]] = set()
    for source_row in rows:
        key = _row_key(source_row)
        if key in seen:
            raise ValueError("duplicate site/unit/time row")
        seen.add(key)
        embedded_reason = source_row.get("row_absence_reason")
        if embedded_reason is not None and embedded_reason not in ROW_ABSENCE_REASONS:
            raise ValueError(f"unsupported row_absence_reason: {embedded_reason}")
        mapped_reason = absence_by_row.get(key)
        if (
            embedded_reason is not None
            and mapped_reason is not None
            and embedded_reason != mapped_reason
        ):
            raise ValueError(f"conflicting row_absence_reason for {key}")
        # A source row carrying an absence reason is already an explicit gap;
        # an empty side map must not silently release its stock/flow values.
        reason = mapped_reason if mapped_reason is not None else embedded_reason
        if reason is not None:
            gaps.append(
                {
                    "hospital_site_id": key[0],
                    "unit_id": key[1],
                    "bucket_start": key[2],
                    "row_absence_reason": reason,
                }
            )
            counts[f"{reason.lower()}_rows"] += 1
            continue
        item = dict(source_row)
        item.setdefault("row_absence_reason", None)
        released.append(item)
        counts["released_rows"] += 1
    counts["disclosure_suppression_rate"] = (
        counts["disclosure_suppressed_rows"] / expected if expected else 0.0
    )
    return released, gaps, counts


def apply_disclosure_eligibility_mask(
    episodes: Sequence[Mapping[str, Any]],
    *,
    gap_keys: set[tuple[str, str, str]],
) -> list[dict[str, Any]]:
    """Invalidate episodes touching an explicit disclosure gap before scoring."""
    masked: list[dict[str, Any]] = []
    for episode in episodes:
        intervals = episode.get("required_intervals")
        if not isinstance(intervals, list) or not intervals:
            item = dict(episode)
            item["eligible"] = False
            item["ineligibility_reason"] = "MISSING_REQUIRED_INTERVALS"
            masked.append(item)
            continue
        normalized = {_row_key(interval) for interval in intervals if isinstance(interval, Mapping)}
        if len(normalized) != len(intervals):
            raise ValueError("episode intervals must contain complete row keys")
        item = dict(episode)
        direct_gap = bool(normalized & gap_keys)
        # Require the declared interval sequence to cover the full span.  If an
        # episode lists endpoints but omits a suppressed interval between them,
        # conservatively invalidate it rather than allowing a silent bridge.
        parsed_intervals = [_instant(key[2], field="episode.bucket_start") for key in normalized]
        span_start = min(parsed_intervals)
        span_end = max(parsed_intervals)
        bridged_gap = any(
            gap_key not in normalized
            and gap_key[0] == key[0]
            and gap_key[1] == key[1]
            and span_start <= _instant(gap_key[2], field="gap.bucket_start") <= span_end
            for key in normalized
            for gap_key in gap_keys
        )
        if direct_gap or bridged_gap:
            item["eligible"] = False
            item["ineligibility_reason"] = "DISCLOSURE_SUPPRESSED_INTERVAL"
        else:
            item["eligible"] = True
            item["ineligibility_reason"] = None
        masked.append(item)
    return masked


def _instant(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _signed_delta(event: Mapping[str, Any]) -> int:
    event_type = event.get("event_type")
    if event_type == "other_signed_census_adjustment":
        value = event.get("signed_delta")
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("signed adjustment requires an integer signed_delta")
        return value
    if not isinstance(event_type, str) or event_type not in EVENT_DELTAS:
        raise ValueError(f"unsupported event_type: {event_type}")
    return EVENT_DELTAS[event_type]


def aggregate_census_intervals(
    *,
    initial_census_count: int,
    interval_start: str,
    bucket_hours: int,
    bucket_count: int,
    events: Sequence[Mapping[str, Any]],
    as_of: str,
) -> list[dict[str, object]]:
    """Aggregate effective movements into half-open UTC buckets.

    Corrections are included only when ``available_at <= as_of``. The returned census
    is an integer stock; occupancy rate is intentionally not derived here because open
    beds are a separately versioned denominator.
    """
    if isinstance(initial_census_count, bool) or initial_census_count < 0:
        raise ValueError("initial_census_count must be a non-negative integer")
    if bucket_hours <= 0 or bucket_count <= 0:
        raise ValueError("positive bucket_hours and bucket_count are required")
    start = _instant(interval_start, field="interval_start")
    cutoff = _instant(as_of, field="as_of")
    seen_ids: set[str] = set()
    prepared: list[tuple[datetime, str, int]] = []
    for event in events:
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id or event_id in seen_ids:
            raise ValueError("event_id must be non-empty and unique")
        seen_ids.add(event_id)
        available_at = _instant(event.get("available_at"), field="available_at")
        if available_at > cutoff:
            continue
        event_time = _instant(event.get("event_time"), field="event_time")
        prepared.append((event_time, event_id, _signed_delta(event)))
    prepared.sort(key=lambda item: (item[0], item[1]))

    rows: list[dict[str, object]] = []
    census = initial_census_count
    cursor = 0
    for bucket_index in range(bucket_count):
        bucket_start = start + timedelta(hours=bucket_index * bucket_hours)
        bucket_end = bucket_start + timedelta(hours=bucket_hours)
        census_start = census
        applied: list[str] = []
        while cursor < len(prepared) and prepared[cursor][0] < bucket_end:
            event_time, event_id, delta = prepared[cursor]
            if event_time >= bucket_start:
                census += delta
                if census < 0:
                    raise ValueError("aggregation produced a negative census")
                applied.append(event_id)
            cursor += 1
        rows.append(
            {
                "bucket_start": bucket_start.isoformat().replace("+00:00", "Z"),
                "bucket_end": bucket_end.isoformat().replace("+00:00", "Z"),
                "patient_census_count_start": census_start,
                "patient_census_count_end": census,
                "applied_event_ids": applied,
            }
        )
    return rows
