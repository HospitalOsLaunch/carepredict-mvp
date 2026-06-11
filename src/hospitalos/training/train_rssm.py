"""Entrypoint for training JEPA-conditioned RSSM dynamics."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
from typing import Any

import lightning as L
import torch
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset

from hospitalos.dynamics.jepa_rssm import JepaRSSM, RSSMConfig
from hospitalos.encoders.ts_jepa.encoder import TransformerEncoder
from hospitalos.encoders.ts_jepa.patcher import Patchifier


def build_dataset(cfg: RSSMConfig) -> Dataset[dict[str, torch.Tensor]]:
    """Must yield dict(series=FloatTensor(T, C), siips=FloatTensor(T,) optional).

    Wired by the maintainer. Not implemented here.
    """
    del cfg
    raise NotImplementedError


def parse_args() -> argparse.Namespace:
    """Parse RSSM training arguments."""
    parser = argparse.ArgumentParser(description="Train a JEPA-conditioned RSSM.")
    parser.add_argument("--encoder-ckpt", type=Path, required=True)
    parser.add_argument("--max-steps", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--joint-finetune", action="store_true", default=False)
    return parser.parse_args()


def load_frozen_encoder(encoder_ckpt: Path) -> tuple[Patchifier, TransformerEncoder, int]:
    """Load patcher and context encoder from a TS-JEPA checkpoint."""
    payload: dict[str, Any] = torch.load(encoder_ckpt, map_location="cpu", weights_only=True)
    patcher_state = payload["patcher"]
    encoder_state = payload["context_encoder"]
    patch_weight = patcher_state["proj.weight"]
    emb_dim = int(patch_weight.shape[0])
    patch_input_dim = int(patch_weight.shape[1])
    patch_len = 24
    in_channels = patch_input_dim // patch_len
    patcher = Patchifier(in_channels=in_channels, patch_len=patch_len, emb_dim=emb_dim)
    encoder = TransformerEncoder(emb_dim=emb_dim)
    patcher.load_state_dict(patcher_state)
    encoder.load_state_dict(encoder_state)
    return patcher, encoder, emb_dim


def enable_joint_finetune(model: JepaRSSM, cfg: RSSMConfig) -> None:
    """Enable low-LR encoder finetuning by replacing optimizer configuration."""
    model.frozen_encoder.requires_grad_(True)
    rssm_params = [
        param
        for name, param in model.named_parameters()
        if not name.startswith("frozen_encoder.") and not name.startswith("patcher.")
    ]
    encoder_params = list(model.frozen_encoder.parameters())

    def configure_joint_optimizers() -> AdamW:
        return AdamW(
            [
                {"params": rssm_params, "lr": cfg.lr},
                {"params": encoder_params, "lr": 1e-5},
            ]
        )

    model.configure_optimizers = configure_joint_optimizers  # type: ignore[method-assign]


def main() -> None:
    """Train RSSM dynamics over frozen TS-JEPA embeddings."""
    args = parse_args()
    patcher, encoder, emb_dim = load_frozen_encoder(args.encoder_ckpt)
    cfg = RSSMConfig(emb_dim=emb_dim)
    model = JepaRSSM(cfg, encoder, patcher)
    if args.joint_finetune:
        enable_joint_finetune(model, cfg)

    dataset = build_dataset(cfg)
    dataloader = DataLoader(dataset, batch_size=32, shuffle=True)
    trainer = L.Trainer(
        max_steps=args.max_steps,
        accelerator="auto",
        gradient_clip_val=cfg.grad_clip,
        gradient_clip_algorithm="norm",
        log_every_n_steps=50,
    )
    trainer.fit(model, dataloader)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model": model.state_dict(),
            "rssm_config": asdict(cfg),
            "encoder_ckpt": str(args.encoder_ckpt),
            "joint_finetune": bool(args.joint_finetune),
        },
        args.out,
    )


if __name__ == "__main__":
    main()
