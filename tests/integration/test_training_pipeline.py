"""Integration smoke test for the training pipeline on synthetic data."""

from __future__ import annotations

from services.ml.models.tft_model import CarePredictTFT, InterpretableTFTFallback
from services.ml.training.data_loader import load_synthetic_training_frame, temporal_split


def test_training_pipeline_smoke() -> None:
    frame = load_synthetic_training_frame(days=10)
    split = temporal_split(frame)
    model = CarePredictTFT(backend=InterpretableTFTFallback())

    metrics = model.fit(split.train)

    assert split.train is not None
    assert "train_mae" in metrics
