"""S0b — Four-channel native V0.4.1 action contract, torch-free.

The four channels are *counts of units with requested lever activations*.
They are not Phase-A staffing/discharge deltas, not executed resources, and
not experimentally identified causal effects.

Only checks metadata, source records, and Stage-1 configuration dimensions.
No ML model, tensor, simulator, training or experiment is imported or run.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import is_dataclass, replace
from typing import Any

from .integrated_full_model_v1_contract import (
    validate_against_stage1,
    validate_spec,
)
from .synthetic_adapter_v1 import V041_ACTIONS, validate_action_ledger

S0B_SCHEMA = "hospitalos.s0b_v041_four_channel_bridge_v1"
SOURCE_CLOCK = "fixed_utc_plus_01_no_dst"
ZERO_PROOF = "full_09h_daily_unit_decision_grid_verified"
SEMANTICS = "hospital_count_of_requested_levers_not_execution_effect"


def with_v041_action_dim(stage1: Any) -> Any:
    """Create a *new* Stage1Config-compatible dataclass with four action channels.

    Does not mutate a historical configuration or migrate old two-channel
    checkpoints. This helper is NOT a model constructor or training command.
    """
    if not is_dataclass(stage1) or isinstance(stage1, type):
        raise TypeError("Expected a Stage1Config dataclass instance")
    if not hasattr(stage1, "action_dim"):
        raise ValueError("Stage 1 is missing action_dim")
    action_dim = getattr(stage1, "action_dim")
    if action_dim not in (2, 4):
        raise ValueError("Only explicit Phase-A(2) to native V0.4.1(4) is supported")
    return replace(stage1, action_dim=4)


def verify_four_channel_binding(
    *,
    spec: dict[str, Any],
    stage1: Any,
    ledger: list[dict[str, Any]],
    coverage: Any,
    entity_id: str,
    source_clock: str,
) -> dict[str, Any]:
    """Validate source action semantics/coverage before permitting *any* model wiring.

    A successful result is a CONTRACT receipt, not an execution authorization.
    """
    validate_spec(spec)
    if spec["action_features"] != list(V041_ACTIONS):
        raise ValueError("S0b requires exact native four-lever channel order")
    validate_against_stage1(spec, stage1)
    if source_clock != SOURCE_CLOCK:
        raise ValueError("Native V0.4.1 clock must be the fixed UTC+01 reference")
    if not isinstance(coverage, dict):
        raise ValueError("Source lacks independently inspectable action coverage")
    if (coverage.get("channels") != list(V041_ACTIONS)
            or coverage.get("zero_proof") != ZERO_PROOF
            or coverage.get("action_semantics") != SEMANTICS):
        raise ValueError("Source action metadata does not attest native lever semantics")
    n_units = coverage.get("unit_count")
    n_decisions = coverage.get("decision_events")
    n_hours = coverage.get("hour_intervals")
    if (type(n_units) is not int or type(n_decisions) is not int
            or type(n_hours) is not int
            or not (0 < n_units <= 2048)
            or not (0 < n_hours <= 1096 * 24)
            or n_hours % 24 != 0
            or n_decisions != n_units * (n_hours // 24)):
        raise ValueError("Unit/day action completeness assertion inconsistent")
    if not entity_id or not isinstance(entity_id, str):
        raise ValueError("Missing hospital entity ID")

    normalized = validate_action_ledger(
        ledger, entity_id, spec["step_hours"], V041_ACTIONS
    )
    if len(normalized) != n_hours:
        raise ValueError("Incomplete or duplicated hourly action ledger")
    if spec["step_hours"] != 1:
        raise ValueError("S0b V0.4.1 action snapshots are strictly hourly")

    intervals = sorted(normalized, key=lambda row: row["start"])
    one_hour = dt.timedelta(hours=1)
    local_clock = dt.timezone(dt.timedelta(hours=1))
    event_hours = 0
    for index, row in enumerate(intervals):
        if row["end"] - row["start"] != one_hour:
            raise ValueError("Non-hourly native action interval")
        if row["available"] != row["end"]:
            raise ValueError("Action interval availability must equal conservative end hour")
        if index and intervals[index - 1]["end"] != row["start"]:
            raise ValueError("Native action intervals are not contiguous")
        # The source's fixed UTC+01 calendar has no DST. Never infer decisions
        # from event_at timestamps in another source clock or geography.
        local_hour = row["start"].astimezone(local_clock).hour
        expected_decision = local_hour == 9
        if index == 0 and local_hour != 0:
            raise ValueError("Action ledger must start at source-day midnight")
        for lever in V041_ACTIONS:
            count = row["values"][lever]
            if type(count) is not int or count > n_units:
                raise ValueError("Lever count cannot exceed the source's unit population")
            if not expected_decision and count:
                raise ValueError("Nonzero native decisions outside 09:00 source policy")
        event_hours += int(expected_decision)
    if event_hours != n_hours // 24:
        raise ValueError("Daily 09:00 decision structure invalid")

    return {
        "schema": S0B_SCHEMA,
        "status": "FOUR_CHANNEL_SOURCE_CONTRACT_VERIFIED_NOT_MODEL_TESTED",
        "action_features": list(V041_ACTIONS),
        "channel_unit": "units_with_native_requested_decision",
        "source_clock": SOURCE_CLOCK,
        "n_units": n_units,
        "decision_events_claimed": n_decisions,
        "hour_intervals_checked": n_hours,
        "rssm_action_dim": stage1.action_dim,
        "rssm_gru_input_width_expected": (
            stage1.latent_dim + stage1.rssm_stoch_dim + stage1.action_dim
        ),
        "origin_rule": "context_lever_interval_available_by_D",
        "no_op_targets_aligned": False,
        "training_loss_authorized": False,
        "model_forward": False,
        "training": False,
        "simulation": False,
    }
