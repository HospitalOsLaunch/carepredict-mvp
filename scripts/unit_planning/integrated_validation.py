"""Independent action contest with the residence profile active at the real plan entry point."""

import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import timedelta
from random import Random
from statistics import mean

from hospitalos.hybrid.models import Bed, Discharge, FactEvent, Patient, Unit
from hospitalos.hybrid.outlook import Emergency, UnitOutlook
from hospitalos.hybrid.planning import plan
from hospitalos.hybrid.synthetic_outlook import synthetic_outlook
from scripts.unit_planning.decision_challenge import D, case, realizations, waiting_cost
from scripts.unit_planning.decision_validation import key
from scripts.unit_planning.flow_validation import OUT

UNIT = "medecine-polyvalente"
ORIGIN = D - timedelta(hours=3)


def request(c, budget, profile):
    req = c.request(budget, unit=UNIT, origin=ORIGIN)
    events = []
    for event in req.events:
        if isinstance(event.fact, Unit):
            event = event.model_copy(
                update={"fact": event.fact.model_copy(update={"staffed_beds": 4})}
            )
        events.append(event)
    age = c.index % 3 + 1
    entered = ORIGIN - timedelta(days=age) + timedelta(hours=6)
    resident = Patient(
        id="resident",
        status="admitted",
        bed_id="D",
        medically_cleared=False,
        compatible_units=(UNIT,),
        waiting_since=entered - timedelta(minutes=40),
    )
    facts = [
        Bed(id="D", unit_id=UNIT, state="occupied", occupant="resident", capabilities=("oxygen",)),
        resident,
        Discharge(
            id="resident",
            documents_ready=True,
            escort_required=False,
            transport_required=False,
            downstream_required=False,
        ),
    ]

    def event_for(f):
        return FactEvent(
            hospital_id=req.hospital_id,
            event_id=f.kind + ":" + f.id,
            source="synthetic_public",
            event_time=ORIGIN,
            available_at=ORIGIN,
            fact=f,
        )

    events.extend(event_for(f) for f in facts)
    with_resident = req.model_copy(
        update={"events": tuple(events), "expected_entities": tuple(e.event_id for e in events)}
    )
    outlook = synthetic_outlook(
        with_resident.state(),
        UNIT,
        admission_times={"out": ORIGIN - timedelta(days=2), "resident": entered}
        if profile
        else None,
    )
    feeds = tuple(
        f.model_copy(
            update={
                "records": tuple(
                    r.model_copy(update={"counts": (c.index // 3 % 3,)}) for r in f.records
                )
            }
        )
        if isinstance(f, Emergency)
        else f
        for f in outlook.feeds
    )
    events.append(event_for(UnitOutlook(id=UNIT, feeds=feeds)))
    return req.model_copy(
        update={"events": tuple(events), "expected_entities": tuple(e.event_id for e in events)}
    )


def run_context(index):
    c = case("transport_cleaning", index)
    augmented = replace(c, beds=(*c.beds, ("D", "occupied", True)), initial_capacity=4)
    latent = []
    age = index % 3 + 1
    for j, w in enumerate(realizations(augmented)):
        rng = Random(691000 + 10 * index + j)
        length = rng.choice([d for d in (1, 2, 2, 3, 4, 5) if d >= age])
        exit_at = 90 + rng.randrange(60) if age == length else None
        arrivals = tuple(rng.randrange(90, 990) for _ in range(index // 3 % 3))
        latent.append((w, exit_at, arrivals))
    rows = []
    for budget in (1, 2):
        costs = {
            key(program): mean(
                waiting_cost(augmented, program, w, resident_exit=departure, emergency=arrivals)
                for w, departure, arrivals in latent
            )
            for program in c.programs(budget)
        }
        best = min(costs.values())
        row = {"index": index, "budget": budget, "ordinary": costs[()], "optimum": best}
        for profile, label in ((False, "historical"), (True, "cohort")):
            p = plan(request(c, budget, profile), research_cohort_ranking=profile)
            if (
                p.decision == "abstain"
                or p.candidates_truncated
                or any(x.violations for x in p.candidates)
                or ("research_cohort_ranking" in p.warnings) != profile
            ):
                raise ValueError((index, profile, p.reasons))
            actions = p.bundle or (() if p.selected.kind == "no_op" else (p.selected,))
            chosen = key(actions)
            row[label] = list(chosen)
            row[label + "_regret"] = costs[chosen] - best
            row[label + "_gain"] = costs[()] - costs[chosen]
        rows.append(row)
    return rows


def main():
    with ProcessPoolExecutor(max_workers=4) as pool:
        rows = [r for group in pool.map(run_context, range(48, 72)) for r in group]
    metrics = []
    for limit in (1, 2):
        q = [r for r in rows if r["budget"] == limit]
        metrics.append(
            {
                "budget": limit,
                "contexts": len(q),
                "changed": sum(r["historical"] != r["cohort"] for r in q),
                "improved": sum(r["cohort_regret"] < r["historical_regret"] for r in q),
                "degraded": sum(r["cohort_regret"] > r["historical_regret"] for r in q),
                **{
                    k: mean(r[k] for r in q)
                    for k in (
                        "historical_regret",
                        "cohort_regret",
                        "historical_gain",
                        "cohort_gain",
                    )
                },
            }
        )
    (OUT / "integrated.json").write_text(
        json.dumps({"summary": metrics, "contexts": rows}, indent=2, allow_nan=False) + "\n"
    )


if __name__ == "__main__":
    main()
