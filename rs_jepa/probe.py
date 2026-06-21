"""Frozen-latent linear probe utilities for RS-JEPA."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from rs_jepa.config import RSJEPAConfig
from rs_jepa.diagnostics_latent import effective_rank
from rs_jepa.encoder import ObservableEncoder
from rs_jepa.splits import CROSS_SITE_VAL, TEMPORAL_VAL, TRAIN


@dataclass(frozen=True)
class ProbeResult:
    split: str
    latent_r2_with_static: float
    latent_r2_without_static: float
    raw_r2: float
    mean_baseline_r2: float
    per_timestep_r2_with_static: float
    per_timestep_r2_without_static: float
    per_timestep_raw_r2: float
    per_timestep_mean_baseline_r2: float
    ceiling_r2: float
    effective_rank_with_static: float
    effective_rank_without_static: float
    n_train: int
    n_eval: int
    per_timestep_n_train: int
    per_timestep_n_eval: int

    @property
    def latent_r2(self) -> float:
        return self.latent_r2_with_static

    @property
    def static_delta(self) -> float:
        return self.latent_r2_with_static - self.latent_r2_without_static

    @property
    def per_timestep_static_delta(self) -> float:
        return self.per_timestep_r2_with_static - self.per_timestep_r2_without_static


@dataclass(frozen=True)
class ProbeMatrices:
    last_latents: np.ndarray
    full_latents: np.ndarray
    raw_last: np.ndarray
    raw_full: np.ndarray
    y_last: np.ndarray
    y_full: np.ndarray


def r2_score(y_true: np.ndarray, pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return 1.0 - ss_res / max(ss_tot, 1e-12)


def numpy_effective_rank(latents: np.ndarray) -> float:
    tensor = torch.as_tensor(latents, dtype=torch.float32)
    return float(effective_rank(tensor).detach().cpu().item())


def fit_linear_predict(X_train: np.ndarray, y_train: np.ndarray, X_eval: np.ndarray) -> np.ndarray:
    x_mean = X_train.mean(axis=0, keepdims=True)
    x_std = X_train.std(axis=0, keepdims=True) + 1e-8
    x_train = (X_train - x_mean) / x_std
    x_eval = (X_eval - x_mean) / x_std
    x_train_aug = np.c_[np.ones(len(x_train)), x_train]
    x_eval_aug = np.c_[np.ones(len(x_eval)), x_eval]
    coef, *_ = np.linalg.lstsq(x_train_aug, y_train, rcond=None)
    return x_eval_aug @ coef


def _site_windows(
    site,
    cfg: RSJEPAConfig,
    split: str,
    *,
    stride: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rows = np.where(site.split == split)[0]
    if len(rows) == 0:
        return (
            np.empty((0, cfg.stage1.context_steps, site.features.shape[1]), dtype=np.float32),
            np.empty((0, site.features.shape[1]), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0, site.static.shape[0]), dtype=np.float32),
            np.empty((0, cfg.stage1.context_steps), dtype=np.float32),
        )
    start_min = int(rows[0])
    start_max = int(rows[-1]) - cfg.stage1.context_steps + 1
    if start_max <= start_min:
        return (
            np.empty((0, cfg.stage1.context_steps, site.features.shape[1]), dtype=np.float32),
            np.empty((0, site.features.shape[1]), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0, site.static.shape[0]), dtype=np.float32),
            np.empty((0, cfg.stage1.context_steps), dtype=np.float32),
        )
    windows = []
    raw_last = []
    targets = []
    statics = []
    timestep_targets = []
    for start in range(start_min, start_max, stride):
        end = start + cfg.stage1.context_steps
        if not np.all(site.split[start:end] == split):
            continue
        target_idx = end - 1
        target_window = site.criticality[start:end]
        if len(target_window) != cfg.stage1.context_steps:
            raise AssertionError("Alignement kappa_t invalide dans la fenêtre probe.")
        windows.append(site.features[start:end])
        raw_last.append(site.features[target_idx])
        targets.append(site.criticality[target_idx])
        statics.append(site.static)
        timestep_targets.append(target_window)
    return (
        np.asarray(windows, dtype=np.float32),
        np.asarray(raw_last, dtype=np.float32),
        np.asarray(targets, dtype=np.float32),
        np.asarray(statics, dtype=np.float32),
        np.asarray(timestep_targets, dtype=np.float32),
    )


def collect_probe_matrices(
    encoder: ObservableEncoder,
    sites,
    cfg: RSJEPAConfig,
    split: str,
    *,
    device: torch.device,
    zero_static: bool = False,
) -> ProbeMatrices:
    windows_all = []
    raw_all = []
    y_all = []
    static_all = []
    y_full_all = []
    for site in sites:
        windows, raw_last, targets, statics, timestep_targets = _site_windows(
            site,
            cfg,
            split,
            stride=cfg.training.probe_stride,
        )
        if len(targets) == 0:
            continue
        windows_all.append(windows)
        raw_all.append(raw_last)
        y_all.append(targets)
        static_all.append(statics)
        y_full_all.append(timestep_targets)
    if not y_all:
        raise ValueError(f"Aucun échantillon probe pour split={split}.")

    windows_np = np.concatenate(windows_all, axis=0)
    raw_np = np.concatenate(raw_all, axis=0)
    y_np = np.concatenate(y_all, axis=0)
    static_np = np.concatenate(static_all, axis=0)
    y_full_np = np.concatenate(y_full_all, axis=0)
    if len(y_np) > cfg.training.probe_max_samples:
        indices = np.linspace(0, len(y_np) - 1, cfg.training.probe_max_samples).astype(int)
        windows_np = windows_np[indices]
        raw_np = raw_np[indices]
        y_np = y_np[indices]
        static_np = static_np[indices]
        y_full_np = y_full_np[indices]

    encoder.eval()
    last_latents = []
    full_latents = []
    with torch.no_grad():
        batch_size = 128
        for start in range(0, len(y_np), batch_size):
            x = torch.as_tensor(windows_np[start : start + batch_size], device=device)
            static = torch.as_tensor(static_np[start : start + batch_size], device=device)
            if zero_static:
                static = torch.zeros_like(static)
            encoded = encoder(x, static)
            encoded_np = encoded.detach().cpu().numpy()
            last_latents.append(encoded_np[:, -1])
            full_latents.append(encoded_np.reshape(-1, encoded_np.shape[-1]))
    full_latents_np = np.concatenate(full_latents, axis=0)
    y_full_flat = y_full_np.reshape(-1)
    raw_full_np = windows_np.reshape(-1, windows_np.shape[-1])
    expected_full = len(y_np) * cfg.stage1.context_steps
    if full_latents_np.shape[0] != expected_full:
        raise AssertionError("La matrice full-latent ne couvre pas tous les pas de temps.")
    if y_full_flat.shape[0] != full_latents_np.shape[0]:
        raise AssertionError("Alignement X/y per-timestep invalide pour le probe.")
    if raw_full_np.shape[0] != full_latents_np.shape[0]:
        raise AssertionError("Alignement raw/kappa_t per-timestep invalide pour le probe.")
    return ProbeMatrices(
        last_latents=np.concatenate(last_latents, axis=0),
        full_latents=full_latents_np,
        raw_last=raw_np,
        raw_full=raw_full_np,
        y_last=y_np,
        y_full=y_full_flat,
    )


def collect_probe_matrix(
    encoder: ObservableEncoder,
    sites,
    cfg: RSJEPAConfig,
    split: str,
    *,
    device: torch.device,
    zero_static: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    matrices = collect_probe_matrices(
        encoder,
        sites,
        cfg,
        split,
        device=device,
        zero_static=zero_static,
    )
    return matrices.last_latents, matrices.raw_last, matrices.y_last


def _collect_probe_matrix_with_rank_latents(
    encoder: ObservableEncoder,
    sites,
    cfg: RSJEPAConfig,
    split: str,
    *,
    device: torch.device,
    zero_static: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    matrices = collect_probe_matrices(
        encoder,
        sites,
        cfg,
        split,
        device=device,
        zero_static=zero_static,
    )
    return matrices.last_latents, matrices.raw_last, matrices.y_last, matrices.full_latents


def evaluate_probe(
    encoder: ObservableEncoder,
    train_sites,
    eval_sites,
    cfg: RSJEPAConfig,
    split: str,
    *,
    ceiling_r2: float,
    device: torch.device,
) -> ProbeResult:
    train = collect_probe_matrices(
        encoder,
        train_sites,
        cfg,
        TRAIN,
        device=device,
    )
    train_no_static = collect_probe_matrices(
        encoder,
        train_sites,
        cfg,
        TRAIN,
        device=device,
        zero_static=True,
    )
    eval_matrices = collect_probe_matrices(
        encoder,
        eval_sites,
        cfg,
        split,
        device=device,
    )
    eval_no_static = collect_probe_matrices(
        encoder,
        eval_sites,
        cfg,
        split,
        device=device,
        zero_static=True,
    )
    latent_pred = fit_linear_predict(
        train.last_latents,
        train.y_last,
        eval_matrices.last_latents,
    )
    latent_no_static_pred = fit_linear_predict(
        train_no_static.last_latents,
        train_no_static.y_last,
        eval_no_static.last_latents,
    )
    raw_pred = fit_linear_predict(train.raw_last, train.y_last, eval_matrices.raw_last)
    mean_pred = np.full_like(eval_matrices.y_last, fill_value=float(train.y_last.mean()))
    per_timestep_pred = fit_linear_predict(
        train.full_latents,
        train.y_full,
        eval_matrices.full_latents,
    )
    per_timestep_no_static_pred = fit_linear_predict(
        train_no_static.full_latents,
        train_no_static.y_full,
        eval_no_static.full_latents,
    )
    per_timestep_raw_pred = fit_linear_predict(
        train.raw_full,
        train.y_full,
        eval_matrices.raw_full,
    )
    per_timestep_mean_pred = np.full_like(
        eval_matrices.y_full,
        fill_value=float(train.y_full.mean()),
    )
    return ProbeResult(
        split=split,
        latent_r2_with_static=float(r2_score(eval_matrices.y_last, latent_pred)),
        latent_r2_without_static=float(
            r2_score(eval_no_static.y_last, latent_no_static_pred)
        ),
        raw_r2=float(r2_score(eval_matrices.y_last, raw_pred)),
        mean_baseline_r2=float(r2_score(eval_matrices.y_last, mean_pred)),
        per_timestep_r2_with_static=float(
            r2_score(eval_matrices.y_full, per_timestep_pred)
        ),
        per_timestep_r2_without_static=float(
            r2_score(eval_no_static.y_full, per_timestep_no_static_pred)
        ),
        per_timestep_raw_r2=float(r2_score(eval_matrices.y_full, per_timestep_raw_pred)),
        per_timestep_mean_baseline_r2=float(
            r2_score(eval_matrices.y_full, per_timestep_mean_pred)
        ),
        ceiling_r2=float(ceiling_r2),
        effective_rank_with_static=numpy_effective_rank(eval_matrices.full_latents),
        effective_rank_without_static=numpy_effective_rank(eval_no_static.full_latents),
        n_train=int(len(train.y_last)),
        n_eval=int(len(eval_matrices.y_last)),
        per_timestep_n_train=int(len(train.y_full)),
        per_timestep_n_eval=int(len(eval_matrices.y_full)),
    )


def run_frozen_latent_probes(
    encoder: ObservableEncoder,
    train_sites,
    cross_site_sites,
    cfg: RSJEPAConfig,
    *,
    ceiling_r2: float,
    device: torch.device,
) -> dict[str, ProbeResult]:
    cross_site = evaluate_probe(
        encoder,
        train_sites,
        cross_site_sites,
        cfg,
        CROSS_SITE_VAL,
        ceiling_r2=ceiling_r2,
        device=device,
    )
    temporal = evaluate_probe(
        encoder,
        train_sites,
        train_sites,
        cfg,
        TEMPORAL_VAL,
        ceiling_r2=ceiling_r2,
        device=device,
    )
    return {"cross_site": cross_site, "temporal": temporal}


def interpret_static_ablation(result: ProbeResult, rank_threshold: float = 4.0) -> str:
    base = (
        f"probe[{result.split}] rank_with_static={result.effective_rank_with_static:.2f} "
        f"rank_without_static={result.effective_rank_without_static:.2f} "
        f"last_step(with={result.latent_r2_with_static:.3f}, "
        f"without={result.latent_r2_without_static:.3f}, "
        f"delta={result.static_delta:.3f}, raw={result.raw_r2:.3f}, "
        f"mean={result.mean_baseline_r2:.3f}) "
        f"per_timestep(with={result.per_timestep_r2_with_static:.3f}, "
        f"without={result.per_timestep_r2_without_static:.3f}, "
        f"delta={result.per_timestep_static_delta:.3f}, "
        f"raw={result.per_timestep_raw_r2:.3f}, "
        f"mean={result.per_timestep_mean_baseline_r2:.3f}) "
        f"ceiling={result.ceiling_r2:.3f}"
    )
    min_rank = min(result.effective_rank_with_static, result.effective_rank_without_static)
    if min_rank < rank_threshold:
        return (
            f"{base} -> LATENT COLLAPSED (rank={min_rank:.2f}) — "
            "probe ablation NOT interpretable"
        )

    anomaly = ""
    if result.latent_r2_without_static > result.latent_r2_with_static:
        anomaly += (
            " | LAST-STEP ANOMALY: without_static exceeds with_static; compare "
            "per-timestep before interpreting"
        )
    if result.per_timestep_r2_without_static > result.per_timestep_r2_with_static:
        anomaly += (
            " | PER-TIMESTEP ANOMALY: without_static exceeds with_static; report, "
            "do not hide"
        )
    if result.per_timestep_static_delta >= -1e-9:
        reading = (
            "anomaly was a last-step artifact; static conditioning helps or is neutral "
            "on full-latent regression"
        )
    else:
        reading = (
            "anomaly persists on per-timestep regression; suspect static-conditioning "
            "injection in encoder.py — escalate to inspect fusion"
        )
    return f"{base} -> {reading}{anomaly}"
