"""Application-scoped service for v2 action-free charge forecasting."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Lock

import torch

from services.ml.forecasting.v2_forecast import (
    DEFAULT_V2_FORECAST_ARTIFACT_DIR,
    V2ForecastArtifacts,
    forecast_v2_steps,
    load_v2_forecast_artifacts,
    v2_forecast_history_length,
)


@dataclass(frozen=True)
class V2ForecastService:
    """Stateless v2 forecast service backed by loaded artifacts."""

    artifacts: V2ForecastArtifacts
    model_version: str
    granularity: str
    history_length: int
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    @classmethod
    def from_artifacts(
        cls,
        artifact_dir: Path = DEFAULT_V2_FORECAST_ARTIFACT_DIR,
    ) -> V2ForecastService:
        """Load forecast artifacts once and return a reusable service instance."""
        artifacts = load_v2_forecast_artifacts(artifact_dir)
        checkpoint_sha = _sha256_file(artifacts.artifact_paths["checkpoint"])[:12]
        git_hash = str(artifacts.train_config.get("git_hash", "unknown"))[:12]
        granularity = str(artifacts.train_config.get("granularity", "unknown"))
        return cls(
            artifacts=artifacts,
            model_version=f"v2-forecast-{git_hash}-{checkpoint_sha}",
            granularity=granularity,
            history_length=v2_forecast_history_length(artifacts),
        )

    def forecast(
        self,
        *,
        history: list[list[float]],
        origin_timestamp: datetime,
        horizon: int,
    ) -> list[dict[str, float | int]]:
        """Return raw-space forecast steps for an already validated feature history."""
        if len(history) != self.history_length:
            raise ValueError(f"history must contain exactly {self.history_length} rows")
        history_tensor = torch.tensor(history, dtype=torch.float32).reshape(1, len(history), -1)
        with self._lock, torch.random.fork_rng(devices=[]):
            torch.manual_seed(0)
            steps = forecast_v2_steps(
                artifacts=self.artifacts,
                history=history_tensor,
                origin=origin_timestamp,
                horizon=horizon,
            )
        return [
            {
                "step_index": step.step_index,
                "predicted_siips": step.predicted_siips,
                "lower_90": step.lower_90,
                "upper_90": step.upper_90,
            }
            for step in steps
        ]


def _sha256_file(path: Path) -> str:
    """Return SHA-256 for a local artifact file."""
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
