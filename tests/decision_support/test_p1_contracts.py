"""P1 — contracts, snapshot boundary, civil time, score versioning, schemas."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from hospitalos.decision_support.clock import CivilTimeError, hours_between, resolve_local
from hospitalos.decision_support.contracts import (
    CivilDeadline,
    Observation,
    PublicSnapshot,
    Recommendation,
    ScenarioLocks,
    StayState,
)
from hospitalos.decision_support.planner import (
    HorizonError,
    Settings,
    resolve_horizon,
    score_descriptor,
)
from hospitalos.decision_support.snapshot import load_json, load_profile

from .conftest import FX

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "contracts" / "decision_support"


def test_configs_are_versioned_and_safe_profile():
    profile = load_profile()
    assert profile["synthetic"] is True and profile["pressure_discharges_enabled"] is False
    objective = load_json(ROOT / "configs/decision_support/OBJECTIVE_CONFIG.json")
    assert objective["objective_id"] and objective["admissions_are_not_a_lever"] is True
    assert [t["rank"] for t in objective["tiers"]] == [0, 1, 2, 3]


def test_t02_observation_received_after_decision_is_excluded(nominal):
    s07 = next(s for s in nominal.stays if s.stay_id == "S07")
    s04 = next(s for s in nominal.stays if s.stay_id == "S04")
    assert s07.medical_authorization == "not_authorized"  # late authorisation ignored
    assert s04.medical_authorization == "not_authorized"  # future event ignored
    assert nominal.excluded_observations == {
        "event_after_decision": 1,
        "available_after_decision": 1,
    }


def test_unknown_is_kept_unknown_and_revocation_wins(nominal):
    s03 = next(s for s in nominal.stays if s.stay_id == "S03")
    assert (s03.destination, s03.transport_need, s03.ready_earliest) == ("unknown", "unknown", None)
    s05 = next(s for s in nominal.stays if s.stay_id == "S05")
    assert s05.medical_authorization == "revoked"
    assert all(s.provenance for s in nominal.stays)


def test_private_fields_cannot_enter_public_contracts(nominal):
    raw = nominal.model_dump(mode="json")
    raw["stays"][0]["ready_h"] = 14
    with pytest.raises(ValidationError):
        PublicSnapshot.model_validate(raw)
    with pytest.raises(ValidationError):
        StayState.model_validate({**nominal.stays[0].model_dump(), "dis_h": 21})
    assert "private_truth" not in json.dumps(raw)


def test_observation_clocks_and_whole_hour_as_of(nominal):
    with pytest.raises(ValidationError):
        Observation.model_validate(
            {
                "obs_id": "x",
                "kind": "bed",
                "subject": "L01",
                "source": "s",
                "event_time": "2026-11-16T19:00:00+00:00",
                "available_at": "2026-11-16T18:00:00+00:00",
                "value": {},
            }
        )
    raw = nominal.model_dump(mode="json")
    raw["as_of"] = "2026-11-16T19:30:00+00:00"
    with pytest.raises(ValidationError):
        PublicSnapshot.model_validate(raw)


def test_t28_europe_paris_dst_resolution():
    # autumn change: 02:30 occurs twice -> explicit fold required
    with pytest.raises(CivilTimeError) as ambiguous:
        resolve_local(date(2026, 10, 25), time(2, 30))
    assert ambiguous.value.code == "AMBIGUOUS_LOCAL_TIME"
    first = resolve_local(date(2026, 10, 25), time(2, 30), fold=0)
    second = resolve_local(date(2026, 10, 25), time(2, 30), fold=1)
    assert hours_between(first, second) == 1
    # spring change: 02:30 does not exist
    with pytest.raises(CivilTimeError) as missing:
        resolve_local(date(2027, 3, 28), time(2, 30))
    assert missing.value.code == "NONEXISTENT_LOCAL_TIME"
    # "demain 20 h" across DST: real UTC durations 25 h and 23 h
    deadline = CivilDeadline(day_offset=1, local_time=time(20))
    autumn = datetime(2026, 10, 24, 18, tzinfo=UTC)  # 20:00 CEST
    spring = datetime(2027, 3, 27, 19, tzinfo=UTC)  # 20:00 CET
    assert hours_between(autumn, deadline.resolve(autumn)) == 25
    assert hours_between(spring, deadline.resolve(spring)) == 23


def test_t28_horizon_never_truncated(nominal):
    profile = load_profile()
    locks = ScenarioLocks(deadline=CivilDeadline(day_offset=1, local_time=time(20)))
    start, end, hours = resolve_horizon(nominal, profile, locks)
    assert hours == 24 and end.isoformat() == "2026-11-17T19:00:00+00:00"
    late = ScenarioLocks(deadline=CivilDeadline(day_offset=1, local_time=time(21)))
    with pytest.raises(HorizonError) as error:
        resolve_horizon(nominal, profile, late)
    assert error.value.code == "UNSUPPORTED_HORIZON"


def test_t26_score_unconfigured_and_formula_versioning():
    settings = Settings.default()
    assert score_descriptor(None) == {"score_status": "UNCONFIGURED", "components_only": True}
    current = score_descriptor(settings.score)
    changed = dict(settings.score)
    changed["coefficients"] = {**changed["coefficients"], "waiting_patient": 3}
    other = score_descriptor(changed)
    assert current["score_status"] == "EXPERIMENTAL_SYNTHETIC"
    assert current["formula_sha256"] != other["formula_sha256"]
    assert current["comparable_only_with_same_formula_sha256"] is True


def test_json_schemas_are_current_and_validate_outputs(auto):
    for model in (PublicSnapshot, ScenarioLocks, Recommendation):
        path = SCHEMAS / f"{model.__name__}.schema.json"
        assert json.loads(path.read_text()) == model.model_json_schema(mode="serialization"), path
    schema = json.loads((SCHEMAS / "Recommendation.schema.json").read_text())
    jsonschema.validate(json.loads(auto.model_dump_json()), schema)


def test_fixtures_are_synthetic_and_bounded(nominal):
    for path in FX.glob("*.json"):
        assert json.loads(path.read_text())["synthetic"] is True, path
    assert len(nominal.stays) <= load_profile()["limits"]["max_present_stays"]
