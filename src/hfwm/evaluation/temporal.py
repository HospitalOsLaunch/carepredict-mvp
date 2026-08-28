"""Point-in-time guards for evaluation features and actions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

FeatureRole = Literal["observation", "action", "context", "target"]


@dataclass(frozen=True)
class PointInTimeValue:
    """Identity and clocks of one candidate model input."""

    record_id: str
    event_time: datetime
    available_at: datetime
    role: FeatureRole

    def __post_init__(self) -> None:
        if not self.record_id:
            raise ValueError("record_id must not be empty")
        if self.event_time.tzinfo is None or self.available_at.tzinfo is None:
            raise ValueError("point-in-time clocks must be timezone-aware")


def validate_snapshot_inputs(
    values: Iterable[PointInTimeValue], *, origin_at: datetime
) -> list[str]:
    """Return fail-closed future observation/action/target leakage findings."""
    if origin_at.tzinfo is None:
        raise ValueError("origin_at must be timezone-aware")
    errors: list[str] = []
    seen_ids: set[str] = set()
    for value in sorted(values, key=lambda item: item.record_id):
        if value.record_id in seen_ids:
            errors.append(f"duplicate_record_id:{value.record_id}")
        seen_ids.add(value.record_id)
        if value.available_at > origin_at:
            errors.append(f"future_observation_leakage:{value.record_id}")
        if value.role == "target":
            errors.append(f"target_in_features:{value.record_id}")
        if value.role == "action" and value.event_time > origin_at:
            errors.append(f"future_action_leakage:{value.record_id}")
    return sorted(set(errors))
