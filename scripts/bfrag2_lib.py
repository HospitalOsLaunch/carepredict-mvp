"""B-FRAG 2 analysis library (PROTOCOLE_BFRAG2 s.6-8): data loading, structure-conditional AUC with
cluster bootstrap over structures, alert rules, decision policies. Pure functions; no simulation."""

from __future__ import annotations

import glob
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "evidence/howm2_bfrag2/runs"
SEED = 20261117
B_BOOT = 2000
ALPHA_PRIMARY = 0.05 / 3  # Bonferroni over A, B, C -> 98.33 % intervals
VIEWS = ("S0", "S1", "S2")
LR_C = (0.01, 0.1, 1.0, 10.0)
HGB = tuple((d, lr) for d in (2, 3) for lr in (0.05, 0.1))
CONFIGS = [("LR", c) for c in LR_C] + [("HGB", g) for g in HGB]  # order = tie-break (LR first, smaller capacity first)
UNIT_DAYS_PER_EPISODE = 7.5  # 2 units x 15 origins x 6 h
FA_MAX = 0.10  # false alerts per unit-day (VAL constraint)


def load(tag: str, part: str, s_range: range | None = None) -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(RUNS / tag / part / "s*_e*.json"))):
        d = json.loads(Path(f).read_text())
        if s_range is None or d["structure"] in s_range:
            out.append(d)
    return out


def view_names(ep: dict) -> dict[str, list[str]]:
    o = ep["origins"][0]
    s0, s1, s2 = sorted(o["S0"]), sorted(o["S1"]), sorted(o["S2"])
    return {"S0": s0, "S1": s0 + s1, "S2": s0 + s1 + s2}


def rows(eps: list[dict], names: dict) -> dict:
    """Origin table (non-active, non-censored origins only)."""
    R = {k: [] for k in ("s", "e", "hour", "y72", "y24", "manifest", "lh", "family")}
    X = {v: [] for v in VIEWS}
    sc = {}
    for ep in eps:
        for o in ep["origins"]:
            L = o["labels"]
            if L["active"] or L["censored"]:
                continue
            for k, v in (("s", ep["structure"]), ("e", ep["episode"]), ("hour", o["hour"]), ("y72", L["y72"]), ("y24", L["y24"]),
                         ("manifest", int(o["manifest"])), ("lh", o["hour"] % 24), ("family", ep["family"])):
                R[k].append(v)
            feat = o["S0"] | o["S1"] | o["S2"]
            for v in VIEWS:
                X[v].append([feat[n] for n in names[v]])
            for m, val in (o.get("score") or {}).items():
                sc.setdefault(m, []).append(val)
    out = {k: np.array(v) for k, v in R.items()}
    out["X"] = {v: np.array(X[v], float) for v in VIEWS}
    out["score"] = {m: np.array(v, float) for m, v in sc.items()}
    return out


# ------------------------------------------------------------------------------ AUC
def _mw(score: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """(U, pairs) for one group; ties count 1/2."""
    pos, neg = score[y == 1], score[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return 0.0, 0.0
    allv = np.concatenate([pos, neg])
    order = allv.argsort(kind="mergesort")
    ranks = np.empty(len(allv))
    sv = allv[order]
    i = 0
    while i < len(sv):  # average ranks for ties
        j = i
        while j + 1 < len(sv) and sv[j + 1] == sv[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    U = ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2
    return float(U), float(len(pos) * len(neg))


def group_up(score: np.ndarray, y: np.ndarray, s: np.ndarray, phase: np.ndarray | None = None) -> dict[int, tuple[float, float]]:
    """Per structure: (U, pairs) summed over within-structure (optionally within-phase) groups."""
    out: dict = {}
    for st in np.unique(s):
        m = s == st
        if phase is None:
            out[int(st)] = _mw(score[m], y[m])
        else:
            U = P = 0.0
            for ph in np.unique(phase[m]):
                mm = m & (phase == ph)
                u, p = _mw(score[mm], y[mm])
                U, P = U + u, P + p
            out[int(st)] = (U, P)
    return out


def cond_auc(score, y, s, phase=None) -> float | None:
    g = group_up(score, y, s, phase)
    P = sum(p for _u, p in g.values())
    return sum(u for u, _p in g.values()) / P if P else None


def cond_auc_equal(score, y, s) -> float | None:
    g = [u / p for u, p in group_up(score, y, s).values() if p]
    return float(np.mean(g)) if g else None


def global_auc(score, y) -> float | None:
    u, p = _mw(score, y)
    return u / p if p else None


def boot_structures(structs: list[int], B: int = B_BOOT, seed: int = SEED) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, len(structs), size=(B, len(structs)))


def auc_diff_ci(sa, sb, y, s, alpha: float, phase=None) -> dict:
    """Pooled conditional AUC(a) - AUC(b), cluster bootstrap over structures (percentile)."""
    ga, gb = group_up(sa, y, s, phase), group_up(sb, y, s, phase)
    st = sorted(ga)
    Ua, Ub, P = (np.array([g[k][i] for k in st]) for g, i in ((ga, 0), (gb, 0), (ga, 1)))
    if P.sum() == 0:
        return {"diff": None}
    idx = boot_structures(st)
    Pb = P[idx].sum(1)
    ok = Pb > 0
    d = (Ua[idx].sum(1)[ok] - Ub[idx].sum(1)[ok]) / Pb[ok]
    return {"auc_a": float(Ua.sum() / P.sum()), "auc_b": float(Ub.sum() / P.sum()), "diff": float((Ua.sum() - Ub.sum()) / P.sum()),
            "ci": [float(np.quantile(d, alpha / 2)), float(np.quantile(d, 1 - alpha / 2))], "level": 1 - alpha,
            "n_structures": len(st), "n_structures_with_pairs": int((P > 0).sum()), "pairs": float(P.sum()), "B": len(idx)}


def auc_ci(sa, y, s, alpha: float = 0.05, phase=None) -> dict:
    ga = group_up(sa, y, s, phase)
    st = sorted(ga)
    U, P = np.array([ga[k][0] for k in st]), np.array([ga[k][1] for k in st])
    if P.sum() == 0:
        return {"auc": None}
    idx = boot_structures(st)
    Pb = P[idx].sum(1)
    ok = Pb > 0
    a = U[idx].sum(1)[ok] / Pb[ok]
    return {"auc": float(U.sum() / P.sum()), "ci": [float(np.quantile(a, alpha / 2)), float(np.quantile(a, 1 - alpha / 2))], "level": 1 - alpha,
            "n_structures_with_pairs": int((P > 0).sum()), "pairs": float(P.sum())}


def mean_diff_ci(per_structure_diff: dict[int, float], alpha: float) -> dict:
    st = sorted(per_structure_diff)
    v = np.array([per_structure_diff[k] for k in st])
    idx = boot_structures(st)
    bm = v[idx].mean(1)
    return {"mean": float(v.mean()), "ci": [float(np.quantile(bm, alpha / 2)), float(np.quantile(bm, 1 - alpha / 2))], "level": 1 - alpha,
            "n_structures": len(st)}


def verdict_auc(ci: list[float], margin: float, pos: str, neg: str) -> str:
    lo, hi = ci
    if lo > 0:
        return pos
    if hi < 0:
        return neg
    if -margin <= lo and hi <= margin:
        return "EQUIVALENT"
    return "INDETERMINE"


# ------------------------------------------------------------------------------ alerts (protocol s.7)
def alert_states(score_seq: list[float], active_seq: list[bool], theta: float, d: int) -> list[int]:
    raw = [int(sc >= theta and not ac) for sc, ac in zip(score_seq, active_seq)]
    out = [0] * len(raw)
    run = 0
    for i, r in enumerate(raw):
        run = run + 1 if r else 0
        out[i] = int(run >= d)
    return out


def alert_episodes(states: list[int], hours: list[int]) -> list[tuple[int, int, int]]:
    """Runs of alert origins, fused across a single non-alert origin; 12-h refractory after an episode
    ends (a new episode cannot start within 12 h). Returns (start_idx, end_idx, start_hour)."""
    eps = []
    i = 0
    last_end_h = -10**9
    while i < len(states):
        if states[i] and hours[i] >= last_end_h + 12:
            j = i
            while j + 1 < len(states) and (states[j + 1] or (j + 2 < len(states) and states[j + 2])):
                j += 1
            while not states[j]:
                j -= 1
            eps.append((i, j, hours[i]))
            last_end_h = hours[j]
            i = j + 1
        else:
            i += 1
    return eps


def episode_alert_metrics(ep: dict, scores: list[float], theta: float, d: int) -> dict:
    hours = [o["hour"] for o in ep["origins"]]
    act = [o["labels"]["active"] for o in ep["origins"]]
    man = [o["manifest"] for o in ep["origins"]]
    st = alert_states(scores, act, theta, d)
    aeps = alert_episodes(st, hours)
    onsets = sorted({a // 4 for v in ep["trace"]["rupture_runs"].values() for a, _b, _s in v if a // 4 >= hours[0]})  # tick -> hour
    false = 0
    for i, j, _h in aeps:
        lo, hi = hours[i], hours[j] + 72
        if not any(lo <= on < hi for on in onsets):
            false += 1
    det = []
    for on in onsets:
        starts = [(hours[i], man[i]) for i, _j, _h in aeps if on - 72 <= hours[i] < on]
        det.append({"onset_h": on, "detected": bool(starts), "lead_h": (on - starts[0][0]) if starts else None,
                    "before_manifest": bool(starts) and not starts[0][1]})
    return {"false_alerts": false, "alert_origins": int(sum(st)), "origins": len(st), "ruptures": det}


def alert_summary(eps: list[dict], score_fn, theta: float, d: int) -> dict:
    fa = ao = no = 0
    rup = []
    for ep in eps:
        m = episode_alert_metrics(ep, score_fn(ep), theta, d)
        fa, ao, no = fa + m["false_alerts"], ao + m["alert_origins"], no + m["origins"]
        rup += m["ruptures"]
    det = [r for r in rup if r["detected"]]
    return {"false_alerts_per_unit_day": fa / (UNIT_DAYS_PER_EPISODE * len(eps)) if eps else None, "time_under_alert": ao / no if no else None,
            "ruptures": len(rup), "detected": len(det), "detection_rate": len(det) / len(rup) if rup else None,
            "median_lead_h": float(np.median([r["lead_h"] for r in det])) if det else None,
            "detected_before_manifest": sum(r["before_manifest"] for r in det)}


def tune_alert(eps: list[dict], score_fn) -> dict:
    vals = sorted({round(float(x), 9) for ep in eps for x in score_fn(ep)})
    best = None
    for d in (1, 2):
        for th in vals:  # smallest threshold satisfying the false-alert constraint
            sm = alert_summary(eps, score_fn, th, d)
            if sm["false_alerts_per_unit_day"] <= FA_MAX:
                cand = {"theta": th, "d": d, "val": sm}
                if best is None or (sm["detection_rate"] or 0) > (best["val"]["detection_rate"] or 0):
                    best = cand
                break
    return best or {"theta": math.inf, "d": 1, "val": None}


# ------------------------------------------------------------------------------ decisions (protocol s.8)
def eval_loss(ep: dict) -> np.ndarray:
    return np.array([np.mean([x["wait_patient_min"] for x in rows_]) for rows_ in ep["decision"]["eval"]])


def eval_metric(ep: dict, k: int, name: str) -> float:
    rows_ = ep["decision"]["eval"][k]
    if name == "share_A":
        return float(np.mean([x["wait_by_unit"]["A"] / max(1e-9, x["wait_patient_min"]) for x in rows_]))
    return float(np.mean([float(x[name]) for x in rows_]))


def structural_candidates() -> list[tuple]:
    return [("fixed", i) for i in range(10)] + [("scarcer", w) for w in range(1, 5)]


def structural_action(cand: tuple, ep: dict) -> int:
    kind, v = cand
    if kind == "fixed":
        return v
    s0 = ep["origins"][0]["S0"]
    res = "cl" if s0["c_cl"] <= s0["c_tr"] else "tr"
    ids = [a["id"] for a in ep["decision"]["actions"]]
    return ids.index(f"{res}+1_w{v}")
