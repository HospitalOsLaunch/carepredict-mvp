"""Training utilities for the Hospital World Model."""

from __future__ import annotations

import random
from dataclasses import dataclass

import mlflow
import numpy as np
import torch
from torch import Tensor
from torch.distributions import Normal, kl_divergence

from services.ml.world_model.config import RewardConfig, TrainConfig
from services.ml.world_model.rssm import HospitalRSSM, RSSMState


@dataclass(frozen=True, slots=True)
class TrainStepOutput:
    """Scalar loss components emitted by a train step."""

    total_loss: float
    reconstruction_loss: float
    reward_loss: float
    kl_loss: float


class WorldModelTrainer:
    """CPU/CUDA trainer implementing RSSM ELBO optimization with KL balancing."""

    def __init__(
        self,
        model: HospitalRSSM,
        reward_config: RewardConfig,
        train_config: TrainConfig | None = None,
        device: torch.device | None = None,
    ) -> None:
        """Create a trainer, move the model to device and initialize the optimizer."""
        self.config = train_config or TrainConfig()
        self.reward_config = reward_config
        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._set_seeds(self.config.seed)
        self.model = model.to(device=self.device)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=self.config.lr)
        self.global_step = 0

    def train_step(self, batch: dict[str, Tensor]) -> dict[str, float]:
        """Run one ELBO optimization step on a normalized batch."""
        self.model.train()
        history_obs = batch["history_obs"].to(self.device)
        history_actions = batch["history_actions"].to(self.device)
        future_actions = batch["future_actions"].to(self.device)
        future_siips_targets = batch["future_siips_targets"].to(self.device)
        states, priors, posteriors = self.model.observe_sequence(history_obs, history_actions)

        reconstruction_loss = self._reconstruction_loss(states, history_obs)
        kl_loss = self._balanced_kl_loss(priors, posteriors)
        future_obs_pred, future_reward_pred = self._imagine_predictions(states, future_actions)
        if future_siips_targets.ndim == 2:
            future_target = future_siips_targets.unsqueeze(-1)
        else:
            future_target = future_siips_targets
        future_reconstruction_loss = torch.nn.functional.mse_loss(future_obs_pred, future_target)
        reward_target = self._reward_target(future_target)
        reward_loss = torch.nn.functional.huber_loss(future_reward_pred, reward_target)
        total_loss = (
            reconstruction_loss
            + future_reconstruction_loss
            + self.config.reward_weight * reward_loss
            + self.config.kl_weight * kl_loss
        )

        self.optimizer.zero_grad(set_to_none=True)
        total_loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=self.config.grad_clip)
        self.optimizer.step()
        self.global_step += 1

        metrics = {
            "total_loss": float(total_loss.detach().cpu().item()),
            "reconstruction_loss": float(reconstruction_loss.detach().cpu().item()),
            "future_reconstruction_loss": float(future_reconstruction_loss.detach().cpu().item()),
            "reward_loss": float(reward_loss.detach().cpu().item()),
            "kl_loss": float(kl_loss.detach().cpu().item()),
        }
        self._log_metrics(metrics)
        return metrics

    def _reconstruction_loss(self, states: dict[str, list[Tensor]], history_obs: Tensor) -> Tensor:
        predictions: list[Tensor] = []
        for step_index in range(len(states["h"])):
            state: RSSMState = {"h": states["h"][step_index], "z": states["z"][step_index]}
            obs_pred, _reward_pred = self.model.decode(state)
            predictions.append(obs_pred)
        stacked = torch.stack(predictions, dim=1)
        return torch.nn.functional.mse_loss(stacked, history_obs)

    def _imagine_predictions(
        self,
        states: dict[str, list[Tensor]],
        future_actions: Tensor,
    ) -> tuple[Tensor, Tensor]:
        if not states["h"] or not states["z"]:
            raise ValueError("Observed states are required before imagination")
        state: RSSMState = {"h": states["h"][-1], "z": states["z"][-1]}
        obs_predictions: list[Tensor] = []
        reward_predictions: list[Tensor] = []
        for step_index in range(int(future_actions.shape[1])):
            state, _prior = self.model.imagine_step(state, future_actions[:, step_index, :])
            obs_pred, reward_pred = self.model.decode(state)
            obs_predictions.append(obs_pred)
            reward_predictions.append(reward_pred)
        return torch.stack(obs_predictions, dim=1), torch.stack(reward_predictions, dim=1)

    def _balanced_kl_loss(self, priors: list[Normal], posteriors: list[Normal]) -> Tensor:
        terms: list[Tensor] = []
        for prior_dist, posterior_dist in zip(priors, posteriors, strict=True):
            posterior_stop = Normal(posterior_dist.mean.detach(), posterior_dist.stddev.detach())
            prior_stop = Normal(prior_dist.mean.detach(), prior_dist.stddev.detach())
            posterior_weighted = kl_divergence(posterior_stop, prior_dist).sum(dim=-1)
            prior_weighted = kl_divergence(posterior_dist, prior_stop).sum(dim=-1)
            balanced = (
                self.model.config.kl_balance * posterior_weighted
                + (1.0 - self.model.config.kl_balance) * prior_weighted
            )
            terms.append(balanced)
        if not terms:
            dtype = next(self.model.parameters()).dtype
            return torch.tensor(self.model.config.free_bits, device=self.device, dtype=dtype)
        mean_kl = torch.stack(terms, dim=1).mean()
        free_bits = torch.tensor(
            self.model.config.free_bits,
            device=self.device,
            dtype=mean_kl.dtype,
        )
        return torch.maximum(mean_kl, free_bits)

    def _reward_target(self, target_siips: Tensor) -> Tensor:
        p75 = torch.tensor(self.reward_config.p75, device=self.device, dtype=target_siips.dtype)
        p90 = torch.tensor(self.reward_config.p90, device=self.device, dtype=target_siips.dtype)
        moderate = torch.tensor(
            self.reward_config.moderate_penalty,
            device=self.device,
            dtype=target_siips.dtype,
        )
        acute = torch.tensor(
            self.reward_config.acute_penalty,
            device=self.device,
            dtype=target_siips.dtype,
        )
        neutral = torch.zeros_like(target_siips, device=self.device, dtype=target_siips.dtype)
        return torch.where(
            target_siips >= p90,
            acute,
            torch.where(target_siips >= p75, moderate, neutral),
        )

    @staticmethod
    def _set_seeds(seed: int) -> None:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

    def _log_metrics(self, metrics: dict[str, float]) -> None:
        try:
            mlflow.log_metrics(metrics, step=self.global_step)
        except Exception:
            return
