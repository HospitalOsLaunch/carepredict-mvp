"""Routing policy of the computer-use agent: which engine handles which task, at what cost.

Engines, cheapest and most controllable first:

* ``playbook``     deterministic Playwright script for a known portal: no model, no cost,
                   no data leaves the agent's machine. Always tried first when it exists.
* ``open_light``   open-weight vision model served by vLLM on infrastructure you control
                   (default: H Company Holo4-35B-A3B, Apache-2.0, ~3B active parameters).
* ``open_heavy``   larger open-weight model on the same kind of endpoint
                   (default: Xiaomi MiMo-V2.6-Flash, MIT, heavy to serve).
* ``closed_fast``  Anthropic Claude Sonnet 5.5 through the computer use toolset.
* ``closed_best``  Anthropic Claude Opus 5.5, best published OSWorld 2.0 score (Sep. 2026).

Defaults are deliberately safe: only the playbook is enabled, and no model engine is
allowed to see screens with identifiable patient data until an administrator confirms
that its hosting and contract allow it (HDS hosting, or a provider contract covering it).
Prices are editable because they change: defaults are the public list prices at the
time of writing (Anthropic models overview, Oct. 2026) and 0 for self-hosted engines,
whose GPU hour cost the group must enter.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TASK_KINDS = ("sync_inbox", "reply_portal")
ENGINE_NAMES = ("playbook", "open_light", "open_heavy", "closed_fast", "closed_best")

EngineKind = Literal["playbook", "openai_compatible", "anthropic"]


class EnginePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    kind: EngineKind
    enabled: bool = False
    model: str | None = None
    open_weights: bool = False
    identifiable_data_allowed: bool = False
    input_usd_per_mtok: float = Field(default=0.0, ge=0)
    output_usd_per_mtok: float = Field(default=0.0, ge=0)
    usd_per_hour: float = Field(default=0.0, ge=0)
    min_calibration: float | None = Field(default=None, ge=0, le=1)


class AgentPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engines: dict[str, EnginePolicy]
    routes: dict[str, list[str]]
    daily_budget_usd: float = Field(default=20.0, ge=0)
    task_budget_usd: dict[str, float] = Field(default_factory=dict)
    sync_interval_minutes: int = Field(default=10, ge=1, le=1440)
    max_attempts: int = Field(default=3, ge=1, le=10)
    write_requires_verification: bool = True

    @model_validator(mode="after")
    def _consistent(self) -> AgentPolicy:
        unknown_engines = set(self.engines) - set(ENGINE_NAMES)
        if unknown_engines:
            raise ValueError(f"moteurs inconnus : {sorted(unknown_engines)}")
        for kind, chain in self.routes.items():
            if kind not in TASK_KINDS:
                raise ValueError(f"type de tâche inconnu : {kind}")
            missing = [e for e in chain if e not in self.engines]
            if missing:
                raise ValueError(f"route {kind} : moteurs absents {missing}")
        if not self.write_requires_verification:
            raise ValueError(
                "la vérification indépendante des écritures sur le portail "
                "ne peut pas être désactivée"
            )
        return self


def default_policy() -> AgentPolicy:
    return AgentPolicy(
        engines={
            "playbook": EnginePolicy(
                label="Script déterministe (Playwright)",
                kind="playbook",
                enabled=True,
                identifiable_data_allowed=True,
            ),
            "open_light": EnginePolicy(
                label="Open source léger (Holo4-35B-A3B, auto-hébergé)",
                kind="openai_compatible",
                model="Hcompany/Holo4-35B-A3B",
                open_weights=True,
                min_calibration=0.9,
            ),
            "open_heavy": EnginePolicy(
                label="Open source puissant (MiMo-V2.6-Flash, auto-hébergé)",
                kind="openai_compatible",
                model="XiaomiMiMo/MiMo-V2.6-Flash",
                open_weights=True,
                min_calibration=0.9,
            ),
            "closed_fast": EnginePolicy(
                label="Claude Sonnet 5.5 (computer use)",
                kind="anthropic",
                model="claude-sonnet-5-5",
                input_usd_per_mtok=2.0,
                output_usd_per_mtok=10.0,
            ),
            "closed_best": EnginePolicy(
                label="Claude Opus 5.5 (computer use)",
                kind="anthropic",
                model="claude-opus-5-5",
                input_usd_per_mtok=4.0,
                output_usd_per_mtok=20.0,
            ),
        },
        routes={
            "sync_inbox": ["playbook", "open_light", "closed_fast"],
            "reply_portal": ["playbook", "open_heavy", "closed_best"],
        },
        task_budget_usd={"sync_inbox": 0.5, "reply_portal": 1.0},
    )


def parse_policy(raw: str | None) -> AgentPolicy:
    if not raw or raw.strip() in ("", "{}"):
        return default_policy()
    return AgentPolicy.model_validate_json(raw)
