"""Action Engine decision workflow state machine."""

from __future__ import annotations

from services.api.schemas.actions import ActionStatus

LEGAL_TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    "proposed": frozenset({"approved", "dismissed"}),
    "approved": frozenset({"in_progress", "dismissed"}),
    "in_progress": frozenset({"done", "dismissed"}),
    "done": frozenset(),
    "dismissed": frozenset(),
}


class InvalidActionTransition(ValueError):
    """Raised when an action status transition is not legal."""


def validate_transition(from_status: ActionStatus, to_status: ActionStatus) -> bool:
    """Validate one Action Engine status transition."""
    if to_status in LEGAL_TRANSITIONS[from_status]:
        return True
    allowed = ", ".join(sorted(LEGAL_TRANSITIONS[from_status])) or "none"
    raise InvalidActionTransition(
        f"illegal action transition {from_status!r} -> {to_status!r}; allowed: {allowed}"
    )
