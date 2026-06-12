"""TimescaleDB-backed TS-JEPA smoke run over canonical hospital data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import lightning as L
import numpy as np
import torch
from lightning.pytorch.loggers import CSVLogger
from torch.utils.data import DataLoader

from hospitalos.data.timescale_adapter import TimescaleDatasetConfig, build_timescale_dataset
from hospitalos.encoders.ts_jepa.config import JEPAConfig
from hospitalos.encoders.ts_jepa.jepa_module import JEPALightningModule
from hospitalos.training.smoke_jepa import compute_final_probes, evaluate_metrics


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse Timescale smoke-run arguments."""
    parser = argparse.ArgumentParser(description="Run a canonical Timescale TS-JEPA smoke train.")
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--train-end", type=str, default="2025-07-01")
    parser.add_argument("--patch-len", type=int, default=JEPAConfig.patch_len)
    parser.add_argument("--out", type=Path, default=Path("runs/smoke_timescale"))
    return parser.parse_args(argv)


def main() -> int:
    """Run the Timescale-backed JEPA smoke training loop."""
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    train_dataset = build_timescale_dataset(
        TimescaleDatasetConfig(split="train", train_end=args.train_end)
    )
    val_dataset = build_timescale_dataset(
        TimescaleDatasetConfig(split="val", train_end=args.train_end)
    )
    generator = torch.Generator().manual_seed(args.seed)
    train_loader = DataLoader(
        train_dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=0,
        generator=generator,
    )
    val_loader = DataLoader(
        val_dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
    )

    sample = train_dataset[0]["series"]
    cfg = JEPAConfig(
        in_channels=int(sample.shape[1]),
        patch_len=int(args.patch_len),
        max_steps=args.steps,
        probe_every_n_steps=50,
    )
    model = JEPALightningModule(cfg)
    logger = CSVLogger(save_dir=str(args.out), name="lightning_logs")
    trainer = L.Trainer(
        max_steps=args.steps,
        logger=logger,
        enable_checkpointing=False,
        accelerator="auto",
        log_every_n_steps=10,
        check_val_every_n_epoch=None,
        val_check_interval=50,
        num_sanity_val_steps=0,
    )
    trainer.fit(model, train_loader, val_loader)

    args.out.mkdir(parents=True, exist_ok=True)
    encoder_path = args.out / "encoder_smoke_timescale.pt"
    torch.save(
        {
            "patcher": model.patcher.state_dict(),
            "context_encoder": model.context_encoder.state_dict(),
        },
        encoder_path,
    )

    probe_metrics = compute_final_probes(model, train_loader)
    verdict = evaluate_metrics(Path(logger.log_dir) / "metrics.csv", probe_metrics)
    print_verdict(
        verdict=verdict,
        encoder_path=encoder_path,
        n_windows_train=len(train_dataset),
        n_windows_val=len(val_dataset),
        n_rejected_windows=train_dataset.n_rejected_windows + val_dataset.n_rejected_windows,
    )
    return 0 if verdict["pass"] else 1


def print_verdict(
    *,
    verdict: dict[str, object],
    encoder_path: Path,
    n_windows_train: int,
    n_windows_val: int,
    n_rejected_windows: int,
) -> None:
    """Print a human-readable Timescale smoke verdict block."""
    status = "SMOKE PASS" if verdict["pass"] else "SMOKE FAIL"
    reasons = verdict["reasons"]
    print("======================================")
    print(status if verdict["pass"] else f"{status} {reasons}")
    print("======================================")
    print(f"n_windows_train:   {n_windows_train}")
    print(f"n_windows_val:     {n_windows_val}")
    print(f"n_rejected_windows:{n_rejected_windows}")
    print(f"first_decile_loss: {verdict['first_loss']}")
    print(f"last_decile_loss:  {verdict['last_loss']}")
    print(f"final_val_loss:    {verdict['final_val_loss']}")
    print(f"final_emb_std:     {verdict['final_emb_std']}")
    print(f"final_offdiag:     {verdict['final_offdiag']}")
    print(f"encoder_path:      {encoder_path}")
    print("======================================")


if __name__ == "__main__":
    sys.exit(main())
