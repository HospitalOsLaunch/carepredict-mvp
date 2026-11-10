"""No-simulation S0a smoke: already-recorded fabricated decisions -> action grid."""
from __future__ import annotations

import datetime as dt
import json

from .synthetic_action_export_v041 import LEVER_CHANNELS, build_ledger


def main() -> int:
    start = dt.datetime(2026, 11, 10, tzinfo=dt.timezone(dt.timedelta(hours=1)))
    config = {
        "start": "2026-11-10",
        "hospital_id": "SMOKE_H",
        "partition": "development",
        "days": 1,
        "poles": [{"pole_id": "P", "units": [{"unit_id": "U1"}, {"unit_id": "U2"}]}],
    }
    truth = {
        "status": "complete",
        "synthetic_only": True,
        "data_role": "simulation_truth_not_training_inputs",
        "partition": "development",
        "hospital_id": "SMOKE_H",
    }
    events = []
    for index, unit in enumerate(("U1", "U2")):
        payload = dict.fromkeys(LEVER_CHANNELS, 0)
        payload["renfort_soignant"] = int(index == 0)
        events.append({
            "type": "DECISION", "event_id": f"SMOKE_H:event:{index}",
            "hospital_id": "SMOKE_H", "pole_id": "P", "unit_id": unit,
            "h": 9,
            "timestamp": (start + dt.timedelta(hours=9)).isoformat(),
            "payload": payload,
        })
    rows, coverage = build_ledger(truth=truth, config=config, events=events)
    assert len(rows) == 24
    assert coverage["decision_events"] == 2
    assert rows[9]["values"]["renfort_soignant"] == 1
    assert rows[9]["available_at"] == (
        start + dt.timedelta(hours=10)
    ).isoformat()
    assert all(all(value == 0 for value in row["values"].values())
               for i, row in enumerate(rows) if i != 9)
    print(json.dumps({
        "status": "PASS_S0A_ACTION_EXPORT_OFFLINE",
        "source": "FABRICATED_ALREADY_RECORDED_EVENTS",
        "source_decisions": coverage["decision_events"],
        "explicit_intervals": coverage["hour_intervals"],
        "action_channels": coverage["channels"],
        "no_model_forward": True,
        "no_training": True,
        "no_simulation": True,
        "gpu_spend": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
