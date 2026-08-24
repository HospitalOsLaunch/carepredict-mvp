"""Dagster assets for model training."""

from __future__ import annotations

from pathlib import Path

from dagster import AssetExecutionContext, asset


@asset(group_name="ml")
def train_tft_model(context: AssetExecutionContext) -> str:
    """Train TFT and calibrate conformal intervals."""
    report_path = Path("reports/backtesting/carepredict_backtest.html")
    context.log.info(f"TFT training asset scaffolded: report_path={report_path}")
    return "tft-moirai-ft-v1.0"


@asset(group_name="ml")
def calibrate_conformal_intervals(context: AssetExecutionContext, train_tft_model: str) -> str:
    """Calibrate MAPIE/split-conformal intervals."""
    context.log.info(f"Conformal calibration asset scaffolded: model_version={train_tft_model}")
    return "coverage-0.90"
