"""Regression tests for the findings of docs/liscop/REVIEW.md (fix-ingest), one per id."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr.domain.pseudonym import keyed_digest, pseudonym
from services.admissions_smr.models import Group, Movement, Stay
from services.admissions_smr.schemas_liscop import MovementIn
from services.admissions_smr.tests.test_api import new_request
from services.admissions_smr.tests.test_hl7_api import HL7, agent_item
from services.admissions_smr.tests.test_hl7_apply import (
    FIXTURES,
    PASSWORD,
    SECRET,
    Apply,
    build_hospital,
    fixture,
    stay_of,
)
from services.admissions_smr.tests.test_hl7_apply import apply as apply  # noqa: F401 - fixture

Login = Callable[[str], dict[str, str]]
MakeGroup = Callable[[str], Group]


@pytest.fixture
def hospital(db: Session) -> Group:
    return build_hospital(db)


def auth(client: TestClient, who: str = "agent") -> dict[str, str]:
    r = client.post("/api/auth/login", json={"email": f"{who}@hl7.test", "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_c3_smr_request_with_an_mco_unit_code_is_refused_not_a_500(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    h = login("coord@g1.fr")

    created = app_client.post(
        "/api/requests", json=new_request(mention_requested="cardiologie"), headers=h
    )

    assert created.status_code == 422


# --- S-H2: identification domain in the pseudonym; one encounter, one patient ------------


def test_s_h2_same_nda_from_two_establishments_are_two_encounters(
    db: Session, hospital: Group, apply: Apply
) -> None:
    first = fixture("a01_admission")
    other_establishment = replace(
        first,
        control_id="MSG-CHB-1",
        movement_ref="CHB-1",
        encounter_domain="CH-B",
        patient_domain="CH-B",
        patient_id="IPP-B-1",
        bed="2102B",
    )

    results = [apply(first), apply(other_establishment)]

    assert [r.status for r in results] == ["applied", "applied"]
    assert db.query(Stay).count() == 2  # not merged into one patient
    assert stay_of(db, hospital, "900001") is not None


def test_s_h2_movement_for_another_patient_of_the_same_encounter_is_refused(
    db: Session, apply: Apply
) -> None:
    apply("a01_admission")

    result = apply(replace(fixture("a02_transfer"), patient_id="IPP-OTHER"))

    assert (result.status, result.ack_code, result.location) == ("rejected", "AE", "PID^1^3")
    assert "IPP-OTHER" not in result.message and "900001" not in result.message
    stay = db.scalars(select(Stay)).one()
    assert stay.mention == "medecine_polyvalente"  # nothing applied


def test_s_h2_without_authority_the_sending_system_is_the_domain(
    db: Session, hospital: Group, apply: Apply
) -> None:
    parsed = replace(fixture("a01_admission"), encounter_domain="", patient_domain="")

    apply(parsed)

    stay = db.scalars(select(Stay)).one()
    expected = pseudonym(SECRET, hospital.id, "nda", "GAM_FICTIF/CHDR_FICTIF", "900001")
    assert stay.encounter_ref == expected


# --- S-H3: keyed digest -------------------------------------------------------------------


def test_s_h3_journal_digest_is_keyed_not_a_plain_sha256(
    app_client: TestClient, db: Session, hospital: Group
) -> None:
    raw = (FIXTURES / "a01_admission.hl7").read_bytes().replace(b"\n", b"\r")
    secret = app_client.app.state.settings.pseudonym_secret  # type: ignore[attr-defined]

    app_client.post("/api/ingest/hl7", content=raw, headers={**HL7, **auth(app_client)})
    app_client.post("/api/ingest/movements", json=[agent_item()], headers=auth(app_client))

    hl7_row, agent_row = db.scalars(select(Movement).order_by(Movement.id)).all()
    assert hl7_row.message_digest == keyed_digest(secret, hospital.id, raw.rstrip(b"\r"))
    assert hl7_row.message_digest != hashlib.sha256(raw).hexdigest()
    plain = json.dumps(
        MovementIn.model_validate(agent_item()).model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    assert agent_row.message_digest != hashlib.sha256(plain.encode()).hexdigest()
    assert len(agent_row.message_digest) == 64
