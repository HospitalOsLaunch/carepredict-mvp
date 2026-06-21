"""Canonical action-channel order for the trained RSSM world model.

The ``rssm-synthetic-v1`` checkpoint was trained with this exact order. Serving
must adapt API field names to this vector layout; the checkpoint is not
retrained when API-facing action names evolve.
"""

from __future__ import annotations

from typing import Final, Literal

ActionChannel = Literal["admissions", "discharges", "surgeries", "transfers_in", "transfers_out"]

ACTION_CHANNELS: Final[tuple[ActionChannel, ...]] = (
    "admissions",
    "discharges",
    "surgeries",
    "transfers_in",
    "transfers_out",
)
ACTION_CHANNEL_INDEX: Final[dict[ActionChannel, int]] = {
    channel: index for index, channel in enumerate(ACTION_CHANNELS)
}

# Reserved for the planned staffing-aware retrain. Until that model exists,
# staffing actions are accepted at the API boundary only as ignored metadata and
# must never occupy a trained RSSM vector position.
RESERVED_FUTURE_CHANNELS: Final[tuple[str, ...]] = ("staff_redeployments",)
