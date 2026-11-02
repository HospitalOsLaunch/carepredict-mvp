"""The HL7 message posted by the demo check is a valid A04 with fresh identifiers."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from services.admissions_smr.domain.hl7_pam import parse
from tools.demo_check import fresh_hl7

PARIS = ZoneInfo("Europe/Paris")


def test_fresh_hl7_is_a_valid_a04_dated_now_with_new_identifiers() -> None:
    now = datetime(2026, 11, 2, 9, 15, tzinfo=PARIS)

    first, second = parse(fresh_hl7(now), PARIS), parse(fresh_hl7(now), PARIS)

    assert (first.event, first.action, first.uf_code) == ("A04", "INSERT", "1001")
    assert first.occurred_at == now
    assert first.control_id != "MSG-A04" and first.control_id != second.control_id
    assert first.movement_ref != second.movement_ref
    assert first.encounter_id != second.encounter_id and first.encounter_id != "900002"
