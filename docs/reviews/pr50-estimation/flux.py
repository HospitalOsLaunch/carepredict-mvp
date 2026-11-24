"""Audit agrégé des flux de la PR 50, à lancer depuis la racine du dépôt."""

from __future__ import annotations

import csv
import json
import subprocess
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import mean

import numpy as np
from hospitalos.hybrid.models import Action
from hospitalos.hybrid.multiday import paired_future
from hospitalos.hybrid.scenarios import FutureArrival, FutureTape
from hospitalos.hybrid.scoring import score
from hospitalos.hybrid.simulation import Assumptions, simulate
from scripts.unit_planning import benchmark as bank

SHA = "85a8ee794ac8952c134cd01e21d691103eb23d3e"
DAY = 1440
NOOP = Action(kind="no_op")


def verify_revision():
    rev = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if rev != SHA:
        raise ValueError("Le rejeu requiert le commit " + SHA)
    subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            SHA,
            "--",
            "src/hospitalos/hybrid",
            "scripts/unit_planning",
            "web/src/fixtures",
        ],
        check=True,
    )


def one_world(world):
    records = []
    for u, uid in enumerate(bank.UNITS):
        cap = 7 + u + world % 3
        stays, _ = bank.truth(u, world, cap)
        for d in bank.ORIGINS:
            origin = bank.clock(d, 8, 30)
            present = {
                s.bed: (s.pid, s.start) for s in stays if s.start <= origin < s.end
            }
            state = bank.public_state(d, u, world, cap, present)
            cleared = {p.id for p in state.patients if p.medically_cleared is True}
            inputs = {p.id for p in state.patients if p.status == "admitted"}
            waiting = sum(p.status == "waiting" for p in state.patients)
            needs_transport = sum(
                x.transport_required is True for x in state.discharges
            )
            draws = defaultdict(list)
            for n in range(bank.SCENARIOS):
                ts = paired_future(state, None, 41, n, DAY, multiday=False)
                tl = paired_future(state, None, 41, n, 7 * DAY, multiday=True)
                ed = [
                    event
                    for event in tl.events
                    if isinstance(event, FutureArrival)
                    and event.id.startswith("ed:")
                    and event.minute <= DAY
                ]
                plus_ed = FutureTape(
                    origin,
                    tuple(sorted((*ts.events, *ed), key=lambda e: (e.minute, e.id))),
                )
                choices = (
                    ("court", ts, False, DAY),
                    ("court_urgences", plus_ed, False, DAY),
                    ("court_dates", ts, True, DAY),
                    ("court_urgences_dates", plus_ed, True, DAY),
                    ("long", tl, True, 7 * DAY),
                )
                for mode, tape, multi, horizon in choices:
                    trajectory = simulate(
                        state,
                        NOOP,
                        Assumptions(),
                        seed=41,
                        scenario=n,
                        horizon_minutes=horizon,
                        future=tape,
                        multiday=multi,
                    )
                    checked = score(state, trajectory, expected_future=tape)
                    assert not checked.violations, checked.violations
                    for h in bank.HORIZONS if mode == "long" else (1,):
                        events = [x for x in trajectory.events if x.minute <= h * DAY]
                        admitted = sum(e.kind == "admit" for e in events)
                        departed = [e.patient_id for e in events if e.kind == "depart"]
                        assert all(p in inputs for p in departed)
                        assert all(p in cleared for p in departed)
                        draws[mode, h].append((admitted, len(departed)))
            # Future values below are used only for scoring and are never passed into simulate().
            for (mode, h), samples in draws.items():
                end = bank.clock(d + h, 8, 30)
                actual_admits = sum(origin < s.start <= end for s in stays)
                actual_departs = [s for s in stays if origin < s.end <= end]
                actual_new_exits = sum(s.start > origin for s in actual_departs)
                actual_uncleared_exits = sum(
                    s.start <= origin and s.pid not in cleared for s in actual_departs
                )
                actual_initial_cleared_exits = (
                    len(actual_departs) - actual_new_exits - actual_uncleared_exits
                )
                actual_census = sum(s.start <= end < s.end for s in stays)
                before = len(present)
                assert before + actual_admits - len(actual_departs) == actual_census
                admits = mean(v[0] for v in samples)
                departs = mean(v[1] for v in samples)
                pred_census = before + admits - departs
                signed = pred_census - actual_census
                assert (
                    abs(
                        signed
                        - ((admits - actual_admits) - (departs - len(actual_departs)))
                    )
                    < 1e-9
                )
                records.append(
                    {
                        "univers": world,
                        "unite": uid,
                        "jour_origine": d,
                        "mode": mode,
                        "h": h,
                        "lits_a_origine": before,
                        "admissions_prevues": admits,
                        "admissions_cible": actual_admits,
                        "sorties_prevues": departs,
                        "sorties_cible": len(actual_departs),
                        "sorties_nouveaux_cible": actual_new_exits,
                        "sorties_init_sans_accord_a_D_cible": actual_uncleared_exits,
                        "sorties_init_avec_accord_a_D_cible": actual_initial_cleared_exits,
                        "lits_biais": signed,
                        "lits_mae": abs(signed),
                        "persistance_mae": abs(before - actual_census),
                        "attente_a_D": waiting,
                        "besoin_transport_a_D": needs_transport,
                    }
                )
    return records


def main():
    verify_revision()
    with ProcessPoolExecutor(max_workers=4) as pool:
        records = [
            row for rows in pool.map(one_world, range(bank.UNIVERSES)) for row in rows
        ]
    by_mode = defaultdict(list)
    for row in records:
        by_mode[row["mode"], row["h"]].append(row)
    with Path("docs/operational/unit-planning-results/metrics.csv").open() as f:
        old = {
            int(r["days"]): float(r["mae"])
            for r in csv.DictReader(f)
            if r["unit"] == "all_units" and r["target"] == "occupied"
        }
    report = []
    for (mode, h), rows in sorted(by_mode.items()):
        assert len(rows) == 1120
        summary = {
            k: mean(r[k] for r in rows)
            for k in rows[0]
            if k not in ("univers", "unite", "jour_origine", "mode", "h")
        }
        if mode == "long":
            assert abs(old[h] - summary["lits_mae"]) < 1e-12
        if mode == "court":
            assert abs(summary["lits_mae"] - 1.7089285714285714) < 1e-12
        report.append({"mode": mode, "jours": h, "releves": len(rows), **summary})
    unit_metrics = []
    for (mode, h), rows in sorted(by_mode.items()):
        for uid in bank.UNITS:
            selected = [row for row in rows if row["unite"] == uid]
            unit_metrics.append(
                {
                    "mode": mode,
                    "jours": h,
                    "unite": uid,
                    "releves": len(selected),
                    **{
                        k: mean(row[k] for row in selected)
                        for k in ("lits_mae", "lits_biais", "persistance_mae")
                    },
                }
            )

    # Same block length as the published bank, descriptive paired analysis on these same origins.
    losses = defaultdict(dict)
    for row in records:
        if row["h"] == 1:
            losses[row["univers"], row["unite"], row["jour_origine"]][row["mode"]] = (
                row["lits_mae"]
            )
    cube = np.array(
        [
            [
                mean(
                    losses[w, uid, day]["court"] - losses[w, uid, day]["court_urgences"]
                    for uid in bank.UNITS
                )
                for day in bank.ORIGINS
            ]
            for w in range(bank.UNIVERSES)
        ]
    )
    rng = np.random.default_rng(7731)
    worlds = rng.integers(0, bank.UNIVERSES, (bank.REPEATS, bank.UNIVERSES))
    blocks = rng.integers(
        0,
        len(bank.ORIGINS) // bank.BLOCK,
        (bank.REPEATS, bank.UNIVERSES, len(bank.ORIGINS) // bank.BLOCK),
    )
    days = (blocks[:, :, :, None] * bank.BLOCK + np.arange(bank.BLOCK)).reshape(
        bank.REPEATS, bank.UNIVERSES, len(bank.ORIGINS)
    )
    samples = cube[worlds[:, :, None], days].mean(axis=(1, 2))
    effect = {
        "baisse_mae_lits": float(cube.mean()),
        "intervalle_95": np.quantile(samples, [0.025, 0.975]).tolist(),
    }
    print(
        json.dumps(
            {
                "revision": SHA,
                "univers": bank.UNIVERSES,
                "scenarios": bank.SCENARIOS,
                "resultats": report,
                "resultats_par_unite": unit_metrics,
                "ajout_urgences_sur_le_panel": effect,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
