"""HOWM-INT-1 corpus loading, TRAIN-only normalisation, size-grouped situation batches."""

from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np

KEYS = ("unit", "res", "glob", "uu", "U", "R", "C", "desc", "states", "costs", "n24", "sit")
LOOKAHEAD_STEPS = {2: 24, 4: 12, 8: 12, 12: 12}  # planner lookahead: 48 h (daily decisions) / 24 h (6-hourly)
RUPT_K = 5


def load(root: str | Path, part: str, s_list: list[int] | None = None) -> list[dict]:
    """One record per structure: arrays + meta; rows = situation x sequence."""
    out = []
    files = sorted(glob.glob(str(Path(root) / part / "s*.npz")))
    want = None if s_list is None else {f"s{s:05d}" for s in s_list}
    for f in files:
        stem = Path(f).stem
        if want is not None and stem not in want:
            continue
        z = np.load(f)
        meta = json.loads(Path(f).with_suffix(".json").read_text())
        out.append({"meta": meta, **{k: z[k] for k in KEYS}})
    return out


def situations(recs: list[dict]) -> list[dict]:
    """Split structure records into situation groups (rows of one decision situation, first row = (none, None))."""
    out = []
    for r in recs:
        for e in sorted(set(r["sit"].tolist())):
            idx = np.where(r["sit"] == e)[0]
            g = {k: r[k][idx] for k in KEYS if k != "sit"}
            g["n"] = r["meta"]["n"]
            g["structure"] = r["meta"]["structure"]
            g["family"] = r["meta"]["family"]
            g["regime"] = r["meta"]["regime"]
            g["seqs"] = r["meta"]["situations"][e]["seqs"]
            g["provenance"] = r["meta"]["situations"][e]["provenance"]
            out.append(g)
    return out


def norm_stats(sits: list[dict]) -> dict:
    """TRAIN-only normalisation (means/scales); counts are standardised, costs scaled by their std."""
    def ms(x):
        x = x.reshape(-1, x.shape[-1]).astype(np.float64)
        return x.mean(0).astype(np.float32), (x.std(0) + 1e-3).astype(np.float32)
    u_m, u_s = ms(np.concatenate([s["unit"].reshape(-1, s["unit"].shape[-1]) for s in sits]))
    r_m, r_s = ms(np.concatenate([s["res"].reshape(-1, s["res"].shape[-1]) for s in sits]))
    g_m, g_s = ms(np.concatenate([s["glob"] for s in sits]))
    st = np.concatenate([s["states"].astype(np.float32).reshape(-1, 9) for s in sits])
    co = np.concatenate([s["costs"].reshape(-1) for s in sits])
    cum = np.concatenate([s["costs"][:, :, : LOOKAHEAD_STEPS[s["n"]]].sum((2, 3)).reshape(-1) for s in sits])
    eff = np.concatenate([(lambda c: (c - c[:1]).reshape(-1))(s["costs"][:, :, : LOOKAHEAD_STEPS[s["n"]]].sum((2, 3))) for s in sits])
    return {"u_m": u_m, "u_s": u_s, "r_m": r_m, "r_s": r_s, "g_m": g_m, "g_s": g_s, "st_s": (st.std(0) + 1e-3).astype(np.float32),
            "cost_s": float(co.std() + 1e-3), "cum_s": float(cum.std() + 1e-3), "eff_s": float(eff.std() + 1e-3)}


def tensors(s: dict, st: dict, rows: np.ndarray | None = None) -> dict:
    import torch

    idx = np.arange(len(s["desc"])) if rows is None else rows
    n = s["n"]
    unit = (s["unit"][idx] - st["u_m"]) / st["u_s"]
    res = (s["res"][idx] - st["r_m"]) / st["r_s"]
    glob = (s["glob"][idx] - st["g_m"]) / st["g_s"]
    aval = (s["res"][idx, 2, 8] > 0).astype(np.float32)
    ur = np.zeros((len(idx), n, 3), np.float32)
    ur[:, :, 0] = 1
    ur[:, :, 1] = 1
    ur[:, :, 2] = aval[:, None]
    beds = s["unit"][idx, :, 0]
    f = lambda x: torch.tensor(np.asarray(x, np.float32))  # noqa: E731
    return {"unit": f(unit), "res": f(res), "glob": f(glob), "ur_mask": f(ur), "uu": f(s["uu"][idx]), "U": f(s["U"][idx]), "R": f(s["R"][idx]),
            "C": f(s["C"][idx]), "beds": f(beds), "desc": f(s["desc"][idx]), "states": f(s["states"][idx]), "costs": f(s["costs"][idx]),
            "n24": f(s["n24"][idx] >= RUPT_K)}
