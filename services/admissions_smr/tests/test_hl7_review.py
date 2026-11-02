"""Regression tests for the findings of docs/liscop/REVIEW.md (fix-ingest), one per id."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.admissions_smr import movement_service
from services.admissions_smr.api import deps, routes_hl7
from services.admissions_smr.domain.hl7_pam import Hl7Error, parse, parse_ts
from services.admissions_smr.domain.pseudonym import keyed_digest, pseudonym
from services.admissions_smr.models import (
    Bed,
    BedPool,
    EdVisit,
    Group,
    Movement,
    Site,
    Stay,
    User,
)
from services.admissions_smr.movement_service import apply_movement
from services.admissions_smr.schemas_liscop import MovementIn
from services.admissions_smr.tests.test_api import new_request
from services.admissions_smr.tests.test_hl7_api import HL7, agent_item
from services.admissions_smr.tests.test_hl7_apply import (
    FIXTURES,
    NOW,
    PARIS,
    PASSWORD,
    RECEIVED,
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


# --- S-M1 / T-16 / T-15: timestamps, control characters, date window ------------------------


def a01_with(old: bytes, new: bytes) -> bytes:
    raw = a01()
    assert old in raw
    return raw.replace(old, new)


@pytest.mark.parametrize(
    "stamp",
    [b"20261025090000+9999", b"00001025090000", b"99991231235959-1400", b"20261025090000+2400"],
)
def test_s_m1_extreme_timestamps_are_ae_102_not_a_crash(stamp: bytes) -> None:
    with pytest.raises(Hl7Error) as caught:
        parse(a01_with(b"|20261025090000||INSERT", b"|" + stamp + b"||INSERT"), PARIS)
    assert (caught.value.ack_code, caught.value.hl7_code) == ("AE", 102)
    assert caught.value.location == "ZBE^1^2" and stamp.decode() not in caught.value.message


@pytest.mark.parametrize("char", [b"\x00", b"\x01", b"\x1b", b"\t"])
def test_s_m1_control_characters_are_refused_with_an_ack(
    app_client: TestClient, db: Session, hospital: Group, char: bytes
) -> None:
    code, ack = send_raw(app_client, a01_with(b"DUPONTEL", b"DUPON" + char + b"TEL"))

    assert code == 400 and "MSA|AR|" in ack and "contrôle" in ack
    assert db.query(Movement).count() == 0


def test_t15_nonexistent_spring_forward_hour_reads_with_the_winter_offset() -> None:
    # 29 March 2026, 02:30 does not exist in Paris: read as 01:30 UTC (03:30 summer time).
    # (PEP 495: compare in UTC, inter-zone == is always False for times in a gap or fold.)
    spring, autumn = parse_ts("20260329023000", PARIS), parse_ts("20261025023000", PARIS)
    assert spring is not None and autumn is not None
    assert spring.astimezone(UTC) == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    assert autumn.astimezone(UTC) == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)  # first 02:30


@pytest.mark.parametrize(
    ("delta", "status"),
    [
        (timedelta(days=-401), "rejected"),
        (timedelta(days=-399), "applied"),
        (timedelta(hours=23), "applied"),
        (timedelta(days=2), "rejected"),  # T-16: a movement dated in the future
    ],
)
def test_s_m1_t16_movement_date_window(
    db: Session, hospital: Group, delta: timedelta, status: str
) -> None:
    parsed = replace(fixture("a01_admission"), occurred_at=NOW + delta)

    result = apply_movement(db, hospital, parsed, NOW, secret=SECRET, zone=PARIS)

    assert result.status == status
    if status == "rejected":
        assert result.ack_code == "AE" and "plage" in result.message
        assert db.scalars(select(Movement)).one().occurred_at == NOW  # never the odd date
        assert db.query(Stay).count() == 0


def test_s_m1_window_is_a_setting(db: Session, hospital: Group) -> None:
    parsed = replace(fixture("a01_admission"), occurred_at=NOW + timedelta(hours=2))

    result = apply_movement(
        db, hospital, parsed, NOW, secret=SECRET, zone=PARIS, max_future=timedelta(hours=1)
    )

    assert result.status == "rejected"


# --- S-L1: no raw sender value echoed in ACK or journal --------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "leak"),
    [
        (b"ADT^A01^ADT_A01", b"ADT^A01^ADT_A01".replace(b"ADT^", b"MME DUPONT^"), "MME DUPONT"),
        (b"||INSERT|N|", b"||INSERT MME DUPONT|N|", "MME DUPONT"),
        (b"PV1||I|2101^", b"PV1||I|MME DUPONT 2101^", "MME DUPONT"),
        (b"^2102A^", b"^Mme Dupont lit A^", "Mme Dupont"),
    ],
)
def test_s_l1_ack_and_journal_never_echo_raw_values(
    app_client: TestClient, db: Session, hospital: Group, old: bytes, new: bytes, leak: str
) -> None:
    code, ack = send_raw(app_client, a01_with(old, new))

    journal = " ".join(str(m.error) for m in db.scalars(select(Movement)))
    assert leak not in ack and leak not in journal
    assert leak.upper().replace(" ", "") not in ack.replace("\\S\\", "")


# --- C-7: item-by-item validation of the agent's batch ---------------------------------------


def test_c7_one_invalid_line_does_not_block_the_batch(
    app_client: TestClient, db: Session, hospital: Group
) -> None:
    batch = [
        agent_item(),
        agent_item(movement_ref="BS-2", event="A99", occurred_at="le 25/10 Mme Durand"),
        "pas un objet",
        agent_item(movement_ref="BS-3", encounter_id="NDA-3", patient_id="IPP-3", bed="2102A"),
    ]

    r = app_client.post("/api/ingest/movements", json=batch, headers=auth(app_client))

    assert r.status_code == 200
    results = r.json()
    assert [x["status"] for x in results] == ["applied", "rejected", "rejected", "applied"]
    assert results[1]["movement_ref"] == "BS-2"
    assert "event" in results[1]["message"] and "occurred_at" in results[1]["message"]
    assert "Durand" not in r.text and "A99" not in r.text  # S-M2: never the value
    assert db.query(Stay).count() == 2


# --- S-L5: HL7 parsed before the tenant write lock ------------------------------------------


def test_s_l5_message_is_parsed_before_the_write_lock(
    app_client: TestClient, hospital: Group, monkeypatch: pytest.MonkeyPatch
) -> None:
    order: list[str] = []
    real_parse, real_auth = parse, deps._authenticate

    def parse_spy(*args: Any, **kwargs: Any) -> Any:
        order.append("parse")
        return real_parse(*args, **kwargs)

    def auth_spy(*args: Any, **kwargs: Any) -> Any:
        order.append("lock+auth")  # the write lock is taken right before authentication
        return real_auth(*args, **kwargs)

    headers = {**HL7, **auth(app_client)}
    monkeypatch.setattr(routes_hl7, "parse", parse_spy)
    monkeypatch.setattr(deps, "_authenticate", auth_spy)

    app_client.post("/api/ingest/hl7", content=a01(), headers=headers)

    assert order == ["parse", "lock+auth"]


# --- S-M2: validation errors never echo the input -------------------------------------------


def test_s_m2_validation_errors_carry_no_input_on_any_route(
    app_client: TestClient, make_group: MakeGroup, login: Login
) -> None:
    make_group("g1")
    body = new_request(patient_ref="Mme Jeanne Durand", special_needs=["Mme Durand"])

    r = app_client.post("/api/requests", json=body, headers=login("coord@g1.fr"))

    assert r.status_code == 422
    assert "Durand" not in r.text
    for error in r.json()["detail"]:
        assert set(error) <= {"loc", "msg", "type"} and error["loc"]


def test_s_h1_mco_demo_ingestion_account_is_bound_to_the_demo_senders() -> None:
    from services.admissions_agent.demo_bedsoft.app import sample
    from services.admissions_smr.seed_mco import INGESTION_SOURCES
    from tools.his_simulator import Simulator

    fixture_source = parse(a01(), PARIS).source_system  # tools/demo_check.py sends a fixture
    simulator_source = parse(next(Simulator().messages()).encode(), PARIS).source_system
    assert sample()  # the fictional bed software, read by the agent as "demo_bedsoft"
    assert {fixture_source, simulator_source, "demo_bedsoft"} == set(INGESTION_SOURCES)


# --- C-2: same-day readmission; manual stays keep their guarantee ---------------------------


def test_c2_same_day_readmission_is_a_second_stay(
    db: Session, hospital: Group, apply: Apply
) -> None:
    apply("a01_admission")
    apply(replace(fixture("a03_discharge"), occurred_at=datetime(2026, 10, 25, 11, tzinfo=PARIS)))
    back = replace(
        fixture("a01_admission"),
        control_id="MSG-A01-R",
        movement_ref="MVT-R",
        encounter_id="900099",
        occurred_at=datetime(2026, 10, 25, 18, tzinfo=PARIS),
    )

    result = apply(back)

    assert result.status == "applied", result.message
    assert db.query(Stay).count() == 2  # same patient, site and day, two encounters


def test_c2_manual_stays_still_unique_per_patient_site_and_day(
    db: Session, hospital: Group
) -> None:
    site = db.scalars(select(Site)).first()
    assert site is not None
    for _ in range(2):
        db.add(
            Stay(group_id=hospital.id, site_id=site.id, mention="polyvalent",
                 patient_ref="P-1", admission_date=NOW.date(), created_at=NOW, updated_at=NOW)
        )  # fmt: skip
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --- C-1: "hébergés", the decision's target unit is kept ------------------------------------


def test_c1_admission_elsewhere_keeps_the_decision_target_unit(
    db: Session, hospital: Group, apply: Apply
) -> None:
    cardio = db.scalars(select(BedPool).where(BedPool.uf_code == "2301")).one()
    apply("a04_ed_arrival")
    apply("a02_ed_decision")  # decision: cardiology

    apply(replace(fixture("a06_ed_to_ward"), uf_code="2101", room="2102", bed="2102B"))

    visit = db.scalars(select(EdVisit)).one()
    stay = db.scalars(select(Stay)).one()
    assert stay.mention == "medecine_polyvalente"  # hosted in medicine
    assert visit.target_pool_id == cardio.id  # still waiting for a cardiology bed


def test_c1_without_decision_the_admission_unit_is_the_target(
    db: Session, hospital: Group, apply: Apply
) -> None:
    apply("a04_ed_arrival")
    apply("a06_ed_to_ward")
    cardio = db.scalars(select(BedPool).where(BedPool.uf_code == "2301")).one()
    assert db.scalars(select(EdVisit)).one().target_pool_id == cardio.id


# --- T-4: historic movements ----------------------------------------------------------------


def test_t4_historic_movement_is_refused_except_a_z99_correction(db: Session, apply: Apply) -> None:
    with pytest.raises(Hl7Error) as caught:
        parse(a01_with(b"||INSERT|N|", b"||INSERT|Y|"), PARIS)
    assert (caught.value.ack_code, caught.value.location) == ("AE", "ZBE^1^5")

    z99 = (FIXTURES / "z99_update.hl7").read_bytes().replace(b"\n", b"\r")
    assert parse(z99.replace(b"|UPDATE|N|", b"|UPDATE|Y|"), PARIS).historic


def test_t4_historic_movement_is_journaled_rejected_over_http(
    app_client: TestClient, db: Session, hospital: Group
) -> None:
    code, ack = send_raw(app_client, a01_with(b"||INSERT|N|", b"||INSERT|Y|"))

    assert code == 422 and "MSA|AE|MSG-A01" in ack
    assert db.scalars(select(Movement)).one().status == "rejected"
    assert db.query(Stay).count() == 0


# --- T-5: a cancellation resent under a new control id --------------------------------------


def test_t5_cancellation_resent_under_a_new_control_id_is_a_duplicate(
    db: Session, apply: Apply
) -> None:
    apply("a01_admission")
    apply("a11_cancel_admission")

    again = apply(replace(fixture("a11_cancel_admission"), control_id="MSG-A11-BIS"))

    assert (again.status, again.ack_code) == ("duplicate", "AA")
    assert db.query(Stay).count() == 0


# --- C-5: admission to a blocked bed --------------------------------------------------------


def test_c5_admission_to_a_blocked_bed_keeps_the_block(
    db: Session, hospital: Group, apply: Apply
) -> None:
    blocked = db.scalars(select(Bed).where(Bed.label == "2102A")).one()
    blocked.status, blocked.status_reason = "bloque", "Travaux"
    db.commit()

    result = apply("a01_admission")

    db.refresh(blocked)
    stay = db.scalars(select(Stay)).one()
    assert result.status == "applied" and "bloqué" in result.message
    assert stay.bed_id is None and blocked.stay_id is None
    assert (blocked.status, blocked.status_reason) == ("bloque", "Travaux")
    journal = db.scalars(select(Movement)).one()
    assert journal.error is not None and "bloqué" in journal.error
    apply("a03_discharge")
    db.refresh(blocked)
    assert blocked.status == "bloque"  # never "libre" after the discharge


# --- C-9: releasing a bed stamps it ---------------------------------------------------------


def test_c9_released_bed_is_stamped(db: Session, hospital: Group, apply: Apply) -> None:
    apply("a01_admission")
    later = RECEIVED + timedelta(hours=1)

    apply_movement(db, hospital, fixture("a03_discharge"), later, secret=SECRET, zone=PARIS)
    db.commit()

    released = db.scalars(select(Bed).where(Bed.label == "2102A")).one()
    assert released.status == "a_nettoyer" and released.updated_at == later


# --- Simplification: sex conflicts come from domain.beds ------------------------------------


def test_simpl_shared_room_conflict_uses_the_domain_rule(
    db: Session, hospital: Group, apply: Apply
) -> None:
    apply(replace(fixture("a01_admission"), sex="F"))  # 2102A
    man = replace(
        fixture("a01_admission"),
        control_id="X2", movement_ref="X2", encounter_id="900004", patient_id="IPP8",
        bed="2102B", sex="M",
    )  # fmt: skip

    result = apply(man)

    assert "Chambre 2102 partagée avec un patient de l'autre sexe" in result.message


# --- T-6: chained cancellations -------------------------------------------------------------


def state_dump(db: Session) -> list[tuple[object, ...]]:
    db.expire_all()
    stays = [(s.id, s.mention, s.bed_id, s.admission_date, s.discharged_at) for s in db.query(Stay)]
    beds = [(b.id, b.status, b.stay_id) for b in db.query(Bed).order_by(Bed.id)]
    visits = [(v.id, v.left_at, v.outcome, v.target_pool_id) for v in db.query(EdVisit)]
    return [*stays, *beds, *visits]


def test_t6_cancellations_unwind_the_encounter_one_movement_at_a_time(
    db: Session, hospital: Group, apply: Apply
) -> None:
    apply("a01_admission")
    after_admission = state_dump(db)
    apply("a02_transfer")  # MVT-2: to cardiology 2302A
    after_first_transfer = state_dump(db)
    second = replace(
        fixture("a02_transfer"), control_id="MSG-A02-2", movement_ref="MVT-2b",
        uf_code="2101", room="2102", bed="2102B",
        occurred_at=datetime(2026, 10, 27, 9, tzinfo=PARIS),
    )  # fmt: skip
    apply(second)

    first_cancel = apply(replace(fixture("a12_cancel_transfer"), movement_ref="MVT-2b"))
    assert first_cancel.status == "applied" and state_dump(db) == after_first_transfer
    second_cancel = apply(replace(fixture("a12_cancel_transfer"), control_id="MSG-A12-2"))
    assert second_cancel.status == "applied" and state_dump(db) == after_admission
    assert apply("a11_cancel_admission").status == "applied"
    assert db.query(Stay).count() == 0
    assert {b.status for b in db.query(Bed)} == {"libre"}


# --- T-7: Z99 error branches ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"movement_ref": "MVT-INCONNU"}, "introuvable"),
        ({"original_event": "A02"}, "ZBE-6"),
        ({"source_system": "AUTRE/SI"}, "introuvable"),  # another system's movement
        ({"uf_code": "9999", "facility": None}, "UF 9999 inconnue"),
    ],
)
def test_t7_z99_errors_are_ae_and_change_nothing(
    db: Session, apply: Apply, change: dict[str, object], reason: str
) -> None:
    apply("a01_admission")
    before = state_dump(db)

    result = apply(replace(fixture("z99_update"), **change))  # type: ignore[arg-type]

    assert (result.status, result.ack_code) == ("rejected", "AE") and reason in result.message
    assert state_dump(db) == before


# --- T-8: nothing partial after a rejection -------------------------------------------------


@pytest.mark.parametrize(
    "name_and_change",
    [
        ("a02_transfer", {"uf_code": "9999", "facility": None}),  # unknown destination
        ("a01_admission", {"control_id": "X", "movement_ref": "X"}),  # second admission
        ("a22_return", {}),  # return without leave
        ("a13_cancel_discharge", {}),  # nothing to cancel
    ],
)
def test_t8_a_rejected_movement_leaves_no_partial_change(
    db: Session, apply: Apply, name_and_change: tuple[str, dict[str, object]]
) -> None:
    apply("a01_admission")
    before = state_dump(db)
    name, change = name_and_change

    result = apply(replace(fixture(name), **change))  # type: ignore[arg-type]

    assert result.status == "rejected"
    assert state_dump(db) == before
    journal = db.scalars(select(Movement).where(Movement.id == result.movement_id)).one()
    assert journal.status == "rejected" and journal.bed_id is None and journal.pool_id is None


# --- T-13: tenant isolation on the journal and on cancellations -----------------------------


def test_t13_journal_and_cancellations_stay_within_their_group(
    app_client: TestClient, db: Session, hospital: Group
) -> None:
    def rename(group_id: int, old: str, new: str, same: bool = True) -> None:
        for user in db.scalars(select(User)):
            if (user.group_id == group_id) == same:
                user.email = user.email.replace(old, new)
        db.commit()

    rename(hospital.id, "@hl7.test", "@a.test")
    build_hospital(db, "CH Autre")
    rename(hospital.id, "@hl7.test", "@autre.test", same=False)
    rename(hospital.id, "@a.test", "@hl7.test")

    def login_other(who: str) -> dict[str, str]:
        r = app_client.post(
            "/api/auth/login", json={"email": f"{who}@autre.test", "password": PASSWORD}
        )
        return {"Authorization": f"Bearer {r.json()['token']}"}

    send_raw(app_client, a01())  # group A
    cancel = (FIXTURES / "a11_cancel_admission.hl7").read_bytes().replace(b"\n", b"\r")
    r = app_client.post("/api/ingest/hl7", content=cancel, headers={**HL7, **login_other("agent")})

    assert r.status_code == 422 and "introuvable" in r.text  # group B cannot cancel it
    assert db.query(Stay).filter(Stay.group_id == hospital.id).count() == 1
    other = app_client.get("/api/movements", headers=login_other("dir")).json()
    assert [m["event"] for m in other["items"]] == ["A11"]
    mine = app_client.get("/api/movements", headers=auth(app_client, "dir")).json()
    assert [m["event"] for m in mine["items"]] == ["A01"]


def test_t13_site_scoped_user_sees_only_its_site_movements(
    app_client: TestClient, db: Session, hospital: Group
) -> None:
    smr = db.scalars(select(Site).where(Site.name == "SMR Test")).one()
    coord = db.scalars(select(User).where(User.email == "coord@hl7.test")).one()
    coord.site_id = smr.id
    db.commit()
    send_raw(app_client, a01())  # MCO site

    page = app_client.get("/api/movements", headers=auth(app_client, "coord")).json()

    assert page["items"] == [] and page["total"] == 0
