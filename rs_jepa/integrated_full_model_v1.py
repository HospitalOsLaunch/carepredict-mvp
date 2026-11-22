"""Integrated synthetic world-model assembly, NOT a training or run script.

Reuses RS-JEPA ObservableEncoder + EMA target + action-conditioned RSSM +
LatentPredictor, adds a multi-horizon probabilistic readout. Nothing runs on
import. Test contracts without importing torch via research_lab.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from research_lab.future_calendar import FEATURES, NATIVE_MINUTES, calendar_grid, check_step
from research_lab.integrated_full_model_v1_contract import (
    CHECKPOINT_SCHEMA,
    COMPONENTS,
    fingerprint,
    inspect_checkpoint,
    validate_against_stage1,
    validate_spec,
)
from rs_jepa.config import Stage1Config
from rs_jepa.ema import EMATargetEncoder
from rs_jepa.encoder import ObservableEncoder
from rs_jepa.predictor import LatentPredictor
from rs_jepa.rssm import RSSM


@dataclass(frozen=True)
class ForecastGrid:
    """Model estimates at interval ends. Intermediate estimates have no 014 labels."""

    end_offsets_minutes: tuple[int, ...]
    means: Tensor
    scales: Tensor


@dataclass(frozen=True)
class ForecastOutput:
    """No clinical calibration or causal identification claim."""
    means: Tensor  # [B, n_horizons, n_targets], in target physical units
    scales: Tensor  # [B, n_horizons, n_targets], positive but uncalibrated
    predicted_latents: Tensor  # [B, future steps, latent_dim]
    belief_states: Tensor  # [B, future steps, deter+stoch]
    prior_means: Tensor
    prior_stds: Tensor
    horizons_hours: tuple[int, ...]
    target_names: tuple[str, ...]
    action_mode: str
    uncertainty_kind: str = "heteroscedastic_uncalibrated"
    future_step_minutes: int = 60
    grid: ForecastGrid | None = None


class MultiHorizonGaussianHead(nn.Module):
    """Shared per-step head sampled at distinct horizon indices."""

    def __init__(self, latent_dim: int, hidden: int, n_targets: int) -> None:
        super().__init__()
        if min(latent_dim, hidden, n_targets) <= 0:
            raise ValueError("Head dimensions must be positive")
        self.n_targets = n_targets
        self.net = nn.Sequential(
            nn.LayerNorm(latent_dim), nn.Linear(latent_dim, hidden),
            nn.GELU(), nn.Linear(hidden, 2 * n_targets),
        )

    def forward(
        self, predicted_latents: Tensor, horizon_indices: tuple[int, ...]
    ) -> tuple[Tensor, Tensor]:
        if predicted_latents.ndim != 3:
            raise ValueError("Predicted latents must have shape [B,H,Z]")
        if not horizon_indices or min(horizon_indices) < 0:
            raise ValueError("Invalid horizon indices")
        if max(horizon_indices) >= predicted_latents.shape[1]:
            raise ValueError("Horizon exceeds RSSM rollout length")
        selected = predicted_latents[:, list(horizon_indices), :]
        result = self.net(selected)
        mean, raw_scale = result.chunk(2, dim=-1)
        return mean, F.softplus(raw_scale) + 1e-4


class IntegratedFullModelV1(nn.Module):
    """Assemble existing RS-JEPA components; no implicit training.

    The producer MUST have already resolved the correct source revision as-of
    D. Tensor-level clocks are a necessary but insufficient integrity guard.
    Synthetic actions not known at D cannot become factual future features.
    """

    def __init__(self, *, spec: dict[str, Any], stage1: Stage1Config) -> None:
        super().__init__()
        self.spec = validate_spec(spec)
        validate_against_stage1(self.spec, stage1)
        n_obs = len(self.spec["observation_features"])
        n_static = len(self.spec["static_features"])
        self.action_dim = len(self.spec["action_features"])
        self.context_steps = self.spec["history_steps"]
        calendar = self.spec.get("future_calendar")
        self.has_calendar = calendar is not None
        self.default_step_minutes = (
            calendar["default_step_minutes"] if calendar else self.spec["step_hours"] * 60
        )
        self.horizon_indices = self._indices(self.default_step_minutes)
        self.rollout_steps = self.horizon_indices[-1] + 1
        self.target_names = tuple(t["name"] for t in self.spec["targets"])

        # This integrated operational contract supplies its own admissible
        # observation feature provenance. The legacy encoder's criticality
        # training denylist is not the source-of-truth for observed occupancy.
        self.encoder = ObservableEncoder(
            n_obs=n_obs, n_static=n_static, cfg=stage1
        )
        self.target_encoder = EMATargetEncoder(self.encoder)
        self.rssm = RSSM(
            stage1, n_static=n_static, future_known_dim=len(FEATURES) if self.has_calendar else 0
        )
        self.jepa_predictor = LatentPredictor(stage1)
        self.forecast_head = MultiHorizonGaussianHead(
            latent_dim=stage1.latent_dim,
            hidden=self.spec["head_hidden_dim"],
            n_targets=len(self.target_names),
        )

    def _indices(self, step_minutes: int) -> tuple[int, ...]:
        return tuple(h * 60 // step_minutes - 1 for h in self.spec["horizons_hours"])

    def _check_input(
        self,
        x: Tensor,
        static: Tensor | None,
        actions_context: Tensor,
        action_available_ns: Tensor,
        origin_ns: Tensor,
        event_ns: Tensor,
        available_ns: Tensor,
        future_actions: Tensor | None,
        future_actions_available_ns: Tensor | None,
        action_mode: str,
        steps: int,
    ) -> None:
        b = x.shape[0] if x.ndim else -1
        t = self.context_steps
        if x.ndim != 3 or x.shape[1:] != (t, len(self.spec["observation_features"])):
            raise ValueError("Observed context has wrong [B,context,features] shape")
        if not torch.isfinite(x).all().item():
            raise ValueError("Nonfinite observed tensor; missingness must use explicit masks")
        if static is None:
            if self.spec["static_features"]:
                raise ValueError("Static observations are required by the model contract")
        elif static.shape != (b, len(self.spec["static_features"])):
            raise ValueError("Static shape does not match model spec")
        if static is not None and not torch.isfinite(static).all().item():
            raise ValueError("Nonfinite static features")
        if actions_context.shape != (b, t, self.action_dim):
            raise ValueError("Context actions do not match contract")
        if not torch.isfinite(actions_context).all().item():
            raise ValueError("Nonfinite context actions")
        if (origin_ns.ndim != 1 or origin_ns.shape[0] != b
                or event_ns.shape != (b, t) or available_ns.shape != (b, t)
                or action_available_ns.shape != (b, t)):

            raise ValueError("Per-version event, availability and origin clocks are required")
        for clock in (origin_ns, event_ns, available_ns, action_available_ns):
            if clock.dtype != torch.int64:
                raise ValueError("As-of clocks must be UTC int64 nanoseconds")
        if ((event_ns > available_ns).any() or (available_ns > origin_ns[:, None]).any()):
            raise ValueError("Observations unavailable at decision origin (as-of leakage)")
        if (action_available_ns > origin_ns[:, None]).any():
            raise ValueError("Historical actions unavailable at decision origin")
        if action_mode not in ("no_op", "known_plan", "counterfactual"):
            raise ValueError("Future action scenario must be explicitly declared")
        if action_mode == "no_op":
            if future_actions is not None or future_actions_available_ns is not None:
                raise ValueError("No-op scenario must not use future action arrays")
        else:
            if future_actions is None or future_actions.shape != (
                b, steps, self.action_dim
            ):
                raise ValueError("Future action schedule shape mismatch")
            if not torch.isfinite(future_actions).all().item():
                raise ValueError("Nonfinite future actions")
            if action_mode == "known_plan":
                if (future_actions_available_ns is None
                        or future_actions_available_ns.shape != (b, steps)
                        or future_actions_available_ns.dtype != torch.int64):
                    raise ValueError("Known plans need version-level availability times")
                if (future_actions_available_ns > origin_ns[:, None]).any():
                    raise ValueError("Future plan was not available at decision origin")
            elif future_actions_available_ns is not None:
                raise ValueError("Counterfactual action schedules cannot masquerade as plans")

    def forward(
        self,
        x: Tensor,
        *,
        static: Tensor | None,
        actions_context: Tensor,
        action_available_ns: Tensor,
        origin_ns: Tensor,
        event_ns: Tensor,
        available_ns: Tensor,
        action_mode: str,
        future_actions: Tensor | None = None,
        future_actions_available_ns: Tensor | None = None,
        future_step_minutes: int | None = None,
        return_grid_forecasts: bool = False,
    ) -> ForecastOutput:
        step = (
            self.default_step_minutes if future_step_minutes is None else check_step(future_step_minutes)
        )
        if not self.has_calendar and step != self.default_step_minutes:
            raise ValueError("Changing forecast resolution requires a calendar-enabled model")
        indices = self._indices(step)
        steps = indices[-1] + 1
        self._check_input(
            x, static, actions_context, action_available_ns, origin_ns,
            event_ns, available_ns, future_actions, future_actions_available_ns,
            action_mode, steps,
        )
        known = None
        stride = 1
        if self.has_calendar:
            # A fixed integration clock keeps predictions at common times invariant to the grid.
            stride = step // NATIVE_MINUTES
            origins = origin_ns.detach().cpu().tolist()
            grids = {d: calendar_grid(d, max(self.spec["horizons_hours"]), NATIVE_MINUTES)
                     for d in set(origins)}
            known = x.new_tensor([grids[d] for d in origins])
            if not self.spec["future_calendar"]["use_civil_calendar"]:
                known[:, :, :-1] = 0  # Keep duration and integration clock in the control arm.
            if future_actions is not None:
                if (
                    future_actions.dtype == torch.bool
                    or (future_actions < 0).any()
                    or (future_actions != future_actions.floor()).any()
                ):
                    raise ValueError("Native lever requests must be nonnegative integer counts")
                # Each slot carries requests at its start. Never repeat a request on substeps.
                impulses = future_actions.new_zeros(x.shape[0], steps * stride, self.action_dim)
                impulses[:, ::stride] = future_actions
                future_actions = impulses
        z_context = self.encoder(x, static)
        rollout = self.rssm.rollout(
            z_context, steps * stride, static=static,
            actions_context=actions_context, actions_future=future_actions, future_known=known,
        )
        at_boundaries = slice(stride - 1, None, stride)
        states = rollout.states[:, at_boundaries]
        z_pred = self.jepa_predictor(states)
        grid = None
        if return_grid_forecasts:
            all_means, all_scales = self.forecast_head(z_pred, tuple(range(steps)))
            grid = ForecastGrid(tuple(range(step, (steps + 1) * step, step)), all_means, all_scales)
            means, scales = all_means[:, list(indices)], all_scales[:, list(indices)]
        else:
            means, scales = self.forecast_head(z_pred, indices)
        return ForecastOutput(
            means=means, scales=scales, predicted_latents=z_pred,
            belief_states=states, prior_means=rollout.prior_mean[:, at_boundaries],
            prior_stds=rollout.prior_std[:, at_boundaries],
            horizons_hours=tuple(self.spec["horizons_hours"]),
            target_names=self.target_names, action_mode=action_mode, future_step_minutes=step, grid=grid,
        )

    @torch.no_grad()
    def update_ema_after_authorized_step(self, *, tau: float) -> None:
        """Only an authorized future trainer should call this after optimizer step."""
        if not 0.0 <= tau <= 1.0:
            raise ValueError("EMA coefficient must be in [0,1]")
        self.target_encoder.update_from(self.encoder, tau)


def save_untrained_assembly(
    model: IntegratedFullModelV1,
    directory: Path,
    *,
    source_commit: str,
) -> dict[str, Any]:
    """Persist random initialized components safely, with no training claim.

    Not used by offline contract tests. Requires torch+safetensors to call.
    """
    from safetensors.torch import save_file

    directory = directory.resolve()
    if directory.exists():
        raise FileExistsError("No checkpoint overwrite allowed")
    if not directory.parent.is_dir():
        raise ValueError("Checkpoint parent must exist")
    tensors = {
        key: value.detach().to("cpu").contiguous()
        for key, value in model.state_dict().items()
    }
    for component in COMPONENTS:
        if not any(key.startswith(component + ".") for key in tensors):
            raise RuntimeError(f"Missing model component {component}")
    with tempfile.TemporaryDirectory(prefix=".integrated-v1-", dir=directory.parent) as tmp:
        staging = Path(tmp) / "checkpoint"
        staging.mkdir()
        weights = staging / "weights.safetensors"
        save_file(tensors, str(weights))
        weights_hash = hashlib.sha256(weights.read_bytes()).hexdigest()
        manifest = {
            "schema": CHECKPOINT_SCHEMA,
            "model_spec_sha256": fingerprint(model.spec),
            "weights_file": "weights.safetensors",
            "weights_sha256": weights_hash,
            "components": list(COMPONENTS),
            "training_status": "UNTRAINED_ASSEMBLY",
            "source_commit": source_commit,
            "run_id": None,
            "approval_id": None,
            "synthetic_data_sha256": None,
            "generator_sha256": None,
            "normalization_sha256": None,
            "global_step": 0,
            "evidence": {"asof_dataset_verified": False, "independent_review": False},
        }
        spec_file = staging / "spec.json"
        spec_file.write_text(json.dumps(model.spec, sort_keys=True, indent=2) + "\n")
        (staging / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n"
        )
        # Validate the artifact before publishing the immutable directory.
        inspect_checkpoint(staging)
        staging.replace(directory)
    return manifest


def load_untrained_assembly(
    directory: Path, *, stage1: Stage1Config
) -> IntegratedFullModelV1:
    """Safe tensor-only loader. Refuses to infer checkpoint scientific promotion."""
    from safetensors.torch import load_file

    receipt = inspect_checkpoint(directory)
    if receipt["training_status"] != "UNTRAINED_ASSEMBLY":
        raise PermissionError("Trained checkpoint needs a separately approved loader")
    spec = json.loads((directory / "spec.json").read_text())
    model = IntegratedFullModelV1(spec=spec, stage1=stage1)
    tensors = load_file(str(directory / "weights.safetensors"))
    model.load_state_dict(tensors, strict=True)
    return model
