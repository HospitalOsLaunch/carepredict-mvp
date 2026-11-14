#!/usr/bin/env python3
"""Write the JSON Schemas of the P1 contracts (validable artefacts, regenerated from code)."""

import json
from pathlib import Path

from hospitalos.decision_support.contracts import (
    ForecastBundle,
    Observation,
    PublicSnapshot,
    Recommendation,
    ReviewResult,
    ScenarioLocks,
)

OUT = Path(__file__).resolve().parents[1] / "contracts" / "decision_support"
OUT.mkdir(parents=True, exist_ok=True)
for model in (Observation, PublicSnapshot, ScenarioLocks, ForecastBundle, Recommendation,
              ReviewResult):
    path = OUT / f"{model.__name__}.schema.json"
    path.write_text(json.dumps(model.model_json_schema(mode="serialization"), indent=1,
                               sort_keys=True) + "\n")
    print(path.name)
