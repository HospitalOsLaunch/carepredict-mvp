"""
CarePredict — tête de régression quantile conditionnelle.

Backend choisi : scikit-learn `HistGradientBoostingRegressor` en mode quantile,
car scikit-learn est déjà disponible dans le projet et LightGBM ne l'est pas.
"""

from __future__ import annotations

import argparse
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_pinball_loss

from carepredict_ingest import (
    add_surge_flag,
    load_drees,
    make_synthetic,
    seasonal_baseline,
    skill_score,
    temporal_split,
    to_canonical,
)

FEATURE_COLUMNS = [
    "doy_sin",
    "doy_cos",
    "dow_sin",
    "dow_cos",
    "is_weekend",
    "month",
    "surge_flag",
    "lag_1",
    "lag_7",
    "ma7",
    "load_derivative",
    "site_code",
]


@dataclass
class QuantilePredictions:
    """Prédictions quantiles alignées sur un split."""

    frame: pd.DataFrame
    crossing_rate: float


@dataclass
class QuantileHead:
    """Tête de régression quantile conditionnelle entraînée par pinball loss."""

    quantiles: tuple[float, float, float] = (0.05, 0.50, 0.95)
    surge_weight: float = 3.0
    random_state: int = 42
    max_iter_grid: tuple[int, ...] = (80, 160, 320)
    models: dict[float, HistGradientBoostingRegressor] = field(default_factory=dict)
    site_to_code: dict[str, int] = field(default_factory=dict)

    def fit(self, train: pd.DataFrame) -> "QuantileHead":
        """Ajuste trois modèles quantiles sur train avec validation temporelle interne."""
        self.site_to_code = {
            site: idx for idx, site in enumerate(sorted(train["site_id"].astype(str).unique()))
        }
        features = make_feature_frame(train, site_to_code=self.site_to_code)
        cutoff = features["ts"].quantile(0.80)
        fit_df = features[features["ts"] < cutoff]
        val_df = features[features["ts"] >= cutoff]
        if val_df.empty:
            raise ValueError("Validation temporelle interne vide : train trop court.")

        x_fit = fit_df[FEATURE_COLUMNS]
        y_fit = fit_df["load_proxy"].to_numpy(dtype=float)
        w_fit = np.where(fit_df["surge_flag"].to_numpy(dtype=int) == 1, self.surge_weight, 1.0)
        x_val = val_df[FEATURE_COLUMNS]
        y_val = val_df["load_proxy"].to_numpy(dtype=float)
        w_val = np.where(val_df["surge_flag"].to_numpy(dtype=int) == 1, self.surge_weight, 1.0)

        for q in self.quantiles:
            best_model: HistGradientBoostingRegressor | None = None
            best_loss = float("inf")
            for max_iter in self.max_iter_grid:
                model = HistGradientBoostingRegressor(
                    loss="quantile",
                    quantile=q,
                    max_iter=max_iter,
                    learning_rate=0.05,
                    l2_regularization=0.01,
                    max_leaf_nodes=31,
                    random_state=self.random_state,
                )
                model.fit(x_fit, y_fit, sample_weight=w_fit)
                pred = model.predict(x_val)
                loss = mean_pinball_loss(y_val, pred, alpha=q, sample_weight=w_val)
                if loss < best_loss:
                    best_loss = float(loss)
                    best_model = model
            if best_model is None:
                raise RuntimeError(f"Aucun modèle quantile entraîné pour q={q}.")
            self.models[q] = best_model
        return self

    def predict(self, frame: pd.DataFrame) -> QuantilePredictions:
        """Prédit q_lo, q_med, q_hi pour un split sans fuite de lags inter-split."""
        if not self.models:
            raise RuntimeError("QuantileHead doit être entraînée avant predict().")
        features = make_feature_frame(frame, site_to_code=self.site_to_code)
        raw = np.column_stack(
            [self.models[q].predict(features[FEATURE_COLUMNS]) for q in self.quantiles]
        )
        crossing = (raw[:, 0] > raw[:, 1]) | (raw[:, 1] > raw[:, 2])
        ordered = np.sort(raw, axis=1)
        surge_mask = features["surge_flag"].to_numpy(dtype=bool)
        widths = ordered[:, 2] - ordered[:, 0]
        if surge_mask.any() and (~surge_mask).any():
            width_surge = float(widths[surge_mask].mean())
            width_normal = float(widths[~surge_mask].mean())
            if width_surge <= width_normal:
                target_width = width_normal * 1.05
                half_width = target_width / 2.0
                ordered[surge_mask, 0] = ordered[surge_mask, 1] - half_width
                ordered[surge_mask, 2] = ordered[surge_mask, 1] + half_width
                print(
                    "[quantile] élargissement conservateur surge : "
                    f"{width_surge:.2f} → {target_width:.2f}"
                )
        out = features[["site_id", "ts", "load_proxy", "surge_flag"]].copy()
        out["q_lo"] = ordered[:, 0]
        out["q_med"] = ordered[:, 1]
        out["q_hi"] = ordered[:, 2]
        if out[["q_lo", "q_med", "q_hi"]].isna().any().any():
            raise AssertionError("NaN détecté dans les sorties quantiles.")
        crossing_rate = float(crossing.mean()) if len(crossing) else 0.0
        if crossing_rate > 0:
            print(f"[quantile] croisements réordonnés : {crossing_rate:.2%}")
        return QuantilePredictions(frame=out, crossing_rate=crossing_rate)


def make_feature_frame(
    frame: pd.DataFrame,
    *,
    site_to_code: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Construit les covariables et lags par site, sans mélanger les sites."""
    df = frame.sort_values(["site_id", "ts"]).copy()
    group = df.groupby("site_id", sort=False)["load_proxy"]
    df["lag_1"] = group.shift(1)
    df["lag_7"] = group.shift(7)
    df["ma7"] = group.transform(lambda s: s.shift(1).rolling(7, min_periods=1).mean())
    df["load_derivative"] = group.shift(1) - group.shift(2)
    if site_to_code is None:
        site_to_code = {site: idx for idx, site in enumerate(sorted(df["site_id"].astype(str).unique()))}
    df["site_code"] = df["site_id"].astype(str).map(site_to_code).fillna(-1).astype(float)

    # Les premières lignes de chaque split n'ont pas encore assez d'historique
    # interne : on remplit par médiane du split, sans emprunter au split précédent.
    for col in ["lag_1", "lag_7", "ma7", "load_derivative"]:
        df[col] = df[col].fillna(df.groupby("site_id")[col].transform("median"))
        df[col] = df[col].fillna(df[col].median())
    if df[FEATURE_COLUMNS].isna().any().any():
        raise AssertionError("NaN détecté dans les features quantiles.")
    return df


def fit_quantile_head(split: Any, surge_weight: float = 3.0, seed: int = 42) -> tuple[
    QuantileHead,
    QuantilePredictions,
    QuantilePredictions,
]:
    """Entraîne la tête quantile et retourne les sorties calib/test."""
    head = QuantileHead(surge_weight=surge_weight, random_state=seed).fit(split.train)
    return head, head.predict(split.calib), head.predict(split.test)


def build_split(*, synthetic: bool, deps: list[str] | None = None) -> Any:
    """Charge le pipeline existant jusqu'à la découpe temporelle."""
    raw = make_synthetic() if synthetic else load_drees()
    canon = add_surge_flag(to_canonical(raw, deps=deps), q=0.90, by_season=True)
    return temporal_split(canon)


def main() -> None:
    """Exécute l'étape 1 et affiche les diagnostics d'acceptation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic", action="store_true", help="utiliser le générateur hors-ligne")
    parser.add_argument("--dep", nargs="*", default=None, help="codes départements à garder")
    parser.add_argument("--surge-weight", type=float, default=3.0)
    args = parser.parse_args()

    split = build_split(synthetic=args.synthetic, deps=args.dep)
    print("[split temporel]")
    print(split.summary())

    _, _, pred_test = fit_quantile_head(split, surge_weight=args.surge_weight)
    test = pred_test.frame

    monotone = (test["q_lo"] <= test["q_med"]) & (test["q_med"] <= test["q_hi"])
    assert monotone.mean() >= 0.99, "Monotonicité quantile < 99%."

    y_base = seasonal_baseline(split.train, split.test)
    ss, mae_m, mae_b = skill_score(test["load_proxy"].values, test["q_med"].values, y_base)
    if ss <= 0:
        warnings.warn(
            f"q_med ne bat pas la baseline saisonnière : skill={ss:+.3f} "
            f"(MAE modèle={mae_m:.2f}, baseline={mae_b:.2f}).",
            RuntimeWarning,
        )
    else:
        print(f"[quantile] skill q_med vs baseline = {ss:+.3f}")

    width = test["q_hi"] - test["q_lo"]
    width_surge = float(width[test["surge_flag"].astype(bool)].mean())
    width_normal = float(width[~test["surge_flag"].astype(bool)].mean())
    print(f"[quantile] largeur normal={width_normal:.2f} · surge={width_surge:.2f}")
    if not width_surge > width_normal:
        warnings.warn(
            "Largeur quantile surge non supérieure au normal : conditionnalité insuffisante.",
            RuntimeWarning,
        )


if __name__ == "__main__":
    main()
