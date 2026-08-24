#!/usr/bin/env python3
"""Train an ActionDeltaHead on frozen RS-JEPA rollouts and true simulator deltas."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

import numpy as np
import torch
from torch.nn import functional as F

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_jepa.heads import ActionDeltaHead  # noqa: E402
from rs_jepa.splits import CROSS_SITE_VAL, TRAIN  # noqa: E402
from rs_jepa.train import build_phase_a_sites, load_stage1_checkpoint  # noqa: E402


class DeltaData(NamedTuple):
    z0: torch.Tensor
    z_action: torch.Tensor
    channel_id: torch.Tensor
    target: torch.Tensor
    action_value: torch.Tensor


def _freeze_chain(chain) -> None:
    for module in (chain.encoder, chain.rssm, chain.predictor):
        module.eval()
        for param in module.parameters():
            param.requires_grad_(False)


def _collect_windows(cfg, split: str, *, horizon: int, max_windows: int | None):
    _sites, train_sites, cross_site_sites = build_phase_a_sites(cfg)
    source_sites = train_sites if split == TRAIN else cross_site_sites
    windows = []
    statics = []
    actions_context = []
    actions_future = []
    deltas_future = []
    stride = max(horizon, cfg.training.probe_stride)
    for site in source_sites:
        rows = np.where(site.split == split)[0]
        if len(rows) == 0:
            continue
        start_min = int(rows[0])
        start_max = int(rows[-1]) - cfg.stage1.context_steps - horizon + 1
        for start in range(start_min, start_max, stride):
            context_end = start + cfg.stage1.context_steps
            end = context_end + horizon
            if not np.all(site.split[start:end] == split):
                continue
            windows.append(site.features[start:context_end])
            statics.append(site.static)
            actions_context.append(site.actions[start:context_end])
            actions_future.append(site.actions[context_end:end])
            deltas_future.append(site.action_deltas[context_end:end])
            if max_windows is not None and len(windows) >= max_windows:
                break
        if max_windows is not None and len(windows) >= max_windows:
            break
    if not windows:
        raise ValueError(f"Aucune fenêtre disponible pour split={split}.")
    return (
        torch.as_tensor(np.asarray(windows, dtype=np.float32)),
        torch.as_tensor(np.asarray(statics, dtype=np.float32)),
        torch.as_tensor(np.asarray(actions_context, dtype=np.float32)),
        torch.as_tensor(np.asarray(actions_future, dtype=np.float32)),
        torch.as_tensor(np.asarray(deltas_future, dtype=np.float32)),
    )


def _rollout_latents(chain, x_context, static, actions_context, actions_future):
    z_context = chain.encoder(x_context, static)
    states = chain.rssm.rollout(
        z_context,
        horizon=actions_future.shape[1],
        static=static,
        actions_context=actions_context,
        actions_future=actions_future,
    ).states
    return chain.predictor(states)


def build_delta_data(
    chain,
    split: str,
    *,
    horizon: int,
    max_windows: int | None,
    device: torch.device,
) -> DeltaData:
    x_context, static, actions_context, actions_future, deltas_future = _collect_windows(
        chain.cfg,
        split,
        horizon=horizon,
        max_windows=max_windows,
    )
    x_context = x_context.to(device)
    static = static.to(device)
    actions_context = actions_context.to(device)
    actions_future = actions_future.to(device)
    deltas_future = deltas_future.to(device)
    zeros = torch.zeros_like(actions_future)
    with torch.no_grad():
        z0 = _rollout_latents(chain, x_context, static, actions_context, zeros)
        z_action_all = []
        for channel in range(chain.cfg.stage1.action_dim):
            channel_actions = torch.zeros_like(actions_future)
            channel_actions[..., channel] = actions_future[..., channel]
            z_action_all.append(
                _rollout_latents(chain, x_context, static, actions_context, channel_actions)
            )
    z0_all = []
    channel_ids = []
    targets = []
    action_values = []
    for channel, _z_action in enumerate(z_action_all):
        z0_all.append(z0)
        channel_ids.append(
            torch.full(
                actions_future.shape[:2],
                channel,
                dtype=torch.long,
                device=device,
            )
        )
        targets.append(deltas_future[..., channel])
        action_values.append(actions_future[..., channel])
    return DeltaData(
        z0=torch.cat(z0_all, dim=0).detach(),
        z_action=torch.cat(z_action_all, dim=0).detach(),
        channel_id=torch.cat(channel_ids, dim=0).detach(),
        target=torch.cat(targets, dim=0).detach(),
        action_value=torch.cat(action_values, dim=0).detach(),
    )


def _iter_batches(n: int, batch_size: int, seed: int):
    generator = torch.Generator().manual_seed(seed)
    order = torch.randperm(n, generator=generator)
    for start in range(0, n, batch_size):
        yield order[start : start + batch_size]


def _params_snapshot(module: torch.nn.Module) -> list[torch.Tensor]:
    return [param.detach().clone() for param in module.parameters()]


def _changed(before: list[torch.Tensor], module: torch.nn.Module) -> bool:
    return any(
        not torch.equal(old.cpu(), new.detach().cpu())
        for old, new in zip(before, module.parameters(), strict=True)
    )


def train_one_seed(
    chain,
    train: DeltaData,
    val: DeltaData,
    *,
    seed: int,
    epochs: int,
    batch_size: int,
    device: torch.device,
) -> ActionDeltaHead:
    torch.manual_seed(seed)
    cfg = replace(chain.cfg.stage2, head_depth=3, head_hidden_dim=128, max_epochs=epochs)
    head = ActionDeltaHead(chain.cfg.stage1.latent_dim, cfg).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    head_before = _params_snapshot(head)
    chain_before = {
        "encoder": _params_snapshot(chain.encoder),
        "rssm": _params_snapshot(chain.rssm),
        "predictor": _params_snapshot(chain.predictor),
    }
    for epoch in range(epochs):
        losses = []
        head.train()
        for batch in _iter_batches(train.z0.shape[0], batch_size, seed + epoch):
            batch = batch.to(device)
            pred = head(train.z0[batch], train.z_action[batch], train.channel_id[batch])
            loss = F.smooth_l1_loss(pred, train.target[batch])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu().item()))
        head.eval()
        with torch.no_grad():
            val_pred = head(val.z0, val.z_action, val.channel_id)
            val_loss = F.smooth_l1_loss(val_pred, val.target)
        print(
            f"DELTA_HEAD seed={seed} epoch={epoch + 1} "
            f"train_loss={np.mean(losses):.8f} val_loss={float(val_loss.cpu()):.8f}"
        )
    assert _changed(head_before, head)
    assert not _changed(chain_before["encoder"], chain.encoder)
    assert not _changed(chain_before["rssm"], chain.rssm)
    assert not _changed(chain_before["predictor"], chain.predictor)
    frozen_grads_none = all(
        param.grad is None
        for module in (chain.encoder, chain.rssm, chain.predictor)
        for param in module.parameters()
    )
    assert frozen_grads_none
    return head.eval()


def scenario_report(
    head: ActionDeltaHead, data: DeltaData, *, channel: int, sign: int
) -> dict[str, float]:
    flat_channel = data.channel_id.reshape(-1)
    flat_action = data.action_value.reshape(-1)
    mask = flat_channel == channel
    mask = mask & (torch.sign(flat_action) == sign)
    n = int(mask.sum().item())
    if n == 0:
        return {"n": 0}
    z0 = data.z0.reshape(-1, data.z0.shape[-1])[mask].unsqueeze(1)
    z_action = data.z_action.reshape(-1, data.z_action.shape[-1])[mask].unsqueeze(1)
    channel_id = flat_channel[mask].unsqueeze(1)
    with torch.no_grad():
        pred = head(z0, z_action, channel_id).squeeze(1)
    true = data.target.reshape(-1)[mask]
    pred_np = pred.detach().cpu().numpy().reshape(-1)
    true_np = true.detach().cpu().numpy().reshape(-1)
    sign_ok = np.sign(pred_np) == np.sign(true_np)
    return {
        "n": n,
        "pred_mean": float(pred_np.mean()),
        "pred_std": float(pred_np.std(ddof=1)),
        "true_mean": float(true_np.mean()),
        "true_std": float(true_np.std(ddof=1)),
        "sign_acc": float(sign_ok.mean()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="runs/phaseA/encoder_10k_actioned_full.pt")
    parser.add_argument("--out", default="runs/phaseA/action_delta_head.pt")
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--max-train-windows", type=int, default=1024)
    parser.add_argument("--max-val-windows", type=int, default=512)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seeds = [int(part) for part in args.seeds.split(",") if part.strip()]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    chain = load_stage1_checkpoint(args.checkpoint, device=device)
    _freeze_chain(chain)
    print(f"checkpoint={args.checkpoint}")
    print("frozen_chain_grads_none=True")
    train = build_delta_data(
        chain,
        TRAIN,
        horizon=args.horizon,
        max_windows=args.max_train_windows,
        device=device,
    )
    val = build_delta_data(
        chain,
        CROSS_SITE_VAL,
        horizon=args.horizon,
        max_windows=args.max_val_windows,
        device=device,
    )
    print(
        f"delta_data train={train.z0.shape} val={val.z0.shape} "
        "paired_rollout=deterministic_prior_mean"
    )
    heads = []
    for seed in seeds:
        head = train_one_seed(
            chain,
            train,
            val,
            seed=seed,
            epochs=args.epochs,
            batch_size=args.batch_size,
            device=device,
        )
        heads.append(head)
        if seed == seeds[0]:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            torch.save({"state_dict": head.state_dict(), "seed": seed}, args.out)
            print(f"saved={args.out}")
        for name, channel, sign in [
            ("staffing+", 0, 1),
            ("staffing-", 0, -1),
            ("discharge+", 1, 1),
            ("discharge-", 1, -1),
        ]:
            row = scenario_report(head, val, channel=channel, sign=sign)
            if row["n"] == 0:
                print(f"SCENARIO seed={seed} {name} n=0 no_true_samples")
                continue
            print(
                f"SCENARIO seed={seed} {name} n={row['n']} "
                f"true={row['true_mean']:.8f}±{row['true_std']:.8f} "
                f"pred={row['pred_mean']:.8f}±{row['pred_std']:.8f} "
                f"sign_acc={row['sign_acc']:.4f}"
            )
    print("NOTE discharge- has true samples only if the simulator emits negative discharge_delta.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
