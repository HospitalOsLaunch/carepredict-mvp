"""Rank real planner proposals against an independent active-practice oracle."""

import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from statistics import mean

import numpy as np

from hospitalos.hybrid.planning import plan
from scripts.unit_planning.decision_challenge import FAMILIES, case, realizations, waiting_cost
from scripts.unit_planning.flow_validation import OUT


def key(actions):
    return tuple(sorted(a.key for a in actions))


def compare(args):
    family, index = args
    c = case(family, index)
    hidden = list(realizations(c))
    rows = []
    for budget in (1, 2):
        programs = c.programs(budget)
        costs = {key(pr): mean(waiting_cost(c, pr, world) for world in hidden) for pr in programs}
        proposal = plan(c.request(budget))
        if (
            proposal.decision == "abstain"
            or any(k.violations for k in proposal.candidates)
            or proposal.candidates_truncated
        ):
            raise RuntimeError((family, index, proposal.reasons))
        steps = proposal.bundle or (
            () if proposal.selected.kind == "no_op" else (proposal.selected,)
        )
        chosen = key(steps)
        if chosen not in costs:
            raise ValueError(("infeasible program", chosen))
        rule = next(p for p in programs if len(p) == budget)
        opt = min(costs.values())
        rows.append(
            {
                "family": family,
                "index": index,
                "budget": budget,
                "delay": c.team_delay,
                "ordinary": costs[()],
                "selected": costs[chosen],
                "rule": costs[key(rule)],
                "optimal": opt,
                "regret": costs[chosen] - opt,
                "rule_regret": costs[key(rule)] - opt,
                "near": costs[chosen] - opt <= 5,
                "harmful": costs[chosen] - costs[()] > 5,
                "active_gain": costs[()] - costs[chosen],
                "predicted_gain": next(x.saved_wait for x in proposal.windows if x.minutes == 720),
                "choices": len(programs),
                "chosen": list(chosen),
                "best": [list(k) for k, v in costs.items() if v == opt],
            }
        )
    return rows


def summary(rows):
    rng = np.random.default_rng(9341)
    groups = sorted({r["family"] for r in rows})
    regs = np.array(
        [[[r["regret"], r["rule_regret"]] for r in rows if r["family"] == g] for g in groups]
    )
    indexes = rng.integers(0, regs.shape[1], (2000, len(groups), regs.shape[1]))
    boot = regs[np.arange(len(groups))[None, :, None], indexes].mean(axis=(1, 2))
    avg, reference = regs.mean(axis=(0, 1))
    relative = 1 - avg / reference if reference > 0 else None
    ci = (
        np.quantile(1 - boot[:, 0] / boot[:, 1], [0.025, 0.975]).tolist()
        if (boot[:, 1] > 0).all()
        else None
    )
    near = mean(r["near"] for r in rows)
    harm = mean(r["harmful"] for r in rows)
    return {
        "n": len(rows),
        "regret": avg,
        "rule_regret": reference,
        "relative": relative,
        "ci95": ci,
        "near": near,
        "harmful": harm,
        "active_gain": mean(r["active_gain"] for r in rows),
        "passive_prediction": mean(r["predicted_gain"] for r in rows),
        "selections": dict(sorted(Counter("+".join(r["chosen"]) or "no_op" for r in rows).items())),
        "passed": bool(
            relative is not None
            and relative >= 0.1
            and ci
            and ci[0] > 0
            and near >= 0.8
            and harm <= 0.05
        ),
    }


def main():
    with ProcessPoolExecutor(max_workers=4) as pool:
        rows = [
            r
            for group in pool.map(compare, [(f, i) for f in FAMILIES for i in range(24)])
            for r in group
        ]
    summaries = [
        dict(
            family=f,
            budget=b,
            **summary([r for r in rows if r["budget"] == b and (f == "all" or r["family"] == f)]),
        )
        for b in (1, 2)
        for f in (*FAMILIES, "all")
    ]
    (OUT / "decisions.json").write_text(
        json.dumps({"summary": summaries, "contexts": rows}, indent=2, allow_nan=False) + "\n"
    )


if __name__ == "__main__":
    main()
