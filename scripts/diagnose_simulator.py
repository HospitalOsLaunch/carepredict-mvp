#!/usr/bin/env python3
"""Diagnostique l'honnêteté du simulateur Phase A RS-JEPA.

Aucun modèle n'est entraîné ici: le script vérifie seulement que le simulateur
contient de la mémoire, de la criticité non instantanée, une part cachée utile,
et une vraie diversité cross-site.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_jepa.config import load_config
from rs_jepa.synthetic import generate_sites


def acf_at_lag(x: np.ndarray, lag: int) -> float:
    x = np.asarray(x, float)
    x = x - x.mean()
    denom = np.sum(x * x)
    if denom == 0:
        return 0.0
    return float(np.sum(x[:-lag] * x[lag:]) / denom)


def fit_ols_score(X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray, y_test: np.ndarray) -> float:
    pred = fit_ols_predict(X_train, y_train, X_test)
    return r2_score(y_test, pred)


def fit_ols_predict(X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray) -> np.ndarray:
    X_mean = X_train.mean(axis=0, keepdims=True)
    X_std = X_train.std(axis=0, keepdims=True) + 1e-8
    Xtr = (X_train - X_mean) / X_std
    Xte = (X_test - X_mean) / X_std
    Xtr_aug = np.c_[np.ones(len(Xtr)), Xtr]
    Xte_aug = np.c_[np.ones(len(Xte)), Xte]
    coef, *_ = np.linalg.lstsq(Xtr_aug, y_train, rcond=None)
    return Xte_aug @ coef


def fit_ridge_score(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    alpha: float,
) -> float:
    X_mean = X_train.mean(axis=0, keepdims=True)
    X_std = X_train.std(axis=0, keepdims=True) + 1e-8
    Xtr = (X_train - X_mean) / X_std
    Xte = (X_test - X_mean) / X_std
    Xtr_aug = np.c_[np.ones(len(Xtr)), Xtr]
    Xte_aug = np.c_[np.ones(len(Xte)), Xte]
    penalty = np.eye(Xtr_aug.shape[1]) * alpha
    penalty[0, 0] = 0.0
    lhs = Xtr_aug.T @ Xtr_aug + penalty
    rhs = Xtr_aug.T @ y_train
    try:
        coef = np.linalg.solve(lhs, rhs)
    except np.linalg.LinAlgError:
        coef, *_ = np.linalg.lstsq(lhs, rhs, rcond=None)
    pred = Xte_aug @ coef
    return r2_score(y_test, pred)


def r2_score(y_true: np.ndarray, pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return 1.0 - ss_res / max(ss_tot, 1e-12)


def pairwise_distances(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a[:, None, :] - b[None, :, :]
    return np.sqrt(np.sum(diff * diff, axis=2))


def stack_instantaneous(site_list):
    X, y = [], []
    for site in site_list:
        X.append(site.observable_instantaneous)
        y.append(site.kappa)
    return np.concatenate(X), np.concatenate(y)


def site_signature(site) -> np.ndarray:
    return np.concatenate([[site.capacity, site.nurse_ratio_target], site.casemix])


def static_features(site, n_rows: int) -> np.ndarray:
    values = site_signature(site)[None, :]
    return np.repeat(values, repeats=n_rows, axis=0)


def stack_instantaneous_with_static(site_list):
    X, y = [], []
    for site in site_list:
        X.append(np.concatenate([site.observable_instantaneous, static_features(site, len(site.kappa))], axis=1))
        y.append(site.kappa)
    return np.concatenate(X), np.concatenate(y)


def config_for_seed(cfg, seed: int):
    return replace(
        cfg,
        seed=seed,
        synthetic=replace(cfg.synthetic, seed=seed),
        split=replace(cfg.split, seed=seed),
    )


def run_diagnostic_for_seed(cfg, seed: int, ridge_alpha: float, mae_cap: float) -> dict[str, float]:
    cfg = config_for_seed(cfg, seed)
    sites = generate_sites(cfg)
    holdout_steps = cfg.split.temporal_holdout_weeks * 7 * 24

    acf72 = np.array([acf_at_lag(site.occupancy_total, 72) for site in sites])
    frac_ok = np.mean(acf72 > 0.3)
    print(f"\n=== Seed {seed} ===")
    print(
        f"[T1] ACF@72h: median={np.median(acf72):.3f}  "
        f"frac>0.3={frac_ok:.2f}  (besoin >=0.80)"
    )

    util = np.concatenate([site.util for site in sites])
    rise = np.concatenate([site.rise for site in sites])
    kappa = np.concatenate([site.kappa for site in sites])
    rise_std = rise.std()
    rng = np.random.default_rng(0)
    idx = rng.choice(len(util), size=200_000, replace=True).reshape(-1, 2)
    i, j = idx[:, 0], idx[:, 1]
    same_util = np.abs(util[i] - util[j]) < 0.01
    diff_rise = np.abs(rise[i] - rise[j]) > 0.3 * rise_std
    mask = same_util & diff_rise
    if mask.sum() < 100:
        print("[T2] pas assez de paires appariées — augmente l'échantillon")
        mean_dkappa = float("nan")
    else:
        mean_dkappa = np.abs(kappa[i] - kappa[j])[mask].mean()
        print(
            f"[T2] |Δκ| sur paires (util~égal, rise différent): "
            f"{mean_dkappa:.3f}  (besoin >0.10)  n_pairs={mask.sum()}"
        )

    train_sites = [site for site in sites if site.split == "train"]
    unseen_sites = [site for site in sites if site.split == "unseen"]
    site_readability = []
    for site in sites:
        X = site.observable_instantaneous
        y = site.kappa
        if len(y) <= holdout_steps:
            raise ValueError(f"Site {site.site_id} trop court pour holdout={holdout_steps}")
        pred = fit_ols_predict(X[:-holdout_steps], y[:-holdout_steps], X[-holdout_steps:])
        y_holdout = y[-holdout_steps:]
        r2 = r2_score(y_holdout, pred)
        baseline = np.full_like(y_holdout, fill_value=float(y[:-holdout_steps].mean()))
        site_readability.append(
            {
                "site_id": site.site_id,
                "r2": float(r2),
                "holdout_var": float(np.var(y_holdout)),
                "baseline_mae": float(np.mean(np.abs(y_holdout - baseline))),
                "n_holdout": float(len(y_holdout)),
            }
        )
    intra_r2 = [row["r2"] for row in site_readability]
    intra_r2 = np.array(intra_r2, dtype=float)
    mean_intra_r2 = float(intra_r2.mean())
    min_intra_r2 = float(intra_r2.min())
    hidden_share = 1.0 - mean_intra_r2
    print(
        f"[T3a] R² OLS instantané INTRA-SITE temporal: mean={mean_intra_r2:.3f} "
        f"min={min_intra_r2:.3f}  (mean cible [0.55,0.88], min>0.40)"
    )
    print(f"[★] Part de variance cachée = {hidden_share:.3f}  (cible [0.12,0.45])")
    var_p10 = float(np.quantile([row["holdout_var"] for row in site_readability], 0.10))
    low_sites = [row for row in site_readability if row["r2"] < 0.40]
    flat_count = 0
    hole_count = 0
    low_mae_ok = True
    if low_sites:
        print("[T3a-low-sites] site_id | R2 | var_kappa_holdout | baseline_MAE | n | tag")
        for row in low_sites:
            low_mae_ok = low_mae_ok and row["baseline_mae"] <= mae_cap
            if row["holdout_var"] <= var_p10:
                tag = "FLAT-TARGET ARTIFACT"
                flat_count += 1
            else:
                tag = "GENUINE READABILITY HOLE"
                hole_count += 1
            print(
                f"  {row['site_id']} | {row['r2']:.3f} | {row['holdout_var']:.6f} | "
                f"{row['baseline_mae']:.3f} | {int(row['n_holdout'])} | {tag}"
            )
    else:
        print("[T3a-low-sites] none")
    low_fraction = len(low_sites) / len(site_readability)
    bulk_fraction = 1.0 - low_fraction
    print(
        f"[T3a-tail] bulk_R2>=0.40={bulk_fraction:.2%} "
        f"sub_count={len(low_sites)} mae_cap={mae_cap:.3f} low_mae_ok={low_mae_ok}"
    )

    Xtr, ytr = stack_instantaneous(train_sites)
    Xte, yte = stack_instantaneous(unseen_sites)
    r2_naive_raw = fit_ridge_score(Xtr, ytr, Xte, yte, alpha=ridge_alpha)
    Xtr_cond, ytr_cond = stack_instantaneous_with_static(train_sites)
    Xte_cond, yte_cond = stack_instantaneous_with_static(unseen_sites)
    r2_cond_raw = fit_ridge_score(Xtr_cond, ytr_cond, Xte_cond, yte_cond, alpha=ridge_alpha)
    r2_naive = max(r2_naive_raw, -1.0)
    r2_cond = max(r2_cond_raw, -1.0)
    static_gain = r2_cond - r2_naive
    print(
        f"[T3b] OOD transfer Ridge(alpha={ridge_alpha:g}): "
        f"R²_naive_raw={r2_naive_raw:.3f} clipped={r2_naive:.3f} "
        f"R²_cond_raw={r2_cond_raw:.3f} clipped={r2_cond:.3f} gain_clipped={static_gain:.3f}"
    )

    tr_sig = np.array([site_signature(site) for site in train_sites])
    un_sig = np.array([site_signature(site) for site in unseen_sites])
    d = pairwise_distances(un_sig, tr_sig).min(axis=1)
    intra = pairwise_distances(tr_sig, tr_sig)
    intra = intra[intra > 0]
    print(
        f"[STRUCT] dist min unseen→train: {d.mean():.2f} | "
        f"étalement intra-train médian: {np.median(intra):.2f}"
    )
    print(
        "  -> si dist unseen ≈ étalement intra-train, les sites sont bien "
        "tirés du même processus hétérogène (OK). Si dist ≈ 0, ils sont des "
        "copies → diversité cosmétique (PROBLÈME)."
    )

    t1_pass = frac_ok >= 0.80
    t2_pass = bool(np.isfinite(mean_dkappa) and mean_dkappa > 0.10)
    t3a_pass = 0.55 <= mean_intra_r2 <= 0.88 and bulk_fraction >= 0.85 and low_mae_ok
    t3b_pass = r2_naive > -1.0 and static_gain > 0.15
    struct_ratio = float(d.mean() / max(np.median(intra), 1e-12))
    print(f"[PASS] T1={t1_pass} T2={t2_pass} T3a={t3a_pass} T3b={t3b_pass}")
    if struct_ratio > 0.70:
        print("[STRUCT FLAG] OOD corner too extreme, consider pulling unseen region inward")
    return {
        "seed": float(seed),
        "t1_median": float(np.median(acf72)),
        "t1_frac": float(frac_ok),
        "t2": float(mean_dkappa),
        "t3a_mean_r2": mean_intra_r2,
        "t3a_min_r2": min_intra_r2,
        "t3a_bulk_fraction": float(bulk_fraction),
        "t3a_sub_count": float(len(low_sites)),
        "t3a_low_mae_ok": float(low_mae_ok),
        "t3b_naive_r2": float(r2_naive),
        "t3b_naive_raw_r2": float(r2_naive_raw),
        "t3b_cond_r2": float(r2_cond),
        "t3b_cond_raw_r2": float(r2_cond_raw),
        "t3b_gain": float(static_gain),
        "flat_count": float(flat_count),
        "hole_count": float(hole_count),
        "hidden_share": float(hidden_share),
        "struct_dist": float(d.mean()),
        "struct_intra": float(np.median(intra)),
        "struct_ratio": struct_ratio,
        "t1_pass": float(t1_pass),
        "t2_pass": float(t2_pass),
        "t3a_pass": float(t3a_pass),
        "t3b_pass": float(t3b_pass),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnostic multi-seed du simulateur Phase A.")
    parser.add_argument("--config", default="configs/phaseA.yaml")
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    parser.add_argument("--ridge-alpha", type=float, default=1.0)
    parser.add_argument("--mae-cap", type=float, default=0.15)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    rows = [
        run_diagnostic_for_seed(cfg, seed, ridge_alpha=args.ridge_alpha, mae_cap=args.mae_cap)
        for seed in args.seeds
    ]

    print("\n=== SUMMARY ===")
    print(
        "seed | T1_median | T1_frac>0.3 | T2_|Δκ| | T3a_mean | T3a_min | hidden | "
        "bulk% | sub<0.40 | T3b_naive(raw/clip) | T3b_cond(raw/clip) | gain | "
        "STRUCT_ratio | low-site tags | PASS"
    )
    for row in rows:
        flags = (
            f"T1={'PASS' if row['t1_pass'] else 'FAIL'},"
            f"T2={'PASS' if row['t2_pass'] else 'FAIL'},"
            f"T3a={'PASS' if row['t3a_pass'] else 'FAIL'},"
            f"T3b={'PASS' if row['t3b_pass'] else 'FAIL'}"
        )
        print(
            f"{int(row['seed']):>4} | {row['t1_median']:.3f}     | {row['t1_frac']:.2f}         | "
            f"{row['t2']:.3f}   | {row['t3a_mean_r2']:.3f}    | {row['t3a_min_r2']:.3f}  | "
            f"{row['hidden_share']:.3f} | {row['t3a_bulk_fraction']:.2f} | "
            f"{int(row['t3a_sub_count'])} | {row['t3b_naive_raw_r2']:.3f}/{row['t3b_naive_r2']:.3f}    | "
            f"{row['t3b_cond_raw_r2']:.3f}/{row['t3b_cond_r2']:.3f}   | {row['t3b_gain']:.3f} | "
            f"{row['struct_ratio']:.3f}       | flat={int(row['flat_count'])},hole={int(row['hole_count'])} | {flags}"
        )
    min_t2 = min(row["t2"] for row in rows)
    verdict = (
        "T2 STABLE"
        if min_t2 >= 0.10
        else "T2 FRAGILE — report only, do NOT auto-tune; flag w_rise/w_inter as candidate levers for human review"
    )
    print(f"\n[MIN T2] {min_t2:.3f} -> {verdict}")
    t1_fracs = [row["t1_frac"] for row in rows]
    t3a_mean = [row["t3a_mean_r2"] for row in rows]
    t3a_min = [row["t3a_min_r2"] for row in rows]
    t3a_bulk = [row["t3a_bulk_fraction"] for row in rows]
    t3a_low_mae_ok = [row["t3a_low_mae_ok"] for row in rows]
    t3b_naive = [row["t3b_naive_r2"] for row in rows]
    t3b_gain = [row["t3b_gain"] for row in rows]
    hidden = [row["hidden_share"] for row in rows]
    struct_ratios = [row["struct_ratio"] for row in rows]
    struct_ratio = float(np.mean(struct_ratios))
    flat_total = int(sum(row["flat_count"] for row in rows))
    hole_total = int(sum(row["hole_count"] for row in rows))
    print(
        f"[STRUCT VERDICT] mean(dist_min/intra_median)={struct_ratio:.3f} — "
        "flag ratio>0.70 as OOD corner too extreme."
    )
    print(f"[T3a-low-sites counts] FLAT-TARGET ARTIFACT={flat_total} | GENUINE READABILITY HOLE={hole_total}")
    print("\n=== GAIN vs STRUCT ===")
    for row in sorted(rows, key=lambda item: item["struct_ratio"]):
        print(
            f"seed={int(row['seed'])} STRUCT={row['struct_ratio']:.3f} "
            f"gain={row['t3b_gain']:.3f} naive={row['t3b_naive_r2']:.3f} cond={row['t3b_cond_r2']:.3f}"
        )
    criteria = {
        "T1 min frac>0.3 >= 0.82": min(t1_fracs) >= 0.82,
        "T3a mean R2 all in [0.55, 0.88]": min(t3a_mean) >= 0.55 and max(t3a_mean) <= 0.88,
        "T3a bulk R2>=0.40 all >= 85%": min(t3a_bulk) >= 0.85,
        "T3a all sub-0.40 baseline MAE <= cap": all(bool(v) for v in t3a_low_mae_ok),
        "hidden_share all in [0.12, 0.45]": min(hidden) >= 0.12 and max(hidden) <= 0.45,
        "STRUCT ratio all in [0.30, 0.55]": min(struct_ratios) >= 0.30 and max(struct_ratios) <= 0.55,
        "T3b naive R2 all > -1.0": min(t3b_naive) > -1.0,
        "T2 min >= 0.10": min_t2 >= 0.10,
    }
    print("\n=== STOP CRITERIA ===")
    print(f"T1_frac min/max: {min(t1_fracs):.2f} / {max(t1_fracs):.2f}")
    print(f"T3a_mean_R2 min/max: {min(t3a_mean):.3f} / {max(t3a_mean):.3f}")
    print(f"T3a_min_R2 min/max: {min(t3a_min):.3f} / {max(t3a_min):.3f}")
    print(f"T3a_bulk_fraction min/max: {min(t3a_bulk):.2f} / {max(t3a_bulk):.2f}")
    print(f"hidden_share min/max: {min(hidden):.3f} / {max(hidden):.3f}")
    print(f"T3b_naive_R2 min/max: {min(t3b_naive):.3f} / {max(t3b_naive):.3f}")
    print(f"T3b_gain min/max: {min(t3b_gain):.3f} / {max(t3b_gain):.3f}")
    print(f"STRUCT ratio min/max: {min(struct_ratios):.3f} / {max(struct_ratios):.3f}")
    for name, passed in criteria.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if min(t3b_gain) > 0.15:
        print("[T3b RESULT] static conditioning recovers OOD transfer")
    else:
        print(
            "[T3b RESULT] static conditioning insufficient for cold-start on moderate-OOD sites; "
            "dynamic (warm-mode) information likely required."
        )
    final = "BENCH HONEST & STABLE" if all(criteria.values()) else "GATES STILL UNSTABLE"
    print(f"\n[FINAL] {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
