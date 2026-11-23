"""Decision-instant controllers and evaluation (DESIGN 5.3-5.4, NORM N2).

* Evaluation: true engine at tau, fresh realisations r in 1..4, U per candidate.
* Oracle (ceiling): U*(w) = min over the 16 candidates of U on each EVALUATION realisation itself
  (exact minimum, no tolerance; not part of the choice/evaluation disjunction).
* C_full: true engine + true current regime, choice realisations r in 101..108.
* C_param: PUBLIC engine + true theta, stationary regime, r in 101..108.
* C_pub-snap: PUBLIC engine + population-prior centre (theta and mechanism flags), stationary.
* Models: PUBLIC engine + ModelProvider, M sample keys (never r).
Selection: OBJ-LEX-1 on U (E[U] within 15 of best, then fewest accepted reinforcement hours, then
fewest interventions, then canonical order). C_full is an evaluated privileged controller, not a
certified optimum.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import numpy as np

from .generator import (
    PRIOR_CENTRE,
    EstablishmentSpec,
    TruthProvider,
    stationary_regime,
    true_regime_at,
)
from .rollout import rollout
from .world import Engine, Plan, candidates

EVAL_R = (1, 2, 3, 4)
CHOICE_R = tuple(range(101, 109))
TOLERANCE = 15.0


def planned_hours(p: Plan) -> int:
    return 0 if p.reinforcement == "none" else 4


def interventions(p: Plan) -> int:
    return int(p.coordinate) + int(p.cleaning != "fifo") + int(p.reinforcement != "none")


def obj_lex(mean_u: list[float]) -> int:
    cands = candidates()
    best = min(mean_u)
    ok = [i for i, v in enumerate(mean_u) if v <= best + TOLERANCE]
    return min(ok, key=lambda i: (planned_hours(cands[i]), interventions(cands[i]), i))


def prior_spec(spec: EstablishmentSpec) -> EstablishmentSpec:
    """Population-prior centre: theta centre and REF-mixture-centre mechanism flags (declared)."""
    return replace(
        spec,
        theta=dict(PRIOR_CENTRE),
        mech={
            "m2": True,
            "m2_common": False,
            "slow": 1.8,
            "m3_kappa": 0.35,
            "m5_drop": False,
            "simple": False,
        },
    )


def truth_u(
    engine: Engine,
    spec: EstablishmentSpec,
    r: int,
    anchor: dict[str, tuple[int, int]],
    plans: list[Plan],
) -> list[float]:
    prov = TruthProvider(spec, r, regime_anchor=anchor)
    return [rollout(engine, prov, p)["U"] for p in plans]


def evaluate_instant(
    ep: Any,
    tau: int,
    public_engine: Engine,
    model_choosers: dict[str, Callable[[], int]],
    plans: list[Plan] | None = None,
    controllers: tuple[str, ...] = ("C_full", "C_param"),
) -> dict[str, Any]:
    plans = plans or candidates()
    spec = ep.spec
    true_eng = ep.instants[tau]
    anchor_true = true_regime_at(ep, tau)
    eval_u = np.array([truth_u(true_eng, spec, r, anchor_true, plans) for r in EVAL_R])  # [4, 16]
    oracle = float(np.mean(eval_u.min(axis=1)))
    choices: dict[str, int] = {}
    if "C_full" in controllers:
        cu = np.array([truth_u(true_eng, spec, r, anchor_true, plans) for r in CHOICE_R]).mean(0)
        choices["C_full"] = obj_lex(list(cu))
    if "C_param" in controllers:
        cu = np.array(
            [
                truth_u(public_engine, spec, r, stationary_regime(spec, r, tau), plans)
                for r in CHOICE_R
            ]
        ).mean(0)
        choices["C_param"] = obj_lex(list(cu))
    if "C_pub_snap" in controllers:
        ps = prior_spec(spec)
        cu = np.array(
            [truth_u(public_engine, ps, r, stationary_regime(ps, r, tau), plans) for r in CHOICE_R]
        ).mean(0)
        choices["C_pub_snap"] = obj_lex(list(cu))
    for name, fn in model_choosers.items():
        choices[name] = fn()
    value = {name: float(eval_u[:, c].mean()) for name, c in choices.items()}
    value["habitual"] = float(eval_u[:, 0].mean())
    return {
        "tau": tau,
        "eval_u": eval_u.tolist(),
        "oracle_U_star": oracle,
        "choices": choices,
        "value": value,
    }


def model_choice(
    public_engine: Engine, providers: list[Any], plans: list[Plan] | None = None
) -> tuple[int, list[float], list[list[float]]]:
    """OBJ-LEX-1 on the model's mean U over its M providers (CRN across candidates)."""
    plans = plans or candidates()
    us = [[rollout(public_engine, prov, p)["U"] for p in plans] for prov in providers]
    mean_u = list(np.mean(np.array(us), axis=0))
    return obj_lex(mean_u), mean_u, us
