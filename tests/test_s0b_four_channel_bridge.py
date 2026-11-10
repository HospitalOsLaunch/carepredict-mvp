"""S0b four-channel compatibility tests; fixture-only, no torch or simulator."""
from __future__ import annotations

from typing import Any

import ast
import copy
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import pytest

from research_lab.integrated_full_model_v1_contract import (
    make_example_spec,
    make_v041_synthetic_spec,
    validate_against_stage1,
)
from research_lab.s0b_four_channel_bridge import (
    S0B_SCHEMA,
    verify_four_channel_binding,
    with_v041_action_dim,
)
from research_lab.synthetic_action_export_v041 import LEVER_CHANNELS, build_ledger

START = dt.datetime(2026, 11, 10, tzinfo=dt.timezone(dt.timedelta(hours=1)))
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class FakeStage1Config:
    latent_dim: int = 128
    rssm_deter_dim: int = 256
    rssm_stoch_dim: int = 32
    action_dim: int = 2
    encoder_max_steps: int = 512


def make_hour(h: int) -> str:
    return (START + dt.timedelta(hours=h)).isoformat()


def fixture(days: int = 2) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    config = {
        "start": "2026-11-10", "hospital_id": "H",
        "partition": "development", "days": days,
        "poles": [{"pole_id": "P", "units": [
            {"unit_id": "u1"}, {"unit_id": "u2"},
        ]}],
    }
    source = {
        "synthetic_only": True, "status": "complete",
        "data_role": "simulation_truth_not_training_inputs",
        "partition": "development", "hospital_id": "H",
    }
    events = []
    for day in range(days):
        h = day * 24 + 9
        for unit in ("u1", "u2"):
            values = dict.fromkeys(LEVER_CHANNELS, 0)
            if unit == "u1":
                values["renfort_soignant"] = 1
            if day == 1 and unit == "u2":
                values["acceleration_aval"] = 1
            events.append({
                "event_id": f"H:{day}:{unit}", "hospital_id": "H",
                "unit_id": unit, "h": h, "timestamp": make_hour(h),
                "type": "DECISION", "payload": values,
            })
    ledger, coverage = build_ledger(truth=source, config=config, events=events)
    return make_v041_synthetic_spec(), ledger, coverage


def verify(
    *,
    spec: dict[str, Any] | None = None,
    stage1: FakeStage1Config | None = None,
    ledger: list[dict[str, Any]] | None = None,
    coverage: dict[str, Any] | None = None,
    source_clock: str = "fixed_utc_plus_01_no_dst",
) -> dict[str, Any]:
    model, events, source = fixture()
    return verify_four_channel_binding(
        spec=model if spec is None else spec,
        stage1=with_v041_action_dim(FakeStage1Config()) if stage1 is None else stage1,
        ledger=events if ledger is None else ledger,
        coverage=source if coverage is None else coverage,
        entity_id="H", source_clock=source_clock,
    )


def test_four_channels_bind_to_a_new_stage1_configuration() -> None:
    two = FakeStage1Config()
    four = with_v041_action_dim(two)
    assert two.action_dim == 2
    assert four.action_dim == 4
    spec = make_v041_synthetic_spec()
    validate_against_stage1(spec, four)
    with pytest.raises(ValueError, match="Action channels"):
        validate_against_stage1(spec, two)
    with pytest.raises(ValueError, match="Action channels"):
        validate_against_stage1(make_example_spec(), four)
    proof = verify()
    assert proof["schema"] == S0B_SCHEMA
    assert proof["rssm_action_dim"] == 4
    assert proof["rssm_gru_input_width_expected"] == 128 + 32 + 4
    assert proof["channel_unit"] == "units_with_native_requested_decision"
    assert proof["hour_intervals_checked"] == 48
    assert proof["decision_events_claimed"] == 4
    assert proof["model_forward"] is False
    assert proof["training"] is False
    assert proof["no_op_targets_aligned"] is False


def test_reject_legacy_phasea_two_channels_as_native_contract() -> None:
    with pytest.raises(ValueError, match="four-lever"):
        verify(spec=make_example_spec())
    with pytest.raises(ValueError, match="Action channels"):
        verify(stage1=FakeStage1Config())


def test_bad_source_clock_or_unsupported_stage1_rejected() -> None:
    with pytest.raises(ValueError, match="fixed UTC"):
        verify(source_clock="Europe/Paris")
    with pytest.raises(ValueError, match="Only explicit"):
        with_v041_action_dim(FakeStage1Config(action_dim=6))
    with pytest.raises(TypeError, match="dataclass"):
        with_v041_action_dim(object())


def test_unit_count_and_declared_coverage_must_be_consistent() -> None:
    _spec, _ledger, coverage = fixture()
    altered = copy.deepcopy(coverage)
    altered["decision_events"] -= 1
    with pytest.raises(ValueError, match="completeness"):
        verify(coverage=altered)
    altered = copy.deepcopy(coverage)
    altered["channels"] = ["staffing_delta", "discharge_delta"]
    with pytest.raises(ValueError, match="semantics"):
        verify(coverage=altered)
    altered = copy.deepcopy(coverage)
    altered["zero_proof"] = "inferred_missing_as_zero"
    with pytest.raises(ValueError, match="semantics"):
        verify(coverage=altered)


def test_no_native_counter_can_exceed_number_of_units() -> None:
    _spec, ledger, _coverage = fixture()
    altered = copy.deepcopy(ledger)
    altered[9]["values"]["renfort_soignant"] = 3
    with pytest.raises(ValueError, match="cannot exceed"):
        verify(ledger=altered)


def test_missing_duplicate_and_nonzero_outside_policy_rejected() -> None:
    _spec, ledger, _coverage = fixture()
    with pytest.raises(ValueError, match="Incomplete"):
        verify(ledger=ledger[:-1])
    altered = copy.deepcopy(ledger)
    bad_retry = copy.deepcopy(ledger[0])
    bad_retry["values"]["renfort_soignant"] = 1
    altered.append(bad_retry)
    with pytest.raises(ValueError, match="Conflicting action version"):
        verify(ledger=altered)
    altered = copy.deepcopy(ledger)
    altered[12]["values"]["lits_supplementaires"] = 1
    with pytest.raises(ValueError, match="outside 09"):
        verify(ledger=altered)


def test_unavailable_or_noncontiguous_hours_are_rejected() -> None:
    _spec, ledger, _coverage = fixture()
    altered = copy.deepcopy(ledger)
    altered[9]["available_at"] = make_hour(12)
    with pytest.raises(ValueError, match="equal conservative"):
        verify(ledger=altered)
    altered = copy.deepcopy(ledger)
    altered[0]["interval_start"] = make_hour(-1)
    with pytest.raises(ValueError, match="interval"):
        verify(ledger=altered)


def test_four_channel_factory_is_source_only_not_training() -> None:
    tree = ast.parse((ROOT / "rs_jepa/integrated_full_model_v041.py").read_text())
    funcs = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert "assemble_v041_untrained" in funcs
    assert "train" not in funcs
    assert "run_experiment" not in funcs
