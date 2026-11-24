"""Independent nominal and practice-matched contrast measurement on fresh contexts."""

import json
from concurrent.futures import ProcessPoolExecutor
from statistics import mean

from hospitalos.hybrid.planning import plan
from scripts.unit_planning.decision_challenge import (
    FAMILIES,
    booking_outcome,
    case,
    realizations,
    waiting_cost,
)
from scripts.unit_planning.flow_validation import OUT


def direction(value):
    return int(value > 5) - int(value < -5)


def compare(args):
    family, index = args
    c = case(family, index)
    draws = list(realizations(c))
    rows = []
    for budget in (1, 2):
        proposal = plan(c.request(budget))
        if proposal.decision == "abstain" or any(x.violations for x in proposal.candidates):
            raise ValueError((family, index, proposal.reasons))
        actions = proposal.bundle or (
            () if proposal.selected.kind == "no_op" else (proposal.selected,)
        )
        predicted = next(w.saved_wait for w in proposal.windows if w.minutes == 720)
        ordinary = [waiting_cost(c, (), w, active=False) for w in draws]
        now = [waiting_cost(c, actions, w, active=False) for w in draws]
        active = mean(waiting_cost(c, (), w) - waiting_cost(c, actions, w) for w in draws)
        nominal = mean(ordinary) - mean(now)
        r = {
            "family": family,
            "index": index,
            "budget": budget,
            "nominal": nominal,
            "active": active,
            "predicted": predicted,
            "matched": None,
            "matched_prediction": None,
            "low": None,
            "high": None,
            "inside": None,
            "active_inside": None,
            "pressure_extra": None,
            "stress_gain": None,
        }
        practice = proposal.team_practice
        if actions and practice and practice.supported:
            lines = [p for p in practice.cases if p.delay_minutes == c.team_delay]
            if len(lines) != 2:
                raise ValueError("Both preparation conventions required")
            low, high = min(p.saved_wait for p in lines), max(p.saved_wait for p in lines)
            convention = "already_started" if c.already_preparing else "after_request"
            estimate = next(p.saved_wait for p in lines if p.preparation == convention)
            effect = mean(
                waiting_cost(
                    c,
                    actions,
                    w,
                    active=False,
                    gesture_at=c.team_delay,
                    preparing=c.already_preparing,
                )
                - current
                for w, current in zip(draws, now, strict=True)
            )
            r.update(
                matched=effect,
                matched_prediction=estimate,
                low=low,
                high=high,
                inside=low <= effect <= high,
                active_inside=low <= active <= high,
            )
        if family == "staff_booking":
            kinds = {a.kind for a in actions}
            ordinary_shock = [booking_outcome(c, set(), w, shock=True) for w in draws]
            action_shock = [booking_outcome(c, kinds, w, shock=True) for w in draws]
            r.update(
                pressure_extra=mean(
                    a[1] - b[1] for a, b in zip(action_shock, ordinary_shock, strict=True)
                ),
                stress_gain=mean(
                    b[0] - a[0] for a, b in zip(action_shock, ordinary_shock, strict=True)
                ),
            )
        rows.append(r)
    return rows


def summary(group):
    supported = [r for r in group if r["inside"] is not None]
    stressed = [r for r in group if r["pressure_extra"] is not None]
    return {
        "n": len(group),
        "nominal_mae": mean(abs(r["nominal"] - r["predicted"]) for r in group),
        "nominal_sign": mean(direction(r["nominal"]) == direction(r["predicted"]) for r in group),
        "intervals": len(supported),
        "matched_covered": sum(r["inside"] for r in supported),
        "active_covered": sum(r["active_inside"] for r in supported),
        "matched_mae": mean(abs(r["matched"] - r["matched_prediction"]) for r in supported)
        if supported
        else None,
        "matched_sign": mean(
            direction(r["matched"]) == direction(r["matched_prediction"]) for r in supported
        )
        if supported
        else None,
        "stress_n": len(stressed),
        "stress_worse": sum(r["pressure_extra"] > 0 for r in stressed),
        "stress_pressure": mean(r["pressure_extra"] for r in stressed) if stressed else None,
    }


def main():
    with ProcessPoolExecutor(max_workers=4) as pool:
        rows = [
            r
            for group in pool.map(compare, [(f, i) for f in FAMILIES for i in range(24, 48)])
            for r in group
        ]
    data = [
        dict(
            family=f,
            budget=b,
            **summary([r for r in rows if r["budget"] == b and (f == "all" or r["family"] == f)]),
        )
        for b in (1, 2)
        for f in (*FAMILIES, "all")
    ]
    (OUT / "gain_quality.json").write_text(
        json.dumps({"summary": data, "contexts": rows}, indent=2, allow_nan=False) + "\n"
    )


if __name__ == "__main__":
    main()
