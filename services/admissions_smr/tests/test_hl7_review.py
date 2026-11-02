"""Regression tests for the findings of docs/liscop/REVIEW.md (fix-ingest), one per id."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.admissions_smr import movement_service
from services.admissions_smr.domain.pseudonym import keyed_digest, pseudonym
from services.admissions_smr.models import EdVisit, Group, Movement, Stay, User
from services.admissions_smr.movement_service import apply_movement
from services.admissions_smr.schemas_liscop import MovementIn
from services.admissions_smr.tests.test_api import new_request
from services.admissions_smr.tests.test_hl7_api import HL7, agent_item
from services.admissions_smr.tests.test_hl7_apply import (
    FIXTURES,
    NOW,
    PARIS,
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


# --- S-H1: MSH-10 reused with another content; ingestion accounts bound to sources -------


def send_raw(client: TestClient, raw: bytes, who: str = "agent") -> tuple[int, str]:
    r = client.post("/api/ingest/hl7", content=raw, headers={**HL7, **auth(client, who)})
    return r.status_code, r.text


def a01() -> bytes:
    return (FIXTURES / "a01_admission.hl7").read_bytes().replace(b"\n", b"\r")


def test_s_h1_reused_control_id_with_other_content_is_ae_and_journaled(
    app_client: TestClient, db: Session, hospital: Group
) -> None:
    send_raw(app_client, a01())
    other_patient = (FIXTURES / "a04_ed_arrival.hl7").read_bytes().replace(b"\n", b"\r")
    reused = other_patient.replace(b"|MSG-A04|", b"|MSG-A01|")

    code, ack = send_raw(app_client, reused)
    again, _ = send_raw(app_client, reused)

    assert code == 422 and "MSA|AE|MSG-A01" in ack
    assert "MSH-10 réutilisé avec un contenu différent" in ack and "ERR||MSH^1^10|" in ack
    assert again == 422
    rows = db.scalars(select(Movement).order_by(Movement.id)).all()
    assert [r.status for r in rows] == ["applied", "rejected"]  # one line per conflict
    assert db.query(EdVisit).count() == 0  # the A04 was not silently dropped as "déjà reçu"
    assert send_raw(app_client, a01())[1].count("déjà reçu") == 1  # same bytes: AA duplicate


def test_s_h1_agent_movement_resent_with_other_content_is_rejected(
    app_client: TestClient, db: Session, hospital: Group
) -> None:
    h = auth(app_client)
    app_client.post("/api/ingest/movements", json=[agent_item()], headers=h)

    same = app_client.post("/api/ingest/movements", json=[agent_item(age=65)], headers=h)
    moved = app_client.post("/api/ingest/movements", json=[agent_item(bed="2102A")], headers=h)

    assert same.json()[0]["status"] == "duplicate"  # the age shown depends on the day
    assert moved.json()[0]["status"] == "rejected"
    assert "contenu différent" in moved.json()[0]["message"]


def test_s_h1_ingestion_account_is_bound_to_its_sending_systems(
    app_client: TestClient, db: Session, hospital: Group
) -> None:
    agent = db.scalars(select(User).where(User.email == "agent@hl7.test")).one()
    agent.allowed_sources = json.dumps(["demo_bedsoft"])
    db.commit()

    code, ack = send_raw(app_client, a01())  # source GAM_FICTIF/CHDR_FICTIF
    agent_path = app_client.post(
        "/api/ingest/movements", json=[agent_item()], headers=auth(app_client)
    )

    assert code == 403 and "MSA|AR|MSG-A01" in ack and "non autorisé" in ack
    assert db.query(Movement).count() == 1  # only the allowed agent movement
    assert agent_path.json()[0]["status"] == "applied"
    agent.allowed_sources = json.dumps(["GAM_FICTIF/CHDR_FICTIF"])
    db.commit()
    assert send_raw(app_client, a01())[0] == 200


# --- T-17: two requests with the same control id --------------------------------------------


def test_t17_unique_violation_race_answers_duplicate(
    db: Session, hospital: Group, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed = replace(fixture("a01_admission"), digest="d" * 64)
    apply_movement(db, hospital, parsed, NOW, secret=SECRET, zone=PARIS)
    db.commit()
    # The other request committed after this one looked the control id up.
    real = movement_service._by_control_id
    calls: list[int] = []

    def late(*args: object) -> Movement | None:
        calls.append(1)
        return None if len(calls) == 1 else real(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(movement_service, "_by_control_id", late)

    result = apply_movement(db, hospital, parsed, NOW, secret=SECRET, zone=PARIS)
    db.commit()

    assert (result.status, result.ack_code) == ("duplicate", "AA")
    assert db.query(Movement).count() == 1 and db.query(Stay).count() == 1


@pytest.mark.skipif(not os.getenv("ADM_TEST_DATABASE_URL"), reason="two writers need PostgreSQL")
def test_t17_two_threads_post_the_same_message_on_postgresql(
    app_client: TestClient, db: Session, hospital: Group
) -> None:
    headers = {**HL7, **auth(app_client)}
    barrier = threading.Barrier(4)
    answers: list[str] = []

    def post() -> None:
        client = TestClient(app_client.app)
        barrier.wait()
        answers.append(client.post("/api/ingest/hl7", content=a01(), headers=headers).text)

    threads = [threading.Thread(target=post) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all("MSA|AA|MSG-A01" in a for a in answers), answers
    assert sum("déjà reçu" in a for a in answers) == 3
    assert db.query(Movement).count() == 1 and db.query(Stay).count() == 1
