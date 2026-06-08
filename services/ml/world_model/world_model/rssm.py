"""Dreamer-style recurrent state-space model for hospital SIIPS dynamics."""

from __future__ import annotations

from dataclasses import asdict
from typing import TypedDict

import torch
from torch import Tensor, nn
from torch.distributions import Normal

from services.ml.world_model.config import RSSMConfig


class RSSMState(TypedDict):
    """Deterministic and stochastic latent state."""

    h: Tensor
    z: Tensor


class RSSMSequence(TypedDict):
    """Observed sequence unroll outputs."""

    h: list[Tensor]
    z: list[Tensor]


class HospitalRSSM(nn.Module):
    """Hybrid Gaussian RSSM with GRU deterministic state and stochastic latent."""

    def __init__(self, config: RSSMConfig | None = None) -> None:
        """Create the RSSM and all encoder, transition, prior, posterior and decoder modules."""
        super().__init__()
        self.config = config or RSSMConfig()
        self.obs_encoder = nn.Sequential(
            nn.Linear(self.config.obs_dim, self.config.hidden_dim),
            nn.SiLU(),
            nn.Linear(self.config.hidden_dim, self.config.hidden_dim),
            nn.SiLU(),
        )
        self.rnn = nn.GRUCell(
            self.config.action_dim + self.config.stoch_dim,
            self.config.deter_dim,
        )
        self.prior_net = nn.Sequential(
            nn.Linear(self.config.deter_dim, self.config.hidden_dim),
            nn.SiLU(),
            nn.Linear(self.config.hidden_dim, 2 * self.config.stoch_dim),
        )
        self.posterior_net = nn.Sequential(
            nn.Linear(self.config.deter_dim + self.config.hidden_dim, self.config.hidden_dim),
            nn.SiLU(),
            nn.Linear(self.config.hidden_dim, 2 * self.config.stoch_dim),
        )
        self.decoder_obs = nn.Sequential(
            nn.Linear(self.config.deter_dim + self.config.stoch_dim, self.config.hidden_dim),
            nn.SiLU(),
            nn.Linear(self.config.hidden_dim, self.config.obs_dim),
        )
        self.decoder_reward = nn.Sequential(
            nn.Linear(self.config.deter_dim + self.config.stoch_dim, self.config.hidden_dim),
            nn.SiLU(),
            nn.Linear(self.config.hidden_dim, 1),
        )

    def initial_state(self, batch_size: int, device: torch.device) -> RSSMState:
        """Return zero deterministic and stochastic states on the requested device."""
        dtype = next(self.parameters()).dtype
        return {
            "h": torch.zeros(batch_size, self.config.deter_dim, device=device, dtype=dtype),
            "z": torch.zeros(batch_size, self.config.stoch_dim, device=device, dtype=dtype),
        }

    def _dist_from_params(self, params: Tensor) -> Normal:
        """Build a diagonal Gaussian from concatenated mean and log-std parameters."""
        mean, raw_std = torch.chunk(params, chunks=2, dim=-1)
        std = torch.nn.functional.softplus(raw_std) + self.config.min_std
        return Normal(mean, std)

    def prior(self, h: Tensor) -> Normal:
        """Return the prior distribution p(z_t | h_t)."""
        return self._dist_from_params(self.prior_net(h))

    def posterior(self, h: Tensor, encoded_obs: Tensor) -> Normal:
        """Return the posterior distribution q(z_t | h_t, o_t)."""
        posterior_input = torch.cat([h, encoded_obs], dim=-1)
        return self._dist_from_params(self.posterior_net(posterior_input))

    def observe_step(
        self,
        prev_state: RSSMState,
        prev_action: Tensor,
        obs: Tensor,
    ) -> tuple[RSSMState, Normal, Normal]:
        """Advance one observed step using the posterior conditioned on the observation."""
        recurrent_input = torch.cat([prev_action, prev_state["z"]], dim=-1)
        h = self.rnn(recurrent_input, prev_state["h"])
        prior_dist = self.prior(h)
        encoded_obs = self.obs_encoder(obs)
        posterior_dist = self.posterior(h, encoded_obs)
        z = posterior_dist.rsample() if self.training else posterior_dist.mean
        return {"h": h, "z": z}, prior_dist, posterior_dist

    def imagine_step(self, prev_state: RSSMState, action: Tensor) -> tuple[RSSMState, Normal]:
        """Advance one imagined future step from the prior without observing future SIIPS."""
        recurrent_input = torch.cat([action, prev_state["z"]], dim=-1)
        h = self.rnn(recurrent_input, prev_state["h"])
        prior_dist = self.prior(h)
        z = prior_dist.rsample() if self.training else prior_dist.mean
        return {"h": h, "z": z}, prior_dist

    def decode(self, state: RSSMState) -> tuple[Tensor, Tensor]:
        """Decode observation and reward predictions from a latent state."""
        latent = torch.cat([state["h"], state["z"]], dim=-1)
        obs_pred = self.decoder_obs(latent)
        reward_pred = self.decoder_reward(latent)
        return obs_pred, reward_pred

    def observe_sequence(
        self,
        history_obs: Tensor,
        history_actions: Tensor,
    ) -> tuple[RSSMSequence, list[Normal], list[Normal]]:
        """Teacher-force a complete observed history and return states and distributions."""
        if history_obs.ndim != 3:
            raise ValueError("history_obs must have shape [batch, time, obs_dim]")
        if history_actions.ndim != 3:
            raise ValueError("history_actions must have shape [batch, time, action_dim]")
        if history_obs.shape[0] != history_actions.shape[0]:
            raise ValueError("history_obs and history_actions batch dimensions must match")
        if history_obs.shape[1] != history_actions.shape[1]:
            raise ValueError("history_obs and history_actions time dimensions must match")

        batch_size = int(history_obs.shape[0])
        device = history_obs.device
        state = self.initial_state(batch_size=batch_size, device=device)
        states: RSSMSequence = {"h": [], "z": []}
        priors: list[Normal] = []
        posteriors: list[Normal] = []
        for step_index in range(int(history_obs.shape[1])):
            state, prior_dist, posterior_dist = self.observe_step(
                prev_state=state,
                prev_action=history_actions[:, step_index, :],
                obs=history_obs[:, step_index, :],
            )
            states["h"].append(state["h"])
            states["z"].append(state["z"])
            priors.append(prior_dist)
            posteriors.append(posterior_dist)
        return states, priors, posteriors

    def config_dict(self) -> dict[str, int | float]:
        """Return a primitive dictionary representation of the architecture config."""
        return asdict(self.config)
