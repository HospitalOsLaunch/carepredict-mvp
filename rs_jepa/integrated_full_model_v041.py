"""Four-channel V0.4.1 model factory. No forward or training on import.

This is an explicit *untrained assembly* from the existing RS-JEPA
architecture; it is NOT a checkpoint migration or a learning recipe.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research_lab.integrated_full_model_v1_contract import (
    make_v041_synthetic_spec,
    validate_against_stage1,
)
from research_lab.s0b_four_channel_bridge import with_v041_action_dim
from rs_jepa.config import Stage1Config
from rs_jepa.integrated_full_model_v1 import IntegratedFullModelV1


@dataclass(frozen=True)
class NativeV041Assembly:
    model: IntegratedFullModelV1
    stage1: Stage1Config
    action_channels: tuple[str, ...]
    trained: bool = False


def assemble_v041_untrained(
    *,
    stage1: Stage1Config,
    spec: dict[str, Any] | None = None,
) -> NativeV041Assembly:
    """Instantiate random-initialized, four-channel modules, no forward.

    No old 2-channel checkpoint can be loaded by this factory. Each assembly
    has new random parameters until a separate authorized training run occurs.
    """
    candidate = make_v041_synthetic_spec() if spec is None else spec
    four = with_v041_action_dim(stage1)
    validate_against_stage1(candidate, four)
    model = IntegratedFullModelV1(spec=candidate, stage1=four)
    return NativeV041Assembly(
        model=model, stage1=four,
        action_channels=tuple(candidate["action_features"]),
    )
