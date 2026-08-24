"""Stage-2 criticality readout training on frozen RS-JEPA latents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn

from rs_jepa.config import RSJEPAConfig
from rs_jepa.encoder import ObservableEncoder
from rs_jepa.heads import (
    CriticalityReadout,
    Stage2Metrics,
    coral_loss,
    per_site_zscore,
    predict_ordinal_level,
    ranking_correlation,
)
from rs_jepa.splits import (
    CROSS_SITE_VAL,
    TEMPORAL_VAL,
    TRAIN,
    add_validation_splits,
    choose_cross_site_validation_sites,
)
from rs_jepa.synthetic import SyntheticHospitalSimulator
from rs_jepa.train import LoadedEncoder, load_encoder_checkpoint


@dataclass(frozen=True)
class Stage2Site:
    site_id: str
    features: np.ndarray
    static: np.ndarray
    criticality: np.ndarray
    levels: np.ndarray
    split: np.ndarray


@dataclass(frozen=True)
class Stage2Examples:
    latents: torch.Tensor
    criticality: torch.Tensor
    levels: torch.Tensor
    site_ids: np.ndarray


@dataclass(frozen=True)
class Stage2Artifacts:
    heads: CriticalityReadout
    metrics: dict[str, Stage2Metrics]
    history: list[dict[str, float]]


def build_stage2_sites(
    cfg: RSJEPAConfig,
) -> tuple[list[Stage2Site], list[Stage2Site], list[Stage2Site]]:
    """Build Phase-A sites with unitless continuous and ordinal criticality targets."""

    site_ids = [f"site-{idx:03d}" for idx in range(cfg.synthetic.n_sites)]
    reserved = set(choose_cross_site_validation_sites(site_ids, cfg.split))
    data = SyntheticHospitalSimulator(cfg.synthetic, reserved_site_ids=reserved).generate()
    split_frame, _summary = add_validation_splits(
        data.temporal[["site_id", "timestamp"]],
        cfg.split,
    )
    temporal = data.temporal.merge(split_frame, on=["site_id", "timestamp"], how="left")
    static = data.static.set_index("site_id")
    sites = []
    for site_id, group in temporal.groupby("site_id", sort=True):
        group = group.sort_values("timestamp")
        site_static = static.loc[site_id]
        sites.append(
            Stage2Site(
                site_id=site_id,
                features=group.loc[:, data.temporal_feature_columns].to_numpy(dtype=np.float32),
                static=site_static.loc[list(data.static_feature_columns)].to_numpy(
                    dtype=np.float32
                ),
                criticality=group["criticality"].to_numpy(dtype=np.float32),
                levels=group["criticality_level"].to_numpy(dtype=np.int64),
                split=group["split"].to_numpy(dtype=str),
            )
        )
    train_sites = [site for site in sites if not np.all(site.split == CROSS_SITE_VAL)]
    cross_site_sites = [site for site in sites if np.all(site.split == CROSS_SITE_VAL)]
    return sites, train_sites, cross_site_sites


def freeze_encoder(encoder: ObservableEncoder) -> ObservableEncoder:
    """Freeze Stage-1 encoder parameters for Stage-2 readout training."""

    encoder.eval()
    for param in encoder.parameters():
        param.requires_grad_(False)
    return encoder


def _window_arrays(
    sites: list[Stage2Site],
    cfg: RSJEPAConfig,
    split: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    windows = []
    statics = []
    criticality = []
    levels = []
    site_ids = []
    for site in sites:
        rows = np.where(site.split == split)[0]
        if len(rows) == 0:
            continue
        start_min = int(rows[0])
        start_max = int(rows[-1]) - cfg.stage1.context_steps + 1
        for start in range(start_min, start_max, cfg.training.probe_stride):
            end = start + cfg.stage1.context_steps
            if not np.all(site.split[start:end] == split):
                continue
            windows.append(site.features[start:end])
            statics.append(site.static)
            criticality.append(site.criticality[start:end])
            levels.append(site.levels[start:end])
            site_ids.extend([site.site_id] * cfg.stage1.context_steps)
    if not windows:
        raise ValueError(f"Aucune fenêtre Stage-2 pour split={split}.")
    return (
        np.asarray(windows, dtype=np.float32),
        np.asarray(statics, dtype=np.float32),
        np.asarray(criticality, dtype=np.float32),
        np.asarray(levels, dtype=np.int64),
        np.asarray(site_ids),
    )


def extract_frozen_examples(
    encoder: ObservableEncoder,
    sites: list[Stage2Site],
    cfg: RSJEPAConfig,
    split: str,
    *,
    device: torch.device,
) -> Stage2Examples:
    """Encode observable windows and align every latent timestep with kappa_t."""

    windows_np, static_np, criticality_np, levels_np, site_ids = _window_arrays(sites, cfg, split)
    if len(windows_np) > cfg.training.probe_max_samples:
        indices = np.linspace(0, len(windows_np) - 1, cfg.training.probe_max_samples).astype(int)
        windows_np = windows_np[indices]
        static_np = static_np[indices]
        criticality_np = criticality_np[indices]
        levels_np = levels_np[indices]
        keep = np.concatenate(
            [
                np.arange(idx * cfg.stage1.context_steps, (idx + 1) * cfg.stage1.context_steps)
                for idx in indices
            ]
        )
        site_ids = site_ids[keep]

    encoder.eval()
    latents = []
    with torch.no_grad():
        for start in range(0, len(windows_np), 128):
            x = torch.as_tensor(windows_np[start : start + 128], device=device)
            static = torch.as_tensor(static_np[start : start + 128], device=device)
            encoded = encoder(x, static)
            latents.append(encoded.reshape(-1, encoded.shape[-1]).detach().cpu())
    flat_latents = torch.cat(latents, dim=0)
    flat_criticality = torch.as_tensor(criticality_np.reshape(-1), dtype=torch.float32)
    flat_levels = torch.as_tensor(levels_np.reshape(-1), dtype=torch.long)
    if flat_latents.shape[0] != flat_levels.shape[0] or flat_levels.shape[0] != len(site_ids):
        raise AssertionError("Alignement Stage-2 latent/kappa/level invalide.")
    return Stage2Examples(
        latents=flat_latents,
        criticality=flat_criticality,
        levels=flat_levels,
        site_ids=site_ids,
    )


def _batches(n: int, batch_size: int, generator: torch.Generator) -> list[torch.Tensor]:
    order = torch.randperm(n, generator=generator)
    return [order[start : start + batch_size] for start in range(0, n, batch_size)]


def train_stage2_heads(
    heads: CriticalityReadout,
    train: Stage2Examples,
    cfg: RSJEPAConfig,
    *,
    device: torch.device,
) -> list[dict[str, float]]:
    heads.to(device)
    optimizer = torch.optim.AdamW(
        heads.parameters(),
        lr=cfg.stage2.lr,
        weight_decay=cfg.stage2.weight_decay,
    )
    generator = torch.Generator().manual_seed(cfg.seed)
    history = []
    latents = train.latents.to(device)
    tension_target = train.criticality.to(device)
    levels = train.levels.to(device)
    for epoch in range(cfg.stage2.max_epochs):
        losses = []
        for batch in _batches(len(levels), cfg.stage2.batch_size, generator):
            batch = batch.to(device)
            out = heads(latents[batch])
            tension_loss = nn.functional.smooth_l1_loss(out["tension"], tension_target[batch])
            ordinal = coral_loss(out["ordinal_logits"], levels[batch], cfg.stage2.k_levels)
            loss = tension_loss + ordinal
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu().item()))
        history.append({"epoch": float(epoch + 1), "loss": float(np.mean(losses))})
    return history


def evaluate_stage2(
    heads: CriticalityReadout,
    examples: Stage2Examples,
    cfg: RSJEPAConfig,
    split: str,
    *,
    device: torch.device,
) -> Stage2Metrics:
    heads.eval()
    with torch.no_grad():
        out = heads(examples.latents.to(device))
        logits = out["ordinal_logits"].cpu()
        tension = out["tension"].cpu().numpy()
    pred = predict_ordinal_level(logits).cpu()
    levels = examples.levels.cpu()
    accuracy = float((pred == levels).to(torch.float32).mean().item())
    mae = float(torch.mean(torch.abs(pred.to(torch.float32) - levels.to(torch.float32))).item())
    normalized_tension = per_site_zscore(tension, examples.site_ids)
    return Stage2Metrics(
        split=split,
        ordinal_accuracy=accuracy,
        mae_levels=mae,
        ranking_corr=ranking_correlation(pred.numpy(), levels.numpy()),
        tension_corr=ranking_correlation(normalized_tension, examples.criticality.numpy()),
        n_eval=int(len(levels)),
    )


def run_stage2_training(
    checkpoint: str | Path,
    cfg: RSJEPAConfig | None = None,
    *,
    log: bool = True,
) -> Stage2Artifacts:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    loaded: LoadedEncoder = load_encoder_checkpoint(checkpoint, device=device)
    run_cfg = cfg or loaded.cfg
    encoder = freeze_encoder(loaded.encoder)
    _sites, train_sites, cross_site_sites = build_stage2_sites(run_cfg)
    train_examples = extract_frozen_examples(encoder, train_sites, run_cfg, TRAIN, device=device)
    cross_examples = extract_frozen_examples(
        encoder,
        cross_site_sites,
        run_cfg,
        CROSS_SITE_VAL,
        device=device,
    )
    temporal_examples = extract_frozen_examples(
        encoder,
        train_sites,
        run_cfg,
        TEMPORAL_VAL,
        device=device,
    )
    heads = CriticalityReadout(run_cfg.stage1.latent_dim, run_cfg.stage2)
    history = train_stage2_heads(heads, train_examples, run_cfg, device=device)
    metrics = {
        "cross_site": evaluate_stage2(
            heads,
            cross_examples,
            run_cfg,
            CROSS_SITE_VAL,
            device=device,
        ),
        "temporal": evaluate_stage2(
            heads,
            temporal_examples,
            run_cfg,
            TEMPORAL_VAL,
            device=device,
        ),
    }
    if log:
        print("Stage 2 criticality heads on frozen Stage-1 latent (wiring validation only)")
        for metric in metrics.values():
            print(
                f"{metric.split}: acc={metric.ordinal_accuracy:.3f} "
                f"mae_levels={metric.mae_levels:.3f} ranking_corr={metric.ranking_corr:.3f} "
                f"tension_corr={metric.tension_corr:.3f} n={metric.n_eval}"
            )
    return Stage2Artifacts(heads=heads, metrics=metrics, history=history)
