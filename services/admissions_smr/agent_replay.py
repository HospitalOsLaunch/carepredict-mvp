"""Agent player storage rules: retention purge and the identifiers a step may not carry.

Steps are masked on the worker before capture (docs/agent/PLAYER_SPEC.md). The API adds a
defence in depth on the text it receives: a label or target that looks like a NIR or a
full date (a birth date cannot be told apart from another date) is refused.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from services.admissions_smr.models import AgentTaskStep

PURGE_EVERY = timedelta(hours=1)

# NIR (13 digits + optional 2-digit key, spaces allowed, Corsica 2A/2B), unanchored version
# of domain.imports._NIR_LIKE; any long run of digits; full dates (d/m/y, y-m-d...).
_FORBIDDEN = (
    re.compile(
        r"(?<![0-9A-Za-z])[12]\s?\d{2}\s?\d{2}\s?(?:\d{2}|2A|2B)\s?\d{3}\s?\d{3}(?:\s?\d{2})?"
        r"(?![0-9A-Za-z])",
        re.I,
    ),
    re.compile(r"\d{13,}"),
    re.compile(r"(?<!\d)\d{1,2}\s?[/.-]\s?\d{1,2}\s?[/.-]\s?(?:19|20)\d{2}(?!\d)"),
    re.compile(r"(?<!\d)(?:19|20)\d{2}\s?[/.-]\s?\d{1,2}\s?[/.-]\s?\d{1,2}(?!\d)"),
)


def forbidden_text(value: str | None) -> bool:
    """True when the text looks like a NIR or a full date."""
    return bool(value) and any(p.search(value or "") for p in _FORBIDDEN)


def purge_steps(session: Session, now: datetime, days: int, group_id: int | None = None) -> int:
    """Delete the steps (and their frames) older than the retention. Caller commits."""
    query = delete(AgentTaskStep).where(AgentTaskStep.created_at < now - timedelta(days=days))
    if group_id is not None:
        query = query.where(AgentTaskStep.group_id == group_id)
    return int(session.execute(query).rowcount or 0)  # type: ignore[attr-defined]


def purge_due(done: dict[int, datetime], group_id: int, now: datetime) -> bool:
    """At most one heartbeat purge per group and per hour (``done``: per API process)."""
    last = done.get(group_id)
    if last is not None and now - last < PURGE_EVERY:
        return False
    done[group_id] = now
    return True
