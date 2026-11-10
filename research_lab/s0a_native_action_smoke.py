"""S0a offline smoke: hand-authored decision records, no simulator/model."""
from __future__ import annotations

import json

from .s0a_native_action_exporter import LEVIERS, build_native_intervals


def main() -> int:
    records = [
        {
            "event_id": f"H:E{i}",
            "hospital_id": "H",
            "unit_id": unit,
            "h": 9,
            "type": "DECISION",
            "payload": dict(zip(LEVIERS, values, strict=True)),
        }
        for i, (unit, values) in enumerate([
            ("u1", (1, 0, 0, 1)),
            ("u2", (0, 0, 1, 0)),
        ])
    ]
    rows = build_native_intervals(
        records, hospital_id="H", units=("u1", "u2"),
        days=1, warmup_hours=24,
    )
    assert len(rows) == 48
    assert sum(r["is_policy_decision_hour"] for r in rows) == 2
    print(json.dumps({
        "status": "PASS_S0A_NATIVE_ACTION_CONTRACT_ONLY",
        "fixture_unit_hours": len(rows),
        "native_levers": list(LEVIERS),
        "same_world_export_executed": False,
        "two_channel_rs_jepa_compatible": False,
        "simulation": False, "training": False,
        "model_forward": False, "gpu_spend": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
