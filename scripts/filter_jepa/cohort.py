"""Daily two-ward synthetic bed census. Independently delayed, exact bed status reports."""
from datetime import date, timedelta

import numpy as np

BEDS = 32
UNITS = 2
START, END = date(2020, 1, 1), date(2025, 1, 1)
PRIOR = np.array([0.62, 0.21, 0.17])  # occupied, ready, dirty
EYE = np.eye(3)


def calendar(day):
    annual = 2 * np.pi * (day - START).days / 365.25
    return np.array([np.sin(annual), np.cos(annual), float(day.weekday() >= 5)])


def transitions(day, ward, extra, shock=0, nominal=False):
    season, _, weekend = calendar(day)
    discharge = .18 - .05 * weekend + .02 * ward
    admit = .57 + .14 * season + .05 * ward
    clean = .59 + .19 * extra - .13 * weekend
    if not nominal:
        discharge += .025 * shock
        admit += .08 * shock
        clean -= .09 * shock
    return np.array([[1-discharge, 0, discharge], [admit, 1-admit, 0], [0, clean, 1-clean]])


def simulate(seed):
    rng = np.random.default_rng(seed)
    days = [START + timedelta(days=i) for i in range((END - START).days)]
    schedule = (rng.random(len(days)) < .23).astype(float)  # committed in advance
    states = rng.choice(3, size=(UNITS, BEDS), p=PRIOR)
    truth, reports = [], [[] for _ in days]
    shock = 0.
    for i, day in enumerate(days):
        shock = np.clip(.85 * shock + rng.normal(0, .32), -1, 1)
        for u in range(UNITS):
            matrix = transitions(day, u, schedule[i], shock)
            cuts = matrix[states[u]].cumsum(axis=1)[:, :2]
            states[u] = (rng.random((BEDS, 1)) > cuts).sum(axis=1)
            for b in np.flatnonzero(rng.random(BEDS) < .55):
                arrived = i + rng.choice(4, p=[.35, .3, .2, .15])
                if arrived < len(days):
                    reports[arrived].append((i, u, b, states[u, b]))
        truth.append(states.copy())
    return days, schedule, np.array(truth), reports


def filter_reports(days, schedule, reports):
    """Propagate the per-bed categorical posterior. Late exact reports anchor it at event time."""
    shape = (UNITS, BEDS, 3)
    posterior = np.broadcast_to(PRIOR, shape).copy()
    last = posterior.copy()
    seen = np.full(shape[:2], -1)
    history, raw = [], []
    kernels = []
    for i, (day, messages) in enumerate(zip(days, reports, strict=True)):
        kernels.append([transitions(day, u, schedule[i], nominal=True) for u in range(UNITS)])
        for u in range(UNITS):
            posterior[u] = posterior[u] @ kernels[i][u]
        for event, u, b, status in messages:
            if event <= seen[u, b]:
                continue
            seen[u, b] = event
            last[u, b] = EYE[status]
            p = last[u, b]
            for k in range(event+1, i+1):
                p = p @ kernels[k][u]
            posterior[u, b] = p
        history.append(posterior.copy())
        raw.append(last.copy())
    return np.array(history), np.array(raw)


def rounds(days):
    for year in range(START.year, END.year):
        for month in (1, 7):
            lo = days.index(date(year, month, 1))
            cut = days.index(date(year, month+5, 1))
            end = date(year, 7, 1) if month == 1 else date(year+1, 1, 1)
            yield lo, cut, (end-START).days
