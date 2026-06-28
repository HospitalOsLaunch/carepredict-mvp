#!/usr/bin/env python3
"""Localise ou l'action se perd dans la chaine RSSM actionnee."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_jepa.heads import CriticalityReadout  # noqa: E402
from rs_jepa.splits import CROSS_SITE_VAL, TRAIN  # noqa: E402
from rs_jepa.train import build_phase_a_sites, load_stage1_checkpoint  # noqa: E402
from rs_jepa.train_stage2 import (  # noqa: E402
    build_stage2_sites,
    evaluate_stage2,
    extract_frozen_examples,
    freeze_encoder,
    train_stage2_heads,
)


class StageMetrics(NamedTuple):
    rssm_mean: float
    rssm_std: float
    latent_mean: float
    latent_std: float
    score_mean: float
    score_std: float
    grad_score: float
    grad_latent: float


def _stage2_cfg(cfg, seed: int):
    return replace(
        cfg,
        seed=seed,
        stage2=replace(cfg.stage2, head_depth=4, head_hidden_dim=128, max_epochs=20),
    )


def _ordinal_score(heads: CriticalityReadout, latents: torch.Tensor) -> torch.Tensor:
    flat = latents.reshape(-1, latents.shape[-1])
    logits = heads(flat)["ordinal_logits"]
    return torch.sigmoid(logits).sum(dim=-1).reshape(latents.shape[0], latents.shape[1])


def _train_head(chain, *, seed: int, device: torch.device) -> CriticalityReadout:
    frozen_encoder = freeze_encoder(chain.encoder)
    _sites, train_sites, cross_site_sites = build_stage2_sites(chain.cfg)
    cfg = _stage2_cfg(chain.cfg, seed)
    train_examples = extract_frozen_examples(frozen_encoder, train_sites, cfg, TRAIN, device=device)
    cross_examples = extract_frozen_examples(
        frozen_encoder,
        cross_site_sites,
        cfg,
        CROSS_SITE_VAL,
        device=device,
    )
    torch.manual_seed(seed)
    np.random.seed(seed)
    heads = CriticalityReadout(cfg.stage1.latent_dim, cfg.stage2).to(device)
    train_stage2_heads(heads, train_examples, cfg, device=device)
    metric = evaluate_stage2(heads, cross_examples, cfg, CROSS_SITE_VAL, device=device)
    print(
        "HEAD "
        f"seed={seed} acc={metric.ordinal_accuracy:.6f} "
        f"mae={metric.mae_levels:.6f} ranking={metric.ranking_corr:.6f} "
        f"tension={metric.tension_corr:.6f} n={metric.n_eval}"
    )
    return heads.eval()


def _collect_contexts(cfg, *, max_contexts: int, horizon: int):
    _sites, _train_sites, cross_site_sites = build_phase_a_sites(cfg)
    contexts = []
    statics = []
    actions_context = []
    stride = max(horizon, cfg.training.probe_stride)
    for site in cross_site_sites:
        rows = np.where(site.split == CROSS_SITE_VAL)[0]
        if len(rows) == 0:
            continue
        start_min = int(rows[0])
        start_max = int(rows[-1]) - cfg.stage1.context_steps - horizon + 1
        for start in range(start_min, start_max, stride):
            end = start + cfg.stage1.context_steps
            if not np.all(site.split[start:end] == CROSS_SITE_VAL):
                continue
            contexts.append(site.features[start:end])
            statics.append(site.static)
            actions_context.append(site.actions[start:end])
            if len(contexts) >= max_contexts:
                break
        if len(contexts) >= max_contexts:
            break
    if not contexts:
        raise ValueError("Aucun contexte cross-site disponible.")
    return (
        torch.as_tensor(np.asarray(contexts, dtype=np.float32)),
        torch.as_tensor(np.asarray(statics, dtype=np.float32)),
        torch.as_tensor(np.asarray(actions_context, dtype=np.float32)),
    )


def _roll(chain, z_context, static, actions_context, actions_future):
    states = chain.rssm.rollout(
        z_context,
        horizon=actions_future.shape[1],
        static=static,
        actions_context=actions_context,
        actions_future=actions_future,
    ).states
    latents = chain.predictor(states)
    return states, latents


def _norm_stats(delta: torch.Tensor) -> tuple[float, float]:
    per_context = delta.norm(dim=-1).mean(dim=1).detach().cpu().numpy()
    return float(per_context.mean()), float(per_context.std(ddof=1))


def _score_stats(heads: CriticalityReadout, latent_action, latent_base) -> tuple[float, float]:
    delta = _ordinal_score(heads, latent_action) - _ordinal_score(heads, latent_base)
    per_context = delta.mean(dim=1).detach().cpu().numpy()
    return float(per_context.mean()), float(per_context.std(ddof=1))


def _grad_norms(
    chain,
    heads: CriticalityReadout,
    z_context: torch.Tensor,
    static: torch.Tensor,
    actions_context: torch.Tensor,
    action_value: torch.Tensor,
    *,
    channel: int,
) -> tuple[float, float]:
    action_leaf = action_value.detach().clone().requires_grad_(True)
    _states, latents = _roll(chain, z_context.detach(), static, actions_context, action_leaf)
    score = _ordinal_score(heads, latents).mean()
    score.backward(retain_graph=True)
    score_grad = action_leaf.grad[..., channel].detach().clone()
    score_norm = float(score_grad.norm(dim=1).mean().cpu().item())

    action_leaf.grad.zero_()
    generator = torch.Generator(device=latents.device).manual_seed(0)
    probe = torch.randn(
        latents.shape,
        generator=generator,
        device=latents.device,
        dtype=latents.dtype,
    )
    latent_probe = (latents * probe).mean()
    latent_probe.backward()
    latent_grad = action_leaf.grad[..., channel].detach()
    latent_norm = float(latent_grad.norm(dim=1).mean().cpu().item())
    return score_norm, latent_norm


def _measure(
    chain,
    heads: CriticalityReadout,
    contexts: torch.Tensor,
    static: torch.Tensor,
    actions_context: torch.Tensor,
    action_value: torch.Tensor,
    *,
    channel: int,
    device: torch.device,
) -> StageMetrics:
    contexts = contexts.to(device)
    static = static.to(device)
    actions_context = actions_context.to(device)
    action_value = action_value.to(device)
    zeros = torch.zeros_like(action_value)
    with torch.no_grad():
        z_context = chain.encoder(contexts, static)
        base_states, base_latents = _roll(chain, z_context, static, actions_context, zeros)
        action_states, action_latents = _roll(
            chain,
            z_context,
            static,
            actions_context,
            action_value,
        )
        rssm_mean, rssm_std = _norm_stats(action_states - base_states)
        latent_mean, latent_std = _norm_stats(action_latents - base_latents)
        score_mean, score_std = _score_stats(heads, action_latents, base_latents)
    grad_score, grad_latent = _grad_norms(
        chain,
        heads,
        z_context,
        static,
        actions_context,
        action_value,
        channel=channel,
    )
    return StageMetrics(
        rssm_mean=rssm_mean,
        rssm_std=rssm_std,
        latent_mean=latent_mean,
        latent_std=latent_std,
        score_mean=score_mean,
        score_std=score_std,
        grad_score=grad_score,
        grad_latent=grad_latent,
    )


def _verdict(channel: str, pos: StageMetrics, neg: StageMetrics) -> str:
    if pos.rssm_mean < 1e-5:
        return f"{channel}: RSSM ignore l'action"
    if pos.latent_mean < 1e-5:
        return f"{channel}: predictor lessive l'action"
    if abs(pos.score_mean) < 1e-4 and abs(neg.score_mean) < 1e-4:
        return f"{channel}: latent bouge sans direction utile"
    expected = pos.score_mean < 0 and neg.score_mean > 0
    if expected:
        return f"{channel}: signe utile appris"
    return f"{channel}: signe inversé / instable = confounding ou lecture non causale"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="runs/phaseA/encoder_10k_actioned_full.pt")
    parser.add_argument("--head-seed", type=int, default=0)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--max-contexts", type=int, default=256)
    parser.add_argument("--staffing", type=float, default=0.16)
    parser.add_argument("--discharge", type=float, default=0.025)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    chain = load_stage1_checkpoint(args.checkpoint, device=device)
    for module in (chain.encoder, chain.rssm, chain.predictor):
        module.eval()
        for param in module.parameters():
            param.requires_grad_(False)
    frozen_ok = all(
        param.grad is None
        for module in (chain.encoder, chain.rssm, chain.predictor)
        for param in module.parameters()
    )
    print(f"checkpoint={args.checkpoint}")
    print(f"frozen_chain_grads_none={frozen_ok} action_dim={chain.cfg.stage1.action_dim}")
    heads = _train_head(chain, seed=args.head_seed, device=device)
    contexts, static, actions_context = _collect_contexts(
        chain.cfg,
        max_contexts=args.max_contexts,
        horizon=args.horizon,
    )
    shape = (len(contexts), args.horizon, chain.cfg.stage1.action_dim)
    scenarios = {
        "staffing+": (0, args.staffing),
        "staffing-": (0, -args.staffing),
        "discharge+": (1, args.discharge),
        "discharge-": (1, -args.discharge),
    }
    results: dict[str, StageMetrics] = {}
    print(f"contexts={len(contexts)} horizon={args.horizon}")
    print(
        "scenario | delta_rssm_state_norm | delta_latent_norm | "
        "delta_head_score | dscore_daction_norm | dlatent_daction_vjp_norm"
    )
    for name, (channel, value) in scenarios.items():
        action = torch.zeros(shape)
        action[..., channel] = value
        metrics = _measure(
            chain,
            heads,
            contexts,
            static,
            actions_context,
            action,
            channel=channel,
            device=device,
        )
        results[name] = metrics
        print(
            f"{name} | "
            f"{metrics.rssm_mean:.8f}±{metrics.rssm_std:.8f} | "
            f"{metrics.latent_mean:.8f}±{metrics.latent_std:.8f} | "
            f"{metrics.score_mean:.8f}±{metrics.score_std:.8f} | "
            f"{metrics.grad_score:.8f} | "
            f"{metrics.grad_latent:.8f}"
        )
    print("VERDICT_LOCALISATION")
    print(_verdict("staffing", results["staffing+"], results["staffing-"]))
    print(_verdict("discharge", results["discharge+"], results["discharge-"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
