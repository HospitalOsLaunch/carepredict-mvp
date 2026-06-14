"""Shared v2 direct-forecast inference used by evaluation and serving."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import Tensor, nn

DEFAULT_V2_FORECAST_ARTIFACT_DIR = Path("artifacts/v2_forecast_multi")


@dataclass(frozen=True)
class V2ForecastArtifacts:
    """Loaded v2 forecast artifacts and metadata."""

    model: nn.Module
    train_config: dict[str, Any]
    q90_lo: np.ndarray
    q90_hi: np.ndarray
    artifact_paths: dict[str, Path]


@dataclass(frozen=True)
class V2ForecastStep:
    """One raw-space forecast point with conformal interval."""

    step_index: int
    predicted_siips: float
    lower_90: float
    upper_90: float


def ensure_hospitalos_importable() -> None:
    """Add the local ``src`` directory to ``sys.path`` when needed."""
    repo_root = Path(__file__).resolve().parents[3]
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)


def infer_transformer_depth(encoder_state: dict[str, Tensor]) -> int:
    """Infer TransformerEncoder depth from a state dict."""
    block_indices = {
        int(key.split(".")[1])
        for key in encoder_state
        if key.startswith("blocks.") and key.split(".")[1].isdigit()
    }
    if not block_indices:
        raise ValueError("encoder state dict does not contain transformer blocks")
    return max(block_indices) + 1


def load_v2_forecast_artifacts(artifact_dir: Path) -> V2ForecastArtifacts:
    """Load a v2 direct-forecast checkpoint, conformal quantiles, and config."""
    ensure_hospitalos_importable()
    from hospitalos.dynamics.jepa_rssm import JepaRSSM, RSSMConfig
    from hospitalos.encoders.ts_jepa.encoder import TransformerEncoder
    from hospitalos.encoders.ts_jepa.patcher import Patchifier

    checkpoint_path = artifact_dir / "checkpoint.pt"
    conformal_path = artifact_dir / "conformal_q.npz"
    config_path = artifact_dir / "train_config.json"

    checkpoint: dict[str, Any] = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    train_config = json.loads(config_path.read_text(encoding="utf-8"))
    q = np.load(conformal_path)
    q90_lo = np.asarray(q["q90_lo"], dtype=np.float64)
    q90_hi = np.asarray(q["q90_hi"], dtype=np.float64)

    cfg = RSSMConfig(**checkpoint["rssm_config"])
    patcher_state = checkpoint["patcher_state_dict"]
    encoder_state = checkpoint["context_encoder_state_dict"]
    patch_weight = patcher_state["proj.weight"]
    emb_dim = int(patch_weight.shape[0])
    patch_input_dim = int(patch_weight.shape[1])
    patch_len = int(train_config["encoder"]["patch_len"])
    if patch_len <= 0 or patch_input_dim % patch_len != 0:
        raise ValueError("invalid patch length in v2 artifacts")

    in_channels = patch_input_dim // patch_len
    patcher = Patchifier(in_channels=in_channels, patch_len=patch_len, emb_dim=emb_dim)
    encoder = TransformerEncoder(emb_dim=emb_dim, depth=infer_transformer_depth(encoder_state))
    patcher.load_state_dict(patcher_state)
    encoder.load_state_dict(encoder_state)
    model = JepaRSSM(cfg, encoder, patcher)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    return V2ForecastArtifacts(
        model=model,
        train_config=train_config,
        q90_lo=q90_lo,
        q90_hi=q90_hi,
        artifact_paths={
            "checkpoint": checkpoint_path,
            "conformal_q": conformal_path,
            "train_config": config_path,
        },
    )


def validate_v2_forecast_artifacts(
    *,
    artifacts: V2ForecastArtifacts,
    expected_git_hash: str | None = None,
) -> None:
    """Validate critical artifact assumptions before evaluation or serving."""
    patch_len = int(artifacts.train_config["encoder"]["patch_len"])
    if patch_len not in {1, 24}:
        raise ValueError(f"expected encoder patch_len in {{1, 24}}, got {patch_len}")
    git_hash = str(artifacts.train_config["git_hash"])
    if expected_git_hash is not None and git_hash != expected_git_hash:
        raise ValueError("train_config git_hash does not match expected commit")
    if artifacts.q90_lo.shape != (48,) or artifacts.q90_hi.shape != (48,):
        raise ValueError("conformal q90 arrays must both have shape (48,)")


def v2_forecast_history_length(artifacts: V2ForecastArtifacts) -> int:
    """Return the feature-history length that extracts the trained origin state."""
    ensure_hospitalos_importable()
    from hospitalos.dynamics.jepa_rssm import forecast_origin_slice

    patch_len = int(artifacts.train_config["encoder"]["patch_len"])
    nominal_steps = 168 // patch_len
    origin_slice = forecast_origin_slice(
        steps=nominal_steps,
        patch_len=patch_len,
        forecast_horizon=int(artifacts.model.cfg.forecast_horizon),
    )
    return int(origin_slice.stop * patch_len)


def history_window_origin(artifacts: V2ForecastArtifacts, origin: datetime) -> datetime:
    """Return the timestamp that should end the feature-history window."""
    if int(artifacts.train_config["encoder"]["patch_len"]) == 24:
        return origin - timedelta(hours=1)
    return origin


def build_calendar_features(start: datetime, length: int) -> Tensor:
    """Build deterministic calendar features for hourly forecast-head inputs."""
    ensure_hospitalos_importable()
    from hospitalos.dynamics.jepa_rssm import calendar_encoding

    hours: list[int] = []
    days: list[int] = []
    for offset in range(length):
        current = start + timedelta(hours=offset)
        hours.append(current.hour)
        days.append(current.weekday())
    return calendar_encoding(
        torch.tensor(hours, dtype=torch.float32),
        torch.tensor(days, dtype=torch.float32),
    )


@torch.inference_mode()
def predict_v2_from_history(model: nn.Module, history: Tensor, origin: datetime) -> Tensor:
    """Return a raw-space 48-hour direct forecast for the requested origin."""
    ensure_hospitalos_importable()
    from hospitalos.dynamics.jepa_rssm import calendar_encoding, symexp

    z = model.encode_series(history)
    states = model.unroll(z)
    origin_features = states["features"][:, -1:, :]
    if model.forecast_head[0].in_features == origin_features.shape[-1] + 2:
        day = torch.tensor([float(origin.weekday())], dtype=torch.float32)
        hour = torch.zeros(1, dtype=torch.float32)
        origin_calendar = calendar_encoding(hour, day)[:, -2:].reshape(1, 1, 2)
    else:
        calendar = build_calendar_features(origin - timedelta(hours=167), 168).unsqueeze(0)
        origin_calendar = calendar[:, -1:, :]
    forecast_input = torch.cat([origin_features, origin_calendar], dim=-1)
    forecast = symexp(model.forecast_head(forecast_input))
    return forecast[0, 0, :].detach().cpu()


def forecast_v2_steps(
    *,
    artifacts: V2ForecastArtifacts,
    history: Tensor,
    origin: datetime,
    horizon: int,
) -> list[V2ForecastStep]:
    """Return raw-space forecast steps with saved conformal intervals."""
    if horizon < 1 or horizon > int(artifacts.model.cfg.forecast_horizon):
        raise ValueError("horizon exceeds v2 forecast artifact support")
    forecast = predict_v2_from_history(artifacts.model, history, origin)
    steps: list[V2ForecastStep] = []
    for index in range(horizon):
        prediction = float(forecast[index])
        steps.append(
            V2ForecastStep(
                step_index=index + 1,
                predicted_siips=prediction,
                lower_90=prediction - float(artifacts.q90_lo[index]),
                upper_90=prediction + float(artifacts.q90_hi[index]),
            )
        )
    return steps
