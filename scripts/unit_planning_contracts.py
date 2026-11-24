"""Export versioned source contracts with deterministic JSON ordering."""

import json
from pathlib import Path

from hospitalos.hybrid.outlook import Bookings, Departures, Emergency, Roster


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "contracts" / "unit_planning"
    for name, model in (
        ("bookings", Bookings),
        ("departures", Departures),
        ("roster", Roster),
        ("emergency", Emergency),
    ):
        (root / f"{name}.v1.schema.json").write_text(
            json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        )


if __name__ == "__main__":
    main()
