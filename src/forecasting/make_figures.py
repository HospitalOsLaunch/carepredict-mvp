#!/usr/bin/env python3
"""Génère les six figures de diagnostic du pipeline MTS-JEPA fédéré."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .mts_jepa_federated import (
    REGIMES,
    ACICalibrator,
    Config,
    DtACICalibrator,
    SplitConformalTrajectory,
    collect_predictions,
    interval_efficiency,
    run_federated,
)


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Calcule l'intervalle de Wilson d'une proportion binomiale."""
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    den = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / den
    radius = z * np.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n) / den
    return float(max(0.0, centre - radius)), float(min(1.0, centre + radius))


def rolling_coverage(hits: Iterable[float], window: int = 200) -> np.ndarray:
    """Retourne une couverture cumulative puis glissante, sans changer la longueur."""
    h = np.asarray(list(hits), dtype=float)
    n = len(h)
    if n == 0:
        return np.empty(0, dtype=float)
    if window <= 0:
        raise ValueError("window doit être strictement positif")
    csum = np.cumsum(h)
    out = np.empty(n, dtype=float)
    prefix = min(window, n)
    out[:prefix] = csum[:prefix] / np.arange(1, prefix + 1)
    if n > window:
        # FIX point 9 : pour i >= window, somme de h[i-window+1:i+1].
        # Cette indexation conserve exactement n éléments et évite le décalage n+1.
        out[window:] = (csum[window:] - csum[: n - window]) / window
    return out


def get_model_and_data(full: bool):
    """Entraîne un modèle léger ou complet et retourne modèle, données, historique, config."""
    if full:
        cfg = Config(device="cpu")
    else:
        cfg = Config(
            d_model=16,
            n_heads=2,
            n_layers=1,
            fed_rounds=2,
            epochs=1,
            num_clients=2,
            batch_size=16,
            device="cpu",
        )
    model, test_ds, history = run_federated(cfg, verbose=False)
    return model, test_ds, history, cfg


def instrumented_global_aci(
    eval_rows, cfg: Config, use_dtaci: bool = True
) -> dict[str, np.ndarray]:
    """Exécute l'ACI globale et capture alpha, couverture et largeur dans le temps."""
    calibrator = (DtACICalibrator if use_dtaci else ACICalibrator)(cfg.target_coverage)
    hits: list[float] = []
    alphas: list[float] = []
    widths: list[float] = []
    regimes: list[str] = []
    for row in sorted(eval_rows, key=lambda value: value["start"]):
        for truth, pred, regime in zip(row["true"], row["pred"], row["regime"], strict=False):
            interval = calibrator.predict_interval(float(pred))
            score = abs(float(truth) - float(pred))
            covered = False
            width = np.nan
            if interval is not None:
                lower, upper = interval
                covered = lower <= float(truth) <= upper
                width = upper - lower
            calibrator.update(score, covered)
            hits.append(float(covered) if interval is not None else np.nan)
            alphas.append(float(calibrator.alpha))
            widths.append(float(width))
            regimes.append(str(regime))
    return {
        "hits": np.asarray(hits, dtype=float),
        "alpha": np.asarray(alphas, dtype=float),
        "width": np.asarray(widths, dtype=float),
        "regime": np.asarray(regimes, dtype=object),
    }


def regime_change_points(regimes_seq: Iterable[str]) -> list[int]:
    """Retourne les indices auxquels le régime change."""
    regimes = list(regimes_seq)
    return [index for index in range(1, len(regimes)) if regimes[index] != regimes[index - 1]]


def fig1_aci_convergence(eval_rows, cfg: Config, use_dtaci: bool = True):
    """Trace la couverture roulante et l'alpha adaptatif."""
    trace = instrumented_global_aci(eval_rows, cfg, use_dtaci)
    valid = np.isfinite(trace["hits"])
    hits = trace["hits"][valid]
    alpha = trace["alpha"][valid]
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    axes[0].plot(rolling_coverage(hits, 200), color="#2563eb", label="Couverture roulante")
    axes[0].axhline(cfg.target_coverage, color="#111827", linestyle="--", label="Cible")
    axes[0].set_ylabel("Couverture")
    axes[0].set_ylim(0.0, 1.02)
    axes[0].legend(frameon=False)
    axes[1].plot(alpha, color="#d97706", label="Alpha adaptatif")
    axes[1].set_xlabel("Instant d'évaluation")
    axes[1].set_ylabel("Alpha")
    axes[1].legend(frameon=False)
    fig.suptitle("Convergence de la calibration conforme adaptative")
    return _finish(fig, axes)


def fig2_coverage_by_regime(eval_rows, cfg: Config, use_dtaci: bool = True):
    """Compare couverture et largeur par régime avec intervalles de Wilson."""
    trace = instrumented_global_aci(eval_rows, cfg, use_dtaci)
    coverage, lower, upper, width = [], [], [], []
    for regime in REGIMES:
        mask = (trace["regime"] == regime) & np.isfinite(trace["hits"])
        values = trace["hits"][mask]
        k, n = int(values.sum()), len(values)
        cov = float(values.mean()) if n else 0.0
        lo, hi = wilson_ci(k, n)
        coverage.append(cov)
        lower.append(cov - lo)
        upper.append(hi - cov)
        regime_widths = trace["width"][mask]
        width.append(float(np.nanmean(regime_widths)) if n else 0.0)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    x = np.arange(len(REGIMES))
    axes[0].bar(x, coverage, color="#2563eb", alpha=0.8)
    axes[0].errorbar(x, coverage, yerr=[lower, upper], fmt="none", color="#111827", capsize=4)
    axes[0].axhline(cfg.target_coverage, color="#111827", linestyle="--")
    axes[0].set_xticks(x, REGIMES)
    axes[0].set_ylim(0.0, 1.05)
    axes[0].set_ylabel("Couverture empirique")
    axes[1].bar(x, width, color="#d97706", alpha=0.8)
    axes[1].set_xticks(x, REGIMES)
    axes[1].set_ylabel("Largeur moyenne")
    fig.suptitle("Couverture marginale et largeur par régime")
    return _finish(fig, axes)


def fig3_drift_stress(cfg: Config):
    """Stress-test statique, ACI et DtACI sous dérive calme-crise-calme."""
    rng = np.random.default_rng(cfg.seed)
    scales = np.concatenate([np.ones(500), np.full(500, 3.0), np.ones(500)])
    scores = np.abs(rng.normal(size=len(scales)) * scales)
    static_q = float(np.quantile(scores[:400], cfg.target_coverage))
    static_hits = scores <= static_q
    traces = {"Statique": rolling_coverage(static_hits, 150)}
    for name, calibrator in (
        ("ACI", ACICalibrator(cfg.target_coverage, eta=cfg.aci_eta)),
        ("DtACI", DtACICalibrator(cfg.target_coverage)),
    ):
        hits = []
        for score in scores:
            interval = calibrator.predict_interval(0.0)
            covered = interval is not None and interval[0] <= score <= interval[1]
            calibrator.update(float(score), bool(covered))
            hits.append(float(covered) if interval is not None else np.nan)
        arr = np.asarray(hits)
        finite = np.isfinite(arr)
        trace = np.full_like(arr, np.nan, dtype=float)
        trace[finite] = rolling_coverage(arr[finite], 150)
        traces[name] = trace
    fig, ax = plt.subplots(figsize=(11, 4.5))
    colors = {"Statique": "#dc2626", "ACI": "#2563eb", "DtACI": "#059669"}
    for name, trace in traces.items():
        ax.plot(trace, label=name, color=colors[name])
    ax.axhline(cfg.target_coverage, color="#111827", linestyle="--", label="Cible")
    ax.axvspan(500, 1000, color="#f59e0b", alpha=0.12, label="Régime crise")
    ax.set_xlabel("Temps")
    ax.set_ylabel("Couverture roulante")
    ax.set_ylim(0.0, 1.02)
    ax.legend(frameon=False, ncol=5)
    ax.set_title("Stress de dérive : calme → crise → calme")
    return _finish(fig, [ax])


def fig4_federation(history):
    """Trace les pertes, la garde anti-collapse et la dérive client."""
    rounds = np.arange(1, len(history) + 1)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    for key, label in (("total", "Totale"), ("jepa", "JEPA"), ("recon", "Reconstruction")):
        axes[0].plot(rounds, [row[key] for row in history], marker="o", label=label)
    axes[0].set_title("Pertes fédérées")
    axes[0].set_xlabel("Round")
    axes[0].legend(frameon=False)
    axes[1].plot(rounds, [row["emb_std"] for row in history], color="#059669", marker="o")
    axes[1].axhline(1e-2, color="#dc2626", linestyle="--", label="Seuil collapse")
    axes[1].set_title("Écart-type des embeddings")
    axes[1].set_xlabel("Round")
    axes[1].legend(frameon=False)
    drift_values = [row.get("client_drift", 0.0) for row in history]
    axes[2].plot(rounds, drift_values, color="#d97706", marker="o")
    axes[2].set_title("Dérive client")
    axes[2].set_xlabel("Round")
    fig.suptitle("Convergence de la fédération et garde anti-collapse")
    return _finish(fig, axes)


def fig5_validity_sweep(cfg: Config):
    """Vérifie la validité empirique multi-niveaux sur quarante graines."""
    targets = np.asarray([0.80, 0.90, 0.95])
    empirical: list[float] = []
    for target in targets:
        coverages = []
        for seed in range(40):
            rng = np.random.default_rng(seed)
            cal = np.abs(rng.normal(size=(800, 48)) + rng.normal(size=(800, 1)) * 0.2)
            test = np.abs(rng.normal(size=(2000, 48)) + rng.normal(size=(2000, 1)) * 0.2)
            radius = SplitConformalTrajectory(float(target)).calibrate(cal)
            coverages.append(float(np.mean(test.max(axis=1) <= radius)))
        empirical.append(float(np.mean(coverages)))
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    ax.plot([0.75, 1.0], [0.75, 1.0], color="#111827", linestyle="--", label="Diagonale")
    ax.scatter(targets, empirical, color="#2563eb", s=60, label="Empirique")
    for target, observed in zip(targets, empirical, strict=False):
        ax.annotate(
            f"{observed:.3f}", (target, observed), xytext=(5, 5), textcoords="offset points"
        )
    ax.set_xlim(0.75, 1.0)
    ax.set_ylim(0.75, 1.0)
    ax.set_xlabel("Couverture nominale")
    ax.set_ylabel("Couverture empirique")
    ax.set_title("Sweep de validité conforme sur 40 graines")
    ax.legend(frameon=False)
    return _finish(fig, [ax])


def fig6_efficiency(eval_rows, cfg: Config):
    """Compare la frontière couverture-largeur du modèle et de la baseline."""
    split = max(1, len(eval_rows) // 2)
    calibration, evaluation = eval_rows[:split], eval_rows[split:]
    levels = np.linspace(0.75, 0.98, 8)
    scale = float(np.std(np.concatenate([row["true"] for row in evaluation])) + 1e-9)
    curves: dict[str, tuple[list[float], list[float]]] = {}
    for key, label in (("pred", "Modèle"), ("base", "Baseline saisonnière")):
        residuals = np.stack([np.abs(row["true"] - row[key]) for row in calibration])
        coverages, widths = [], []
        for level in levels:
            radius = SplitConformalTrajectory(float(level)).calibrate(residuals)
            hits = [np.max(np.abs(row["true"] - row[key])) <= radius for row in evaluation]
            coverage = float(np.mean(hits))
            metric = interval_efficiency(coverage, 2.0 * radius, scale)
            coverages.append(metric["coverage"])
            widths.append(metric["normalized_width"])
        curves[label] = coverages, widths
    fig, ax = plt.subplots(figsize=(6.5, 5))
    for label, (coverage, width) in curves.items():
        ax.plot(width, coverage, marker="o", label=label)
    ax.axhline(cfg.target_coverage, color="#111827", linestyle="--", label="Cible 90 %")
    ax.set_xlabel("Largeur normalisée")
    ax.set_ylabel("Couverture trajectoire")
    ax.set_title("Frontière couverture / largeur")
    ax.legend(frameon=False)
    return _finish(fig, [ax])


def _finish(fig, axes):
    for ax in np.asarray(list(axes), dtype=object).reshape(-1):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(True, linestyle=":", alpha=0.3)
    fig.tight_layout()
    return fig


def _flatten_rows(model, test_ds, cfg: Config):
    per_client = collect_predictions(model, test_ds, cfg)
    rows = [row for client_rows in per_client for row in client_rows]
    rows.sort(key=lambda value: value["start"])
    return rows


def _load_history(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    history = payload.get("history", payload)
    if not isinstance(history, list):
        raise ValueError("Le fichier d'historique doit contenir une liste de rounds")
    return history


def main() -> None:
    """Génère les six figures PNG dans le répertoire demandé."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--history",
        type=Path,
        default=None,
        help="Historique JSON d'un entraînement existant",
    )
    parser.add_argument("--full", action="store_true", help="Utiliser la configuration complète")
    parser.add_argument(
        "--no-dtaci", action="store_true", help="Utiliser ACI simple au lieu de DtACI"
    )
    parser.add_argument("--outdir", type=Path, default=Path("figures"), help="Répertoire de sortie")
    args = parser.parse_args()

    model, test_ds, generated_history, cfg = get_model_and_data(args.full)
    history = _load_history(args.history) if args.history else generated_history
    rows = _flatten_rows(model, test_ds, cfg)
    args.outdir.mkdir(parents=True, exist_ok=True)
    figures = [
        ("fig1_aci_convergence.png", fig1_aci_convergence(rows, cfg, not args.no_dtaci)),
        ("fig2_coverage_by_regime.png", fig2_coverage_by_regime(rows, cfg, not args.no_dtaci)),
        ("fig3_drift_stress.png", fig3_drift_stress(cfg)),
        ("fig4_federation.png", fig4_federation(history)),
        ("fig5_validity_sweep.png", fig5_validity_sweep(cfg)),
        ("fig6_efficiency.png", fig6_efficiency(rows, cfg)),
    ]
    for name, fig in figures:
        path = args.outdir / name
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"Figure sauvegardée : {path}")


if __name__ == "__main__":
    main()
