"""Shared honesty diagnostics for the Phase A synthetic simulator."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Iterable

import numpy as np

from rs_jepa.synthetic import generate_sites


def acf_at_lag(x: np.ndarray, lag: int) -> float:
    x = np.asarray(x, float)
    x = x - x.mean()
    denom = np.sum(x * x)
    if denom == 0:
        return 0.0
    return float(np.sum(x[:-lag] * x[lag:]) / denom)


def r2_score(y_true: np.ndarray, pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return 1.0 - ss_res / max(ss_tot, 1e-12)


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
    return r2_score(y_test, Xte_aug @ coef)


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


def run_diagnostic_for_seed(
    cfg,
    seed: int,
    ridge_alpha: float = 1.0,
    mae_cap: float = 0.15,
    log: Callable[[str], None] | None = None,
) -> dict[str, float | list[dict[str, float | str]]]:
    log = log or (lambda _line: None)
    cfg = config_for_seed(cfg, seed)
    sites = generate_sites(cfg)
    holdout_steps = cfg.split.temporal_holdout_weeks * 7 * 24

    acf72 = np.array([acf_at_lag(site.occupancy_total, 72) for site in sites])
    frac_ok = float(np.mean(acf72 > 0.3))
    log(f"\n=== Seed {seed} ===")
    log(f"[T1] ACF@72h: median={np.median(acf72):.3f}  frac>0.3={frac_ok:.2f}  (besoin >=0.80)")

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
        mean_dkappa = float("nan")
        log("[T2] pas assez de paires appariées — augmente l'échantillon")
    else:
        mean_dkappa = float(np.abs(kappa[i] - kappa[j])[mask].mean())
        log(f"[T2] |Δκ| sur paires (util~égal, rise différent): {mean_dkappa:.3f}  (besoin >0.10)  n_pairs={mask.sum()}")

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
        baseline = np.full_like(y_holdout, fill_value=float(y[:-holdout_steps].mean()))
        site_readability.append(
            {
                "site_id": site.site_id,
                "r2": float(r2_score(y_holdout, pred)),
                "holdout_var": float(np.var(y_holdout)),
                "baseline_mae": float(np.mean(np.abs(y_holdout - baseline))),
                "n_holdout": float(len(y_holdout)),
            }
        )

    intra_r2 = np.array([row["r2"] for row in site_readability], dtype=float)
    mean_intra_r2 = float(intra_r2.mean())
    min_intra_r2 = float(intra_r2.min())
    hidden_share = 1.0 - mean_intra_r2
    log(f"[T3a] R² OLS instantané INTRA-SITE temporal: mean={mean_intra_r2:.3f} min={min_intra_r2:.3f}  (mean cible [0.55,0.88], min>0.40)")
    log(f"[★] Part de variance cachée = {hidden_share:.3f}  (cible [0.12,0.45])")

    var_p10 = float(np.quantile([row["holdout_var"] for row in site_readability], 0.10))
    low_sites = [row for row in site_readability if row["r2"] < 0.40]
    flat_count = 0
    hole_count = 0
    low_mae_ok = True
    low_site_rows = []
    if low_sites:
        log("[T3a-low-sites] site_id | R2 | var_kappa_holdout | baseline_MAE | n | tag")
        for row in low_sites:
            low_mae_ok = low_mae_ok and row["baseline_mae"] <= mae_cap
            if row["holdout_var"] <= var_p10:
                tag = "FLAT-TARGET ARTIFACT"
                flat_count += 1
            else:
                tag = "GENUINE READABILITY HOLE"
                hole_count += 1
            tagged = dict(row)
            tagged["tag"] = tag
            low_site_rows.append(tagged)
            log(f"  {row['site_id']} | {row['r2']:.3f} | {row['holdout_var']:.6f} | {row['baseline_mae']:.3f} | {int(row['n_holdout'])} | {tag}")
    else:
        log("[T3a-low-sites] none")
    bulk_fraction = 1.0 - len(low_sites) / len(site_readability)
    log(f"[T3a-tail] bulk_R2>=0.40={bulk_fraction:.2%} sub_count={len(low_sites)} mae_cap={mae_cap:.3f} low_mae_ok={low_mae_ok}")

    Xtr, ytr = stack_instantaneous(train_sites)
    Xte, yte = stack_instantaneous(unseen_sites)
    r2_naive_raw = fit_ridge_score(Xtr, ytr, Xte, yte, alpha=ridge_alpha)
    Xtr_cond, ytr_cond = stack_instantaneous_with_static(train_sites)
    Xte_cond, yte_cond = stack_instantaneous_with_static(unseen_sites)
    r2_cond_raw = fit_ridge_score(Xtr_cond, ytr_cond, Xte_cond, yte_cond, alpha=ridge_alpha)
    r2_naive = max(r2_naive_raw, -1.0)
    r2_cond = max(r2_cond_raw, -1.0)
    static_gain = r2_cond - r2_naive
    log(f"[T3b] OOD transfer Ridge(alpha={ridge_alpha:g}): R²_naive_raw={r2_naive_raw:.3f} clipped={r2_naive:.3f} R²_cond_raw={r2_cond_raw:.3f} clipped={r2_cond:.3f} gain_clipped={static_gain:.3f}")

    tr_sig = np.array([site_signature(site) for site in train_sites])
    un_sig = np.array([site_signature(site) for site in unseen_sites])
    d = pairwise_distances(un_sig, tr_sig).min(axis=1)
    intra = pairwise_distances(tr_sig, tr_sig)
    intra = intra[intra > 0]
    struct_dist = float(d.mean())
    struct_intra = float(np.median(intra))
    struct_ratio = struct_dist / max(struct_intra, 1e-12)
    log(f"[STRUCT] dist min unseen→train: {struct_dist:.2f} | étalement intra-train médian: {struct_intra:.2f}")
    log("  -> si dist unseen ≈ étalement intra-train, les sites sont bien tirés du même processus hétérogène (OK). Si dist ≈ 0, ils sont des copies → diversité cosmétique (PROBLÈME).")

    t1_pass = frac_ok >= 0.80
    t2_pass = bool(np.isfinite(mean_dkappa) and mean_dkappa > 0.10)
    t3a_pass = 0.55 <= mean_intra_r2 <= 0.88 and bulk_fraction >= 0.85 and low_mae_ok
    t3b_pass = r2_naive > -1.0 and static_gain > 0.15
    log(f"[PASS] T1={t1_pass} T2={t2_pass} T3a={t3a_pass} T3b={t3b_pass}")

    return {
        "seed": float(seed),
        "t1_median": float(np.median(acf72)),
        "t1_frac": frac_ok,
        "t2": mean_dkappa,
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
        "struct_dist": struct_dist,
        "struct_intra": struct_intra,
        "struct_ratio": float(struct_ratio),
        "t1_pass": float(t1_pass),
        "t2_pass": float(t2_pass),
        "t3a_pass": float(t3a_pass),
        "t3b_pass": float(t3b_pass),
        "low_sites": low_site_rows,
    }


def summarize_rows(rows: Iterable[dict[str, float]]) -> dict[str, bool | float]:
    rows = list(rows)
    t1_fracs = [row["t1_frac"] for row in rows]
    t3a_mean = [row["t3a_mean_r2"] for row in rows]
    t3a_bulk = [row["t3a_bulk_fraction"] for row in rows]
    t3a_low_mae_ok = [row["t3a_low_mae_ok"] for row in rows]
    hidden = [row["hidden_share"] for row in rows]
    struct_ratios = [row["struct_ratio"] for row in rows]
    min_t2 = min(row["t2"] for row in rows)
    criteria = {
        "T1 min frac>0.3 >= 0.82": min(t1_fracs) >= 0.82,
        "T3a mean R2 all in [0.55, 0.88]": min(t3a_mean) >= 0.55 and max(t3a_mean) <= 0.88,
        "T3a bulk R2>=0.40 all >= 85%": min(t3a_bulk) >= 0.85,
        "T3a all sub-0.40 baseline MAE <= cap": all(bool(v) for v in t3a_low_mae_ok),
        "hidden_share all in [0.12, 0.45]": min(hidden) >= 0.12 and max(hidden) <= 0.45,
        "STRUCT ratio all in [0.30, 0.55]": min(struct_ratios) >= 0.30 and max(struct_ratios) <= 0.55,
        "T2 min >= 0.10": min_t2 >= 0.10,
    }
    return {
        **criteria,
        "all_gates": all(criteria.values()),
        "min_t2": float(min_t2),
        "min_t3b_gain": float(min(row["t3b_gain"] for row in rows)),
        "struct_min": float(min(struct_ratios)),
        "struct_max": float(max(struct_ratios)),
    }
