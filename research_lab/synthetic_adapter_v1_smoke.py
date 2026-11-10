"""Safe offline synthetic_adapter_v1 smoke. Fabricated miniature records only."""
from __future__ import annotations

import datetime as dt
import json

from .integrated_full_model_v1_contract import make_example_spec
from .synthetic_adapter_v1 import ACTION_SCHEMA, build_window


def main() -> int:
    spec = make_example_spec()
    spec["history_steps"] = 3
    origin = dt.datetime(2026, 11, 10, 12, tzinfo=dt.timezone.utc)

    def time(hour: int) -> str:
        return (origin + dt.timedelta(hours=hour)).isoformat()

    observations = [
        {
            "schema_version": "OPERATIONAL_V2_RESEARCH_1",
            "event_id": f"fixture:obs:{hour}",
            "version": 1,
            "entity_id": "H",
            "level": "hospital",
            "source_system": "synthetic_observed",
            "event_time": time(hour),
            "recorded_at": time(hour),
            "ingested_at": time(hour),
            "available_at": time(hour),
            "values": {"ed_waiting": 5 + hour, "occupancy": 20 + hour},
        }
        for hour in (-2, -1, 0, 1, 6, 24)
    ]
    actions = [
        {
            "schema": ACTION_SCHEMA,
            "event_id": f"fixture:action:{hour}",
            "version": 1,
            "entity_id": "H",
            "source_system": "synthetic_action_observed",
            "interval_start": time(hour - 1),
            "interval_end": time(hour),
            "recorded_at": time(hour),
            "available_at": time(hour),
            "values": {"staffing_delta": 0.0, "discharge_delta": 0.0},
            "synthetic_only": True,
        }
        for hour in (-2, -1, 0)
    ]
    topology = {
        "schema_version": "OPERATIONAL_V2_RESEARCH_1",
        "topology_id": "fixture:topology",
        "version": 1,
        "valid_from": time(-100),
        "valid_to": None,
        "available_at": time(-100),
        "nodes": [
            {"entity_id": "H", "level": "hospital", "parent_id": None,
             "capacity_beds": 40.0}
        ],
    }
    window = build_window(
        spec=spec, observations=observations, action_intervals=actions,
        topology=topology, entity_id="H", origin=time(0),
        label_cutoff=time(25), partition="development", max_age_hours=3,
    )
    assert window["x"][0] == [
        [3.0, 0.0, 0.0], [4.0, 0.0, 0.0], [5.0, 0.0, 0.0]
    ]
    assert len(window["actions_context"][0]) == 3
    assert window["training_target_mask"] == [[[1, 1]] * 3]
    assert window["forward_executed"] is False
    print(json.dumps({
        "status": "PASS_SYNTHETIC_ADAPTER_OFFLINE",
        "samples": 1,
        "context_steps": len(window["x"][0]),
        "features": len(window["x"][0][0]),
        "action_channels": len(window["actions_context"][0][0]),
        "target_horizons": spec["horizons_hours"],
        "source": "FABRICATED_FIXTURE_NOT_MODEL_DATA",
        "model_forward": False, "training": False, "simulation": False,
        "test_holdout_opened": False, "gpu_spend": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
