"""HTTP contracts (Pydantic v2) of the LISCOP modules.

Each agent appends its own models under its own section only (see docs/liscop/PLAN.md),
so parallel branches merge without conflicts. Reuse ``Strict`` from ``schemas`` for inputs.
"""

from __future__ import annotations

# --- beds-ed ---

# --- movement-ingest ---

MOVEMENT_BATCH_MAX = 500  # items per POST /api/ingest/movements (also splits import blocks)

from datetime import datetime  # noqa: E402
from typing import Literal  # noqa: E402

from pydantic import AwareDatetime, BaseModel, Field  # noqa: E402

from services.admissions_smr.schemas import Strict  # noqa: E402


class MovementIn(Strict):
    """A movement read on a bed-management screen (computer-use agent). Clear identifiers
    are pseudonymised on receipt and never stored; any extra field is refused."""

    source_system: str = Field(min_length=1, max_length=60)
    movement_ref: str = Field(min_length=1, max_length=50)
    event: Literal["A01", "A02", "A03", "A04", "A06", "A21", "A22"]
    action: Literal["INSERT", "CANCEL"] = "INSERT"
    occurred_at: AwareDatetime
    encounter_id: str = Field(min_length=1, max_length=64)
    patient_id: str = Field(min_length=1, max_length=64)
    patient_class: Literal["E", "I", "R", "O", "N"] | None = None
    uf_code: str | None = Field(default=None, max_length=20)
    room: str | None = Field(default=None, max_length=40)
    bed: str | None = Field(default=None, max_length=40)
    facility_finess: str | None = Field(default=None, pattern=r"^\d{2}[0-9AB]\d{6}$")
    sex: Literal["F", "M", "U"] | None = None
    age: int | None = Field(default=None, ge=0, le=130)
    outcome: Literal["hospitalise", "sortie", "transfert", "fugue", "deces"] | None = None


class MovementResultOut(BaseModel):
    movement_ref: str
    status: str  # applied | duplicate | ignored | rejected
    message: str
    movement_id: int | None


class MovementOut(BaseModel):
    """One journal line. ``encounter`` is the start of the pseudonym, to follow a venue."""

    id: int
    received_at: datetime
    occurred_at: datetime
    source_system: str
    movement_ref: str | None
    event: str
    event_label: str
    action: str
    status: str
    error: str | None
    encounter: str
    site_id: int | None
    unit_label: str | None
    bed_label: str | None


class MovementPageOut(BaseModel):
    items: list[MovementOut]
    total: int
    last_24h: dict[str, int]
    rejection_rate_24h: float | None


# --- forecast-engine ---

# --- ror-oru-export ---
