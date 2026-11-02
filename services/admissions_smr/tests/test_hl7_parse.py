"""Parsing and acknowledgement of IHE PAM France messages (pure domain)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from services.admissions_smr.domain.hl7_pam import (
    Hl7Error,
    build_ack,
    parse,
    parse_header,
    parse_ts,
)

FIXTURES = Path(__file__).parent / "fixtures" / "hl7"
PARIS = ZoneInfo("Europe/Paris")
NOW = datetime(2026, 10, 25, 8, 30, tzinfo=UTC)


def fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}.hl7").read_bytes()


def test_admission_is_read_into_a_typed_movement() -> None:
    # Act
    m = parse(fixture("a01_admission"), PARIS)

    # Assert
    assert (m.event, m.action, m.movement_ref) == ("A01", "INSERT", "MVT-1")
    assert m.source_system == "GAM_FICTIF/CHDR_FICTIF" and m.control_id == "MSG-A01"
    assert m.occurred_at == datetime(2026, 10, 25, 9, 0, tzinfo=PARIS)  # ZBE-2 wins
    assert (m.patient_class, m.uf_code, m.room, m.bed) == ("I", "2101", "2102", "2102A")
    assert m.facility == "590000017" and m.sex == "F" and m.age == 76
    assert m.patient_id == "IPP4242"  # the PI identifier, never the INS
    assert m.encounter_id == "900001"
    assert (m.encounter_domain, m.patient_domain) == ("GAM", "GAM")
    assert m.digest == ""  # keyed by the caller, with the group key


def test_repr_never_shows_clear_identifiers() -> None:
    m = parse(fixture("a01_admission"), PARIS)
    assert "IPP4242" not in repr(m) and "900001" not in repr(m)


@pytest.mark.parametrize(
    "transform",
    [
        lambda b: b.replace(b"\n", b"\r"),
        lambda b: b.replace(b"\n", b"\r\n"),
        lambda b: b"\x0b" + b.replace(b"\n", b"\r") + b"\x1c\r",
    ],
    ids=["cr", "crlf", "mllp"],
)
def test_segment_separators_and_mllp_framing_are_accepted(transform: object) -> None:
    raw = transform(fixture("a01_admission"))  # type: ignore[operator]
    assert parse(raw, PARIS).encounter_id == "900001"


@pytest.mark.parametrize(
    ("name", "event", "action", "extra"),
    [
        ("a02_transfer", "A02", "INSERT", {"uf_code": "2301", "bed": "2302A"}),
        ("a03_discharge", "A03", "INSERT", {}),
        ("a11_cancel_admission", "A11", "CANCEL", {"movement_ref": "MVT-1"}),
        ("a12_cancel_transfer", "A12", "CANCEL", {"movement_ref": "MVT-2"}),
        ("a13_cancel_discharge", "A13", "CANCEL", {}),
        ("a21_leave", "A21", "INSERT", {}),
        ("a22_return", "A22", "INSERT", {}),
        ("a52_cancel_leave", "A52", "CANCEL", {}),
        ("a53_cancel_return", "A53", "CANCEL", {}),
        ("z99_update", "Z99", "UPDATE", {"original_event": "A01", "bed": "2101"}),
        ("a04_ed_arrival", "A04", "INSERT", {"patient_class": "E", "facility": None}),
        ("a06_ed_to_ward", "A06", "INSERT", {"patient_class": "I"}),
        ("a07_cancel_a06", "A07", "CANCEL", {"movement_ref": "MVT-12"}),
        ("a03_ed_discharge", "A03", "INSERT", {"outcome": "sortie"}),
        ("a05_preadmission_ignored", "A05", "INSERT", {"supported": False}),
    ],
)
def test_every_fixture_parses(name: str, event: str, action: str, extra: dict[str, object]) -> None:
    m = parse(fixture(name), PARIS)
    assert (m.event, m.action) == (event, action)
    for key, value in extra.items():
        assert getattr(m, key) == value


def test_timestamps_with_offset_and_partial_precision() -> None:
    assert parse_ts("202610250900+0000", PARIS) == datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    assert parse_ts("20261025", PARIS) == datetime(2026, 10, 25, tzinfo=PARIS)
    assert parse_ts("20261025093012.1234", PARIS) == datetime(2026, 10, 25, 9, 30, 12, tzinfo=PARIS)
    assert parse_ts("20261332", PARIS) is None
    assert parse_ts("hier", PARIS) is None


def test_unknown_message_type_is_rejected_with_ar() -> None:
    with pytest.raises(Hl7Error) as caught:
        parse(fixture("oru_unsupported"), PARIS)
    assert caught.value.ack_code == "AR" and caught.value.hl7_code == 200
    assert caught.value.header is not None and caught.value.header.control_id == "MSG-ORU"


def test_oversized_message_is_rejected() -> None:
    with pytest.raises(Hl7Error) as caught:
        parse(fixture("a01_admission") + b"X" * 70_000, PARIS, max_bytes=65_536)
    assert caught.value.ack_code == "AR"


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\x00\x01\x02",
        b"MSH",
        b"MSH|",
        b"MSH|^~\\&",
        b"MSH|^~\\&|",
        b"MSH|#~\\&|A|B|C|D|20261025||ADT^A01|1|P|2.5",
        b"PID|||1\rMSH|^~\\&|A",
        b"MSH|^~\\&|A|B|C|D|20261025||ADT^A01||P|2.5",
        b"MSH|^~\\&|A|B|C|D|20261025||ADT^A01|1|P|2.5",
        b"MSH|^~\\&|A|B|C|D|20261025||ADT^A01|1|P|2.5\rPID\rPV1",
        b"MSH|^~\\&|A|B|C|D|20261025||ADT^A01|1|P|2.5\rPID|||^^^^PI\rPV1||I",
        b"MSH|^~\\&|A|B|C|D|xx||ADT^A01|1|P|2.5\rPID|||1\rPV1||I||||||||||||||||2",
        b"MSH|^~\\&|A|B|C|D|20261025||ADT^A12|1|P|2.5\rPID|||1\rPV1||I|||||||||||||||||2"
        b"\rZBE|M|20261025||INSERT",
        b"MSH|^~\\&|A|B|C|D|20261025||ADT^A01|1|P|3.0",
        b"MSH|^~\\&|A|B|C|D|20261025||ADT^A1|1|P|2.5",
        "MSH|^~\\&|É|B|C|D|20261025||ADT^A01|1|P|2.5\rPID|||1".encode("latin-1"),
        b"MSH|^~\\&|A|B|C|D|20261025||ADT^A01|1|P|2.5\r" + b"PID|" + b"^" * 5000,
    ],
)
def test_malformed_input_raises_hl7error_never_crashes(raw: bytes) -> None:
    with pytest.raises(Hl7Error) as caught:
        parse(raw, PARIS)
    assert caught.value.ack_code in ("AE", "AR") and caught.value.message


def test_ack_aa_echoes_the_control_id() -> None:
    _, header = parse_header(fixture("a01_admission").decode().replace("\n", "\r"))

    ack = build_ack(header, "AA", "Mouvement appliqué", NOW, "ACK-1")

    segments = ack.rstrip("\r").split("\r")
    assert segments[0].startswith("MSH|^~\\&|HOSPITALOS|CHDR|GAM_FICTIF|CHDR_FICTIF|")
    assert "|ACK^A01^ACK|ACK-1|P|2.5" in segments[0]
    assert segments[1] == "MSA|AA|MSG-A01|Mouvement appliqué"
    assert len(segments) == 2


def test_ack_error_has_err_segment_and_escapes_separators() -> None:
    ack = build_ack(None, "AR", "Illisible | ^ & ~ \\\rPID", NOW, "ACK-2", 100, "MSH^1^9")

    segments = ack.rstrip("\r").split("\r")
    assert len(segments) == 3
    assert segments[1].startswith("MSA|AR||Illisible \\F\\ \\S\\ \\T\\ \\R\\ \\E\\")
    assert segments[2].startswith("ERR||MSH\\S\\1\\S\\9|100^")
    assert segments[2].endswith("^HL70357|E")
