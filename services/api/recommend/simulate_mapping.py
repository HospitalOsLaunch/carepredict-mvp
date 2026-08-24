"""Gate B lever-to-simulation mapping for action counterfactuals.

Only levers with a clean ``ActionStep`` channel are mapped to real
counterfactuals. Levers that need missing capacity or workflow channels remain
honest Gate A heuristics until the model input space supports them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from services.api.schemas.actions import ActionLever
from services.api.schemas.simulate import ActionStep

SimulationMode = Literal["counterfactual", "heuristic"]

PRIORITIZE_DISCHARGE_TOTAL = 16

HEURISTIC_LEVERS: frozenset[ActionLever] = frozenset(
    {"move_staff", "open_beds", "close_beds", "rebalance_workload"}
)


@dataclass(frozen=True, slots=True)
class LeverSimulationPlan:
    """Simulation plan for one recommendation lever."""

    mode: SimulationMode
    actions: list[ActionStep]
    rationale: str


def zero_action_steps(horizon_h: int) -> list[ActionStep]:
    """Return a zero-intervention baseline action sequence."""
    return [_action_step() for _ in range(horizon_h)]


def action_plan_for_lever(lever: ActionLever, horizon_h: int) -> LeverSimulationPlan:
    """Map an action lever to auditable intervention magnitudes.

    Gate B real counterfactuals are limited to the world-model action channels:
    discharges and staff redeployments. Capacity and ambiguous workflow levers
    remain heuristic because no clean model input channel exists yet.
    """
    if lever == "prioritize_discharge":
        actions = zero_action_steps(horizon_h)
        for index in range(min(PRIORITIZE_DISCHARGE_TOTAL, horizon_h)):
            actions[index] = actions[index].model_copy(update={"scheduled_discharges": 1})
        return LeverSimulationPlan(
            mode="counterfactual",
            actions=actions,
            rationale=(
                f"Counterfactual schedules {min(PRIORITIZE_DISCHARGE_TOTAL, horizon_h)} "
                "additional confirmed discharges across the horizon."
            ),
        )
    if lever == "move_staff":
        return LeverSimulationPlan(
            mode="heuristic",
            actions=[],
            rationale=(
                "move_staff is kept heuristic in Gate B: live direction sanity showed "
                "the current world model associates staff redeployment with higher load."
            ),
        )
    return LeverSimulationPlan(
        mode="heuristic",
        actions=[],
        rationale=(
            f"{lever} has no clean ActionStep channel in Gate B; returning Gate A heuristic impact."
        ),
    )


def _action_step() -> ActionStep:
    return ActionStep(
        scheduled_admissions=0,
        scheduled_discharges=0,
        staff_redeployments=0,
        scheduled_surgeries=0,
        expected_transfers=0,
    )
