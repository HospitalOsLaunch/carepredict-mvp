"""Entrypoint for TS-JEPA pretraining.

The dataset builder is intentionally left for the maintainer to wire without
touching the data plane in this additive implementation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import lightning as L
import torch
from torch.utils.data import DataLoader, Dataset

from hospitalos.encoders.ts_jepa.config import JEPAConfig
from hospitalos.encoders.ts_jepa.jepa_module import JEPALightningModule


def build_dataset(cfg: JEPAConfig) -> Dataset[dict[str, torch.Tensor]]:
    """Must yield dict(series=FloatTensor(T, C)) with T % cfg.patch_len == 0.

    Wired by the maintainer. Not implemented here.
    """
    del cfg
    raise NotImplementedError


def parse_args() -> argparse.Namespace:
    """Parse TS-JEPA pretraining arguments."""
    parser = argparse.ArgumentParser(description="Pretrain a TS-JEPA encoder.")
    parser.add_argument("--in-channels", type=int, required=True)
    parser.add_argument("--max-steps", type=int, default=JEPAConfig.max_steps)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lr", type=float, default=JEPAConfig.lr)
    parser.add_argument("--mask-ratio", type=float, default=JEPAConfig.mask_ratio)
    return parser.parse_args()


def main() -> None:
    """Run TS-JEPA pretraining and persist patcher plus context encoder weights."""
    args = parse_args()
    cfg = JEPAConfig(
        in_channels=args.in_channels,
        max_steps=args.max_steps,
        lr=args.lr,
        mask_ratio=args.mask_ratio,
    )
    dataset = build_dataset(cfg)
    dataloader = DataLoader(dataset, batch_size=32, shuffle=True)
    model = JEPALightningModule(cfg)
    trainer = L.Trainer(
        max_steps=cfg.max_steps,
        accelerator="auto",
        gradient_clip_val=None,
        log_every_n_steps=50,
    )
    trainer.fit(model, dataloader)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "patcher": model.patcher.state_dict(),
            "context_encoder": model.context_encoder.state_dict(),
        },
        args.out,
    )


if __name__ == "__main__":
    main()
