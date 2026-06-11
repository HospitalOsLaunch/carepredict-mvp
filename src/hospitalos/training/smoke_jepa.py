"""Synthetic-only TS-JEPA smoke run."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import lightning as L
import numpy as np
import torch
from lightning.pytorch.loggers import CSVLogger
from torch.utils.data import DataLoader

from hospitalos.data.synthetic_adapter import SyntheticDatasetConfig, build_synthetic_dataset
from hospitalos.encoders.ts_jepa.config import JEPAConfig
from hospitalos.encoders.ts_jepa.jepa_module import JEPALightningModule
from hospitalos.encoders.ts_jepa.probes import embedding_std, mean_offdiag_corr


def parse_args() -> argparse.Namespace:
    """Parse smoke-run arguments."""
    parser = argparse.ArgumentParser(description="Run a synthetic TS-JEPA smoke train.")
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-days", type=int, default=60)
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--out", type=Path, default=Path("runs/smoke"))
    return parser.parse_args()


def main() -> int:
    """Run the synthetic-only JEPA smoke training loop."""
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    dataset = build_synthetic_dataset(
        SyntheticDatasetConfig(n_days=args.n_days, window_days=args.window_days, seed=args.seed)
    )
    generator = torch.Generator().manual_seed(args.seed)
    dataloader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=0,
        generator=generator,
    )
    sample = dataset[0]["series"]
    cfg = JEPAConfig(
        in_channels=int(sample.shape[1]),
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
    )
    trainer.fit(model, dataloader)
    args.out.mkdir(parents=True, exist_ok=True)
    encoder_path = args.out / "encoder_smoke.pt"
    torch.save(
        {
            "patcher": model.patcher.state_dict(),
            "context_encoder": model.context_encoder.state_dict(),
        },
        encoder_path,
    )
    probe_metrics = compute_final_probes(model, dataloader)
    verdict = evaluate_metrics(Path(logger.log_dir) / "metrics.csv", probe_metrics)
    print_verdict(verdict, encoder_path)
    return 0 if verdict["pass"] else 1


def compute_final_probes(
    model: JEPALightningModule,
    dataloader: DataLoader[dict[str, torch.Tensor]],
) -> dict[str, float]:
    """Compute final anti-collapse probes directly from the trained target encoder."""
    batch = next(iter(dataloader))
    device = next(model.parameters()).device
    series = batch["series"].to(device=device, dtype=torch.float32)
    with torch.inference_mode():
        tokens = model.patcher(series)
        pos_idx = torch.arange(tokens.shape[1], device=device, dtype=torch.long)
        embeddings = model.target_encoder(tokens, pos_idx)
    return {
        "probe/emb_std": embedding_std(embeddings.detach().cpu()),
        "probe/offdiag_corr": mean_offdiag_corr(embeddings.detach().cpu()),
    }


def evaluate_metrics(metrics_path: Path, probe_metrics: dict[str, float]) -> dict[str, object]:
    """Read CSVLogger metrics and compute smoke verdict criteria."""
    rows = read_metrics(metrics_path)
    losses = metric_values(rows, ("jepa/loss", "jepa/loss_step", "jepa/loss_epoch"))
    emb_std = metric_values(rows, ("probe/emb_std",))
    offdiag = metric_values(rows, ("probe/offdiag_corr",))
    if not emb_std:
        emb_std = [probe_metrics["probe/emb_std"]]
    if not offdiag:
        offdiag = [probe_metrics["probe/offdiag_corr"]]
    reasons: list[str] = []
    loss_pass = False
    if len(losses) >= 10:
        decile = max(1, len(losses) // 10)
        first = float(np.mean(losses[:decile]))
        last = float(np.mean(losses[-decile:]))
        loss_pass = last < 0.7 * first
        if not loss_pass:
            reasons.append(f"loss criterion not met: first={first:.6f} last={last:.6f}")
    else:
        first = float(losses[0]) if losses else float("nan")
        last = float(losses[-1]) if losses else float("nan")
        reasons.append("not enough loss points")

    final_emb = float(emb_std[-1]) if emb_std else float("nan")
    emb_pass = bool(emb_std and final_emb > 0.1)
    if not emb_pass:
        reasons.append(f"embedding std criterion not met: final={final_emb}")

    final_offdiag = float(offdiag[-1]) if offdiag else float("nan")
    offdiag_pass = bool(offdiag and final_offdiag < 0.5 and not is_monotone_increasing(offdiag[len(offdiag) // 2 :]))
    if not offdiag_pass:
        reasons.append(f"offdiag criterion not met: final={final_offdiag}")

    return {
        "pass": loss_pass and emb_pass and offdiag_pass,
        "first_loss": first,
        "last_loss": last,
        "final_emb_std": final_emb,
        "final_offdiag": final_offdiag,
        "reasons": reasons,
    }


def metric_values(rows: list[dict[str, float | None]], names: tuple[str, ...]) -> list[float]:
    """Extract finite metric values from any of several Lightning CSV column names."""
    values: list[float] = []
    for row in rows:
        for name in names:
            value = row.get(name)
            if value is not None and np.isfinite(value):
                values.append(float(value))
                break
    return values


def read_metrics(metrics_path: Path) -> list[dict[str, float | None]]:
    """Read metric rows from a Lightning CSVLogger metrics file."""
    with metrics_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, float | None]] = []
        for row in reader:
            parsed: dict[str, float | None] = {}
            for key, value in row.items():
                if value == "" or value is None:
                    parsed[key] = None
                else:
                    parsed[key] = float(value)
            rows.append(parsed)
        return rows


def is_monotone_increasing(values: list[float]) -> bool:
    """Return whether values are monotonically non-decreasing."""
    if len(values) < 3:
        return False
    return all(right >= left for left, right in zip(values, values[1:], strict=False))


def print_verdict(verdict: dict[str, object], encoder_path: Path) -> None:
    """Print a human-readable smoke verdict block."""
    status = "SMOKE PASS" if verdict["pass"] else "SMOKE FAIL"
    reasons = verdict["reasons"]
    print("======================================")
    print(status if verdict["pass"] else f"{status} {reasons}")
    print("======================================")
    print(f"first_decile_loss: {verdict['first_loss']}")
    print(f"last_decile_loss:  {verdict['last_loss']}")
    print(f"final_emb_std:     {verdict['final_emb_std']}")
    print(f"final_offdiag:     {verdict['final_offdiag']}")
    print(f"encoder_path:      {encoder_path}")
    print("======================================")


if __name__ == "__main__":
    sys.exit(main())
