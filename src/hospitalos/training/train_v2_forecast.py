"""Train the v2 direct SIIPS forecast head on canonical Timescale windows."""

from __future__ import annotations

import argparse
import json
import random
import subprocess
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import lightning as L
import numpy as np
import torch
from lightning.pytorch.loggers import CSVLogger
from torch import Tensor
from torch.utils.data import DataLoader, Dataset

from hospitalos.data.timescale_adapter import TimescaleDatasetConfig, TimescaleHospitalDataset
from hospitalos.dynamics.jepa_rssm import JepaRSSM, RSSMConfig, calendar_encoding, symexp
from hospitalos.encoders.ts_jepa.encoder import TransformerEncoder
from hospitalos.encoders.ts_jepa.patcher import Patchifier

DEFAULT_ENCODER_CKPT = Path("runs/jepa_pretrain_long/encoder_smoke_timescale.pt")
DEFAULT_OUT = Path("artifacts/v2_forecast")
CALIBRATION_FRAC = 0.1
DEFAULT_BATCH_SIZE = 8
DEFAULT_NUM_WORKERS = 0


class CalendarWindowDataset(Dataset[dict[str, Tensor]]):
    """Dataset wrapper adding per-hour calendar encodings to Timescale windows."""

    def __init__(self, base: TimescaleHospitalDataset, indices: list[int]) -> None:
        """Create a deterministic subset over Timescale windows."""
        self.base = base
        self.indices = list(indices)

    def __len__(self) -> int:
        """Return subset length."""
        return len(self.indices)

    def __getitem__(self, index: int) -> dict[str, Tensor]:
        """Return one window with series, SIIPS target, and calendar features."""
        base_index = self.indices[index]
        item = self.base[base_index]
        length = int(item["series"].shape[0])
        return {
            "series": item["series"],
            "siips": item["siips"],
            "calendar": build_calendar_features(self.base.window_starts[base_index], length),
        }


class FrozenForecastModel:
    """Minimal forecasting protocol for calibration without mutating model state."""

    def __init__(self, model: JepaRSSM) -> None:
        """Wrap a trained JepaRSSM."""
        self.model = model

    @torch.inference_mode()
    def predict_window(self, batch: dict[str, Tensor]) -> Tensor:
        """Return raw-space forecasts with shape [B, valid_origins, horizon]."""
        device = next(self.model.parameters()).device
        series = batch["series"].to(device=device, dtype=torch.float32)
        calendar = batch["calendar"].to(device=device, dtype=torch.float32)
        z = self.model.encode_series(series)
        states = self.model.unroll(z)
        return symexp(self.model.forecast(states, calendar)).detach().cpu()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse v2 forecast training arguments."""
    parser = argparse.ArgumentParser(description="Train v2 direct RSSM SIIPS forecast head.")
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--train-end", type=str, default="2025-07-01")
    parser.add_argument("--services", type=str, default="urg-001")
    parser.add_argument("--encoder-ckpt", type=Path, default=DEFAULT_ENCODER_CKPT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    """Run v2 forecast-head training, calibration, and artifact persistence."""
    args = parse_args(argv)
    set_seeds(int(args.seed))
    services = parse_services(str(args.services))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    train_base = TimescaleHospitalDataset(
        TimescaleDatasetConfig(split="train", train_end=str(args.train_end), services=services)
    )
    train_indices, calibration_indices = split_train_calibration_indices(
        train_base.window_starts,
        cal_frac=CALIBRATION_FRAC,
    )
    if not train_indices or not calibration_indices:
        raise ValueError("training and calibration subsets must both be non-empty")
    train_dataset = CalendarWindowDataset(train_base, train_indices)
    calibration_dataset = CalendarWindowDataset(train_base, calibration_indices)

    sample = train_dataset[0]["series"]
    patcher, encoder, emb_dim, encoder_meta = load_frozen_encoder(
        Path(args.encoder_ckpt),
        in_channels=int(sample.shape[1]),
    )
    if int(encoder_meta["patch_len"]) != 24:
        raise ValueError("v2 forecast training requires a daily JEPA checkpoint with patch_len=24")
    cfg = RSSMConfig(emb_dim=emb_dim, forecast_horizon=48)
    model = JepaRSSM(cfg, encoder, patcher)

    generator = torch.Generator().manual_seed(int(args.seed))
    train_loader = DataLoader(
        train_dataset,
        batch_size=DEFAULT_BATCH_SIZE,
        shuffle=True,
        num_workers=DEFAULT_NUM_WORKERS,
        generator=generator,
    )
    logger = CSVLogger(save_dir=str(out_dir), name="lightning_logs")
    trainer = L.Trainer(
        max_steps=int(args.steps),
        accelerator="auto",
        logger=logger,
        enable_checkpointing=False,
        log_every_n_steps=10,
        gradient_clip_val=cfg.grad_clip,
        gradient_clip_algorithm="norm",
    )
    trainer.fit(model, train_loader)

    calibration_loader = DataLoader(
        calibration_dataset,
        batch_size=DEFAULT_BATCH_SIZE,
        shuffle=False,
        num_workers=DEFAULT_NUM_WORKERS,
    )
    conformal_path = save_conformal_quantiles(
        out_dir / "conformal_q.npz",
        FrozenForecastModel(model.eval()),
        calibration_loader,
        horizon=cfg.forecast_horizon,
    )
    checkpoint_path = save_checkpoint(
        out_dir / "checkpoint.pt",
        model=model,
        cfg=cfg,
        encoder_ckpt=Path(args.encoder_ckpt),
        patcher=patcher,
        encoder=encoder,
    )
    train_config = build_train_config(
        args=args,
        services=services,
        train_base=train_base,
        train_indices=train_indices,
        calibration_indices=calibration_indices,
        encoder_meta=encoder_meta,
        cfg=cfg,
    )
    config_path = out_dir / "train_config.json"
    config_path.write_text(
        json.dumps(train_config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "checkpoint": str(checkpoint_path),
        "conformal_q": str(conformal_path),
        "train_config": str(config_path),
        "final_metrics": final_metrics(logger.log_dir),
        "n_train_windows": len(train_indices),
        "n_calibration_windows": len(calibration_indices),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def set_seeds(seed: int) -> None:
    """Seed Python, NumPy, and Torch."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def parse_services(value: str) -> list[str]:
    """Parse comma-separated service ids."""
    services = [part.strip() for part in value.split(",") if part.strip()]
    if not services:
        raise ValueError("--services must contain at least one service id")
    return services


def split_train_calibration_indices(
    window_starts: list[datetime],
    *,
    cal_frac: float,
) -> tuple[list[int], list[int]]:
    """Split windows by date, reserving the last fraction for calibration."""
    if not 0.0 < cal_frac < 1.0:
        raise ValueError("cal_frac must be in (0, 1)")
    ordered = sorted(range(len(window_starts)), key=lambda index: window_starts[index])
    n_calibration = max(1, int(np.ceil(len(ordered) * cal_frac)))
    if len(ordered) <= n_calibration:
        raise ValueError("not enough windows to reserve a calibration slice")
    return ordered[:-n_calibration], ordered[-n_calibration:]


def build_calendar_features(start: datetime, length: int) -> Tensor:
    """Build [sin,cos] hour-of-day and day-of-week features for each hour."""
    hours: list[int] = []
    days: list[int] = []
    for offset in range(length):
        current = start + timedelta(hours=offset)
        hours.append(current.hour)
        days.append(current.weekday())
    return calendar_encoding(
        torch.tensor(hours, dtype=torch.float32),
        torch.tensor(days, dtype=torch.float32),
    )


def load_frozen_encoder(
    encoder_ckpt: Path,
    *,
    in_channels: int,
) -> tuple[Patchifier, TransformerEncoder, int, dict[str, int]]:
    """Load a frozen JEPA patcher and context encoder from checkpoint."""
    payload: dict[str, Any] = torch.load(encoder_ckpt, map_location="cpu", weights_only=True)
    patcher_state = payload["patcher"]
    encoder_state = payload["context_encoder"]
    patch_weight = patcher_state["proj.weight"]
    emb_dim = int(patch_weight.shape[0])
    patch_input_dim = int(patch_weight.shape[1])
    if patch_input_dim % in_channels != 0:
        raise ValueError("patcher input dimension is not divisible by the Timescale channel count")
    patch_len = patch_input_dim // in_channels
    depth = infer_transformer_depth(encoder_state)
    patcher = Patchifier(in_channels=in_channels, patch_len=patch_len, emb_dim=emb_dim)
    encoder = TransformerEncoder(emb_dim=emb_dim, depth=depth)
    patcher.load_state_dict(patcher_state)
    encoder.load_state_dict(encoder_state)
    patcher.eval().requires_grad_(False)
    encoder.eval().requires_grad_(False)
    return patcher, encoder, emb_dim, {"patch_len": patch_len, "emb_dim": emb_dim, "depth": depth}


def infer_transformer_depth(state: dict[str, Tensor]) -> int:
    """Infer transformer depth from block-indexed state-dict keys."""
    block_ids = {
        int(key.split(".")[1])
        for key in state
        if key.startswith("blocks.") and key.split(".")[1].isdigit()
    }
    if not block_ids:
        raise ValueError("context encoder checkpoint contains no transformer blocks")
    return max(block_ids) + 1


def save_conformal_quantiles(
    path: Path,
    forecaster: FrozenForecastModel,
    dataloader: DataLoader[dict[str, Tensor]],
    *,
    horizon: int,
) -> Path:
    """Save per-horizon one-sided raw-space 90% residual quantiles."""
    lower_residuals: list[list[float]] = [[] for _ in range(horizon)]
    upper_residuals: list[list[float]] = [[] for _ in range(horizon)]
    for batch in dataloader:
        pred = forecaster.predict_window(batch).numpy()
        truth = batch["siips"].numpy()
        origin_start = horizon
        valid_origins = pred.shape[1]
        for origin_offset in range(valid_origins):
            origin = origin_start + origin_offset
            for step in range(horizon):
                target = float(truth[:, origin + step + 1][0]) if truth.shape[0] == 1 else None
                if target is not None:
                    predicted = float(pred[0, origin_offset, step])
                    lower_residuals[step].append(max(predicted - target, 0.0))
                    upper_residuals[step].append(max(target - predicted, 0.0))
                else:
                    for batch_index in range(truth.shape[0]):
                        predicted = float(pred[batch_index, origin_offset, step])
                        target_value = float(truth[batch_index, origin + step + 1])
                        lower_residuals[step].append(max(predicted - target_value, 0.0))
                        upper_residuals[step].append(max(target_value - predicted, 0.0))
    q90_lo = np.asarray([np.quantile(values, 0.9) for values in lower_residuals], dtype=np.float64)
    q90_hi = np.asarray([np.quantile(values, 0.9) for values in upper_residuals], dtype=np.float64)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, q90_lo=q90_lo, q90_hi=q90_hi)
    return path


def save_checkpoint(
    path: Path,
    *,
    model: JepaRSSM,
    cfg: RSSMConfig,
    encoder_ckpt: Path,
    patcher: Patchifier,
    encoder: TransformerEncoder,
) -> Path:
    """Persist v2 model and frozen encoder metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "rssm_config": asdict(cfg),
            "encoder_ckpt": str(encoder_ckpt),
            "patcher_state_dict": patcher.state_dict(),
            "context_encoder_state_dict": encoder.state_dict(),
        },
        path,
    )
    return path


def build_train_config(
    *,
    args: argparse.Namespace,
    services: list[str],
    train_base: TimescaleHospitalDataset,
    train_indices: list[int],
    calibration_indices: list[int],
    encoder_meta: dict[str, int],
    cfg: RSSMConfig,
) -> dict[str, Any]:
    """Build the persisted v2 train config JSON payload."""
    return {
        "args": {
            "steps": int(args.steps),
            "train_end": str(args.train_end),
            "services": str(args.services),
            "encoder_ckpt": str(args.encoder_ckpt),
            "out": str(args.out),
            "seed": int(args.seed),
        },
        "dataset": {
            "services": services,
            "n_total_train_split_windows": len(train_base),
            "n_train_windows": len(train_indices),
            "n_calibration_windows": len(calibration_indices),
            "n_rejected_windows": train_base.n_rejected_windows,
            "calibration_frac": CALIBRATION_FRAC,
            "train_window_start_min": train_base.window_starts[train_indices[0]].isoformat(),
            "train_window_start_max": train_base.window_starts[train_indices[-1]].isoformat(),
            "calibration_window_start_min": train_base.window_starts[
                calibration_indices[0]
            ].isoformat(),
            "calibration_window_start_max": train_base.window_starts[
                calibration_indices[-1]
            ].isoformat(),
        },
        "encoder": {**encoder_meta, "checkpoint_sha256": sha256_file(Path(args.encoder_ckpt))},
        "granularity": "daily_patch_24",
        "design_decision": "F4_option_B",
        "rssm_config": asdict(cfg),
        "git_hash": git_hash(),
        "training_constants": {
            "batch_size": DEFAULT_BATCH_SIZE,
            "num_workers": DEFAULT_NUM_WORKERS,
        },
    }


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for a file."""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_hash() -> str:
    """Return the current git commit hash, or unknown outside git."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return "unknown"
    return result.stdout.strip()


def final_metrics(log_dir: str) -> dict[str, float]:
    """Read final Lightning CSV metrics if available."""
    metrics_path = Path(log_dir) / "metrics.csv"
    if not metrics_path.exists():
        return {}
    import csv

    final: dict[str, float] = {}
    with metrics_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            for key, value in row.items():
                if value not in {None, ""}:
                    final[key] = float(value)
    return final


if __name__ == "__main__":
    main()
