"""G_alt — independent fixed-step implementation of ONE family: transport and cleaning service
queues under m0+m1 (DESIGN 1.7). Written separately from G_main (no shared code beyond numpy):
1-minute steps, numpy Generator draws, its own queue logic. Used only as an out-of-generator
check of G_main's service-time mechanism on development (T-GEN-08, informative).
"""

from __future__ import annotations

import numpy as np


def simulate_queue(
    n_jobs: int,
    servers: int,
    median_min: float,
    sigma: float,
    inter_arrival_min: float,
    seed: int,
    cleaning_hours: tuple[int, int] | None = None,
) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    arrivals = np.cumsum(rng.exponential(inter_arrival_min, n_jobs)).astype(int)
    durations = np.maximum(
        15, np.ceil(median_min * np.exp(sigma * rng.standard_normal(n_jobs)) / 15.0) * 15
    ).astype(int)
    free_at = np.zeros(servers, int)
    start = np.zeros(n_jobs, int)
    minute = 0
    q: list[int] = []
    nxt = 0
    done = 0
    busy_until = np.zeros(servers, int)
    while done < n_jobs:
        while nxt < n_jobs and arrivals[nxt] <= minute:
            q.append(nxt)
            nxt += 1
        open_ = (
            cleaning_hours is None or cleaning_hours[0] <= (minute // 60) % 24 < cleaning_hours[1]
        )
        if minute % 15 == 0 and open_:
            for s in range(servers):
                if busy_until[s] <= minute and q:
                    j = q.pop(0)
                    start[j] = minute
                    busy_until[s] = minute + durations[j]
                    done += 1
        minute += 1
    del free_at
    return {"arrival": arrivals, "start": start, "duration": durations, "wait": start - arrivals}
