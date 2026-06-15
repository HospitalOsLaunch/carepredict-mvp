"""Tests des garanties statistiques et mécaniques du pipeline MTS-JEPA."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
import torch

from src.forecasting.make_figures import rolling_coverage
from src.forecasting.mts_jepa_federated import (
    ACICalibrator,
    Config,
    MTS_JEPA_Forecaster,
    MultiScalePatchifier,
    SplitConformalTrajectory,
    TemporalPredictor,
    bootstrap_diff,
    run_federated,
    seasonal_baseline,
)


def tiny_config(mu_prox: float = 0.01, seed: int = 0) -> Config:
    """Retourne la configuration CPU minimale imposée pour la CI."""
    return Config(
        seed=seed,
        batch_size=32,
        d_model=16,
        n_heads=2,
        n_layers=1,
        fed_rounds=2,
        epochs=1,
        num_clients=2,
        mu_prox=mu_prox,
        device="cpu",
    )


def exchangeable_residuals(seed: int, n: int) -> np.ndarray:
    """Génère des trajectoires échangeables avec facteur commun gaussien."""
    rng = np.random.default_rng(seed)
    return np.abs(rng.normal(size=(n, 48)) + 0.2 * rng.normal(size=(n, 1)))


def test_rolling_coverage_length() -> None:
    """La couverture roulante conserve toujours la longueur d'entrée."""
    rng = np.random.default_rng(0)
    for n in [1, 100, 300, 301, 7452]:
        result = rolling_coverage(rng.integers(0, 2, size=n), 300)
        assert len(result) == n
        assert np.all((result >= 0.0) & (result <= 1.0))


def test_conformal_validity_under_exchangeability() -> None:
    """La bande trajectoire atteint 90 % sous échangeabilité."""
    coverages = []
    for seed in range(30):
        radius = SplitConformalTrajectory(0.90).calibrate(
            exchangeable_residuals(seed, 500)
        )
        test = exchangeable_residuals(seed + 10_000, 2000)
        coverages.append(float(np.mean(test.max(axis=1) <= radius)))
    assert 0.88 <= float(np.mean(coverages)) <= 0.92


@pytest.mark.parametrize("target", [0.80, 0.90, 0.95])
def test_conformal_validity_multilevel(target: float) -> None:
    """La correction de finitude reste valide à plusieurs niveaux."""
    coverages = []
    for seed in range(30):
        radius = SplitConformalTrajectory(target).calibrate(
            exchangeable_residuals(seed, 500)
        )
        test = exchangeable_residuals(seed + 20_000, 2000)
        coverages.append(float(np.mean(test.max(axis=1) <= radius)))
    assert abs(float(np.mean(coverages)) - target) < 0.02


def test_static_conformal_fails_under_drift() -> None:
    """Le conformal statique calibré au calme s'effondre en crise."""
    rng = np.random.default_rng(0)
    calm = np.abs(rng.normal(size=(500, 48)))
    crisis = np.abs(rng.normal(size=(3000, 48)) * 3.0)
    radius = SplitConformalTrajectory(0.90).calibrate(calm)
    assert float(np.mean(crisis.max(axis=1) <= radius)) < 0.5


def test_aci_recovers_under_drift() -> None:
    """L'ACI récupère sa couverture de long terme après la dérive."""
    final_coverages = []
    for seed in range(12):
        rng = np.random.default_rng(seed)
        scores = np.abs(rng.normal(size=1500) * np.r_[np.ones(500), np.full(1000, 3.0)])
        calibrator = ACICalibrator(0.90, eta=0.02, warmup=50, min_scores=2)
        hits = []
        for index, score in enumerate(scores):
            interval = calibrator.predict_interval(0.0)
            covered = bool(interval is not None and interval[0] <= score <= interval[1])
            calibrator.update(float(score), covered)
            if interval is not None and index >= 1000:
                hits.append(covered)
        final_coverages.append(float(np.mean(hits)))
    assert 0.85 <= float(np.mean(final_coverages)) <= 0.93


def test_patchifier_scale_a_not_degenerate() -> None:
    """L'échelle bi-journalière distingue des profils à moyenne globale égale."""
    torch.manual_seed(0)
    patchifier = MultiScalePatchifier(d_model=16)
    first = torch.zeros(1, 96, 2)
    first[:, 48:, :] = 2.0
    second = torch.ones(1, 96, 2)
    assert torch.allclose(first.mean(dim=1), second.mean(dim=1))
    assert not torch.allclose(patchifier(first)["a"], patchifier(second)["a"])


def test_no_causal_mask_in_predictor() -> None:
    """Le décodeur parallèle ne reçoit aucun masque causal factice."""
    torch.manual_seed(0)
    predictor = TemporalPredictor(16, 2, 1, {"h": 48, "d": 2, "a": 1})
    with patch.object(predictor.decoder, "forward", wraps=predictor.decoder.forward) as spy:
        output = predictor([torch.randn(2, 7, 16)], ["h"])
    assert output["h"].shape == (2, 48, 16)
    assert spy.call_count == 1
    assert spy.call_args.kwargs.get("tgt_mask") is None


def test_seasonal_baseline_uses_last_24h() -> None:
    """La baseline répète les dernières 24 heures, alignées en phase."""
    context = torch.zeros(1, 168, 2)
    context[:, :48, :] = -7.0
    last_day = torch.arange(48, dtype=torch.float32).view(1, 24, 2)
    context[:, -24:, :] = last_day
    assert torch.equal(seasonal_baseline(context, 48), last_day.repeat(1, 2, 1))


def test_fedprox_reduces_drift_vs_fedavg() -> None:
    """FedProx réduit la dérive finale sans revendiquer un gain prédictif."""
    _, _, fedavg = run_federated(tiny_config(mu_prox=0.0), verbose=False)
    _, _, fedprox = run_federated(tiny_config(mu_prox=0.01), verbose=False)
    assert fedprox[-1]["drift_mean"] <= fedavg[-1]["drift_mean"]


def test_single_ema_update() -> None:
    """Le teacher global ne reçoit qu'une mise à jour EMA par round."""
    original = MTS_JEPA_Forecaster.ema_update_from
    calls = 0

    def counted(self, student_ctx_sd, student_patch_sd, tau):
        nonlocal calls
        calls += 1
        return original(self, student_ctx_sd, student_patch_sd, tau)

    cfg = tiny_config()
    with patch.object(MTS_JEPA_Forecaster, "ema_update_from", new=counted):
        run_federated(cfg, verbose=False)
    assert calls == cfg.fed_rounds


def test_no_collapse_short_run() -> None:
    """Un run court conserve des embeddings non effondrés et les métriques séparées."""
    _, _, history = run_federated(tiny_config(), verbose=False)
    expected = {"total", "jepa", "recon", "vic", "scale", "prox", "emb_std"}
    assert expected.issubset(history[-1])
    assert history[-1]["emb_std"] > 0.1


def test_bootstrap_detects_significant_diff() -> None:
    """Le bootstrap distingue un écart franc et refuse un faux positif."""
    rng = np.random.default_rng(0)
    errors_b = rng.normal(1.0, 0.1, size=1000)
    errors_a = errors_b + 0.5
    significant = bootstrap_diff(errors_a, errors_b, n_boot=1000, seed=0)
    assert significant["significant"] is True
    assert significant["ci95_low"] > 0.0

    similar_a = rng.normal(1.0, 0.1, size=1000)
    similar_b = rng.normal(1.0, 0.1, size=1000)
    similar = bootstrap_diff(similar_a, similar_b, n_boot=1000, seed=0)
    assert similar["significant"] is False
    assert similar["ci95_low"] <= 0.0 <= similar["ci95_high"]


def test_ema_update_is_no_grad() -> None:
    """Les paramètres du teacher restent gelés dès l'initialisation."""
    model = MTS_JEPA_Forecaster(tiny_config())
    assert all(not parameter.requires_grad for parameter in model.target_encoder.parameters())
    assert all(not parameter.requires_grad for parameter in model.target_patchifier.parameters())


def test_reproducibility() -> None:
    """Deux runs de même graine reproduisent les pertes du premier round."""
    _, _, first = run_federated(tiny_config(seed=7), verbose=False)
    _, _, second = run_federated(tiny_config(seed=7), verbose=False)
    for key in ["total", "jepa", "recon", "vic", "scale", "prox", "emb_std"]:
        assert first[0][key] == pytest.approx(second[0][key], abs=1e-4)
