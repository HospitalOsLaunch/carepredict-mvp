"""Manual mode = constraints on the SAME candidate generator and operator (DESIGN 1.4; T-LIFE-04/05).

Locks restrict the 16-candidate universe (same code path, never a separate route). A hypothesis
that is not publicly authorised (e.g. "suppose stay S is authorised now") is simulable on a
cloned engine but the result is marked approvable=False; it never changes the real state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .rollout import rollout
from .world import Engine, Plan, candidates


@dataclass(frozen=True)
class Locks:
    coordinate: bool | None = None
    cleaning: str | None = None
    reinforcement: str | None = None


@dataclass
class Hypothesis:
    authorise: list[str] = field(default_factory=list)


def manual_universe(locks: Locks) -> list[Plan]:
    out = []
    for p in candidates():
        if locks.coordinate is not None and p.coordinate != locks.coordinate:
            continue
        if locks.cleaning is not None and p.cleaning != locks.cleaning:
            continue
        if locks.reinforcement is not None and p.reinforcement != locks.reinforcement:
            continue
        out.append(p)
    return out


def simulate_hypothesis(engine: Engine, plan: Plan, hyp: Hypothesis, prov: Any) -> dict[str, Any]:
    eng = engine.clone()
    for sid in hyp.authorise:
        st = eng.stays.get(sid)
        if st is not None and not st.authorised and st.departed is None:
            st.auth_tick = eng.tick  # hypothetical authorisation, simulation only
    res = rollout(eng, prov, plan)
    res["approvable"] = not hyp.authorise
    res["hypothetical"] = bool(hyp.authorise)
    return res
