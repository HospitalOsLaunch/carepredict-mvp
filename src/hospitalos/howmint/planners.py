"""HOWM-INT-1 common planner and model-based policies.

Every planner (W, D variants, R1, F) uses the SAME admissible catalogue, the SAME candidate sequences
(loop.sequences), the SAME lookahead (48 h for daily decisions, 24 h for 6-hourly), the SAME selection operator
(minimal predicted cost; ties -> fewer staff-hours, then candidate index) and executes only a0.
Inputs: the policy's own public history (graph features built from its own stream at t, t - 6 h, t - 24 h)."""

from __future__ import annotations

import time
from typing import Any, Callable

import numpy as np

from . import actions as A
from . import data as DA
from . import features as F
from . import loop as L

TPH = 4


def fixed_features(g: dict, sch: dict, desc: np.ndarray, L_steps: int) -> np.ndarray:
    """Fixed-length vector for Ridge/HGB references: pooled unit features (mean/max/sum), resources, global,
    sequence descriptor, schedule summaries over the lookahead, features of the unit targeted by staff actions."""
    u = g["unit"]
    us = sch["U"][:L_steps].mean(0)  # [n,3]
    tgt = int(np.argmax(us[:, 0])) if us[:, 0].max() > 0 else -1
    tu = u[tgt] if tgt >= 0 else np.zeros(u.shape[1], np.float32)
    return np.concatenate([u.mean(0), u.max(0), u.sum(0), g["res"].reshape(-1), g["glob"], desc, us.mean(0), us.max(0),
                           sch["R"][:L_steps].mean(0).reshape(-1), tu, [float(len(u))]]).astype(np.float32)


def candidates(peng: Any, units: list[str], n: int, t_start: int) -> tuple[list[dict], list[bool], list[list]]:
    cat = A.catalogue(peng, units)
    adm = [A.admissible(peng, a, n, t_start) for a in cat]
    return cat, adm, L.sequences(cat, adm)


def choose(costs: np.ndarray, seqs: list[list]) -> int:
    staff = [sum(a["staff_hours"] for a in s if a is not None) for s in seqs]
    return int(min(range(len(seqs)), key=lambda i: (round(float(costs[i]), 6), staff[i], i)))


def graph_at(view: Callable, t: int, units: list[str], t_start: int, n: int) -> tuple[dict, Any, Any]:
    snaps = {}
    for lag in (6, 24):
        ps_h, pe_h = view(t - lag * TPH)
        snaps[lag] = {un: F.unit_raw(pe_h, ps_h, un) for un in units}
    ps, pe = view(t)
    return F.graph(pe, ps, snaps, units, t_start, n), ps, pe


def model_policy(score: Callable, interval_h: int, timing: list | None = None) -> Callable:
    """Wrap a sequence scorer score(g, schedules, descs, n, L) -> predicted lookahead costs."""

    def pol(**kw: Any) -> dict:
        t0 = time.process_time()
        sp, t, t_start = kw["spec"], kw["t"], kw["t_start"]
        g, _ps, pe = graph_at(kw["view"], t, sp.units, t_start, sp.n)
        cat, adm, seqs = candidates(pe, sp.units, sp.n, t_start)
        Ls = DA.LOOKAHEAD_STEPS[sp.n]
        schs = [F.schedule(sq, sp.units, t, Ls, interval_h, sp.drop) for sq in seqs]
        descs = [F.seq_descriptor(sq, t) for sq in seqs]
        costs = score(g, schs, descs, sp.n, Ls)
        i = choose(np.asarray(costs), seqs)
        if timing is not None:
            timing.append(time.process_time() - t0)
        return seqs[i][0]

    return pol


# ------------------------------------------------------------------------------ scorers
def w_scorer(models: list, norm: dict) -> Callable:
    """W (ensemble = mean predicted cost over the given models; one model = single seed)."""
    import torch

    def score(g, schs, descs, n, Ls):
        m = len(schs)
        s = {"unit": np.repeat(g["unit"][None], m, 0), "res": np.repeat(g["res"][None], m, 0), "glob": np.repeat(g["glob"][None], m, 0),
             "uu": np.repeat(g["uu"][None], m, 0), "U": np.stack([x["U"] for x in schs]), "R": np.stack([x["R"] for x in schs]),
             "C": np.stack([x["C"] for x in schs]), "desc": np.stack(descs), "n": n,
             "states": np.zeros((m, 1, Ls, n, 9), np.float32), "costs": np.zeros((m, 1, Ls, n), np.float32), "n24": np.zeros((m, 1, Ls, n))}
        t = DA.tensors(s, norm)
        out = []
        with torch.no_grad():
            for mod in models:
                _sh, ch, _rh = mod(t["unit"], t["res"], t["glob"], t["ur_mask"], t["uu"], t["U"], t["R"], t["C"], t["beds"], steps=Ls)
                out.append((ch.sum((1, 2)) * norm["cost_s"]).numpy())
        return np.mean(out, 0)

    return score


def d_scorer(model: Any) -> Callable:
    """Ridge/HGB reference: predicted cost = base(situation) + effect(situation, sequence)."""

    def score(g, schs, descs, n, Ls):
        X = np.stack([fixed_features(g, sc, de, Ls) for sc, de in zip(schs, descs)])
        return model.predict(X)

    return score


def dset_scorer(net: Any, norm: dict) -> Callable:
    import torch

    def score(g, schs, descs, n, Ls):
        m = len(schs)
        s = {"unit": np.repeat(g["unit"][None], m, 0), "res": np.repeat(g["res"][None], m, 0), "glob": np.repeat(g["glob"][None], m, 0),
             "uu": np.repeat(g["uu"][None], m, 0), "U": np.stack([x["U"] for x in schs]), "R": np.stack([x["R"] for x in schs]),
             "C": np.stack([x["C"] for x in schs]), "desc": np.stack(descs), "n": n,
             "states": np.zeros((m, 1, Ls, n, 9), np.float32), "costs": np.zeros((m, 1, Ls, n), np.float32), "n24": np.zeros((m, 1, Ls, n))}
        t = DA.tensors(s, norm)
        with torch.no_grad():
            base, eff = net(t["unit"], t["res"], t["glob"], t["U"][:, :Ls], t["R"][:, :Ls], t["desc"])
        return ((base + eff) * norm["cum_s"]).numpy()

    return score


# ------------------------------------------------------------------------------ F and R1 (2-unit mode), adapted
def sim_rollout(eng_m: Any, prov_m: Any, seq: list, hours: int, interval_h: int, n: int, t_start: int) -> float:
    """Simulated lookahead cost of a sequence from a simulator draw: same commitment/admissibility rules as truth."""
    from hospitalos.howm.generator import refresh_private

    from . import world as W

    eng = eng_m.clone()
    eng.on_event = None
    eng.emit_log = False
    cal = W._Cal(prov_m, eng.spec_meta.get("drop", {}))
    refresh_private(eng, cal)
    t0 = eng.tick
    w0 = sum(eng.waiting_ticks.values())
    for i in range(hours * TPH):
        k = i // (interval_h * TPH)
        if i % (interval_h * TPH) == 0 and k < len(seq) and seq[k] is not None:
            a = seq[k] if k == 0 else L._shift(eng, seq[k], t0 + k * interval_h * TPH, None)
            if a is not None and A.admissible(eng, a, n, t_start):
                A.apply(eng, a, cal)
        eng.step(prov_m)
    return 15.0 * (sum(eng.waiting_ticks.values()) - w0)


def as_engine_n(eng: Any, pe: Any) -> Any:
    """Simulator engine (frozen-class clone from the F/R1 chain) -> EngineN carrying the public commitments,
    external-slot state and calendar of the policy's public engine."""
    from . import world as W

    if isinstance(eng, W.EngineN):
        return eng
    out = W.EngineN.__new__(W.EngineN)
    out.__dict__.update(eng.__dict__)
    for k in ("spec_meta", "base_c_cl", "base_c_tr", "aval_used", "aval_blocked", "transfer_pending", "commitments", "coord_ticks"):
        setattr(out, k, L.deep(getattr(pe, k)))
    return out


def sim_policy(kind: str, Md: int, interval_h: int, timing: list | None = None, rep: int = 0) -> Callable:
    """F (historical B-FRAG chain: L4 posterior + L4-N nowcast + generator-structure simulator) or R1 (L2 statistical
    dynamics), adapted to repeated decisions: at EVERY decision the chain is re-run on the policy's own public history;
    candidate sequences, lookahead and selection operator are the common ones. 2-unit mode only."""
    import json as _json
    from pathlib import Path as _P

    from hospitalos.bfrag import core as K
    from hospitalos.bfrag2 import core2 as C2
    from hospitalos.howm.b0 import B0Params

    from . import world as W

    root = _P(__file__).resolve().parents[3]
    pb = B0Params.from_json(_json.loads((root / "evidence/howm1/B0_PARAMS.json").read_text())) if kind == "R1" else None

    def pol(**kw: Any) -> dict:
        t0c = time.process_time()
        sp, t, t_start = kw["spec"], kw["t"], kw["t_start"]
        assert sp.n == 2, "F/R1 are adapted to the 2-unit mode only"
        ps, pe = kw["view"](t)
        pub = ps.obs[: ps.i]
        w = K.make_world(sp.part, sp.idx, W.D2, family=sp.family)
        base_pe = pe.clone()
        if kind == "F":
            pairs = C2.f_pairs(w, pub, ps, base_pe, t, Md, rep)
        else:
            from hospitalos.howm2 import data as D_

            orig = D_.origins
            D_.origins = _origins_ext()  # frozen origins() sizes arrays for 192-h HOWM-1 episodes; decisions here reach 216 h
            try:
                pairs = C2.r1_pairs(w, pub, ps, base_pe, t, pb, Md, rep)
            finally:
                D_.origins = orig
        cat, adm, seqs = candidates(pe, sp.units, sp.n, t_start)
        hours = DA.LOOKAHEAD_STEPS[sp.n] * 2
        costs = np.array([np.mean([sim_rollout(as_engine_n(e, pe), pv, sq, hours, interval_h, sp.n, t_start) for e, pv in pairs]) for sq in seqs])
        i = choose(costs, seqs)
        if timing is not None:
            timing.append(time.process_time() - t0c)
        return seqs[i][0]

    return pol


_ORIGINS_EXT = None


def _origins_ext():
    """howm2.data.origins derived by source substitution with a 400-h horizon (frozen source untouched; the
    arrays only hold arrival labels and features indexed by absolute hour)."""
    global _ORIGINS_EXT
    if _ORIGINS_EXT is None:
        import inspect

        from hospitalos.howm2 import data as D_

        src = inspect.getsource(D_.origins)
        ns = dict(D_.__dict__)
        ns["N_HOURS"] = 400
        exec(compile(src, "<int1 derived origins (400 h)>", "exec"), ns)  # noqa: S102
        _ORIGINS_EXT = ns["origins"]
    return _ORIGINS_EXT
