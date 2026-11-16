"""Information ladder L0..L5 for one establishment, scored with the R1 protocol (NORM A1-A4)."""

from __future__ import annotations

import math
import time
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import numpy as np
from scipy.special import logsumexp
from scipy.stats import nbinom

from hospitalos.howm import generator as G
from hospitalos.howm.b0 import B0Params, _newton_1d, day_period, to_bins
from hospitalos.howm.dataset import DATA_END_MIN
from hospitalos.howm.keys import u as ku
from hospitalos.howm.predict import b0_predict, member_logscores
from hospitalos.howm.world import SKILLS

from . import data as D
from . import laws as Lw
from .filter import HFAM, Ladder, PublicState, truth_info

HORIZONS = (1, 6, 24)
LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
ORIGINS = list(range(24, 144))


def window_long(ps: Any, t: int) -> dict[str, Any]:
    """Same statistics as howm.dataset._window, over the WHOLE public past (L2)."""
    from hospitalos.howm.dataset import HAZARD_FAMILIES

    w: dict[str, list] = {f: [] for f in HAZARD_FAMILIES}
    known = ps.obs[: ps.i]
    first: dict[tuple[str, str], int] = {}
    avail_end: dict[tuple[str, str], int] = {}
    for ev, av, kind, subj, _u, _v in known:
        first.setdefault((kind, subj), ev)
        avail_end.setdefault((kind, subj), av)
    starts = {"auth": "placed", "ready": "authorised", "transport": "transport_start", "confirmation": "transport_requested"}
    ends = {"auth": "authorised", "ready": "ready", "transport": "transport_done", "confirmation": "transport_accepted"}
    for fam in ("auth", "ready", "transport", "confirmation"):
        for (kind, subj), ev in first.items():
            if kind == starts[fam]:
                w[fam].append((ev, avail_end.get((ends[fam], subj)), {}))
    cl_start = {f"{subj}@{ev}": ev for ev, av, kind, subj, _u, _v in known if kind == "cleaning_start"}
    done = sorted((ev, av, subj) for ev, av, kind, subj, _u, _v in known if kind == "cleaning_done")
    for keyv, s in cl_start.items():
        bed = keyv.split("@")[0]
        w["cleaning"].append((s, next((av for ev, av, b in done if b == bed and ev >= s), None), {}))
    care = [(v["ide"], v["as_"]) for ev, av, kind, subj, _u, v in known if kind == "care_due"]
    pres = [kind == "offer_present" for ev, av, kind, subj, _u, v in known if kind in ("offer_present", "offer_absent")]
    return {"t": t, "hazard": w, "arrivals": None, "care": care, "presence": pres}


def long_arrivals_delta(p: B0Params, ps: Any, n_beds: dict[str, int], t: int) -> float:
    H = t // 60
    cnt = np.zeros((2, H))
    for o in ps.obs[: ps.i]:
        if o[2] == "request_arrival" and o[0] < t:
            cnt["AB".index(o[4]), o[0] // 60] += 1
    mu0 = np.array([[math.exp(p.arr_a + math.log(n_beds[un]) + p.arr_tod[j % 24]) for j in range(H)] for un in "AB"])
    r = p.arr_r

    def gh(d: float) -> tuple[float, float]:
        mu = mu0 * math.exp(d)
        return float(np.sum(cnt - (cnt + r) * mu / (r + mu))), float(-np.sum((cnt + r) * mu * r / (r + mu) ** 2))

    return _newton_1d(gh, p.tau.get("arrivals", 0.35))


def l2_predict(p: B0Params, od: Any, est: Any, ps: Any) -> Any:
    t = od.H * 60
    od_long = replace(od, window={**window_long(ps, t), "arrivals": od.window["arrivals"]})
    pr = b0_predict(p, od_long, est, True)
    d_arr = long_arrivals_delta(p, ps, est.n_beds, t)
    pr.arr_mu = np.array([[math.exp(p.arr_a + math.log(est.n_beds[un]) + p.arr_tod[(od.H + k) % 24] + d_arr) for k in range(24)] for un in "AB"])
    pr.meta["system"] = "B0-local-long"
    return pr


def _acc(acc: dict, lvl: str, h: int, fam: str, vals: np.ndarray | list) -> None:
    a = acc[lvl][str(h)].setdefault(fam, [0.0, 0])
    a[0] += float(-np.sum(vals))
    a[1] += len(vals)


def run_establishment(partition: str, idx: int, p: B0Params, pit_levels: tuple[str, ...] = ("L4",), keep_items: bool = False) -> dict[str, Any]:
    t0 = time.time()
    spec = G.establishment(partition, idx)
    ep = G.generate(spec)
    truth = truth_info(ep)
    static = next(o[5] for o in ep.observations if o[2] == "static")
    est = SimpleNamespace(n_beds=dict(spec.beds))
    lad = Ladder(spec.population, static, est.n_beds, truth)
    pub = PublicState(spec.population, est.n_beds)
    acc = {lv: {str(h): {} for h in HORIZONS} for lv in LEVELS}
    pits: dict[str, dict[str, list[float]]] = {lv: {} for lv in pit_levels}
    items_dump: list = []
    prev = 0
    timing = {"r1_levels": 0.0, "filter": 0.0}
    for H, od, ps in D.origins(ep, ORIGINS):
        t = H * 60
        pub.ingest(ps.obs[prev: ps.i])
        prev = ps.i
        t1 = time.time()
        for lvl, pr in (("L0", b0_predict(p, od, est, False)), ("L1", b0_predict(p, od, est, True)), ("L2", l2_predict(p, od, est, ps))):
            for h in HORIZONS:
                for fam, v in member_logscores(pr, od, h).items():
                    _acc(acc, lvl, h, fam, v)
        timing["r1_levels"] += time.time() - t1
        t1 = time.time()
        ctx = lad.context(pub, ps, t)
        for fam in HFAM:
            for it in od.items.get(fam, []):
                for lvl in ("L3", "L4", "L5"):
                    pm, tail = lad.hazard_pred(lvl, fam, it, t, pub, ps, ctx)
                    for h in HORIZONS:
                        _q, e, ev, b = to_bins(it["start"], t, it.get("end_avail"), min(t + 60 * h, DATA_END_MIN), 15)
                        _acc(acc, lvl, h, fam, [Lw.hazard_score(pm, tail, e, b, ev)])
                    if lvl in pit_levels:
                        _q, e, ev, b = to_bins(it["start"], t, it.get("end_avail"), min(t + 60 * 24, DATA_END_MIN), 15)
                        pits[lvl].setdefault(fam, []).append(Lw.randomized_pit(pm, tail, e, b, ev, ku("HOWM2-pit", partition, idx, H, fam, it["ref"])))
                    if keep_items and lvl == "L4" and fam in ("transport", "cleaning"):
                        items_dump.append({"H": H, "fam": fam, "start": it["start"], "pz_ctx": None})
        _levels_counts(lad, ctx, od, H, est, acc, pits, pit_levels, partition, idx)
        timing["filter"] += time.time() - t1
    return {"partition": partition, "index": idx, "population": spec.population, "mech": spec.mech, "acc": acc,
            "pits": pits, "seconds": round(time.time() - t0, 2), "timing": timing}


def _levels_counts(lad: Ladder, ctx: dict[str, Any], od: Any, H: int, est: Any, acc: dict, pits: dict,
                   pit_levels: tuple[str, ...], partition: str, idx: int) -> None:
    th = lad.truth["theta"]
    t = H * 60
    # arrivals: log-probabilities per (unit, k) once, partial sums per horizon
    wpost, L, A = ctx["arr_post"]
    lp = {lv: np.full((2, 24), np.nan) for lv in ("L3", "L4", "L5")}
    for ui, un in enumerate("AB"):
        for k in range(24):
            c = od.arrivals[ui, k]
            if c < 0:
                continue
            mu4 = Lw.arrivals_mean(est.n_beds[un], H + k, L, A)
            lp["L4"][ui, k] = float(logsumexp(Lw.nb_logpmf(np.array(c), mu4), b=wpost))
            mu3 = Lw.arrivals_mean(est.n_beds[un], H + k, th["los_days"], th["arr_mult"])
            lp["L3"][ui, k] = lp["L5"][ui, k] = float(Lw.nb_logpmf(np.array(c), mu3))
            if "L4" in pit_levels:
                r = 3.0
                cdf_lo = float(np.sum(wpost * nbinom.cdf(c - 1, r, r / (r + mu4)))) if c > 0 else 0.0
                pmf = float(np.sum(wpost * np.exp(Lw.nb_logpmf(np.array(c), mu4))))
                pits["L4"].setdefault("arrivals", []).append(cdf_lo + ku("HOWM2-pit", partition, idx, H, "arr", ui, k) * pmf)
    for h in HORIZONS:
        for lv in ("L3", "L4", "L5"):
            v = lp[lv][:, :h]
            _acc(acc, lv, h, "arrivals", v[~np.isnan(v)])
    # care: tables (skill x acuity x day x bin) for L4 (posterior mixture) and L3/L5 (true multiplier)
    tab4 = np.log(np.maximum(np.einsum("g,gsadb->sadb", ctx["care_post"], np.exp(lad.care_logtab)), 1e-300))
    tab3 = lad.true_care_logtab
    n = len(od.care_ref)
    if n:
        acu = np.array([int(np.argmax(x[7:10])) for x in od.care_x])
        ii, kk = np.nonzero(od.care_mask)
        dd = np.array([int(7 <= (H + k) % 24 < 21) for k in kk], int)
        for lv, tab in (("L4", tab4), ("L3", tab3), ("L5", tab3)):
            vals = np.zeros((len(ii), 2))
            for si in range(2):
                bins = np.minimum((od.care[ii, kk, si] // 5).astype(int), 120)
                vals[:, si] = tab[si, acu[ii], dd, bins]
            for h in HORIZONS:
                _acc(acc, lv, h, "care", vals[kk < h].reshape(-1))
    else:
        for lv in ("L3", "L4", "L5"):
            for h in HORIZONS:
                _acc(acc, lv, h, "care", [])
    # presence
    pres = od.items.get("presence", [])
    for h in HORIZONS:
        for lvl in ("L3", "L4", "L5"):
            vals = []
            for it in pres:
                if it["label"] is None or it["slot_start"] > t + 60 * h:
                    continue
                pp = float(ctx["pres_post"] @ (1 - lad.g["noshow"])) if lvl == "L4" else 1 - th["noshow"]
                vals.append(math.log(pp if it["label"] else 1 - pp))
            _acc(acc, lvl, h, "presence", vals)


def level_L(res: dict[str, Any], lvl: str, h: str, families: tuple[str, ...]) -> float:
    fam = res["acc"][lvl][h]
    vals = [fam[f][0] / fam[f][1] for f in families if f in fam and fam[f][1] > 0]
    return float(np.mean(vals)) if vals else float("nan")


CRITERION_FAMILIES = ("ready", "transport", "cleaning", "confirmation", "presence", "arrivals", "care")
_ = (day_period, nbinom)
