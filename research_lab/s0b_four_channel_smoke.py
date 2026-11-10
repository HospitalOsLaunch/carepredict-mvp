"""S0b smoke: native four-channel action counts -> RSSM metadata binding.

Fabricated decision events only. No torch, simulator, forward or training.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass

from .integrated_full_model_v1_contract import make_v041_synthetic_spec
from .s0b_four_channel_bridge import (
    verify_four_channel_binding,
    with_v041_action_dim,
)
from .synthetic_action_export_v041 import LEVER_CHANNELS, build_ledger


@dataclass(frozen=True)
class Stage1Fixture:
    latent_dim: int = 128
    rssm_deter_dim: int = 256
    rssm_stoch_dim: int = 32
    action_dim: int = 2
    encoder_max_steps: int = 512


def main() -> int:
    source_time = dt.datetime(
        2026, 11, 10, tzinfo=dt.timezone(dt.timedelta(hours=1))
    )
    config = {
        "start": "2026-11-10", "hospital_id": "S0B",
        "partition": "development", "days": 1,
        "poles": [{"pole_id": "P", "units": [
            {"unit_id": "u1"}, {"unit_id": "u2"},
        ]}],
    }
    truth = {
        "status": "complete", "synthetic_only": True,
        "data_role": "simulation_truth_not_training_inputs",
        "partition": "development", "hospital_id": "S0B",
    }
    events = []
    for index, unit in enumerate(("u1", "u2")):
        levers = dict.fromkeys(LEVER_CHANNELS, 0)
        levers["renfort_soignant"] = int(index == 0)
        events.append({
            "type": "DECISION",
            "event_id": f"S0B:decision:{index}",
            "hospital_id": "S0B",
            "unit_id": unit, "h": 9,
            "timestamp": (source_time + dt.timedelta(hours=9)).isoformat(),
            "payload": levers,
        })
    ledger, coverage = build_ledger(truth=truth, config=config, events=events)
    stage1 = with_v041_action_dim(Stage1Fixture())
    receipt = verify_four_channel_binding(
        spec=make_v041_synthetic_spec(), stage1=stage1,
        ledger=ledger, coverage=coverage, entity_id="S0B",
        source_clock="fixed_utc_plus_01_no_dst",
    )
    assert receipt["rssm_action_dim"] == 4
    assert receipt["rssm_gru_input_width_expected"] == 164
    assert receipt["training_loss_authorized"] is False
    print(json.dumps({
        "status": "PASS_S0B_NATIVE_FOUR_CHANNEL_CONTRACT",
        "channels": receipt["action_features"],
        "unit_count": receipt["n_units"],
        "hour_intervals_checked": receipt["hour_intervals_checked"],
        "rssm_action_dim": receipt["rssm_action_dim"],
        "expected_gru_input_width": receipt["rssm_gru_input_width_expected"],
        "stage1_config_migrated": False,
        "model_forward": False, "training": False,
        "simulation": False, "gpu_spend": 0,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
