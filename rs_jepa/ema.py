"""EMA target encoder utilities for RS-JEPA."""

from __future__ import annotations

import copy
from typing import Any, cast

import torch
from torch import Tensor, nn


def tau_schedule(step: int, ramp_steps: int, start: float = 0.996, end: float = 0.9999) -> float:
    """Linear monotonic EMA tau ramp."""

    if ramp_steps <= 0:
        return float(end)
    progress = min(max(step, 0) / float(ramp_steps), 1.0)
    return float(start + (end - start) * progress)


class EMATargetEncoder(nn.Module):
    """Structural EMA copy of an online encoder with a stop-gradient forward."""

    def __init__(self, online_encoder: nn.Module) -> None:
        super().__init__()
        self.target = copy.deepcopy(online_encoder)
        self.target.eval()
        for param in self.target.parameters():
            param.requires_grad_(False)

    @torch.no_grad()
    def update_from(self, online_encoder: nn.Module, tau: float) -> None:
        target_params = dict(self.target.named_parameters())
        online_params = dict(online_encoder.named_parameters())
        if target_params.keys() != online_params.keys():
            raise ValueError("L'encodeur online et la cible EMA n'ont pas la même structure.")
        for name, target_param in target_params.items():
            target_param.mul_(tau).add_(online_params[name].detach(), alpha=1.0 - tau)
        target_buffers = dict(self.target.named_buffers())
        online_buffers = dict(online_encoder.named_buffers())
        for name, target_buffer in target_buffers.items():
            if name in online_buffers and target_buffer.shape == online_buffers[name].shape:
                target_buffer.copy_(online_buffers[name].detach())

    @torch.no_grad()
    def forward(self, *args: Any, **kwargs: Any) -> Tensor:
        self.target.eval()
        return cast(Tensor, self.target(*args, **kwargs))
