"""Planned intervention schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


InterventionType = Literal[
    "discharge",
    "surgery",
    "transfer_in",
    "transfer_out",
    "admission",
    "procedure",
    "staff_redeployment",
]


class PlannedIntervention(BaseModel):
    """Known future intervention supplied by the dashboard/API caller."""

    model_config = ConfigDict(extra="forbid")

    type: InterventionType
    scheduled_at: datetime
    count: int = Field(ge=0)
