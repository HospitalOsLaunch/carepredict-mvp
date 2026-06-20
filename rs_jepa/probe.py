"""Frozen-latent linear probe utilities for RS-JEPA."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from rs_jepa.config import RSJEPAConfig
from rs_jepa.encoder import ObservableEncoder
from rs_jepa.splits import CROSS_SITE_VAL, TEMPORAL_VAL, TRAIN


@dataclass(frozen=True)
class ProbeResult:
    split: str
    latent_r2: float
    raw_r2: float
    mean_baseline_r2: float
    ceiling_r2: float
    n_train: int
    n_eval: int


def r2_score(y_true: np.ndarray, pred: np.ndarray) -> float:
    ss_res = float(np.sum((y_true - pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    return 1.0 - ss_res / max(ss_tot, 1e-12)


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
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rows = np.where(site.split == split)[0]
    if len(rows) == 0:
        return (
            np.empty((0, cfg.stage1.context_steps, site.features.shape[1]), dtype=np.float32),
            np.empty((0, site.features.shape[1]), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0, site.static.shape[0]), dtype=np.float32),
        )
    start_min = int(rows[0])
    start_max = int(rows[-1]) - cfg.stage1.context_steps + 1
    if start_max <= start_min:
        return (
            np.empty((0, cfg.stage1.context_steps, site.features.shape[1]), dtype=np.float32),
            np.empty((0, site.features.shape[1]), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0, site.static.shape[0]), dtype=np.float32),
        )
    windows = []
    raw_last = []
    targets = []
    statics = []
    for start in range(start_min, start_max, stride):
        end = start + cfg.stage1.context_steps
        if not np.all(site.split[start:end] == split):
            continue
        target_idx = end - 1
        windows.append(site.features[start:end])
        raw_last.append(site.features[target_idx])
        targets.append(site.criticality[target_idx])
        statics.append(site.static)
    return (
        np.asarray(windows, dtype=np.float32),
        np.asarray(raw_last, dtype=np.float32),
        np.asarray(targets, dtype=np.float32),
        np.asarray(statics, dtype=np.float32),
    )


def collect_probe_matrix(
    encoder: ObservableEncoder,
    sites,
    cfg: RSJEPAConfig,
    split: str,
    *,
    device: torch.device,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    windows_all = []
    raw_all = []
    y_all = []
    static_all = []
    for site in sites:
        windows, raw_last, targets, statics = _site_windows(
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
    if not y_all:
        raise ValueError(f"Aucun échantillon probe pour split={split}.")

    windows_np = np.concatenate(windows_all, axis=0)
    raw_np = np.concatenate(raw_all, axis=0)
    y_np = np.concatenate(y_all, axis=0)
    static_np = np.concatenate(static_all, axis=0)
    if len(y_np) > cfg.training.probe_max_samples:
        indices = np.linspace(0, len(y_np) - 1, cfg.training.probe_max_samples).astype(int)
        windows_np = windows_np[indices]
        raw_np = raw_np[indices]
        y_np = y_np[indices]
        static_np = static_np[indices]

    encoder.eval()
    latents = []
    with torch.no_grad():
        batch_size = 128
        for start in range(0, len(y_np), batch_size):
            x = torch.as_tensor(windows_np[start : start + batch_size], device=device)
            static = torch.as_tensor(static_np[start : start + batch_size], device=device)
            encoded = encoder(x, static)
            latents.append(encoded[:, -1].detach().cpu().numpy())
    return np.concatenate(latents, axis=0), raw_np, y_np


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
    train_latent, train_raw, y_train = collect_probe_matrix(
        encoder,
        train_sites,
        cfg,
        TRAIN,
        device=device,
    )
    eval_latent, eval_raw, y_eval = collect_probe_matrix(
        encoder,
        eval_sites,
        cfg,
        split,
        device=device,
    )
    latent_pred = fit_linear_predict(train_latent, y_train, eval_latent)
    raw_pred = fit_linear_predict(train_raw, y_train, eval_raw)
    mean_pred = np.full_like(y_eval, fill_value=float(y_train.mean()))
    return ProbeResult(
        split=split,
        latent_r2=float(r2_score(y_eval, latent_pred)),
        raw_r2=float(r2_score(y_eval, raw_pred)),
        mean_baseline_r2=float(r2_score(y_eval, mean_pred)),
        ceiling_r2=float(ceiling_r2),
        n_train=int(len(y_train)),
        n_eval=int(len(y_eval)),
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
