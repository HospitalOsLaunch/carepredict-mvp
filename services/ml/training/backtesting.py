"""Walk-forward backtesting metrics for CarePredict forecasting."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pandas as pd

from services.ml.models.tft_model import CarePredictTFT
from services.ml.uq.conformal import ConformalForecaster


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    """Backtesting metrics used as training gates."""

    mae: float
    mape: float
    crps: float
    coverage: float
    ece: float

    def as_dict(self) -> dict[str, float]:
        """Return metrics as a plain dictionary."""
        return {
            "mae": self.mae,
            "mape": self.mape,
            "crps": self.crps,
            "coverage": self.coverage,
            "ece": self.ece,
        }


def calculate_metrics(
    y_true: npt.ArrayLike,
    y_pred: npt.ArrayLike,
    lower: npt.ArrayLike,
    upper: npt.ArrayLike,
    target_coverage: float = 0.90,
) -> BacktestMetrics:
    """Calculate MAE, MAPE, CRPS approximation, coverage and ECE."""
    true_values = np.asarray(y_true, dtype=float)
    pred_values = np.asarray(y_pred, dtype=float)
    lower_values = np.asarray(lower, dtype=float)
    upper_values = np.asarray(upper, dtype=float)
    _validate_shapes(true_values, pred_values, lower_values, upper_values)

    errors = np.abs(true_values - pred_values)
    mae = float(errors.mean())
    mape = float((errors / np.clip(np.abs(true_values), 1.0, None)).mean())
    interval_width = np.maximum(upper_values - lower_values, 1e-6)
    crps = float(np.mean(errors / interval_width))
    coverage = float(((true_values >= lower_values) & (true_values <= upper_values)).mean())
    ece = abs(coverage - target_coverage)
    return BacktestMetrics(mae=mae, mape=mape, crps=crps, coverage=coverage, ece=ece)


def assert_metric_targets(metrics: BacktestMetrics) -> None:
    """Fail training when MVP metric gates are not met."""
    failures: list[str] = []
    if metrics.mae > 0.8:
        failures.append(f"MAE {metrics.mae:.3f} > 0.800")
    if metrics.mape > 0.12:
        failures.append(f"MAPE {metrics.mape:.3f} > 0.120")
    if metrics.crps > 0.15:
        failures.append(f"CRPS {metrics.crps:.3f} > 0.150")
    if not 0.88 <= metrics.coverage <= 0.92:
        failures.append(f"coverage {metrics.coverage:.3f} outside [0.880, 0.920]")
    if metrics.ece > 0.05:
        failures.append(f"ECE {metrics.ece:.3f} > 0.050")
    if failures:
        raise RuntimeError("Backtesting metric targets failed: " + "; ".join(failures))


def run_walk_forward_backtest(
    frame: pd.DataFrame,
    model: CarePredictTFT,
    conformal: ConformalForecaster,
    horizon: int = 12,
    lookback: int = 24,
) -> BacktestMetrics:
    """Run a simple walk-forward backtest over the provided frame."""
    if len(frame) <= lookback + horizon:
        raise ValueError("frame is too short for walk-forward backtesting")

    predictions: list[float] = []
    actuals: list[float] = []
    lower: list[float] = []
    upper: list[float] = []
    ordered = frame.sort_values("timestamp").reset_index(drop=True)

    for index in range(lookback, len(ordered) - horizon):
        history = ordered.iloc[index - lookback : index].reset_index(drop=True)
        target = float(ordered.iloc[index + horizon - 1]["siips_score"])
        forecast = model.predict(history)
        interval = conformal.predict_interval(forecast.value)
        predictions.append(forecast.value)
        actuals.append(target)
        lower.append(interval.lower)
        upper.append(interval.upper)

    return calculate_metrics(actuals, predictions, lower, upper)


def render_backtest_report(
    output_path: Path,
    metrics: BacktestMetrics,
    title: str = "CarePredict Backtesting Report",
) -> Path:
    """Render a small standalone HTML report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(
        f"<tr><th>{name}</th><td>{value:.4f}</td></tr>"
        for name, value in metrics.as_dict().items()
    )
    output_path.write_text(
        f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body>
<h1>{title}</h1>
<table>{rows}</table>
</body>
</html>
""",
        encoding="utf-8",
    )
    return output_path


def _validate_shapes(*arrays: npt.NDArray[np.float64]) -> None:
    shapes = {array.shape for array in arrays}
    if len(shapes) != 1:
        raise ValueError("all metric arrays must have matching shapes")
    if next(iter(shapes))[0] == 0:
        raise ValueError("metric arrays must not be empty")
