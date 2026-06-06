"""Conformal prediction wrapper for calibrated nursing workload intervals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import structlog

LOGGER = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ConformalConfig:
    """Configuration for split-conformal forecasting intervals."""

    coverage: float = 0.90
    method: str = "cv_plus"
    allow_mapie: bool = True

    def __post_init__(self) -> None:
        """Validate conformal parameters."""
        if not 0.0 < self.coverage < 1.0:
            raise ValueError("coverage must be in (0, 1)")
        if self.method not in {"cv_plus", "split"}:
            raise ValueError("method must be either 'cv_plus' or 'split'")


@dataclass(frozen=True, slots=True)
class PredictionInterval:
    """Point forecast and calibrated prediction interval."""

    value: float
    lower: float
    upper: float
    coverage: float
    residual_quantile: float


class ConformalForecaster:
    """Calibrate and apply 90% conformal intervals around point forecasts."""

    def __init__(self, config: ConformalConfig | None = None) -> None:
        self.config = config or ConformalConfig()
        self._residual_quantile: float | None = None
        self._backend_name = self._detect_backend()

    @property
    def backend_name(self) -> str:
        """Return active conformal backend name."""
        return self._backend_name

    @property
    def is_calibrated(self) -> bool:
        """Return whether calibration residuals have been fitted."""
        return self._residual_quantile is not None

    def calibrate(
        self,
        y_true: npt.ArrayLike,
        y_pred: npt.ArrayLike,
    ) -> float:
        """Calibrate the residual quantile on a validation set."""
        true_values = np.asarray(y_true, dtype=float)
        pred_values = np.asarray(y_pred, dtype=float)
        self._validate_matching_arrays(true_values, pred_values)

        residuals = np.abs(true_values - pred_values)
        quantile_level = min(1.0, np.ceil((len(residuals) + 1) * self.config.coverage) / len(residuals))
        self._residual_quantile = float(np.quantile(residuals, quantile_level, method="higher"))
        LOGGER.info(
            "conformal_calibration_completed",
            backend=self.backend_name,
            coverage=self.config.coverage,
            residual_quantile=self._residual_quantile,
            samples=len(residuals),
        )
        return self._residual_quantile

    def predict_interval(self, point_forecast: float) -> PredictionInterval:
        """Return a calibrated interval for a single point forecast."""
        residual_quantile = self._require_residual_quantile()
        return PredictionInterval(
            value=float(point_forecast),
            lower=float(point_forecast - residual_quantile),
            upper=float(point_forecast + residual_quantile),
            coverage=self.config.coverage,
            residual_quantile=residual_quantile,
        )

    def predict_intervals(self, point_forecasts: npt.ArrayLike) -> list[PredictionInterval]:
        """Return calibrated intervals for multiple point forecasts."""
        values = np.asarray(point_forecasts, dtype=float)
        if values.ndim != 1:
            raise ValueError("point_forecasts must be one-dimensional")
        return [self.predict_interval(float(value)) for value in values]

    def empirical_coverage(
        self,
        y_true: npt.ArrayLike,
        y_pred: npt.ArrayLike,
    ) -> float:
        """Measure empirical coverage on a test set."""
        true_values = np.asarray(y_true, dtype=float)
        pred_values = np.asarray(y_pred, dtype=float)
        self._validate_matching_arrays(true_values, pred_values)
        residual_quantile = self._require_residual_quantile()
        covered = np.abs(true_values - pred_values) <= residual_quantile
        return float(covered.mean())

    def to_artifact_dict(self) -> dict[str, float | str]:
        """Return a serializable calibration artifact."""
        return {
            **asdict(self.config),
            "backend_name": self.backend_name,
            "residual_quantile": self._require_residual_quantile(),
        }

    def save_artifact(self, path: Path) -> None:
        """Save calibration config as a small JSON artifact."""
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_artifact_dict(), indent=2), encoding="utf-8")

    @classmethod
    def from_residual_quantile(
        cls,
        residual_quantile: float,
        config: ConformalConfig | None = None,
    ) -> "ConformalForecaster":
        """Build a calibrated forecaster from a stored residual quantile."""
        if residual_quantile < 0:
            raise ValueError("residual_quantile must be non-negative")
        forecaster = cls(config=config)
        forecaster._residual_quantile = residual_quantile
        return forecaster

    def _require_residual_quantile(self) -> float:
        if self._residual_quantile is None:
            raise RuntimeError("ConformalForecaster must be calibrated before prediction")
        return self._residual_quantile

    @staticmethod
    def _validate_matching_arrays(
        true_values: npt.NDArray[np.float64],
        pred_values: npt.NDArray[np.float64],
    ) -> None:
        if true_values.ndim != 1 or pred_values.ndim != 1:
            raise ValueError("y_true and y_pred must be one-dimensional")
        if len(true_values) == 0:
            raise ValueError("calibration arrays must not be empty")
        if true_values.shape != pred_values.shape:
            raise ValueError("y_true and y_pred must have matching shapes")

    def _detect_backend(self) -> str:
        if not self.config.allow_mapie:
            return "split_conformal"
        try:
            __import__("mapie")
        except ImportError:
            return "split_conformal"
        return "mapie_available_split_conformal"
