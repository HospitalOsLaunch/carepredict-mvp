"""Short Stage-1 training harness for RS-JEPA Phase A."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.optim.adamw import AdamW

from rs_jepa.config import RSJEPAConfig, config_from_dict
from rs_jepa.diagnostics import run_diagnostic_for_seed as run_honesty_diagnostic
from rs_jepa.diagnostics import summarize_rows
from rs_jepa.diagnostics_latent import latent_batch_stats
from rs_jepa.ema import EMATargetEncoder, tau_schedule
from rs_jepa.encoder import ObservableEncoder
from rs_jepa.loss import latent_jepa_loss
from rs_jepa.masking import apply_stage1_masks
from rs_jepa.predictor import LatentPredictor
from rs_jepa.probe import ProbeResult, interpret_static_ablation, run_frozen_latent_probes
from rs_jepa.rssm import RSSM
from rs_jepa.seed import set_global_seed
from rs_jepa.splits import (
    CROSS_SITE_VAL,
    TRAIN,
    add_validation_splits,
    choose_cross_site_validation_sites,
)
from rs_jepa.synthetic import SyntheticHospitalSimulator
from rs_jepa.typing import Array


@dataclass(frozen=True)
class PhaseASite:
    site_id: str
    features: Array
    static: Array
    criticality: Array
    actions: Array
    action_deltas: Array
    split: Array


@dataclass
class Stage1Artifacts:
    encoder: ObservableEncoder
    ema_target: EMATargetEncoder
    rssm: RSSM
    predictor: LatentPredictor
    history: list[dict[str, float]]
    probes: dict[str, ProbeResult]
    initial_target_distance: float
    final_target_distance: float
    target_update_distance: float


@dataclass(frozen=True)
class LoadedEncoder:
    encoder: ObservableEncoder
    cfg: RSJEPAConfig
    n_obs: int
    n_static: int


@dataclass(frozen=True)
class LoadedStage1Chain:
    encoder: ObservableEncoder
    rssm: RSSM
    predictor: LatentPredictor
    cfg: RSJEPAConfig
    n_obs: int
    n_static: int


def build_phase_a_sites(
    cfg: RSJEPAConfig,
) -> tuple[list[PhaseASite], list[PhaseASite], list[PhaseASite]]:
    site_ids = [f"site-{idx:03d}" for idx in range(cfg.synthetic.n_sites)]
    reserved = set(choose_cross_site_validation_sites(site_ids, cfg.split))
    data = SyntheticHospitalSimulator(cfg.synthetic, reserved_site_ids=reserved).generate()
    split_source = data.temporal[["site_id", "timestamp"]]
    split_frame, _summary = add_validation_splits(split_source, cfg.split)
    temporal = data.temporal.merge(split_frame, on=["site_id", "timestamp"], how="left")
    static = data.static.set_index("site_id")
    sites = []
    for site_id, group in temporal.groupby("site_id", sort=True):
        group = group.sort_values("timestamp")
        site_static = static.loc[site_id]
        sites.append(
            PhaseASite(
                site_id=site_id,
                features=group.loc[:, data.temporal_feature_columns].to_numpy(dtype=np.float32),
                static=site_static.loc[list(data.static_feature_columns)].to_numpy(
                    dtype=np.float32
                ),
                criticality=group["criticality"].to_numpy(dtype=np.float32),
                actions=group.loc[:, data.action_columns].to_numpy(dtype=np.float32),
                action_deltas=group.loc[:, data.action_delta_columns].to_numpy(dtype=np.float32),
                split=group["split"].to_numpy(dtype=str),
            )
        )
    train_sites = [site for site in sites if not np.all(site.split == CROSS_SITE_VAL)]
    cross_site_sites = [site for site in sites if np.all(site.split == CROSS_SITE_VAL)]
    return sites, train_sites, cross_site_sites


def _sample_windows(
    sites: list[PhaseASite],
    cfg: RSJEPAConfig,
    *,
    generator: torch.Generator,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, int]:
    horizon = int(
        torch.tensor(cfg.stage1.horizons)[
            int(torch.randint(len(cfg.stage1.horizons), (1,), generator=generator).item())
        ].item()
    )
    window_len = cfg.stage1.context_steps + horizon
    chosen = []
    chosen_actions = []
    chosen_action_deltas = []
    statics = []
    for _idx in range(cfg.stage1.batch_size):
        for _attempt in range(100):
            site_index = int(torch.randint(len(sites), (1,), generator=generator).item())
            site = sites[site_index]
            train_rows = np.where(site.split == TRAIN)[0]
            start_min = int(train_rows[0])
            start_max = int(train_rows[-1]) - window_len + 1
            if start_max <= start_min:
                continue
            start = int(torch.randint(start_min, start_max, (1,), generator=generator).item())
            end = start + window_len
            if np.all(site.split[start:end] == TRAIN):
                chosen.append(site.features[start:end])
                chosen_actions.append(site.actions[start:end])
                chosen_action_deltas.append(site.action_deltas[start:end])
                statics.append(site.static)
                break
        else:
            raise ValueError("Impossible d'échantillonner une fenêtre train sans fuite.")
    return (
        torch.as_tensor(np.asarray(chosen, dtype=np.float32)),
        torch.as_tensor(np.asarray(statics, dtype=np.float32)),
        torch.as_tensor(np.asarray(chosen_actions, dtype=np.float32)),
        torch.as_tensor(np.asarray(chosen_action_deltas, dtype=np.float32)),
        horizon,
    )


def _encoder_target_distance(encoder: ObservableEncoder, target: EMATargetEncoder) -> float:
    total = torch.tensor(0.0)
    for online_param, target_param in zip(
        encoder.parameters(),
        target.target.parameters(),
        strict=True,
    ):
        total = total + torch.sum((online_param.detach() - target_param.detach()) ** 2)
    return float(torch.sqrt(total).cpu().item())


def _target_snapshot(target: EMATargetEncoder) -> list[torch.Tensor]:
    return [param.detach().clone() for param in target.target.parameters()]


def _target_snapshot_distance(target: EMATargetEncoder, snapshot: list[torch.Tensor]) -> float:
    total = torch.tensor(0.0)
    for param, old_param in zip(target.target.parameters(), snapshot, strict=True):
        total = total + torch.sum((param.detach().cpu() - old_param.cpu()) ** 2)
    return float(torch.sqrt(total).item())


def _mean_metrics(metrics: list[dict[str, float]]) -> dict[str, float]:
    keys = metrics[0].keys()
    return {key: float(np.mean([row[key] for row in metrics])) for key in keys}


def _action_grad_norm(rssm: RSSM, cfg: RSJEPAConfig) -> float:
    grad = rssm.gru.weight_ih.grad
    if grad is None or cfg.stage1.action_dim <= 0:
        return 0.0
    action_start = cfg.stage1.latent_dim + cfg.stage1.rssm_stoch_dim
    action_grad = grad[:, action_start : action_start + cfg.stage1.action_dim]
    return float(torch.linalg.vector_norm(action_grad.detach()).cpu().item())


def save_encoder_checkpoint(
    path: str | Path,
    encoder: ObservableEncoder,
    cfg: RSJEPAConfig,
    *,
    n_obs: int,
    n_static: int,
    rssm: RSSM | None = None,
    predictor: LatentPredictor | None = None,
) -> None:
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "encoder_state_dict": encoder.state_dict(),
        "config": asdict(cfg),
        "n_obs": int(n_obs),
        "n_static": int(n_static),
    }
    if rssm is not None:
        payload["rssm_state_dict"] = rssm.state_dict()
    if predictor is not None:
        payload["predictor_state_dict"] = predictor.state_dict()
    torch.save(payload, target_path)


def load_encoder_checkpoint(
    path: str | Path,
    *,
    device: torch.device | None = None,
) -> LoadedEncoder:
    load_device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
    payload = torch.load(Path(path), map_location=load_device, weights_only=False)
    cfg = config_from_dict(payload["config"])
    encoder = ObservableEncoder(
        n_obs=int(payload["n_obs"]),
        n_static=int(payload["n_static"]),
        cfg=cfg.stage1,
    ).to(load_device)
    encoder.load_state_dict(payload["encoder_state_dict"])
    encoder.eval()
    return LoadedEncoder(
        encoder=encoder,
        cfg=cfg,
        n_obs=int(payload["n_obs"]),
        n_static=int(payload["n_static"]),
    )


def load_stage1_checkpoint(
    path: str | Path,
    *,
    device: torch.device | None = None,
) -> LoadedStage1Chain:
    """Load the full Stage-1 chain required for action-conditioned rollouts."""

    load_device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
    payload = torch.load(Path(path), map_location=load_device, weights_only=False)
    missing = [key for key in ("rssm_state_dict", "predictor_state_dict") if key not in payload]
    if missing:
        raise ValueError(
            "Checkpoint Stage 1 incomplet: "
            f"{Path(path)} ne contient pas {missing}. "
            "Les anciens checkpoints encodeur-seul restent valides pour Stage 2, "
            "mais pas pour un rollout RSSM actionné."
        )
    cfg = config_from_dict(payload["config"])
    n_obs = int(payload["n_obs"])
    n_static = int(payload["n_static"])
    encoder = ObservableEncoder(n_obs=n_obs, n_static=n_static, cfg=cfg.stage1).to(load_device)
    encoder.load_state_dict(payload["encoder_state_dict"])
    encoder.eval()
    rssm = RSSM(cfg.stage1, n_static=n_static).to(load_device)
    rssm.load_state_dict(payload["rssm_state_dict"])
    rssm.eval()
    predictor = LatentPredictor(cfg.stage1).to(load_device)
    predictor.load_state_dict(payload["predictor_state_dict"])
    predictor.eval()
    return LoadedStage1Chain(
        encoder=encoder,
        rssm=rssm,
        predictor=predictor,
        cfg=cfg,
        n_obs=n_obs,
        n_static=n_static,
    )


def run_checkpoint_probe(path: str | Path, *, log: bool = True) -> dict[str, ProbeResult]:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    loaded = load_encoder_checkpoint(path, device=device)
    _sites, train_sites, cross_site_sites = build_phase_a_sites(loaded.cfg)
    ceiling_rows = [run_honesty_diagnostic(loaded.cfg, seed) for seed in range(5)]
    ceiling = 1.0 - float(np.mean([row["hidden_share"] for row in ceiling_rows]))
    probes = run_frozen_latent_probes(
        loaded.encoder,
        train_sites,
        cross_site_sites,
        loaded.cfg,
        ceiling_r2=ceiling,
        device=device,
    )
    if log:
        for result in probes.values():
            print(interpret_static_ablation(result, loaded.cfg.training.probe_rank_threshold))
    return probes


def run_stage1_training(cfg: RSJEPAConfig, *, log: bool = True) -> Stage1Artifacts:
    set_global_seed(cfg.seed, deterministic=cfg.stage1.deterministic)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    sites, train_sites, cross_site_sites = build_phase_a_sites(cfg)
    n_obs = train_sites[0].features.shape[1]
    n_static = train_sites[0].static.shape[0]
    encoder = ObservableEncoder(n_obs=n_obs, n_static=n_static, cfg=cfg.stage1).to(device)
    ema_target = EMATargetEncoder(encoder).to(device)
    rssm = RSSM(cfg.stage1, n_static=n_static).to(device)
    predictor = LatentPredictor(cfg.stage1).to(device)
    params: list[nn.Parameter] = []
    for module in (encoder, rssm, predictor):
        params.extend(module.parameters())
    optimizer = AdamW(params, lr=cfg.stage1.lr, weight_decay=cfg.stage1.weight_decay)
    total_steps = max(1, cfg.training.max_epochs * cfg.training.steps_per_epoch)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=total_steps)
    generator = torch.Generator().manual_seed(cfg.seed)
    history = []
    global_step = 0
    initial_target_distance: float | None = None
    initial_target_snapshot = _target_snapshot(ema_target)

    for epoch in range(cfg.training.max_epochs):
        epoch_metrics = []
        for _step in range(cfg.training.steps_per_epoch):
            x_window, static, action_window, _action_delta_window, horizon = _sample_windows(
                train_sites,
                cfg,
                generator=generator,
            )
            x_window = x_window.to(device)
            static = static.to(device)
            action_window = action_window.to(device)
            masked = apply_stage1_masks(x_window, cfg.stage1, horizon=horizon, generator=generator)
            x_context = masked["context"].to(device)
            x_target = masked["target"].to(device)
            context_idx = masked["context_idx"].to(device)
            target_idx = masked["target_idx"].to(device)
            actions_context = action_window[:, context_idx] if cfg.stage1.action_dim > 0 else None
            actions_future = action_window[:, target_idx] if cfg.stage1.action_dim > 0 else None
            z_context = encoder(x_context, static)
            states = rssm.rollout(
                z_context,
                horizon=x_target.shape[1],
                static=static,
                actions_context=actions_context,
                actions_future=actions_future,
            ).states
            pred_latents = predictor(states)
            target_latents = ema_target(x_target, static)
            loss, components = latent_jepa_loss(pred_latents, target_latents, cfg.stage1)

            optimizer.zero_grad(set_to_none=True)
            loss.backward()  # type: ignore[no-untyped-call]
            action_grad_norm = _action_grad_norm(rssm, cfg)
            torch.nn.utils.clip_grad_norm_(params, cfg.stage1.grad_clip)
            optimizer.step()
            scheduler.step()
            if initial_target_distance is None:
                initial_target_distance = _encoder_target_distance(encoder, ema_target)
            tau = tau_schedule(
                global_step,
                cfg.stage1.ema_ramp_steps,
                start=cfg.stage1.ema_start,
                end=cfg.stage1.ema_end,
            )
            ema_target.update_from(encoder, tau=tau)
            latent_stats = latent_batch_stats(pred_latents.detach())
            epoch_metrics.append(
                {
                    "loss": float(loss.detach().cpu().item()),
                    "pred": float(components["pred"].cpu().item()),
                    "var": float(components["var"].cpu().item()),
                    "cov": float(components["cov"].cpu().item()),
                    "effective_rank": latent_stats["effective_rank"],
                    "per_dim_std_min": latent_stats["per_dim_std_min"],
                    "per_dim_std_mean": latent_stats["per_dim_std_mean"],
                    "action_grad_norm": action_grad_norm,
                    "tau": float(tau),
                }
            )
            global_step += 1
        mean = _mean_metrics(epoch_metrics)
        mean["epoch"] = float(epoch + 1)
        history.append(mean)
        if log:
            print(
                "epoch={epoch:.0f} loss={loss:.4f} pred={pred:.4f} "
                "var={var:.4f} cov={cov:.4f} rank={effective_rank:.2f} "
                "std_min={per_dim_std_min:.3f} std_mean={per_dim_std_mean:.3f} "
                "action_grad={action_grad_norm:.6f} tau={tau:.5f}".format(**mean)
            )
            if mean["effective_rank"] < cfg.training.early_collapse_rank_threshold:
                print(
                    "WARNING: latent effective_rank proche du collapse "
                    f"({mean['effective_rank']:.2f})"
                )

    ceiling_rows = [run_honesty_diagnostic(cfg, seed) for seed in range(5)]
    ceiling = 1.0 - float(np.mean([row["hidden_share"] for row in ceiling_rows]))
    _summary = summarize_rows(ceiling_rows)
    probes = run_frozen_latent_probes(
        encoder,
        train_sites,
        cross_site_sites,
        cfg,
        ceiling_r2=ceiling,
        device=device,
    )
    if log:
        for result in probes.values():
            print(interpret_static_ablation(result, cfg.training.probe_rank_threshold))
    if cfg.training.checkpoint_path:
        save_encoder_checkpoint(
            cfg.training.checkpoint_path,
            encoder,
            cfg,
            n_obs=n_obs,
            n_static=n_static,
            rssm=rssm,
            predictor=predictor,
        )
        if log:
            print(f"encoder_checkpoint_saved={cfg.training.checkpoint_path}")
    return Stage1Artifacts(
        encoder=encoder,
        ema_target=ema_target,
        rssm=rssm,
        predictor=predictor,
        history=history,
        probes=probes,
        initial_target_distance=float(initial_target_distance or 0.0),
        final_target_distance=_encoder_target_distance(encoder, ema_target),
        target_update_distance=_target_snapshot_distance(ema_target, initial_target_snapshot),
    )
