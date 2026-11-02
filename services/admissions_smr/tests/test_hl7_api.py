"""HTTP ingestion of movements: HL7 ACK semantics, roles, limits, journal, no clear data."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, select
from sqlalchemy.orm import Session

from services.admissions_smr.clock import FrozenClock
from services.admissions_smr.models import EdVisit, Group, Movement, Stay
from services.admissions_smr.tests.test_hl7_apply import PASSWORD, RECEIVED, build_hospital

FIXTURES = Path(__file__).parent / "fixtures" / "hl7"
HL7 = {"Content-Type": "x-application/hl7-v2+er7"}
CLEAR_VALUES = [
    "DUPONTEL", "MARGOT", "19500615", "1950-06-15", "1850599123456", "LILAS", "0320123456",
    "IPP4242", "900001", "LEBRUNET", "ARTHUR", "19880203", "0611223344", "IPP5151", "900002",
    "ROUBAIX", "IPP-AGENT-77", "NDA-AGENT-77",
]  # fmt: skip


@pytest.fixture
def hospital(app_client: TestClient, db: Session) -> Group:
    app_client.app.state.clock = FrozenClock(RECEIVED)  # type: ignore[attr-defined]
    return build_hospital(db)


@pytest.fixture
def headers(app_client: TestClient, hospital: Group) -> Callable[[str], dict[str, str]]:
    def login(who: str) -> dict[str, str]:
        r = app_client.post(
            "/api/auth/login", json={"email": f"{who}@hl7.test", "password": PASSWORD}
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    return login


def send(client: TestClient, auth: dict[str, str], name: str, **kw: str) -> tuple[int, str]:
    body = (FIXTURES / f"{name}.hl7").read_bytes().replace(b"\n", b"\r")
    r = client.post("/api/ingest/hl7", content=body, headers={**HL7, **auth, **kw})
    return r.status_code, r.text


def msa(ack: str) -> list[str]:
    return next(s for s in ack.split("\r") if s.startswith("MSA")).split("|")


def test_admission_is_acknowledged_aa_and_applied(
    app_client: TestClient, headers: Callable[[str], dict[str, str]], db: Session
) -> None:
    # Act
    code, ack = send(app_client, headers("agent"), "a01_admission")

    # Assert
    assert code == 200
    assert ack.startswith("MSH|^~\\&|HOSPITALOS|CHDR|GAM_FICTIF|CHDR_FICTIF|")
    assert msa(ack)[:3] == ["MSA", "AA", "MSG-A01"]
    assert db.query(Stay).count() == 1


def test_resent_message_is_acknowledged_without_effect(
    app_client: TestClient, headers: Callable[[str], dict[str, str]], db: Session
) -> None:
    auth = headers("agent")
    send(app_client, auth, "a01_admission")

    code, ack = send(app_client, auth, "a01_admission")

    assert code == 200 and msa(ack)[1] == "AA" and "déjà reçu" in ack
    assert db.query(Movement).count() == 1


def test_unknown_message_type_is_ar_and_journaled(
    app_client: TestClient, headers: Callable[[str], dict[str, str]], db: Session
) -> None:
    code, ack = send(app_client, headers("agent"), "oru_unsupported")

    assert code == 400 and msa(ack)[:3] == ["MSA", "AR", "MSG-ORU"]
    assert "ERR||MSH^1^9|200^" in ack.replace("\\S\\", "^")
    row = db.scalars(select(Movement)).one()
    assert (row.status, row.event, row.encounter_ref) == ("rejected", "R01", "")


def test_content_error_is_ae_with_err(
    app_client: TestClient, headers: Callable[[str], dict[str, str]]
) -> None:
    auth = headers("agent")

    code, ack = send(app_client, auth, "a03_discharge")  # no admission first

    assert code == 422 and msa(ack)[1] == "AE" and "ERR|" in ack
    assert "Sortie sans séjour" in ack


@pytest.mark.parametrize(
    "body",
    [b"", b"\x00\xff", b"MSH|", b"PID|||1", b"MSH|^~\\&|A|B|C|D|x||ADT^A01|1|P|2.5\rPID"],
)
def test_malformed_messages_never_crash(
    app_client: TestClient, headers: Callable[[str], dict[str, str]], body: bytes
) -> None:
    r = app_client.post("/api/ingest/hl7", content=body, headers={**HL7, **headers("agent")})
    assert r.status_code in (400, 422) and "MSA|A" in r.text


def test_size_and_media_type_limits(
    app_client: TestClient, headers: Callable[[str], dict[str, str]]
) -> None:
    auth = headers("agent")
    big = b"MSH|^~\\&|A|B|C|D|20261025||ADT^A01|1|P|2.5\r" + b"X" * 70_000

    too_big = app_client.post("/api/ingest/hl7", content=big, headers={**HL7, **auth})
    wrong_type = app_client.post(
        "/api/ingest/hl7", content=b"MSH", headers={"Content-Type": "application/json", **auth}
    )

    assert too_big.status_code == 413 and "MSA|AR" in too_big.text
    assert wrong_type.status_code == 415 and "text/plain" in wrong_type.json()["detail"]


@pytest.mark.parametrize("who", ["coord", "admin", "dir"])
def test_only_the_ingestion_account_can_post(
    app_client: TestClient, headers: Callable[[str], dict[str, str]], who: str
) -> None:
    code, _ = send(app_client, headers(who), "a01_admission")
    r = app_client.post("/api/ingest/movements", json=[], headers=headers(who))
    assert code == 403 and r.status_code == 403
    assert send(app_client, {}, "a01_admission")[0] == 401


def agent_item(**changes: object) -> dict[str, object]:
    item: dict[str, object] = {
        "source_system": "demo_bedsoft",
        "movement_ref": "BS-1",
        "event": "A01",
        "occurred_at": "2026-10-25T09:00:00+02:00",
        "encounter_id": "NDA-AGENT-77",
        "patient_id": "IPP-AGENT-77",
        "uf_code": "2101",
        "room": "2102",
        "bed": "2102B",
        "sex": "M",
        "age": 64,
    }
    return item | changes


def test_structured_movements_from_the_agent(
    app_client: TestClient, headers: Callable[[str], dict[str, str]], db: Session
) -> None:
    auth = headers("agent")

    first = app_client.post("/api/ingest/movements", json=[agent_item()], headers=auth)
    again = app_client.post(
        "/api/ingest/movements",
        json=[agent_item(), agent_item(movement_ref="BS-1", action="CANCEL")],
        headers=auth,
    )

    assert first.status_code == 200 and first.json()[0]["status"] == "applied"
    assert [r["status"] for r in again.json()] == ["duplicate", "applied"]
    assert db.query(Stay).count() == 0  # admission cancelled
    stays = db.query(Movement).filter(Movement.event == "A11").count()
    assert stays == 1


def test_structured_movements_refuse_extra_fields(
    app_client: TestClient, headers: Callable[[str], dict[str, str]], db: Session
) -> None:
    r = app_client.post(
        "/api/ingest/movements",
        json=[agent_item(patient_name="Mme Exemple")],
        headers=headers("agent"),
    )
    assert r.status_code == 200  # REVIEW C-7: refused item by item
    (result,) = r.json()
    assert result["status"] == "rejected" and "patient_name" in result["message"]
    assert "Exemple" not in r.text and db.query(Movement).count() == 0


def test_journal_is_paginated_pseudonymous_and_reports_rejections(
    app_client: TestClient, headers: Callable[[str], dict[str, str]]
) -> None:
    auth = headers("agent")
    for name in ("a01_admission", "a02_transfer", "oru_unsupported"):
        send(app_client, auth, name)

    page = app_client.get("/api/movements?limit=2", headers=headers("dir"))
    forbidden = app_client.get("/api/movements", headers=auth)

    assert page.status_code == 200 and forbidden.status_code == 403
    body = page.json()
    assert body["total"] == 3 and len(body["items"]) == 2
    assert body["last_24h"] == {"applied": 2, "rejected": 1}
    assert body["rejection_rate_24h"] == pytest.approx(1 / 3, abs=1e-3)
    transfer = body["items"][1]
    assert transfer["event_label"] == "Mutation" and transfer["bed_label"] == "2302A"
    assert transfer["unit_label"] == "cardiologie" and len(transfer["encounter"]) == 8
    assert not any(v in page.text for v in CLEAR_VALUES)


def test_no_clear_identifier_is_stored_anywhere(
    app_client: TestClient, headers: Callable[[str], dict[str, str]], db: Session
) -> None:
    # Arrange: every fixture (names, birth dates, INS/NIR, addresses, phones) + the agent path.
    auth = headers("agent")
    for path in sorted(FIXTURES.glob("*.hl7")):
        send(app_client, auth, path.stem)
    app_client.post("/api/ingest/movements", json=[agent_item()], headers=auth)
    assert db.query(Movement).count() >= 10 and db.query(EdVisit).count() == 1

    # Act: dump every column of every table.
    metadata = MetaData()
    metadata.reflect(bind=db.get_bind())
    dump: list[str] = []
    for table in metadata.sorted_tables:
        for row in db.execute(table.select()):
            dump.extend(str(v) for v in row)
    text = "\n".join(dump).upper()

    # Assert
    leaked = [v for v in CLEAR_VALUES if v.upper() in text]
    assert leaked == []
