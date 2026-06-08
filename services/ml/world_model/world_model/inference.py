"""Stateless serving boundary for the Hospital World Model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import torch

from services.ml.world_model.config import RSSMConfig, ServingConfig
from services.ml.world_model.rssm import HospitalRSSM, RSSMState


@dataclass(frozen=True, slots=True)
class StandardScalerState:
    """Persisted StandardScaler parameters for SIIPS normalization."""

    mean: float
    std: float


@dataclass(frozen=True, slots=True)
class ConformalState:
    """Persisted split-conformal residual matrix and interval parameters."""

    absolute_residuals: npt.NDArray[np.float64]
    alpha: float


@dataclass(frozen=True, slots=True)
class WorldModelService:
    """Immutable, concurrency-safe world model service for simulation requests."""

    config: ServingConfig
    rssm_config: RSSMConfig
    model: HospitalRSSM
    scaler: StandardScalerState
    conformal: ConformalState
    service_p95_threshold: float
    model_version: str
    device: torch.device

    @classmethod
    def from_artifacts(cls, config: ServingConfig | None = None) -> WorldModelService:
        """Load model weights, scaler statistics and conformal residuals from disk."""
        serving_config = config or ServingConfig()
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        checkpoint_path = Path(serving_config.checkpoint_path)
        scaler_path = Path(serving_config.scaler_path)
        residual_path = Path(serving_config.calibration_residuals_path)
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"World model checkpoint not found: {checkpoint_path}")
        if not scaler_path.exists():
            raise FileNotFoundError(f"World model scaler not found: {scaler_path}")
        if not residual_path.exists():
            raise FileNotFoundError(f"World model residuals not found: {residual_path}")

        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=True)
        rssm_config = _rssm_config_from_checkpoint(checkpoint)
        model = HospitalRSSM(rssm_config).to(device=device)
        state_dict = _state_dict_from_checkpoint(checkpoint)
        model.load_state_dict(state_dict)
        model.eval()

        scaler_npz = np.load(scaler_path)
        scaler = StandardScalerState(
            mean=float(np.asarray(scaler_npz["mean"], dtype=np.float64).reshape(-1)[0]),
            std=max(float(np.asarray(scaler_npz["std"], dtype=np.float64).reshape(-1)[0]), 1e-6),
        )
        residual_npz = np.load(residual_path)
        residuals = np.asarray(residual_npz["residuals"], dtype=np.float64)
        if residuals.size == 0:
            raise ValueError("Conformal residual artifact must contain at least one value")
        service_p95_threshold = float(
            residual_npz["service_p95_threshold"]
            if "service_p95_threshold" in residual_npz
            else scaler.mean + serving_config.critical_quantile * scaler.std
        )
        if isinstance(checkpoint, dict) and "model_version" in checkpoint:
            model_version = str(checkpoint["model_version"])
        else:
            model_version = "rssm-world-model-v1"
        return cls(
            config=serving_config,
            rssm_config=rssm_config,
            model=model,
            scaler=scaler,
            conformal=ConformalState(
                absolute_residuals=np.abs(residuals).astype(np.float64),
                alpha=serving_config.conformal_alpha,
            ),
            service_p95_threshold=service_p95_threshold,
            model_version=model_version,
            device=device,
        )

    @torch.inference_mode()
    def simulate(
        self,
        history_siips: list[float],
        action_sequence: list[list[float]],
    ) -> list[dict[str, float | int | bool]]:
        """Simulate future SIIPS values and conformal intervals from history and actions."""
        self._validate_inputs(history_siips=history_siips, action_sequence=action_sequence)
        dtype = next(self.model.parameters()).dtype
        history_array = np.asarray(
            history_siips[-self.config.max_history_length :],
            dtype=np.float64,
        )
        normalized_history = (history_array - self.scaler.mean) / self.scaler.std
        history_obs = torch.tensor(
            normalized_history.reshape(1, -1, self.rssm_config.obs_dim),
            device=self.device,
            dtype=dtype,
        )
        history_actions = torch.zeros(
            1,
            int(history_obs.shape[1]),
            self.rssm_config.action_dim,
            device=self.device,
            dtype=dtype,
        )
        states, _priors, _posteriors = self.model.observe_sequence(history_obs, history_actions)
        if not states["h"] or not states["z"]:
            raise ValueError("History did not produce an RSSM state")

        state: RSSMState = {"h": states["h"][-1], "z": states["z"][-1]}
        future_actions = torch.tensor(
            np.asarray(action_sequence, dtype=np.float64),
            device=self.device,
            dtype=dtype,
        )
        results: list[dict[str, float | int | bool]] = []
        for step_index in range(int(future_actions.shape[0])):
            state, _prior = self.model.imagine_step(
                state,
                future_actions[step_index : step_index + 1],
            )
            normalized_pred, reward_pred = self.model.decode(state)
            predicted_siips = float(normalized_pred.reshape(-1)[0].detach().cpu().item())
            denormalized_pred = predicted_siips * self.scaler.std + self.scaler.mean
            interval_radius = self._conformal_radius(step_index=step_index)
            lower_bound = max(0.0, denormalized_pred - interval_radius)
            upper_bound = denormalized_pred + interval_radius
            results.append(
                {
                    "step_index": step_index,
                    "predicted_siips": float(denormalized_pred),
                    "lower_bound": float(lower_bound),
                    "upper_bound": float(upper_bound),
                    "reward": float(reward_pred.reshape(-1)[0].detach().cpu().item()),
                    "is_critical": bool(denormalized_pred >= self.service_p95_threshold),
                }
            )
        return results

    def _validate_inputs(
        self,
        history_siips: list[float],
        action_sequence: list[list[float]],
    ) -> None:
        """Validate raw Python inputs before tensor conversion."""
        if not history_siips:
            raise ValueError("history_siips must contain at least one observation")
        if len(history_siips) > self.config.max_history_length:
            raise ValueError("history_siips exceeds max_history_length")
        if not action_sequence:
            raise ValueError("action_sequence must contain at least one action")
        if len(action_sequence) > self.config.max_horizon:
            raise ValueError("action_sequence exceeds max_horizon")
        for value in history_siips:
            if not np.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError("history_siips values must be finite and non-negative")
        for action in action_sequence:
            if len(action) != self.rssm_config.action_dim:
                raise ValueError(f"each action must have {self.rssm_config.action_dim} values")
            for value in action:
                if not np.isfinite(float(value)):
                    raise ValueError("action values must be finite")

    def _conformal_radius(self, step_index: int) -> float:
        """Return the split-conformal radius for a zero-indexed horizon step."""
        residuals = self.conformal.absolute_residuals
        if residuals.ndim == 1:
            step_residuals = residuals
        elif step_index < residuals.shape[1]:
            step_residuals = residuals[:, step_index]
        else:
            step_residuals = residuals[:, 0]
        finite = step_residuals[np.isfinite(step_residuals)]
        if finite.size == 0:
            finite = np.asarray([self.scaler.std], dtype=np.float64)
        quantile = float(np.quantile(np.abs(finite), 1.0 - self.conformal.alpha))
        horizon_factor = 1.0 + float(step_index) / max(float(self.config.max_horizon), 1.0)
        return max(quantile * horizon_factor, self.scaler.std * 0.01)


def _rssm_config_from_checkpoint(checkpoint: Any) -> RSSMConfig:
    if isinstance(checkpoint, dict) and "config" in checkpoint:
        config_value = checkpoint["config"]
        if isinstance(config_value, RSSMConfig):
            return config_value
        if isinstance(config_value, dict):
            return RSSMConfig(**config_value)
    return RSSMConfig()


def _state_dict_from_checkpoint(checkpoint: Any) -> dict[str, torch.Tensor]:
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        state = checkpoint["model_state_dict"]
    elif isinstance(checkpoint, dict) and "state_dict" in checkpoint:
        state = checkpoint["state_dict"]
    elif isinstance(checkpoint, dict):
        state = checkpoint
    else:
        raise ValueError("Unsupported world model checkpoint format")
    if not isinstance(state, dict):
        raise ValueError("Checkpoint state must be a dictionary")
    return {str(key): value for key, value in state.items() if isinstance(value, torch.Tensor)}
