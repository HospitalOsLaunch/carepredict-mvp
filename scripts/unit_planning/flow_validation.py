"""Prospective synthetic flow comparison. Optional origin CSV permits independent reanalysis."""

import argparse
import csv
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from functools import partial
from pathlib import Path
from statistics import mean

from hospitalos.hybrid.flow_clock import VERSION
from hospitalos.hybrid.models import Action
from hospitalos.hybrid.multiday import PROFILE, paired_future
from hospitalos.hybrid.outlook import Emergency, horizon_check
from hospitalos.hybrid.scenarios import FutureArrival
from hospitalos.hybrid.scoring import score
from hospitalos.hybrid.simulation import Assumptions, simulate
from scripts.unit_planning import benchmark as bank

OUT = bank.ROOT / "docs/operational/unit-flow-v2"
RECEIPT = bank.ROOT / "src/hospitalos/hybrid/unit_flow_v2_receipt.json"
DAYS = bank.HORIZONS
MODES = ("historical_short", "historical_published", "cohort_v2")


FACTORS = ("neither", "published_ed", "cohort_exits", "both")


def study(index, *, factorial=False):
    world = (500 if factorial else 400) + index
    samples, outcomes, coverage = [], [], []
    for u, unit in enumerate(bank.UNITS):
        cap = 7 + u + world % 3
        stays, emergency = bank.truth(u, world, cap)
        census = {
            d: {s.bed: (s.pid, s.start) for s in stays if s.start <= bank.clock(d, 8, 30) < s.end}
            for d in range(65)
        }
        for d in bank.ORIGINS:
            prior = bank.public_state(d, u, world, cap, census[d])
            new = bank.public_state(d, u, world, cap, census[d], cohort=True)
            audit = horizon_check(new, unit, 7)
            assert audit.data_ready
            dates = next(f for f in audit.feeds if f.kind == "departures")
            coverage.append((unit, dates.covered, dates.expected))
            ed = next(f for f in new.outlooks[0].feeds if isinstance(f, Emergency))
            for h in DAYS:
                t = d + h
                target_day = bank.FIRST + bank.timedelta(days=t)
                expected_ed = mean(next(row.counts for row in ed.records if row.day == target_day))
                outcomes.append(
                    (
                        index,
                        unit,
                        d,
                        h,
                        "emergency",
                        expected_ed,
                        emergency[t],
                        emergency[d - 1],
                        emergency[t - (14 if h == 7 else 7)],
                    )
                )
            for mode in FACTORS if factorial else MODES:
                new_model = factorial or mode == "cohort_v2"
                state = new if new_model else prior
                short = mode == "historical_short"
                horizons = (1,) if short else DAYS
                flows = defaultdict(list)
                for sc in range(bank.SCENARIOS):
                    limit = 1440 * max(horizons)
                    tape = paired_future(state, None, 41, sc, limit, multiday=not short)
                    assert bool(tape.cohort) == new_model
                    if factorial:
                        tape = replace(
                            tape,
                            events=tuple(
                                e
                                for e in tape.events
                                if not isinstance(e, FutureArrival)
                                or not e.id.startswith("ed:")
                                or mode in {"published_ed", "both"}
                            ),
                            cohort=tape.cohort if mode in {"cohort_exits", "both"} else None,
                        )
                    path = simulate(
                        state,
                        Action(kind="no_op"),
                        Assumptions(),
                        seed=41,
                        scenario=sc,
                        horizon_minutes=limit,
                        future=tape,
                        multiday=not short,
                    )
                    checks = score(state, path, expected_future=tape)
                    if checks.violations:
                        raise ValueError(checks.violations)
                    for h in horizons:
                        events = [e.kind for e in path.events if e.minute <= 1440 * h]
                        arrivals = events.count("admit")
                        exits = events.count("depart") + events.count("forecast_depart")
                        flows[h].append((arrivals, exits))
                for h in horizons:
                    t = d + h
                    arrivals, exits = [mean(column) for column in zip(*flows[h], strict=True)]
                    lo, hi = state.at, bank.clock(t, 8, 30)
                    admitted = sum(lo < s.start <= hi for s in stays)
                    departed = sum(lo < s.end <= hi for s in stays)
                    actual = len(census[t])
                    assert len(census[d]) + admitted - departed == actual
                    projected = len(census[d]) + arrivals - exits
                    samples.append(
                        (
                            world,
                            unit,
                            d,
                            h,
                            mode,
                            projected,
                            actual,
                            arrivals,
                            admitted,
                            exits,
                            departed,
                        )
                    )
                    if new_model:
                        outcomes.append(
                            (
                                index,
                                unit,
                                d,
                                h,
                                "occupied",
                                projected,
                                actual,
                                len(census[d]),
                                len(census[t - 7]),
                            )
                        )
    return samples, outcomes, coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rows", type=Path)
    parser.add_argument("--factorial", action="store_true", help="Separate attribution lot 500–507")
    args = parser.parse_args()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        pieces = list(pool.map(partial(study, factorial=args.factorial), range(bank.UNIVERSES)))
    samples, outcomes, coverage = ([row for part in pieces for row in part[i]] for i in range(3))
    if args.rows:
        with args.rows.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                (
                    "world",
                    "unit",
                    "origin",
                    "days",
                    "mode",
                    "occupancy",
                    "actual_occupancy",
                    "admissions",
                    "actual_admissions",
                    "exits",
                    "actual_exits",
                )
            )
            w.writerows(samples)
    gates, qualified = bank.summarise(outcomes) if not args.factorial else ([], {})
    date_coverage = {
        u: sum(r[1] for r in coverage if r[0] == u) / sum(r[2] for r in coverage if r[0] == u)
        for u in bank.UNITS
    }
    for u in bank.UNITS:
        if date_coverage[u] < 0.90:
            qualified[u] = []
    comparisons = []
    for scope in (*bank.UNITS, "all_units"):
        for h in DAYS:
            for mode in FACTORS if args.factorial else MODES:
                rows = [
                    r
                    for r in samples
                    if (scope == "all_units" or r[1] == scope) and r[3:5] == (h, mode)
                ]
                if rows:
                    comparisons.append(
                        {
                            "unit": scope,
                            "days": h,
                            "mode": mode,
                            "origins": len(rows),
                            "occupancy_mae": mean(abs(r[5] - r[6]) for r in rows),
                            "occupancy_bias": mean(r[5] - r[6] for r in rows),
                            "admissions": mean(r[7] for r in rows),
                            "actual_admissions": mean(r[8] for r in rows),
                            "departures": mean(r[9] for r in rows),
                            "actual_departures": mean(r[10] for r in rows),
                            "admissions_mae": mean(abs(r[7] - r[8]) for r in rows),
                            "departures_mae": mean(abs(r[9] - r[10]) for r in rows),
                            "admissions_bias": mean(r[7] - r[8] for r in rows),
                            "departures_bias": mean(r[9] - r[10] for r in rows),
                        }
                    )
    if args.factorial:
        (OUT / "factorial.json").write_text(
            json.dumps(
                {"worlds": list(range(500, 508)), "comparisons": comparisons},
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
        return
    receipt = {
        "forecast_version": VERSION,
        "profile": PROFILE,
        "synthetic_only": True,
        "qualified_days": qualified,
        "source_protocol": "docs/operational/unit-flow-v2/PROTOCOL.md",
    }
    for path, payload in (
        (RECEIPT, receipt),
        (
            OUT / "flows.json",
            {
                "receipt": receipt,
                "worlds": list(range(400, 408)),
                "coverage": date_coverage,
                "comparisons": comparisons,
                "gates": gates,
            },
        ),
    ):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
