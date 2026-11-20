"""Run the bed-filter pilot with NumPy: python scripts/filter_jepa/benchmark_filter.py.

The experiment estimates current state (daily arrivals allowed) and predicts the
next month (no reports after origin). MAE is ready beds per ward per day.
Each of the ten held-out calendar months is weighted equally.
"""

import json

import numpy as np

from cohort import EYE, filter_reports, rounds, simulate, transitions


def evaluate(seed):
    days, schedule, states, reports = simulate(seed)
    posterior, latest = filter_reports(days, schedule, reports)
    observed = EYE[states]
    ready = observed[..., 1].sum(axis=-1)
    scores = []
    for _, start, end in rounds(days):
        target = ready[start:end]
        projected = posterior[start - 1].copy()
        forecasts = []
        for day in range(start, end):
            for unit in range(len(projected)):
                kernel = transitions(days[day], unit, schedule[day], nominal=True)
                projected[unit] = projected[unit] @ kernel
            forecasts.append(projected[..., 1].sum(axis=-1))

        def nowcast_mae(probabilities):
            return float(np.abs(probabilities[start:end, ..., 1].sum(axis=-1) - target).mean())

        scores.append({
            "month": str(days[start])[:7],
            "latest_mae": nowcast_mae(latest),
            "filter_mae": nowcast_mae(posterior),
            "open_loop_mae": float(np.abs(np.array(forecasts) - target).mean()),
        })
    return scores


if __name__ == "__main__":
    print(json.dumps({seed: evaluate(seed) for seed in (11, 23, 37)}, indent=2))
