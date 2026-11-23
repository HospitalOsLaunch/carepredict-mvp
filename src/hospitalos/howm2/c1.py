"""HOWM-2 C1 palier 1 (decision n.5; NORME C1 palier 1, addendum C1-P1): data stream, systems
C.1 / C.2a / C.2b, one-pass training with exact resume, predictions.

Frozen HOWM-1 code is only imported; the C.2a / C.2b encoders are derived from the frozen H1
source by declared textual substitutions (same encoder, same heads), checked by tests.
"""

from __future__ import annotations

import gzip
import hashlib
import inspect
import json
import math
import pickle
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

from hospitalos.howm import generator as G
from hospitalos.howm import nets
from hospitalos.howm.b0 import B0Params, local_deltas
from hospitalos.howm.dataset import HAZARD_FAMILIES, build
from hospitalos.howm.history import PublicStream
from hospitalos.howm.keys import key
from hospitalos.howm.nets import H1, HN, NetConfig, forward_losses, total_loss

from . import space
from .ladder import long_arrivals_delta, window_long

ROOT = Path(__file__).resolve().parents[3]
EV = ROOT / "evidence" / "howm2_c1"
DATA = Path(
    "/tmp/claude-0/-home-user-carepredict-mvp/766fa6b7-33a5-533f-a444-71f97217a53a/scratchpad/howm2_c1_data"
)
C1_PARTS = {"HOWM2_CTRAIN": ("REF", 10000), "HOWM2_CVAL": ("REF", 48), "HOWM2_CEVAL": ("REF", 200)}
ORIGINS = list(range(24, 166, 3))
SHARD = 100
BATCH = 32
EVAL_EVERY = 500
PATIENCE = 6
LR = 3e-4
SEEDS = (0, 1, 2)
SIZES = (100, 1000)
SYSTEMS = ("C.1", "C.2a", "C.2b")
L2D_ORDER = ("auth", "ready", "transport", "cleaning", "confirmation", "arrivals", "care", "presence")
CKPT_EVERY_S = 400.0


def register() -> None:
    space.register()
    for p, (pop, n) in C1_PARTS.items():
        G.PARTITION_SIZES[p] = n
        G.POPULATION_OF[p] = pop


def c1_keys() -> dict[str, set[int]]:
    return {p: {key("HOWM1", p, i) for i in range(n)} for p, (_, n) in C1_PARTS.items()}


# ------------------------------------------------------------------------------ data
def b0() -> B0Params:
    return B0Params.from_json(json.loads((ROOT / "evidence/howm1/B0_PARAMS.json").read_text()))


def l2_inputs(p: B0Params, ep: Any, est: Any) -> dict[int, list[float]]:
    """The 8 local intercepts of L2 (B0-local over the whole public past) at every origin."""
    ps = PublicStream(ep.observations)
    out = {}
    for H in ORIGINS:
        t = H * 60
        ps.advance(t)
        od = est.origins[H]
        d = local_deltas(p, {**window_long(ps, t), "arrivals": od.window["arrivals"]}, est.n_beds)
        d["arrivals"] = long_arrivals_delta(p, ps, est.n_beds, t)
        out[H] = [float(d[f]) for f in L2D_ORDER]
    return out


def make_record(part: str, i: int, p: B0Params) -> dict[str, Any]:
    ep = G.generate(G.establishment(part, i))
    est = build(ep, ORIGINS)
    return {"part": part, "index": i, "ekey": ep.spec.ekey, "data": est, "l2d": l2_inputs(p, ep, est)}


def shard_path(part: str, j: int) -> Path:
    return DATA / part / f"{j:03d}.pkl.gz"


def write_shard(part: str, j: int, idx: list[int]) -> dict[str, Any]:
    register()
    p = b0()
    recs = [make_record(part, i, p) for i in idx]
    path = shard_path(part, j)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wb", compresslevel=3) as f:
        pickle.dump(recs, f, protocol=pickle.HIGHEST_PROTOCOL)
    return {
        "part": part,
        "shard": j,
        "indices": [idx[0], idx[-1]],
        "n": len(idx),
        "file": str(path.relative_to(DATA)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "ekeys_sha256": hashlib.sha256(json.dumps([r["ekey"] for r in recs]).encode()).hexdigest(),
    }


def manifest() -> dict[str, Any]:
    return json.loads((EV / "DATA_MANIFEST.json").read_text())


def load_shard(part: str, j: int) -> list[dict[str, Any]]:
    entry = manifest()["shards"][f"{part}/{j:03d}"]
    path = shard_path(part, j)
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise RuntimeError(f"shard hash mismatch: {path}")
    with gzip.open(path, "rb") as f:
        return pickle.load(f)  # self-produced, hash-checked against the manifest


# ------------------------------------------------------------------------------ systems
def _derive(fn: Any, subs: list[tuple[str, str]], name: str) -> Any:
    src = inspect.getsource(fn)
    for _a, b in subs:  # new names must not collide with names of the frozen source
        for tok in ("c1_win_start", "Wl"):
            if tok in b and tok in src:
                raise RuntimeError(f"derivation of {name}: name collision {tok}")
    lines = src.splitlines()
    ind = len(lines[0]) - len(lines[0].lstrip())
    src = "\n".join(line[ind:] for line in lines)
    for a, b in subs:
        if src.count(a) != 1:
            raise RuntimeError(f"derivation of {name}: pattern found {src.count(a)} times: {a!r}")
        src = src.replace(a, b)
    ns: dict[str, Any] = {}
    exec(compile(src, f"<c1-derived {name}>", "exec"), nets.__dict__, ns)  # noqa: S102
    return ns[fn.__name__]


graph_batch_window = _derive(
    nets.graph_batch,
    [
        ("def graph_batch(pairs: list[tuple[EstablishmentData, int]])",
         "def graph_batch(pairs: list[tuple[EstablishmentData, int]], cap: int | None = None)"),
        ('    """Union of nodes present in each window; edges remapped to batch indices."""',
         '    """Union of nodes present in each window; edges remapped to batch indices."""\n'
         "    c1_win_start = [0 if cap is None else max(0, H - cap) for _, H in pairs]\n"
         "    Wl = max(H - s for (_, H), s in zip(pairs, c1_win_start))"),
        ("pres = est.present[t][H - W : H].any(0)", "pres = est.present[t][c1_win_start[oi] : H].any(0)"),
        ("    for k in range(W):\n        fk", "    for k in range(Wl):\n        fk"),
        ("            hh = H - W + k\n",
         "            hh = H - Wl + k\n"
         "            if hh < c1_win_start[oi]:\n"
         "                for t in NODE_TYPES:\n"
         "                    fk[t].append(np.zeros((len(sel_per[oi][t]), NODE_DIMS[t]), np.float32))\n"
         "                continue\n"),
    ],
    "graph_batch_window",
)
_encode_long = _derive(
    H1.encode,
    [
        ("    xs = torch.zeros(\n        W, n, HN\n    )", "    Wl = len(g[\"feats\"])\n    xs = torch.zeros(\n        Wl, n, HN\n    )"),
        ("for k in range(W)])", "for k in range(Wl)])"),
        ("    for k in range(W):\n        x = xs[k]", "    for k in range(Wl):\n        x = xs[k]"),
    ],
    "encode_long",
)
_encode_stats = _derive(
    H1.encode,
    [("pooled], 1))", 'pooled, batch["l2d"]], 1))')],
    "encode_stats",
)


class H1Long(H1):
    """C.2a: the H1 encoder run over the whole public hourly sequence (window [0, H))."""

    cap: int | None = None
    encode = _encode_long


class H1Stats(H1):
    """C.2b: H1 (W = 24 h) with the 8 L2 local intercepts appended to the read-out input. The
    extra read-out columns start at zero; all other parameters are initialised as in C.1."""

    encode = _encode_stats

    def __init__(self, b0p: B0Params, cfg: NetConfig = NetConfig("H1")):
        super().__init__(b0p, cfg)
        old = self.read[0]
        lin = nn.Linear(3 * HN + len(L2D_ORDER), old.out_features)
        with torch.no_grad():
            lin.weight.zero_()
            lin.weight[:, : 3 * HN] = old.weight
            lin.bias.copy_(old.bias)
        self.read = nn.Sequential(lin, nn.Tanh())


def new_model(system: str, b0p: B0Params, seed: int) -> nn.Module:
    torch.manual_seed(seed)
    if system == "C.1":
        return H1(b0p, NetConfig("H1"))
    if system == "C.2a":
        return H1Long(b0p, NetConfig("H1"))
    if system == "C.2b":
        return H1Stats(b0p, NetConfig("H1"))
    raise ValueError(system)


@contextmanager
def _graph_window(cap: int | None):
    orig = nets.graph_batch
    nets.graph_batch = lambda pairs: graph_batch_window(pairs, cap=cap)
    try:
        yield
    finally:
        nets.graph_batch = orig


def make_batch(system: str, recs_pairs: list[tuple[dict, int]], with_labels: bool = True) -> dict:
    pairs = [(r["data"], H) for r, H in recs_pairs]
    if system == "C.2a":
        with _graph_window(H1Long.cap):
            batch = nets.make_batch(pairs, "H1", with_labels)
    else:
        batch = nets.make_batch(pairs, "H1", with_labels)
    if system == "C.2b":
        batch["l2d"] = torch.tensor([r["l2d"][H] for r, H in recs_pairs], dtype=torch.float32)
    return batch


@torch.no_grad()
def predict_many(model: nn.Module, system: str, rec: dict, hs: list[int], chunk: int = 16) -> list:
    out = []
    for i in range(0, len(hs), chunk):
        part = hs[i : i + chunk]
        batch = make_batch(system, [(rec, H) for H in part], with_labels=False)
        z_all, enc = model.encode(batch)
        zk_all = model.prop(z_all, batch["hours"])
        for oi, H in enumerate(part):
            out.append(nets._assemble(model, "H1", rec["data"], H, oi, batch, z_all, enc, zk_all))
    return out


# ------------------------------------------------------------------------------ training
def scales() -> dict[str, float]:
    return json.loads((ROOT / "evidence/howm1/LOSS_SCALES.json").read_text())["s_f"]


def shard_order(seed: int, j: int, n_pairs: int) -> np.ndarray:
    ks = np.array([key("HOWM2-C1-order", seed, j, i) for i in range(n_pairs)], dtype=np.uint64)
    return np.argsort(ks, kind="stable")


def run_dir(system: str, N: int, seed: int) -> Path:
    return EV / "train" / f"{system.replace('.', '')}_N{N}_s{seed}"


def eval_loss(model: nn.Module, system: str, recs: list[dict], sc: dict[str, float]) -> dict:
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    pairs = [(r, H) for r in recs for H in ORIGINS]
    model.eval()
    with torch.no_grad():
        for i in range(0, len(pairs), BATCH):
            for f, (s, n) in forward_losses(model, make_batch(system, pairs[i : i + BATCH])).items():
                sums[f] = sums.get(f, 0.0) + float(s)
                counts[f] = counts.get(f, 0) + n
    model.train()
    means = {f: sums[f] / max(counts[f], 1) for f in sums}
    return {"total": sum(means[f] / sc[f] for f in means if f in sc), "means": means, "counts": counts}


def _save(path: Path, obj: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    torch.save(obj, tmp)
    tmp.replace(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path, sha: str) -> dict:
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise RuntimeError(f"checkpoint hash mismatch: {path}")
    return torch.load(path, weights_only=True)


def train(system: str, N: int, seed: int, budget_s: float, cval: list[dict], max_steps: int | None = None) -> dict:
    """One pass over HOWM2_CTRAIN[0, N) in shards of SHARD; resumable without replay."""
    t_start = time.monotonic()
    torch.set_num_threads(1)
    d = run_dir(system, N, seed)
    meta_p = d / "state.json"
    sc = scales()
    n_steps = N * len(ORIGINS) // BATCH
    model = new_model(system, b0(), seed)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    if meta_p.exists():
        meta = json.loads(meta_p.read_text())
        if meta["done"]:
            return {"run": d.name, "done": True}
        ck = _load(d / "last.pt", meta["last_sha256"])
        model.load_state_dict(ck["model"])
        opt.load_state_dict(ck["optimizer"])
        torch.set_rng_state(ck["torch_rng"])
        st = meta["state"]
    else:
        meta = {"config": {"system": system, "N": N, "seed": seed, "lr": LR, "batch": BATCH, "eval_every": EVAL_EVERY,
                           "patience": PATIENCE, "origins": ORIGINS, "shard": SHARD, "n_steps_planned": n_steps,
                           "scheduler": "none", "optimizer": "Adam(lr=3e-4, default betas/eps)",
                           "order_key": "key('HOWM2-C1-order', seed, shard, pair_index)", "loss_scales": sc},
                "log": [], "done": False}
        st = {"step": 0, "best_total": None, "best_step": None, "bad": 0, "train_sums": {}, "train_counts": {},
              "consumed": [], "seconds": 0.0}
    shard_cache: dict[int, list] = {}
    last_ck = time.monotonic()

    def checkpoint() -> None:
        meta["state"] = st
        meta["last_sha256"] = _save(d / "last.pt", {"model": model.state_dict(), "optimizer": opt.state_dict(),
                                                     "torch_rng": torch.get_rng_state(), "step": st["step"]})
        meta_p.parent.mkdir(parents=True, exist_ok=True)
        meta_p.write_text(json.dumps(meta, indent=1) + "\n")

    def evaluate() -> None:
        recs_cval = cval() if callable(cval) else cval  # loaded only when needed (memory)
        ev = eval_loss(model, system, recs_cval, sc)
        del recs_cval
        tr = {f: st["train_sums"][f] / max(st["train_counts"][f], 1) for f in st["train_sums"]}
        improved = st["best_total"] is None or ev["total"] < st["best_total"]
        if improved:
            st["best_total"], st["best_step"], st["bad"] = ev["total"], st["step"], 0
            meta["best_sha256"] = _save(d / "best.pt", {"model": model.state_dict(), "step": st["step"]})
        else:
            st["bad"] += 1
        meta["log"].append({"step": st["step"], "cval_total": ev["total"], "cval_means": ev["means"],
                            "train_means_since_last_eval": tr, "improved": improved})
        st["train_sums"], st["train_counts"] = {}, {}

    steps_here = 0
    while st["step"] < n_steps:
        if time.monotonic() - t_start > budget_s or (max_steps is not None and steps_here >= max_steps):
            break
        steps_here += 1
        pos = st["step"] * BATCH
        j, off = divmod(pos, SHARD * len(ORIGINS))
        if j not in shard_cache:
            shard_cache.clear()
            recs = load_shard("HOWM2_CTRAIN", j)
            pairs = [(r, H) for r in recs for H in ORIGINS]
            order = shard_order(seed, j, len(pairs))
            shard_cache[j] = [pairs[k] for k in order]
        chunk = shard_cache[j][off : off + BATCH]
        parts = forward_losses(model, make_batch(system, chunk))
        loss = total_loss(parts, sc)
        opt.zero_grad()
        loss.backward()
        opt.step()
        for f, (s, n) in parts.items():
            st["train_sums"][f] = st["train_sums"].get(f, 0.0) + float(s)
            st["train_counts"][f] = st["train_counts"].get(f, 0) + n
        st["consumed"].append([j, off])
        st["step"] += 1
        if st["step"] % EVAL_EVERY == 0 or st["step"] == n_steps:
            evaluate()
            if st["bad"] >= PATIENCE:
                break
        if time.monotonic() - last_ck > CKPT_EVERY_S:
            st["seconds"] += time.monotonic() - last_ck
            checkpoint()
            last_ck = time.monotonic()
    st["seconds"] += time.monotonic() - last_ck
    meta["done"] = st["step"] >= n_steps or st["bad"] >= PATIENCE
    checkpoint()
    return {"run": d.name, "step": st["step"], "of": n_steps, "done": meta["done"], "best_step": st["best_step"],
            "best_total": st["best_total"]}


def consumed_check(state: dict, N: int) -> dict:
    """No replay, no second pass: the (shard, offset) positions are exactly the planned stream."""
    exp = [[*divmod(s * BATCH, SHARD * len(ORIGINS))] for s in range(state["step"])]
    return {"steps": state["step"], "planned": N * len(ORIGINS) // BATCH, "exact_no_replay": state["consumed"] == exp,
            "establishments_consumed": math.ceil(state["step"] * BATCH / len(ORIGINS)),
            "origins_consumed": state["step"] * BATCH}
