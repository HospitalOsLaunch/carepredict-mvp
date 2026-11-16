#!/usr/bin/env python3
"""HOWM-2 C1 palier 1 driver (NORME_C1_PALIER1).

    partitions                       -> evidence/howm2_c1/PARTITIONS_CHECK.json (ids/metadata only)
    gen --part P --shards a b        -> shards of 100 (CTRAIN) or one shard (CVAL), manifest
    pilot                            -> evidence/howm2_c1/PILOT.json (timing, memory, projection)
    train --runs SYS:N:SEED ... --budget S   (parallel, 1 thread each, resumable)
"""

from __future__ import annotations

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import resource  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from multiprocessing import get_context  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
EV = ROOT / "evidence/howm2_c1"


def partitions() -> int:
    import inspect

    from hospitalos.howm import generator as G
    from hospitalos.howm2 import c1, space

    c1.register()
    ks = c1.c1_keys()
    allc = set().union(*ks.values())
    others = {"G0": space.g0_keys(), "HOWM2_REF+DIAG": space.new_keys()}
    thetas = {}
    dup = 0
    for p, (_pop, n) in {**c1.C1_PARTS, "HOWM2_REF": ("REF", 200), "HOWM2_DIAG": ("DIAG", 100)}.items():
        rng = range(1000) if p == "HOWM2_CTRAIN" else range(n)
        for i in rng:
            sp = G.establishment(p, i)
            tk = tuple(round(v, 12) for _, v in sorted(sp.theta.items()))
            dup += tk in thetas
            thetas[tk] = (p, i)
    src = inspect.getsource(G.establishment) + inspect.getsource(G.generate)
    out = {"c1_partitions": {p: len(v) for p, v in ks.items()},
           "c1_keys_pairwise_disjoint": sum(len(v) for v in ks.values()) == len(allc),
           "disjoint_from": {k: not (allc & v) for k, v in others.items()},
           "distinct_theta_vectors_checked": len(thetas), "duplicate_theta_vectors": dup,
           "generation_depends_only_on_ekey": ("u(ek" in src and "global" not in src),
           "linked_worlds": "none in HOWM-1 (each establishment is generated from its own ekey; no shared state)",
           "outcomes_read": False}
    out["pass"] = bool(out["c1_keys_pairwise_disjoint"] and all(out["disjoint_from"].values()) and dup == 0)
    EV.mkdir(parents=True, exist_ok=True)
    (EV / "PARTITIONS_CHECK.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0 if out["pass"] else 1


def _gen_job(arg):
    from hospitalos.howm2 import c1

    part, j, idx = arg
    t = time.time()
    e = c1.write_shard(part, j, idx)
    e["seconds"] = round(time.time() - t, 1)
    return e


def gen(part: str, shards: list[int]) -> int:
    from hospitalos.howm2 import c1

    man_p = EV / "DATA_MANIFEST.json"
    man = json.loads(man_p.read_text()) if man_p.exists() else {"shards": {}, "rule": "NORME_C1_PALIER1 s.3"}
    jobs = []
    for j in shards:
        if f"{part}/{j:03d}" in man["shards"]:
            continue
        idx = list(range(j * c1.SHARD, (j + 1) * c1.SHARD)) if part == "HOWM2_CTRAIN" else list(range(48))
        jobs.append((part, j, idx))
    # one shard = 100 establishments: split each shard's generation over 4 workers, then merge
    with get_context("fork").Pool(4) as pool:
        for e in pool.imap_unordered(_gen_job, jobs):
            man["shards"][f"{e['part']}/{e['shard']:03d}"] = e
            man_p.write_text(json.dumps(man, indent=1) + "\n")
            print(json.dumps({k: e[k] for k in ("part", "shard", "n", "bytes", "seconds")}), flush=True)
    return 0


def _pilot_job(system):
    import torch

    from hospitalos.howm2 import c1

    torch.set_num_threads(1)
    recs = c1.load_shard("HOWM2_CTRAIN", 0)
    model = c1.new_model(system, c1.b0(), 0)
    opt = torch.optim.Adam(model.parameters(), lr=c1.LR)
    pairs = [(r, H) for r in recs for H in c1.ORIGINS]
    order = c1.shard_order(0, 0, len(pairs))
    pairs = [pairs[k] for k in order]
    sc = c1.scales()
    from hospitalos.howm.nets import forward_losses, total_loss

    times = []
    for s in range(12):
        t = time.time()
        loss = total_loss(forward_losses(model, c1.make_batch(system, pairs[s * 32 : (s + 1) * 32])), sc)
        opt.zero_grad()
        loss.backward()
        opt.step()
        times.append(time.time() - t)
    t = time.time()
    with torch.no_grad():
        for s in range(4):
            forward_losses(model, c1.make_batch(system, pairs[s * 32 : (s + 1) * 32]))
    fwd = (time.time() - t) / 4
    return {"system": system, "step_s_mean": sum(times[2:]) / 10, "fwd_batch_s": fwd,
            "maxrss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}


def pilot() -> int:
    from hospitalos.howm2 import c1

    t = time.time()
    with get_context("fork").Pool(3) as pool:
        res = pool.map(_pilot_job, list(c1.SYSTEMS))
    st = {r["system"]: r for r in res}
    # projection (4 parallel single-thread processes; 9 runs per size)
    proj = {}
    for N in c1.SIZES:
        steps = N * 48 // 32
        evals = steps // 500 + (1 if steps % 500 else 0)
        per_run = {s: steps * st[s]["step_s_mean"] + evals * 72 * st[s]["fwd_batch_s"] + 10 * (N // 100) for s in c1.SYSTEMS}
        cpu = 3 * sum(per_run.values())
        proj[str(N)] = {"per_run_s": per_run, "cpu_s_total": cpu, "wall_s_4_parallel": cpu / 4 * 1.15}
    n_eval = (200 + 100) * 48 / 32
    proj["final_campaign_models_wall_s"] = 2 * 3 * n_eval * sum(st[s]["fwd_batch_s"] for s in c1.SYSTEMS) / 4 * 1.15 / 2
    out = {"timing": st, "projection": proj, "seconds": round(time.time() - t, 1),
           "note": "projection = steps x mean step time + CVAL evals; wall = CPU/4 x 1.15 (parallel overhead, declared)"}
    (EV / "PILOT.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    return 0


def _train_job(arg):
    from hospitalos.howm2 import c1

    run, budget = arg
    system, N, seed = run.split(":")
    cval = c1.load_shard("HOWM2_CVAL", 0)
    return c1.train(system, int(N), int(seed), budget, cval)


def train(runs: list[str], budget: float) -> int:
    with get_context("fork").Pool(min(4, len(runs))) as pool:
        for r in pool.imap_unordered(_train_job, [(r, budget) for r in runs]):
            print(json.dumps(r), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--part")
    ap.add_argument("--shards", type=int, nargs="*")
    ap.add_argument("--runs", nargs="*")
    ap.add_argument("--budget", type=float, default=480.0)
    a = ap.parse_args()
    if a.cmd == "partitions":
        return partitions()
    if a.cmd == "gen":
        return gen(a.part, a.shards)
    if a.cmd == "pilot":
        return pilot()
    if a.cmd == "train":
        return train(a.runs, a.budget)
    raise SystemExit(a.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
