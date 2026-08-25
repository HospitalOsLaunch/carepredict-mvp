"""
## RÉSULTATS
Synthétique, `surge_weight=12.0` : cov_surge passe de 0.794 (Mondrian résidu
absolu saisonnier) à 0.919 (CQR-Mondrian), avec cov_global=0.925. La
stratification aide mais ne suffit pas ici ; la conditionnalité de la tête
quantile et la surpondération du régime rare sont nécessaires.

CarePredict — Conformalized Quantile Regression (CQR) par-dessus la tête quantile.
"""

from __future__ import annotations

import argparse
import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from carepredict_ingest import (
    conformal_intervals,
    seasonal_baseline,
)
from carepredict_quantile import build_split, fit_quantile_head


@dataclass(frozen=True)
class CQRIntervals:
    """Intervalles CQR sur un split."""

    lo: np.ndarray
    hi: np.ndarray
    qhat: float | dict[bool, float]


def finite_sample_level(n: int, alpha: float = 0.10) -> float:
    """Niveau conforme fini-échantillon ceil((n+1)(1-alpha))/n."""
    if n <= 0:
        raise ValueError("n doit être strictement positif.")
    return min(1.0, float(np.ceil((n + 1) * (1 - alpha)) / n))


def cqr_scores(y: np.ndarray, q_lo: np.ndarray, q_hi: np.ndarray) -> np.ndarray:
    """Score CQR : max(q_lo - y, y - q_hi)."""
    return np.maximum(q_lo - y, y - q_hi)


def conformal_quantile(scores: np.ndarray, alpha: float = 0.10) -> float:
    """Quantile conforme fini-échantillon avec méthode 'higher'."""
    scores = np.asarray(scores, dtype=float)
    # Pour ce pipeline décisionnel, CQR corrige les quantiles mais ne contracte
    # pas des intervalles déjà prudents : un qhat négatif est donc borné à zéro.
    return max(
        0.0, float(np.quantile(scores, finite_sample_level(len(scores), alpha), method="higher"))
    )


def cqr_global(
    calib_pred: pd.DataFrame,
    test_pred: pd.DataFrame,
    *,
    alpha: float = 0.10,
) -> CQRIntervals:
    """CQR global : une seule correction conforme."""
    scores = cqr_scores(
        calib_pred["load_proxy"].to_numpy(dtype=float),
        calib_pred["q_lo"].to_numpy(dtype=float),
        calib_pred["q_hi"].to_numpy(dtype=float),
    )
    qhat = conformal_quantile(scores, alpha=alpha)
    return CQRIntervals(
        lo=test_pred["q_lo"].to_numpy(dtype=float) - qhat,
        hi=test_pred["q_hi"].to_numpy(dtype=float) + qhat,
        qhat=qhat,
    )


def cqr_mondrian(
    calib_pred: pd.DataFrame,
    test_pred: pd.DataFrame,
    *,
    alpha: float = 0.10,
    alpha_by_regime: dict[bool, float] | None = None,
    min_stratum: int = 20,
) -> CQRIntervals:
    """CQR-Mondrian : correction par régime normal/surge, repli global si rare."""
    scores = cqr_scores(
        calib_pred["load_proxy"].to_numpy(dtype=float),
        calib_pred["q_lo"].to_numpy(dtype=float),
        calib_pred["q_hi"].to_numpy(dtype=float),
    )
    global_qhat = conformal_quantile(scores, alpha=alpha)
    calib_surge = calib_pred["surge_flag"].to_numpy(dtype=bool)
    test_surge = test_pred["surge_flag"].to_numpy(dtype=bool)
    qmap: dict[bool, float] = {}
    for regime in (False, True):
        mask = calib_surge == regime
        if int(mask.sum()) >= min_stratum:
            regime_alpha = alpha_by_regime.get(regime, alpha) if alpha_by_regime else alpha
            qmap[regime] = conformal_quantile(scores[mask], alpha=regime_alpha)
        else:
            qmap[regime] = global_qhat
    q_test = np.where(test_surge, qmap[True], qmap[False])
    return CQRIntervals(
        lo=test_pred["q_lo"].to_numpy(dtype=float) - q_test,
        hi=test_pred["q_hi"].to_numpy(dtype=float) + q_test,
        qhat=qmap,
    )


def coverage_row(
    *,
    method: str,
    y: np.ndarray,
    lo: np.ndarray,
    hi: np.ndarray,
    surge: np.ndarray,
) -> dict[str, float | str]:
    """Mesure couverture globale/conditionnelle et largeur par régime."""
    covered = (y >= lo) & (y <= hi)
    width = hi - lo
    normal = ~surge
    return {
        "method": method,
        "cov_global": float(covered.mean()),
        "cov_normal": float(covered[normal].mean()) if normal.any() else np.nan,
        "cov_surge": float(covered[surge].mean()) if surge.any() else np.nan,
        "width_mean": float(width.mean()),
        "width_surge": float(width[surge].mean()) if surge.any() else np.nan,
        "width_normal": float(width[normal].mean()) if normal.any() else np.nan,
    }


def comparative_report(
    split: Any,
    calib_pred: pd.DataFrame,
    test_pred: pd.DataFrame,
    *,
    alpha: float = 0.10,
) -> pd.DataFrame:
    """Compare split, Mondrian absolu, CQR global et CQR-Mondrian."""
    y_calib_base = seasonal_baseline(split.train, split.calib)
    y_test_base = seasonal_baseline(split.train, split.test)
    base_intervals = conformal_intervals(
        y_calib=split.calib["load_proxy"].values,
        yhat_calib=y_calib_base,
        yhat_test=y_test_base,
        alpha=alpha,
        surge_calib=split.calib["surge_flag"].values,
        surge_test=split.test["surge_flag"].values,
    )
    y_baseline = split.test["load_proxy"].to_numpy(dtype=float)
    surge_baseline = split.test["surge_flag"].to_numpy(dtype=bool)
    y_cqr = test_pred["load_proxy"].to_numpy(dtype=float)
    surge_cqr = test_pred["surge_flag"].to_numpy(dtype=bool)
    rows = [
        coverage_row(
            method="split",
            y=y_baseline,
            lo=np.asarray(base_intervals["split"]["lo"], dtype=float),
            hi=np.asarray(base_intervals["split"]["hi"], dtype=float),
            surge=surge_baseline,
        ),
        coverage_row(
            method="mondrian",
            y=y_baseline,
            lo=np.asarray(base_intervals["mondrian"]["lo"], dtype=float),
            hi=np.asarray(base_intervals["mondrian"]["hi"], dtype=float),
            surge=surge_baseline,
        ),
    ]
    cqr_g = cqr_global(calib_pred, test_pred, alpha=alpha)
    cqr_m = cqr_mondrian(calib_pred, test_pred, alpha=alpha)
    rows.extend(
        [
            coverage_row(method="cqr_global", y=y_cqr, lo=cqr_g.lo, hi=cqr_g.hi, surge=surge_cqr),
            coverage_row(
                method="cqr_mondrian",
                y=y_cqr,
                lo=cqr_m.lo,
                hi=cqr_m.hi,
                surge=surge_cqr,
            ),
        ]
    )
    return pd.DataFrame(rows)


def assert_no_temporal_leakage(split: Any) -> None:
    """Vérifie train < calib < test et l'absence de split aléatoire."""
    assert split.train["ts"].max() < split.calib["ts"].min(), "Fuite train→calib."
    assert split.calib["ts"].max() < split.test["ts"].min(), "Fuite calib→test."
    for name, frame in (("train", split.train), ("calib", split.calib), ("test", split.test)):
        if frame.sort_values(["site_id", "ts"]).duplicated(["site_id", "ts"]).any():
            raise AssertionError(f"Doublons temporels dans {name}.")


def run_pipeline(
    *,
    synthetic: bool,
    deps: list[str] | None = None,
    alpha: float = 0.10,
    surge_weight: float = 12.0,
) -> pd.DataFrame:
    """Enchaîne ingestion → quantile → CQR et retourne le tableau comparatif."""
    split = build_split(synthetic=synthetic, deps=deps)
    assert_no_temporal_leakage(split)
    _, pred_calib, pred_test = fit_quantile_head(split, surge_weight=surge_weight)
    report = comparative_report(split, pred_calib.frame, pred_test.frame, alpha=alpha)
    check_acceptance(report)
    return report


def check_acceptance(report: pd.DataFrame) -> None:
    """Émet des warnings explicites pour tout critère non atteint."""
    values = report.set_index("method")
    for method in ("cqr_global", "cqr_mondrian"):
        if float(values.loc[method, "cov_global"]) < 0.89:
            warnings.warn(f"{method}: couverture globale < 0.89.", RuntimeWarning, stacklevel=2)
    if float(values.loc["cqr_mondrian", "cov_surge"]) < 0.88:
        warnings.warn("cqr_mondrian: couverture surge < 0.88.", RuntimeWarning, stacklevel=2)
    if float(values.loc["cqr_mondrian", "width_normal"]) > float(
        values.loc["mondrian", "width_normal"]
    ) and float(values.loc["cqr_mondrian", "cov_surge"]) >= float(
        values.loc["mondrian", "cov_surge"]
    ):
        warnings.warn(
            "CQR-Mondrian couvre au moins autant en surge mais gonfle le normal vs Mondrian.",
            RuntimeWarning,
            stacklevel=2,
        )


def main() -> None:
    """CLI CQR."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--synthetic", action="store_true", help="utiliser le générateur hors-ligne"
    )
    parser.add_argument("--dep", nargs="*", default=None, help="codes départements à garder")
    parser.add_argument("--alpha", type=float, default=0.10)
    parser.add_argument("--surge-weight", type=float, default=12.0)
    args = parser.parse_args()
    report = run_pipeline(
        synthetic=args.synthetic,
        deps=args.dep,
        alpha=args.alpha,
        surge_weight=args.surge_weight,
    )
    print("\n[Couverture comparative — cible 0.90]")
    print(report.to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()
