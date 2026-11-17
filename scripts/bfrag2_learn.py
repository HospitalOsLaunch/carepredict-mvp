#!/usr/bin/env python3
"""B-FRAG 2 learned references (PROTOCOLE_BFRAG2 s.6): fit 8 configurations x 3 views on TRAIN,
score VAL (100 structures), select per view and the common configuration for question A."""

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_v] = "1"
import hashlib  # noqa: E402
import json  # noqa: E402
import pickle  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bfrag2_lib as L  # noqa: E402

EV = L.ROOT / "evidence/howm2_bfrag2"
MODELS = EV / "models"


def make(cfg):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    fam, h = cfg
    if fam == "LR":
        return make_pipeline(StandardScaler(), LogisticRegression(C=h, max_iter=2000))
    d, lr = h
    return HistGradientBoostingClassifier(max_depth=d, learning_rate=lr, max_iter=200, min_samples_leaf=20, l2_regularization=1.0,
                                          early_stopping=False, random_state=0)


def cfg_name(cfg):
    return f"LR_C{cfg[1]}" if cfg[0] == "LR" else f"HGB_d{cfg[1][0]}_lr{cfg[1][1]}"


def main() -> int:
    tr_eps = L.load("F", "BF2_TRAIN")
    va_eps = L.load("F", "BF2_VAL")
    names = L.view_names(tr_eps[0])
    tr, va = L.rows(tr_eps, names), L.rows(va_eps, names)
    MODELS.mkdir(parents=True, exist_ok=True)
    table = {}
    for v in L.VIEWS:
        for cfg in L.CONFIGS:
            t = time.time()
            m = make(cfg).fit(tr["X"][v], tr["y72"])
            sec = time.time() - t
            blob = pickle.dumps(m)
            p = MODELS / f"{v}_{cfg_name(cfg)}.pkl"
            p.write_bytes(blob)
            sv = m.predict_proba(va["X"][v])[:, 1]
            table[f"{v}|{cfg_name(cfg)}"] = {"view": v, "config": cfg_name(cfg), "fit_seconds": sec, "bytes": len(blob),
                                             "sha256": hashlib.sha256(blob).hexdigest(),
                                             "val_cond_auc": L.cond_auc(sv, va["y72"], va["s"]), "val_global_auc": L.global_auc(sv, va["y72"]),
                                             "val_brier": float(np.mean((sv - va["y72"]) ** 2))}
    best = {}
    for v in L.VIEWS:
        cand = [(table[f"{v}|{cfg_name(c)}"]["val_cond_auc"], -i, cfg_name(c)) for i, c in enumerate(L.CONFIGS)]
        best[v] = max(cand)[2]
    common = max(((table[f"S1|{cfg_name(c)}"]["val_cond_auc"] + table[f"S2|{cfg_name(c)}"]["val_cond_auc"]) / 2, -i, cfg_name(c))
                 for i, c in enumerate(L.CONFIGS))[2]
    out = {"train": {"episodes": len(tr_eps), "rows": int(len(tr["y72"])), "positives": int(tr["y72"].sum())},
           "val": {"episodes": len(va_eps), "rows": int(len(va["y72"])), "positives": int(va["y72"].sum()),
                   "structures_with_pairs": sum(1 for u, p in L.group_up(np.zeros(len(va["y72"])), va["y72"], va["s"]).values() if p)},
           "feature_names": names, "table": table, "best_per_view": best, "common_config_A": common,
           "rule": "selection by VAL pooled structure-conditional AUC; ties -> LR first, smaller capacity first"}
    (EV / "LEARN.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"best": best, "common": common, "train": out["train"], "val": out["val"],
                      "auc": {k: round(r["val_cond_auc"], 4) for k, r in table.items()}}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
