"""Information ladder predictors L3 (theta known), L4 (public reference filter), L5 (state known).

All use the exact generator laws (laws.py). L4 sees only public observations available at t and the
population prior; L3/L5 receive privileged truth (theta, mechanisms; L5 also regime and m3 load).
In-progress items do not enter inference (NORM A addendum 1.2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.special import logsumexp

from hospitalos.howm import generator as G
from hospitalos.howm.world import SKILLS

from . import laws as Lw

NG = 41
ZERO_LAG = {"transport_requested", "offer_requested", "plan", "static"}
HFAM = ("ready", "transport", "cleaning", "confirmation")


def ranges(pop: str) -> dict[str, tuple[float, float]]:
    return {"los_days": (2.5, 5.0), "ready_h": (1.0, 5.0), "tr_min": (30, 90), "cl_min": (30, 75), "conf_tr_min": (15, 120),
            "conf_off_min": (30, 240), "noshow": (0.0, 0.25), "arr_mult": (0.85, 1.15), "care_mult": (0.85, 1.15),
            "lag_min": (0.0, 60.0 if pop == "REF" else 120.0)}


def grid(lo: float, hi: float, n: int = NG) -> np.ndarray:
    return lo + (hi - lo) * (np.arange(n) + 0.5) / n  # midpoints: uniform prior on [lo, hi]


def mech_types(pop: str) -> list[tuple[str, float, bool, float]]:
    """(name, prior, m2_on, kappa)."""
    if pop == "REF":
        return [("simple", 0.3, False, 0.0), ("m3", 0.2, False, 0.5), ("m2m3", 0.5, True, 0.5)]
    return [("diag", 1.0, True, 1.5)]


def slow_of(pop: str) -> float:
    return 1.8 if pop == "REF" else 2.5


def public_load(ps: Any, unit: str, a: int) -> float:
    """Public m3 load at auth tick a, as known now (substitute, NORM A2.1)."""
    dem = 0.0
    for st in ps.stays.values():
        if st.get("unit") != unit or "placed" not in st:
            continue
        if st["placed"] >= a * 15:
            continue
        dep = st.get("departure")
        if dep is not None and dep < a * 15:
            continue
        dem += G.CARE_MEAN["IDE"][st["acuity"]]
    hour = a // 4
    dem *= 1.25 if 7 <= hour % 24 < 21 else 0.6
    roster = ps.static["units"][unit]["roster"]["IDE"]
    return dem / (60.0 * max(1, roster[min(hour, len(roster) - 1)]))


def true_load(truth: dict[str, Any], unit: str, a: int) -> float:
    dem = 0.0
    for sid, (u, ac, placed, dep) in truth["stays"].items():
        if u == unit and placed < a and (dep is None or dep >= a):
            dem += G.CARE_MEAN["IDE"][ac]
    hour = a // 4
    dem *= 1.25 if 7 <= hour % 24 < 21 else 0.6
    roster = truth["roster"][unit]
    return dem / (60.0 * max(1, roster[min(hour, len(roster) - 1)]))


def truth_info(ep: Any) -> dict[str, Any]:
    stays: dict[str, list[Any]] = {}
    for tick, kind, subj, v in ep.truth_log:
        if kind == "placed":
            placed = (v["placed_min"] // 15) if "placed_min" in v else tick
            stays[subj] = [v["unit"], v["acuity"], placed, None]
        elif kind == "departure" and subj in stays:
            stays[subj][3] = tick
    return {"stays": {k: tuple(v) for k, v in stays.items()}, "roster": {u: d["roster"]["IDE"] for u, d in ep.static["units"].items()},
            "regimes": ep.regimes, "theta": ep.spec.theta, "mech": ep.spec.mech}


@dataclass
class PublicState:
    """Incremental sufficient statistics of the public history (L4)."""

    pop: str
    n_beds: dict[str, int]
    lags: list[tuple[int, int]] = field(default_factory=list)  # (event_min, lag_min)
    starts: dict[str, dict[str, int]] = field(default_factory=lambda: {f: {} for f in ("transport", "cleaning", "conf_tr", "conf_off")})
    done: dict[str, list[tuple[int, int]]] = field(default_factory=lambda: {f: [] for f in ("transport", "cleaning", "conf_tr", "conf_off")})
    auth: dict[str, int] = field(default_factory=dict)
    ready_done: list[tuple[int, int, str, int]] = field(default_factory=list)  # (a, delta, unit, avail_min)
    arrivals: dict[tuple[int, int], int] = field(default_factory=dict)  # (unit_idx, hour) -> count available
    care_counts: np.ndarray = field(default_factory=lambda: np.zeros((2, 3, 2, 121)))  # skill x acuity x day x bin
    presence: list[bool] = field(default_factory=list)
    acuity: dict[str, int] = field(default_factory=dict)
    clean_open: dict[str, int] = field(default_factory=dict)

    def ingest(self, obs: list[tuple]) -> None:
        for ev, av, kind, subj, un, v in obs:
            if kind not in ZERO_LAG and not (kind == "placed" and "placed_min" in v):
                self.lags.append((ev, av - ev))
            if kind == "placed":
                self.acuity[subj] = v["acuity"]
            elif kind == "transport_start":
                self.starts["transport"][subj] = ev // 15
            elif kind == "transport_done" and subj in self.starts["transport"]:
                s = self.starts["transport"].pop(subj)
                self.done["transport"].append((s, ev // 15 - s))
            elif kind == "cleaning_start":
                self.clean_open[subj] = ev // 15
            elif kind == "cleaning_done" and subj in self.clean_open:
                s = self.clean_open.pop(subj)
                self.done["cleaning"].append((s, ev // 15 - s))
            elif kind == "transport_requested":
                self.starts["conf_tr"][subj] = ev // 15
            elif kind == "transport_accepted" and subj in self.starts["conf_tr"]:
                s = self.starts["conf_tr"].pop(subj)
                self.done["conf_tr"].append((s, ev // 15 - s))
            elif kind == "offer_requested" and v.get("source") == "pool":
                self.starts["conf_off"][subj] = ev // 15
            elif kind == "offer_confirmed" and subj in self.starts["conf_off"]:
                s = self.starts["conf_off"].pop(subj)
                self.done["conf_off"].append((s, ev // 15 - s))
            elif kind == "authorised":
                self.auth[subj] = ev // 15
            elif kind == "ready" and subj in self.auth:
                self.ready_done.append((self.auth[subj], ev // 15 - self.auth[subj], un, av))
            elif kind == "request_arrival":
                k = ("AB".index(un), ev // 60)
                self.arrivals[k] = self.arrivals.get(k, 0) + 1
            elif kind == "care_due" and subj in self.acuity:
                d = int(7 <= v["hour"] % 24 < 21)
                a = self.acuity[subj] - 1
                self.care_counts[0, a, d, min(int(v["ide"]) // 5, 120)] += 1
                self.care_counts[1, a, d, min(int(v["as_"]) // 5, 120)] += 1
            elif kind in ("offer_present", "offer_absent") and "pool" in subj:
                self.presence.append(kind == "offer_present")


class Ladder:
    """Per establishment: K-tables on grids, incremental likelihoods, predictions for L3/L4/L5."""

    def __init__(self, pop: str, static: dict[str, Any], n_beds: dict[str, int], truth: dict[str, Any] | None):
        self.pop, self.static, self.n_beds, self.truth = pop, static, n_beds, truth
        R = ranges(pop)
        self.R = R
        ng2 = 21 if pop == "DIAG" else NG
        self.g = {"tr": grid(*R["tr_min"], ng2), "cl": grid(*R["cl_min"], ng2), "ready": grid(*R["ready_h"]),
                  "conf_tr": grid(*R["conf_tr_min"]), "conf_off": grid(*R["conf_off_min"]), "lag": grid(*R["lag_min"], 61),
                  "care": grid(*R["care_mult"]), "noshow": grid(*R["noshow"]), "los": grid(*R["los_days"], 21), "arr": grid(*R["arr_mult"], 21)}
        sl = slow_of(pop)
        self.tab = {}
        for f, key, sig in (("transport", "tr", Lw.SIGMA["transport"]), ("cleaning", "cl", Lw.SIGMA["cleaning"])):
            meds = np.stack([self.g[key], self.g[key] * sl], 1)  # [G, 2]
            p, tail = Lw.k_pmf(meds, sig)
            self.tab[f] = (p, tail)
        for f in ("conf_tr", "conf_off"):
            self.tab[f] = Lw.k_pmf(self.g[f], Lw.SIGMA[f])
        if truth is not None:
            th, mech = truth["theta"], truth["mech"]
            self.true_tab = {}
            for f, key, sig in (("transport", "tr_min", 0.4), ("cleaning", "cl_min", 0.35)):
                meds = np.array([[th[key], th[key] * mech["slow"]]])
                self.true_tab[f] = Lw.k_pmf(meds, sig)
            self.true_tab["conf_tr"] = Lw.k_pmf(np.array([th["conf_tr_min"]]), 0.6)
            self.true_tab["conf_off"] = Lw.k_pmf(np.array([th["conf_off_min"]]), 0.5)
        self.ready_ll: list[np.ndarray] = []  # per completed ready item: [n_kappa, G]
        self.ready_seen = 0
        self.kappas = sorted({k for _, _, _, k in mech_types(pop)})
        self.chain = Lw.chain_prior(400)
        tab = np.zeros((NG, 2, 3, 2, 121))
        for si, sk in enumerate(SKILLS):
            for a in range(3):
                for d, hour in ((0, 2), (1, 12)):
                    tab[:, si, a, d] = np.log(np.maximum(Lw.care_bin_probs(Lw.care_median(sk, a + 1, hour, self.g["care"])), 1e-300))
        self.care_logtab = tab
        if truth is not None:
            tt = np.zeros((2, 3, 2, 121))
            for si, sk in enumerate(SKILLS):
                for a in range(3):
                    for d, hour in ((0, 2), (1, 12)):
                        tt[si, a, d] = np.log(np.maximum(Lw.care_bin_probs(Lw.care_median(sk, a + 1, hour, np.array(truth["theta"]["care_mult"]))), 1e-300))
            self.true_care_logtab = tt

    # ------------------------------------------------------------------ posteriors
    def lag_post(self, ps: PublicState, t: int) -> np.ndarray:
        th = self.g["lag"]
        lags = np.array([l for _, l in ps.lags], float)
        evs = np.array([e for e, _ in ps.lags], float)
        with np.errstate(divide="ignore", invalid="ignore"):
            ll = np.zeros_like(th)
            for i, theta in enumerate(th):
                lp = np.log(np.maximum(np.exp(-lags / theta) - np.exp(-(lags + 1) / theta), 1e-300))
                rec = (t - evs) < 20 * th.max()
                trunc = np.log(np.maximum(1 - np.exp(-((t - evs[rec]) + 1) / theta), 1e-300)) if rec.any() else 0.0
                ll[i] = lp.sum() - np.sum(trunc)
        w = np.exp(ll - ll.max())
        return w / w.sum()

    def lag_mean(self, w: np.ndarray) -> float:
        return float(np.sum(w * self.g["lag"]))

    def _hmm(self, emis: np.ndarray, H: int) -> tuple[np.ndarray, np.ndarray]:
        """emis [H, G, 2] log-emissions; chain from state 0 at hour 0. -> (logZ[G], smoothed P(z=1)[H, G])."""
        T = np.array([[1 - Lw.P01, Lw.P01], [Lw.P10, 1 - Lw.P10]])
        Gn = emis.shape[1]
        la = np.zeros((H, Gn, 2))
        logZ = np.zeros(Gn)
        a = np.zeros((Gn, 2))
        a[:, 0] = 1.0
        for h in range(H):
            if h > 0:
                a = a @ T
            m = emis[h].max(1, keepdims=True)
            a = a * np.exp(emis[h] - m)
            s = a.sum(1, keepdims=True)
            logZ += np.log(s[:, 0]) + m[:, 0]
            a = a / s
            la[h] = a
        post = np.zeros((H, Gn))
        b = np.ones((Gn, 2))
        for h in range(H - 1, -1, -1):
            g = la[h] * b
            post[h] = g[:, 1] / g.sum(1)
            if h > 0:
                b = (b * np.exp(emis[h] - emis[h].max(1, keepdims=True))) @ T.T
                b = b / b.sum(1, keepdims=True)
        return logZ, post

    def _emissions(self, ps: PublicState, f: str, H: int, tab: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
        p, tail = tab
        E = np.zeros((H, p.shape[0], 2))
        for s, k in ps.done[f]:
            h = s // 4
            if h >= H:
                continue
            E[h] += np.log(np.maximum(p[:, :, k] if k < Lw.KM else tail, 1e-300))
        return E

    def regime_posteriors(self, ps: PublicState, t: int) -> dict[str, Any]:
        """L4: per family, grid posteriors under m2 off / on, smoothed P(slow at hour h | g)."""
        H = t // 60 + 1
        out: dict[str, Any] = {}
        if self.pop == "DIAG":
            Et = self._emissions(ps, "transport", H, self.tab["transport"])
            Ec = self._emissions(ps, "cleaning", H, self.tab["cleaning"])
            n1, n2 = Et.shape[1], Ec.shape[1]
            Ej = (Et[:, :, None, :] + Ec[:, None, :, :]).reshape(H, n1 * n2, 2)
            logZ, post = self._hmm(Ej, H)
            out["joint"] = {"logZ": logZ, "post_slow": post, "shape": (n1, n2)}
            return out
        for f in ("transport", "cleaning"):
            E = self._emissions(ps, f, H, self.tab[f])
            logZ_on, post = self._hmm(E, H)
            logZ_off = E[:, :, 0].sum(0)
            out[f] = {"on": logZ_on, "off": logZ_off, "post_slow": post}
        return out

    def ready_ll_update(self, ps: PublicState, psx: Any) -> None:
        while self.ready_seen < len(ps.ready_done):
            a, d, unit, _ = ps.ready_done[self.ready_seen]
            load = public_load(psx, unit, a)
            rows = []
            for kap in self.kappas:
                med = self.g["ready"] * 60 * (1 + kap * max(0.0, load - 0.9))
                p, tail = Lw.k_pmf(med, Lw.SIGMA["ready"])
                ps_, pt = Lw.snap(p, tail, a)
                rows.append(np.log(np.maximum(ps_[:, d] if d < Lw.KM else pt, 1e-300)))
            self.ready_ll.append(np.array(rows))
            self.ready_seen += 1

    def type_posterior(self, reg: dict[str, Any]) -> tuple[list, np.ndarray]:
        types = mech_types(self.pop)
        rl = np.sum(self.ready_ll, 0) if self.ready_ll else np.zeros((len(self.kappas), NG))
        lps = []
        for name, prior, m2, kap in types:
            lp = math.log(prior) + logsumexp(rl[self.kappas.index(kap)]) - math.log(NG)
            if self.pop == "REF":
                for f in ("transport", "cleaning"):
                    z = reg[f]["on" if m2 else "off"]
                    lp += logsumexp(z) - math.log(len(z))
            lps.append(lp)
        lps = np.array(lps)
        w = np.exp(lps - lps.max())
        return types, w / w.sum()

    # ------------------------------------------------------------------ hazard predictions
    def hazard_pred(self, level: str, fam: str, it: dict[str, Any], t: int, ps: PublicState, psx: Any,
                    ctx: dict[str, Any]) -> tuple[np.ndarray, float]:
        """pmf over public-duration bins (incl. lag) for one cohort item at origin t."""
        lw = ctx["lag_w"] if level == "L4" else None
        if level == "L4":
            qs, ws = Lw.lag_q(self.g["lag"]), lw
        else:
            qs, ws = Lw.lag_q(np.array([self.truth["theta"]["lag_min"]])), np.array([1.0])
        s = it["start"] // 15
        if fam in ("transport", "cleaning"):
            h = s // 4
            if level == "L4":
                p, tail = self._l4_service(fam, h, ctx)
            else:
                mech = self.truth["mech"]
                pt, tt = self.true_tab[fam]
                if not mech["m2"]:
                    pz = 0.0
                elif level == "L3":
                    pz = float(self.chain[min(h, len(self.chain) - 1)])
                else:
                    team = "common" if mech["m2_common"] else fam
                    reg = self.truth["regimes"]["transport" if team == "common" else fam]
                    pz = float(reg[min(h, len(reg) - 1)])
                p = (1 - pz) * pt[0, 0] + pz * pt[0, 1]
                tail = float((1 - pz) * tt[0, 0] + pz * tt[0, 1])
        elif fam == "confirmation":
            key = "conf_tr" if it["kind"] == "transport" else "conf_off"
            if level == "L4":
                post = ctx["conf_post"][key]
                p, tail = self.tab[key][0].T @ post, float(self.tab[key][1] @ post)
            else:
                p, tail = self.true_tab[key][0][0], float(self.true_tab[key][1][0])
        elif fam == "ready":
            unit = it["unit"]
            if level == "L5":
                load = true_load(self.truth, unit, s)
            else:
                load = public_load(psx, unit, s)
            if level == "L4":
                p, tail = np.zeros(Lw.KM), 0.0
                for (name, _pr, _m2, kap), wt in zip(ctx["types"], ctx["type_w"], strict=True):
                    post = ctx["ready_post"][self.kappas.index(kap)]
                    med = self.g["ready"] * 60 * (1 + kap * max(0.0, load - 0.9))
                    pk, tk = Lw.k_pmf(med, Lw.SIGMA["ready"])
                    sp, st_ = Lw.snap(pk, tk, s)
                    p = p + wt * (post @ sp)
                    tail += wt * float(post @ st_)
            else:
                kap = self.truth["mech"]["m3_kappa"]
                med = np.array([self.truth["theta"]["ready_h"] * 60 * (1 + kap * max(0.0, load - 0.9))])
                pk, tk = Lw.k_pmf(med, Lw.SIGMA["ready"])
                sp, st_ = Lw.snap(pk, tk, s)
                p, tail = sp[0], float(st_[0])
        else:
            raise ValueError(fam)
        return Lw.add_lag(np.asarray(p, float), tail, qs, ws)

    def _l4_service(self, fam: str, h: int, ctx: dict[str, Any]) -> tuple[np.ndarray, float]:
        p_tab, t_tab = self.tab[fam]
        reg = ctx["reg"]
        if self.pop == "DIAG":
            J = reg["joint"]
            n1, n2 = J["shape"]
            lz = J["logZ"]
            w = np.exp(lz - lz.max())
            w /= w.sum()
            ps_ = J["post_slow"][min(h, J["post_slow"].shape[0] - 1)]
            W = np.stack([w * (1 - ps_), w * ps_], 1).reshape(n1, n2, 2)
            Wf = W.sum(1) if fam == "transport" else W.sum(0)
        else:
            Wf = np.zeros((p_tab.shape[0], 2))
            for (name, _pr, m2, _k), wt in zip(ctx["types"], ctx["type_w"], strict=True):
                lz = reg[fam]["on" if m2 else "off"]
                w = np.exp(lz - lz.max())
                w /= w.sum()
                if m2:
                    ps_ = reg[fam]["post_slow"][min(h, reg[fam]["post_slow"].shape[0] - 1)]
                    Wf[:, 0] += wt * w * (1 - ps_)
                    Wf[:, 1] += wt * w * ps_
                else:
                    Wf[:, 0] += wt * w
        p = np.einsum("gz,gzk->k", Wf, p_tab)
        tail = float(np.sum(Wf * t_tab))
        return p, tail

    def context(self, ps: PublicState, psx: Any, t: int) -> dict[str, Any]:
        ctx: dict[str, Any] = {"lag_w": self.lag_post(ps, t)}
        ctx["reg"] = self.regime_posteriors(ps, t)
        self.ready_ll_update(ps, psx)
        ctx["types"], ctx["type_w"] = self.type_posterior(ctx["reg"]) if self.pop == "REF" else (mech_types("DIAG"), np.array([1.0]))
        rl = np.sum(self.ready_ll, 0) if self.ready_ll else np.zeros((len(self.kappas), NG))
        ctx["ready_post"] = [np.exp(r - r.max()) / np.exp(r - r.max()).sum() for r in rl]
        cp = {}
        for key in ("conf_tr", "conf_off"):
            p, tail = self.tab[key]
            ll = np.zeros(p.shape[0])
            for _s, k in ps.done[key]:
                ll += np.log(np.maximum(p[:, k] if k < Lw.KM else tail, 1e-300))
            w = np.exp(ll - ll.max())
            cp[key] = w / w.sum()
        ctx["conf_post"] = cp
        # care multiplier: sufficient statistics (skill x acuity x day/night x bin)
        ll = np.einsum("sadb,gsadb->g", ps.care_counts, self.care_logtab)
        w = np.exp(ll - ll.max())
        ctx["care_post"] = w / w.sum()
        # presence
        ns = self.g["noshow"]
        ll = sum(np.log(1 - ns) if y else np.log(np.maximum(ns, 1e-300)) for y in ps.presence) if ps.presence else np.zeros(NG)
        w = np.exp(ll - ll.max())
        ctx["pres_post"] = w / w.sum()
        # arrivals (los x arr), binomial thinning of recent hours with the posterior-mean lag
        lagm = self.lag_mean(ctx["lag_w"])
        L, A = np.meshgrid(self.g["los"], self.g["arr"], indexing="ij")
        ll = np.zeros(L.shape)
        H = t // 60
        for ui, un in enumerate("AB"):
            for j in range(H):
                c = ps.arrivals.get((ui, j), 0)
                pth = 1.0 - math.exp(-max(0.0, t - (60 * j + 30)) / lagm) if lagm > 0 else 1.0
                mu = Lw.arrivals_mean(self.n_beds[un], j, L, A) * max(pth, 1e-9)
                ll += Lw.nb_logpmf(np.array(c), mu)
        w = np.exp(ll - ll.max())
        ctx["arr_post"] = (w / w.sum(), L, A)
        return ctx
