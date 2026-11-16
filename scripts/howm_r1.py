#!/usr/bin/env python3
"""HOWM-1 R1 commands (run under scripts/howm_budget_run.py).

b0                      fit B0-pool on TRAIN, choose tau_f on TRAIN, loss scales s_f (TRAIN only)
pilot                   VAL-only timings, projections of every lot, declared ladder decision
train --kind --lr --seed --budget   resumable training run
select                  lr per model kind on VAL (seed 0), NORM A4
"""

from __future__ import annotations

import argparse
import json
import math
import resource
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hospitalos.howm import corpus as C  # noqa: E402
from hospitalos.howm import g0check  # noqa: E402
from hospitalos.howm.b0 import TAU_GRID, B0Params, fit_pool  # noqa: E402
from hospitalos.howm.dataset import HAZARD_FAMILIES  # noqa: E402
from hospitalos.howm.generator import EVAL_DAY, PARTITION_SIZES  # noqa: E402
from hospitalos.howm.predict import b0_predict, member_logscores  # noqa: E402

EVID = C.EVID
B0_FILE = EVID / "B0_PARAMS.json"
SCALES_FILE = EVID / "LOSS_SCALES.json"
PILOT_FILE = EVID / "PILOT.json"
FAMS = (*HAZARD_FAMILIES, "presence", "arrivals", "care")
LRS = (3e-4, 1e-3)
torch.set_num_threads(4)


def load_part(part: str, n: int | None = None, guarded: bool = False) -> list[dict]:
    n = PARTITION_SIZES[part] if n is None else n
    return [C.load(part, i, allow_guarded=guarded) for i in range(n)]


def b0_params() -> B0Params:
    return B0Params.from_json(json.loads(B0_FILE.read_text()))


def scales() -> dict[str, float]:
    from hospitalos.howm.heads import check_scales

    return check_scales(json.loads(SCALES_FILE.read_text())["s_f"])


def cmd_b0(train_n: int) -> None:
    from hospitalos.howm.nets import B2, forward_losses, make_batch

    g0check.check()
    t0 = time.time()
    tr = load_part("TRAIN", train_n)
    eps = [d["episode"] for d in tr]
    p = fit_pool(eps)
    arr = [o[5] for ep in eps for o in ep.observations if o[2] == "request_arrival"]
    p.new_profile_freq = {
        "p_iso": float(np.mean([a["iso"] for a in arr])),
        "p_transport": float(np.mean([a["transport"] for a in arr])),
        **{f"p_acuity_{k}": float(np.mean([a["acuity"] == k for a in arr])) for k in (1, 2, 3)},
    }
    # tau_f on TRAIN only: predictive log-score of the next 24 h (grid), per family
    origins = [(d["data"], H) for d in tr for H in d["data"].origins if (H - 24) % 12 == 0]
    tau_scores = {}
    for tau in TAU_GRID:
        p.tau = {f: tau for f in FAMS}
        tot = {f: [0.0, 0] for f in FAMS}
        for est, H in origins:
            sc = member_logscores(b0_predict(p, est.origins[H], est, True), est.origins[H], 24)
            for f in FAMS:
                tot[f][0] += float(np.sum(sc[f]))
                tot[f][1] += len(sc[f])
        tau_scores[tau] = {f: tot[f][0] / max(tot[f][1], 1) for f in FAMS}
    p.tau = {f: max(TAU_GRID, key=lambda t: tau_scores[t][f]) for f in FAMS}
    B0_FILE.write_text(json.dumps(p.to_json(), indent=1) + "\n")
    # loss scales: B0-pool TRAIN NLL per family on the TRAINING items (fresh B2 heads == B0-pool)
    torch.manual_seed(0)
    m = B2(p)
    pairs = [(d["data"], H) for d in tr for H in sorted(d["data"].origins)]
    sums, cnt = {}, {}
    with torch.no_grad():
        for i in range(0, len(pairs), 32):
            for f, (s, n) in forward_losses(m, make_batch(pairs[i : i + 32], "B2")).items():
                sums[f] = sums.get(f, 0.0) + float(s)
                cnt[f] = cnt.get(f, 0) + n
    s_f = {f: sums[f] / cnt[f] for f in sums}
    from hospitalos.howm.heads import check_scales

    check_scales(s_f)
    SCALES_FILE.write_text(
        json.dumps(
            {
                "rule": "s_f = mean TRAIN NLL of B0-pool per family on the training items (NORM N1.2)",
                "s_f": s_f,
                "counts": cnt,
                "train_establishments": train_n,
                "excluded_no_train_items": sorted(set(FAMS) - set(s_f)),
            },
            indent=1,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "tau": p.tau,
                "tau_scores": {str(k): v for k, v in tau_scores.items()},
                "s_f": s_f,
                "seconds": round(time.time() - t0, 1),
            }
        )
    )


def _freq(p: B0Params):
    from hospitalos.howm.rollout import NewProfileFreq

    f = p.new_profile_freq
    return NewProfileFreq(
        f["p_iso"], (f["p_acuity_1"], f["p_acuity_2"], f["p_acuity_3"]), f["p_transport"]
    )


def cmd_pilot() -> None:
    """VAL only. Measures, projects every lot at full grid x 1.25, applies only the declared ladder."""
    from hospitalos.howm.controllers import evaluate_instant, model_choice
    from hospitalos.howm.history import PublicStream
    from hospitalos.howm.nets import B2, H1, forward_losses, make_batch, n_params, predict_many
    from hospitalos.howm.rollout import ModelProvider, rollout, rollout_key
    from hospitalos.howm.train import BATCH, evaluate_loss

    g0check.check()
    p, sc = b0_params(), scales()
    T: dict[str, float] = {}
    t0 = time.time()
    tr = load_part("TRAIN", 8)
    va = load_part("VAL", 4)
    T["load_12_files_s"] = time.time() - t0
    train_pairs = [(d["data"], H) for d in tr for H in sorted(d["data"].origins)]
    val_pairs = [(d["data"], H) for d in va for H in sorted(d["data"].origins)]
    counts = {}
    for kind in ("B2", "H1"):
        torch.manual_seed(0)
        m = B2(p) if kind == "B2" else H1(p)
        counts[kind] = n_params(m)
        opt = torch.optim.Adam(m.parameters(), lr=1e-3)
        ts = []
        for i in range(6):
            t1 = time.time()
            batch = make_batch(train_pairs[i * BATCH : (i + 1) * BATCH], kind)
            from hospitalos.howm.nets import total_loss

            loss = total_loss(forward_losses(m, batch), sc)
            opt.zero_grad()
            loss.backward()
            opt.step()
            ts.append(time.time() - t1)
        T[f"{kind}_train_step_s"] = float(np.median(ts[1:]))
        t1 = time.time()
        evaluate_loss(m, kind, val_pairs[: 4 * BATCH], sc)
        T[f"{kind}_val_batch_s"] = (time.time() - t1) / 4
        t1 = time.time()
        predict_many(m, va[0]["data"], list(range(24, 56)))
        T[f"{kind}_predict_origin_s"] = (time.time() - t1) / 32
    # rollouts (B0-local) and log-scores per origin
    est, ep = va[0]["data"], va[0]["episode"]
    ps = PublicStream(ep.observations)
    t1 = time.time()
    n = 0
    for H in range(24, 144, 10):
        ps.advance(H * 60)
        eng = ps.to_engine(H * 60)
        pr = b0_predict(p, est.origins[H], est, True)
        member_logscores(pr, est.origins[H], 24)
        for mm in range(16):
            rollout(
                eng,
                ModelProvider(pr, est.origins[H], 4 * H, mm, rollout_key("VAL", 0, H), _freq(p)),
                None,
            )
        n += 1
    T["origin_16_rollouts_plus_scores_s"] = (time.time() - t1) / n
    # one decision instant: truth controllers + 4 systems x 16 candidates x 16 rollouts (B0 used for timing)
    tau = EVAL_DAY * 96 + 11 * 4
    ps2 = PublicStream(ep.observations)
    ps2.advance(tau * 15)
    peng = ps2.to_engine(tau * 15)
    t1 = time.time()
    evaluate_instant(ep, tau, peng, {}, controllers=("C_full", "C_param"))
    T["instant_truth_s"] = time.time() - t1
    H = tau // 4
    pr = b0_predict(p, est.origins[H] if H in est.origins else est.origins[143], est, True)
    od = est.origins[H] if H in est.origins else est.origins[143]
    t1 = time.time()
    model_choice(
        peng,
        [ModelProvider(pr, od, tau, mm, rollout_key("VAL", 0, H), _freq(p)) for mm in range(16)],
    )
    T["instant_one_system_s"] = time.time() - t1
    T["peak_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    # ------------------------------------------------------------------ projections (x 1.25)
    n_tr = len(C.ORIGINS["TRAIN"]) * PARTITION_SIZES["TRAIN"]
    n_va = len(C.ORIGINS["VAL"]) * PARTITION_SIZES["VAL"]
    load_full = T["load_12_files_s"] * 60 / 12

    def train_lot(kind: str, n_train: int, runs: int) -> float:
        epoch = (
            math.ceil(n_train / BATCH) * T[f"{kind}_train_step_s"]
            + math.ceil(n_va / BATCH) * T[f"{kind}_val_batch_s"]
        )
        return 1.25 * (runs * 60 * epoch + runs * 3 * load_full)

    eval_pred = (
        36
        * 120
        * (
            T["origin_16_rollouts_plus_scores_s"] * 4
            + 3 * (T["B2_predict_origin_s"] + T["H1_predict_origin_s"])
        )
    )

    def eval_lot(instants: int, m_dec: int) -> float:
        dec = 36 * instants * (T["instant_truth_s"] + 4 * T["instant_one_system_s"] * m_dec / 16)
        return 1.25 * (eval_pred + dec + 36 * load_full / 60 * 2)

    caps = {"R1.B2": 3000.0, "R1.H1": 7200.0, "R1.EVAL": 3600.0}
    ladder = []
    state = {"instants": 4, "m_dec": 16, "train_n": PARTITION_SIZES["TRAIN"], "runs": 4}

    def project() -> dict[str, float]:
        ntr = len(C.ORIGINS["TRAIN"]) * state["train_n"]
        return {
            "R1.B2": train_lot("B2", ntr, state["runs"]),
            "R1.H1": train_lot("H1", ntr, state["runs"]),
            "R1.EVAL": eval_lot(state["instants"], state["m_dec"]),
        }

    proj = project()
    steps = [
        (
            "1: decision diagnostic 4->2 instants, M 16->8 (decision only)",
            lambda: state.update(instants=2, m_dec=8),
        ),
        (
            "2: TRAIN 48->32 establishments (all models, B0 included)",
            lambda: state.update(train_n=32),
        ),
        ("3: seeds 3->2 for B2 and H1", lambda: state.update(runs=3)),
    ]
    for name, act in steps:
        if all(proj[k] <= caps[k] for k in caps):
            break
        act()
        ladder.append(name)
        proj = project()
    feasible = all(proj[k] <= caps[k] for k in caps)
    out = {
        "timings": T,
        "param_counts": counts,
        "projections_x1_25": proj,
        "caps": caps,
        "ladder_applied": ladder,
        "state": state,
        "feasible": feasible,
        "n_train_origins": n_tr,
        "n_val_origins": n_va,
        "rule": "projection = measured unit cost x planned volume x 1.25; max 60 epochs assumed for every run; "
        "only declared ladder steps; predictive origins never reduced; otherwise stop",
    }
    PILOT_FILE.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out))


def cmd_permuted() -> None:
    """T-INF-08 (diagnostic, non-blocking): B2 trained briefly with inputs paired to OTHER establishments'
    labels must not beat B0-pool on VAL beyond noise."""
    from hospitalos.howm.nets import B2
    from hospitalos.howm.train import evaluate_loss, train
    import hospitalos.howm.train as TR

    p, sc = b0_params(), scales()
    tr = load_part("TRAIN", 8)
    va = load_part("VAL", 3)
    swapped = [replace(tr[i]["data"], b2=tr[(i + 1) % len(tr)]["data"].b2) for i in range(len(tr))]
    pairs = [(e, H) for e in swapped for H in sorted(e.origins)]
    val = [(d["data"], H) for d in va for H in sorted(d["data"].origins)][::4]
    TR.RUNS = EVID / "diag_permuted"
    torch.manual_seed(0)
    base = evaluate_loss(B2(p), "B2", val, sc)["total"]
    r = train("B2", 1e-3, 0, 400, pairs, val, p, sc, max_steps=60)
    obj = __import__("hospitalos.howm.ckpt", fromlist=["x"])
    meta = json.loads((TR.run_dir("B2", 1e-3, 0) / "state.json").read_text())
    m = B2(p)
    m.load_state_dict(
        obj.load_verified(TR.run_dir("B2", 1e-3, 0) / "last.pt", meta["last_sha256"])["model"]
    )
    after = evaluate_loss(m, "B2", val, sc)["total"]
    out = {
        "test": "T-INF-08 permuted inputs/labels",
        "val_loss_B0_pool": base,
        "val_loss_after_60_steps": after,
        "improvement": base - after,
        "status": r["status"],
        "note": "diagnostic only; a large improvement would suggest leakage",
    }
    (EVID / "DIAG_T_INF_08.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out))


def cmd_train(kind: str, lr: float, seed: int, budget: float, train_n: int) -> None:
    from hospitalos.howm.train import train

    g0check.check()
    p, sc = b0_params(), scales()
    t0 = time.time()
    tr = load_part("TRAIN", train_n)
    va = load_part("VAL")
    load_s = time.time() - t0
    train_pairs = [(d["data"], H) for d in tr for H in sorted(d["data"].origins)]
    val_pairs = [(d["data"], H) for d in va for H in sorted(d["data"].origins)]
    res = train(kind, lr, seed, budget - load_s - 15.0, train_pairs, val_pairs, p, sc)
    print(json.dumps({"kind": kind, "lr": lr, "seed": seed, "load_s": round(load_s, 1), **res}))


def cmd_select() -> None:
    from hospitalos.howm.train import run_dir

    out = {}
    for kind in ("B2", "H1"):
        best = {}
        for lr in LRS:
            st = json.loads((run_dir(kind, lr, 0) / "state.json").read_text())
            done = st["log"] and len(st["log"]) > 0
            best[lr] = min(e["val_total"] for e in st["log"]) if done else math.inf
        lo = min(best.values())
        chosen = min(lr for lr in LRS if best[lr] <= lo * (1 + 1e-4))  # tie -> smaller lr (A4)
        out[kind] = {"val_best_by_lr": {str(k): v for k, v in best.items()}, "chosen_lr": chosen}
    (EVID / "SELECTION.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--kind", default="B2")
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--budget", type=float, default=500.0)
    ap.add_argument("--train-n", type=int, default=PARTITION_SIZES["TRAIN"])
    a = ap.parse_args()
    if a.cmd == "b0":
        cmd_b0(a.train_n)
    elif a.cmd == "pilot":
        cmd_pilot()
    elif a.cmd == "permuted":
        cmd_permuted()
    elif a.cmd == "train":
        cmd_train(a.kind, a.lr, a.seed, a.budget, a.train_n)
    elif a.cmd == "select":
        cmd_select()
    else:
        raise SystemExit(f"unknown command {a.cmd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
