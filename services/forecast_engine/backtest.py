"""Pre-registered rolling-origin backtest (protocol: docs/liscop/BACKTEST.md).

Every origin replays the live pipeline with the data known before it (``compute`` with
plans known at the date), then scores J+1..J+7 against what happened. Origins, gates and
the regime-shift test follow the protocol; nothing here is tuned on its results.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from services.forecast_engine.capacity import IntDraws, summarise
from services.forecast_engine.conformal import ALPHA, GAMMA, WINDOW, adaptive_conformal
from services.forecast_engine.conformal import conformal_offsets as offsets
from services.forecast_engine.data import History, Series, load_history
from services.forecast_engine.models import cross_validate, forecast_series
from services.forecast_engine.pipeline import ED_ARRIVALS, compute

log = logging.getLogger("forecast_engine")

ORIGINS = 21
HORIZONS = range(1, 8)  # J+1 .. J+7
COVERAGE_GATE = (0.75, 0.85)
SHIFT_FACTOR = 1.5
SHIFT_DAYS = 21
SHIFT_START_BEFORE_END = 48  # S = T - 48
ACI_TOLERANCE = 0.05
PIT_SEED = 80


def protocol_origins(last_day: date, n: int = ORIGINS) -> list[date]:
    """Weekly origins, the last one seven days before the last full day."""
    final = last_day - timedelta(days=7)
    return [final - timedelta(days=7 * (n - 1 - i)) for i in range(n)]


def _ratio(errors: Sequence[float], reference: Sequence[float]) -> float | None:
    ref = float(np.sum(reference))
    return None if ref == 0 else round(float(np.sum(errors)) / ref, 4)


def _coverage(hits: Sequence[bool]) -> float | None:
    return round(float(np.mean(hits)), 4) if hits else None


def run_backtest(
    session: Session,
    group_id: int,
    today: date,
    timezone: str,
    origins: Sequence[date] | None = None,
    shift_start: date | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    last_day = today - timedelta(days=1)
    history = load_history(session, group_id, last_day, timezone)
    origins = list(origins or protocol_origins(last_day))
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    chosen: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    beds = [p for p, u in history.units.items() if u.installed > 0]
    pit = np.random.default_rng(PIT_SEED)

    for n, origin in enumerate(origins, 1):
        log.info("Origine %s/%s : %s", n, len(origins), origin)
        result = compute(session, history, origin, use_current_plans=False, progress=log.debug)
        for key, fc in result.forecasts.items():
            chosen[key.split(":")[0]][fc.model] += 1
            name, ident = key.split(":")
            values = (
                history.unit_series[name][int(ident)]
                if name == "arrivals"
                else history.site_series[name][int(ident)]
            )
            for k in HORIZONS:
                day = origin + timedelta(days=k)
                rows[name].append(
                    {
                        "key": key,
                        "origin": origin,
                        "k": k,
                        "point": float(fc.point[k]),
                        "reference": float(fc.reference[k]),
                        "q10": float(fc.q10[k]),
                        "q90": float(fc.q90[k]),
                        "actual": float(values[history.index(day)]),
                    }
                )
        for pool_id in beds:
            draws = result.unit_draws[pool_id]
            s = summarise(draws)
            yesterday = origin - timedelta(days=1)
            for k in HORIZONS:
                day = origin + timedelta(days=k)
                rows["available_beds"].append(
                    {
                        "key": f"pool:{pool_id}",
                        "origin": origin,
                        "k": k,
                        "point": float(s.mean[k]),
                        "reference": float(_available(history, pool_id, yesterday)),
                        "q10": float(s.q10[k]),
                        "q90": float(s.q90[k]),
                        "actual": float(_available(history, pool_id, day)),
                        "pit_hit": _pit_hit(draws[:, k], _available(history, pool_id, day), pit),
                    }
                )

    report: dict[str, Any] = {
        "group_id": group_id,
        "generated_for": today.isoformat(),
        "last_full_day": last_day.isoformat(),
        "origins": [o.isoformat() for o in origins],
        "units": {f"pool:{p}": history.units[p].label for p in beds},
        "models_chosen": {k: dict(v) for k, v in chosen.items()},
    }
    report["arrivals"] = _accuracy(rows["arrivals"])
    report["boarding_10h"] = _accuracy(rows["boarding_10h"])
    report["ed_arrivals"] = _accuracy(rows[ED_ARRIVALS])
    report["available_beds"] = _accuracy(rows["available_beds"])
    shift = shift_start or last_day - timedelta(days=SHIFT_START_BEFORE_END)
    report["regime_shift"] = regime_shift(history, shift)
    report["gates"] = _gates(report)
    report["runtime_seconds"] = round(time.monotonic() - started, 1)
    return report


def _available(history: History, pool_id: int, day: date) -> int:
    """Beds open minus patients present at the end of ``day``, within [0, open beds]."""
    open_beds = history.capacity_on(pool_id, day)[1]
    occupied = int(history.unit_series["occupancy"][pool_id][history.index(day)])
    return max(0, min(open_beds, open_beds - occupied))


def _pit_hit(draws: IntDraws, actual: int, rng: np.random.Generator) -> bool:
    """Randomised PIT inside [0.1, 0.9]: an 80 % coverage check fit for discrete outcomes.

    With an atom (a full unit: 0 available beds in most draws), the inclusive interval
    [q10, q90] over-covers by construction; the randomised PIT F(y−) + U·(F(y) − F(y−))
    is uniform when the forecast is calibrated (Czado, Gneiting & Held, Biometrics 2009).
    """
    low, high = float(np.mean(draws < actual)), float(np.mean(draws <= actual))
    value = low + rng.random() * (high - low)
    return 0.1 <= value <= 0.9


def _accuracy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}

    def stats(subset: list[dict[str, Any]]) -> dict[str, Any]:
        err = [abs(r["point"] - r["actual"]) for r in subset]
        ref = [abs(r["reference"] - r["actual"]) for r in subset]
        hits = [r["q10"] <= r["actual"] <= r["q90"] for r in subset]
        out = {
            "n": len(subset),
            "mae": round(float(np.mean(err)), 3),
            "mae_reference": round(float(np.mean(ref)), 3),
            "mae_ratio": _ratio(err, ref),
            "coverage_80": _coverage(hits),
        }
        if subset and "pit_hit" in subset[0]:
            out["coverage_80_randomised"] = _coverage([r["pit_hit"] for r in subset])
            out["share_q10_zero_actual_zero"] = _coverage(
                [r["q10"] == 0 and r["actual"] == 0 for r in subset]
            )
        return out

    by_k = {str(k): stats([r for r in rows if r["k"] == k]) for k in HORIZONS}
    keys = sorted({r["key"] for r in rows})
    return {
        "pooled": stats(rows),
        "by_horizon": by_k,
        "by_series": {key: stats([r for r in rows if r["key"] == key]) for key in keys},
    }


def regime_shift(history: History, start: date, gamma: float = GAMMA) -> dict[str, Any]:
    """Multiply arrivals by 1.5 for 21 days on a copy; compare static and ACI coverage."""
    end = start + timedelta(days=SHIFT_DAYS - 1)
    cv_last = start + timedelta(days=SHIFT_DAYS - 1 + 6)  # step-2 forecasts of `end`
    first_cutoff = start - timedelta(days=8 + WINDOW + 8)
    n_windows = (cv_last - timedelta(days=8) - first_cutoff).days + 1
    base: dict[str, Series] = {}
    for p, u in history.units.items():
        if u.installed > 0:
            base[f"arrivals:{p}"] = history.unit_series["arrivals"][p]
    for s, values in history.site_series[ED_ARRIVALS].items():
        base[f"{ED_ARRIVALS}:{s}"] = values
    before = {k: v[: history.index(start)] for k, v in base.items()}
    models = {k: fc.model for k, fc in forecast_series(before, start - timedelta(days=1)).items()}
    shifted: dict[str, Series] = {}
    for key, values in base.items():
        copy = values[: history.index(cv_last) + 1].copy()
        window = slice(history.index(start), history.index(end) + 1)
        copy[window] = np.round(copy[window] * SHIFT_FACTOR)
        shifted[key] = copy
    cv = cross_validate(shifted, cv_last, n_windows=n_windows)

    static_hits: dict[int, list[bool]] = defaultdict(list)
    aci_hits: dict[int, list[bool]] = defaultdict(list)
    for key in shifted:
        rows = cv[cv["unique_id"] == key].sort_values(["cutoff", "ds"])
        step = (rows["ds"] - rows["cutoff"]).dt.days.to_numpy(int)
        target = [d.date() for d in rows["ds"]]
        resid = rows["y"].to_numpy(float) - np.clip(rows[models[key]].to_numpy(float), 0, None)
        for k in HORIZONS:
            mask = step == k + 1
            r = resid[mask]
            days = [d for d, m in zip(target, mask, strict=True) if m]
            pre = np.array([x for x, d in zip(r, days, strict=True) if d < start])
            lo, hi = offsets(pre[-WINDOW:], ALPHA)
            trace = adaptive_conformal(r, ALPHA, gamma, WINDOW, lag=k + 1)
            for i, d in enumerate(days):
                if start <= d <= end and trace.covered[i] is not None:
                    static_hits[k].append(bool(lo <= r[i] <= hi))
                    aci_hits[k].append(bool(trace.covered[i]))
    return {
        "window": [start.isoformat(), end.isoformat()],
        "series": sorted(shifted),
        "models": models,
        "static": {
            "pooled": _coverage([h for k in HORIZONS for h in static_hits[k]]),
            "by_horizon": {str(k): _coverage(static_hits[k]) for k in HORIZONS},
        },
        "aci": {
            "pooled": _coverage([h for k in HORIZONS for h in aci_hits[k]]),
            "by_horizon": {str(k): _coverage(aci_hits[k]) for k in HORIZONS},
        },
        "n": sum(len(v) for v in aci_hits.values()),
    }


def _gates(report: dict[str, Any]) -> dict[str, Any]:
    low, high = COVERAGE_GATE
    ratios = [report["arrivals"]["by_horizon"][str(k)]["mae_ratio"] for k in HORIZONS]
    a = all(r is not None and r < 1 for r in ratios)
    cov_arr = report["arrivals"]["pooled"]["coverage_80"]
    cov_beds = report["available_beds"]["pooled"]["coverage_80"]
    b = low <= cov_arr <= high and low <= cov_beds <= high
    shift = report["regime_shift"]
    static, aci = shift["static"]["pooled"], shift["aci"]["pooled"]
    if static is None or aci is None or static >= low:
        c = "non concluant"
    else:
        c = "réussi" if abs(aci - (1 - ALPHA)) <= ACI_TOLERANCE else "échoué"
    board = report["boarding_10h"]["pooled"]["mae_ratio"] if report["boarding_10h"] else None
    d = "non évaluable" if board is None else ("réussi" if board < 1 else "échoué")
    return {
        "a_arrivals_mae_ratio": "réussi" if a else "échoué",
        "b_coverage_80": "réussi" if b else "échoué",
        "c_regime_shift": c,
        "d_boarding_mae_ratio": d,
    }


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f} %"


def _num(x: float | None) -> str:
    return "—" if x is None else f"{x:.3f}"


def render_markdown(report: dict[str, Any]) -> str:
    """The results section of docs/liscop/BACKTEST.md."""
    g = report["gates"]
    units = report["units"]
    lines = [
        f"Démo générée pour le {report['generated_for']} ; dernier jour complet "
        f"{report['last_full_day']} ; {len(report['origins'])} origines du "
        f"{report['origins'][0]} au {report['origins'][-1]} ; durée "
        f"{report['runtime_seconds']} s.",
        "",
        "| Critère | Résultat |",
        "|---|---|",
        f"| (a) MAE arrivées / SeasonalNaive < 1 à chaque horizon | {g['a_arrivals_mae_ratio']} |",
        f"| (b) Couverture 80 % dans [75 %, 85 %] (arrivées et lits) | {g['b_coverage_80']} |",
        f"| (c) Rupture de régime : ACI à ±5 points, statique < 75 % | {g['c_regime_shift']} |",
        f"| (d) MAE lits brancards à 10 h / SeasonalNaive < 1 | {g['d_boarding_mae_ratio']} |",
        "",
        "### Par horizon",
        "",
        "| Horizon | Arrivées : MAE / réf. | Arrivées : couverture | Lits disponibles : "
        "couverture | Lits dispo : MAE (persistance) | Brancards 10 h : MAE / réf. |",
        "|---|---|---|---|---|---|",
    ]
    for k in HORIZONS:
        a = report["arrivals"]["by_horizon"][str(k)]
        b = report["available_beds"]["by_horizon"][str(k)]
        d = report["boarding_10h"]["by_horizon"][str(k)] if report["boarding_10h"] else {}
        lines.append(
            f"| J+{k} | {_num(a['mae_ratio'])} | {_pct(a['coverage_80'])} | "
            f"{_pct(b['coverage_80'])} | {b['mae']:.2f} ({b['mae_reference']:.2f}) | "
            f"{_num(d.get('mae_ratio'))} |"
        )
    pa, pb = report["arrivals"]["pooled"], report["available_beds"]["pooled"]
    pd_ = report["boarding_10h"]["pooled"] if report["boarding_10h"] else {}
    lines.append(
        f"| **Poolé** | **{_num(pa['mae_ratio'])}** | **{_pct(pa['coverage_80'])}** | "
        f"**{_pct(pb['coverage_80'])}** | **{pb['mae']:.2f} ({pb['mae_reference']:.2f})** | "
        f"**{_num(pd_.get('mae_ratio'))}** |"
    )
    lines += [
        "",
        "### Par unité (J+1 à J+7 poolés)",
        "",
        "| Unité | Arrivées : MAE (réf.) | MAE / réf. | Couverture arrivées | "
        "Lits dispo : MAE (persistance) | Couverture lits |",
        "|---|---|---|---|---|---|",
    ]
    for key, label in units.items():
        a = report["arrivals"]["by_series"].get(f"arrivals:{key.split(':')[1]}", {})
        b = report["available_beds"]["by_series"].get(key, {})
        lines.append(
            f"| {label} | {a.get('mae', 0):.2f} ({a.get('mae_reference', 0):.2f}) | "
            f"{_num(a.get('mae_ratio'))} | {_pct(a.get('coverage_80'))} | "
            f"{b.get('mae', 0):.2f} ({b.get('mae_reference', 0):.2f}) | "
            f"{_pct(b.get('coverage_80'))} |"
        )
    ed = report["ed_arrivals"].get("pooled", {})
    if ed:
        lines += [
            "",
            f"Passages aux urgences (informatif) : MAE {ed['mae']:.2f} contre "
            f"{ed['mae_reference']:.2f} pour la référence (rapport {_num(ed['mae_ratio'])}), "
            f"couverture {_pct(ed['coverage_80'])}.",
        ]
    s = report["regime_shift"]
    lines += [
        "",
        f"### Rupture de régime (×{SHIFT_FACTOR} du {s['window'][0]} au {s['window'][1]}, "
        f"{len(s['series'])} séries, {s['n']} prévisions)",
        "",
        "| Horizon | Statique | ACI |",
        "|---|---|---|",
    ]
    for k in HORIZONS:
        lines.append(
            f"| J+{k} | {_pct(s['static']['by_horizon'][str(k)])} | "
            f"{_pct(s['aci']['by_horizon'][str(k)])} |"
        )
    lines.append(
        f"| **Poolé** | **{_pct(s['static']['pooled'])}** | **{_pct(s['aci']['pooled'])}** |"
    )
    lines += ["", "Modèles retenus (toutes origines) :", ""]
    for target, counts in report["models_chosen"].items():
        detail = ", ".join(f"{m} {n}" for m, n in sorted(counts.items()))
        lines.append(f"- `{target}` : {detail}")
    return "\n".join(lines)
