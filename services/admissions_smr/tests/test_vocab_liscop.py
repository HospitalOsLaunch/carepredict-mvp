from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.admissions_smr.schemas import RequestCreate, StayCreate
from services.admissions_smr.vocab import (
    LISCOP_DISCIPLINES,
    MCO_UNITS,
    MENTIONS,
    UNIT_CODES,
    UNIT_KINDS,
    UNIT_TYPES,
)


def test_unit_codes_cover_smr_mentions_and_mco_units() -> None:
    assert set(UNIT_CODES) == set(MENTIONS) | set(MCO_UNITS)
    assert not set(MENTIONS) & set(MCO_UNITS)


def test_every_mco_unit_has_a_known_type_and_liscop_discipline() -> None:
    assert len(LISCOP_DISCIPLINES) == 7
    assert set(UNIT_KINDS) == set(MCO_UNITS)
    for unit_type, discipline in UNIT_KINDS.values():
        assert unit_type in UNIT_TYPES
        assert discipline in LISCOP_DISCIPLINES
    assert UNIT_KINDS["reanimation"] == ("soins_critiques", "soins_critiques")
    assert UNIT_KINDS["urgences"][0] == "urgences"


def test_stay_accepts_mco_and_smr_codes_and_refuses_unknown_ones() -> None:
    base = {"site_id": 1, "patient_ref": "ABC-1", "admission_date": date(2026, 10, 1)}
    assert StayCreate.model_validate(base | {"mention": "cardiologie"}).mention == "cardiologie"
    assert StayCreate.model_validate(base | {"mention": "geriatrie"}).mention == "geriatrie"
    with pytest.raises(ValidationError, match="mention inconnue"):
        StayCreate.model_validate(base | {"mention": "astrologie"})


def test_request_stays_on_smr_mentions_and_refuses_mco_or_unknown_codes() -> None:
    # REVIEW C-3: an SMR referral with an MCO unit code used to crash site assignment.
    base = {
        "source": "mail",
        "received_at": "2026-10-01T08:00:00Z",
        "referrer_facility": "CH",
        "patient_ref": "ABC-1",
    }
    assert RequestCreate.model_validate(base | {"mention_requested": "geriatrie"})
    for code in ("medecine_polyvalente", "astrologie"):
        with pytest.raises(ValidationError, match="mention inconnue"):
            RequestCreate.model_validate(base | {"mention_requested": code})


def test_vocabulary_endpoint_exposes_liscop_vocabularies(app_client: TestClient) -> None:
    body = app_client.get("/api/vocabulary").json()
    assert body["mentions"] == MENTIONS  # unchanged for existing clients
    assert body["unit_codes"]["reanimation"] == "Réanimation"
    assert body["unit_types"] == UNIT_TYPES
    assert body["liscop_disciplines"]["medico_social"] == "Médico-social (grand âge)"
    assert body["unit_kinds"]["cardiologie"] == ["medecine", "medecine"]
    for key in (
        "bed_statuses",
        "sex_constraints",
        "stay_sources",
        "admission_modes",
        "ed_outcomes",
        "tension_kinds",
    ):
        assert body[key], key
