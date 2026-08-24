"""Train the Hospital RSSM world model on synthetic SIIPS data.

The script generates a single-service synthetic SIIPS time series, derives
hourly intervention/action counts, trains the existing Dreamer-style RSSM, and
persists the three serving artifacts consumed by ``WorldModelService``:
``rssm_checkpoint.pt``, ``siips_scaler.npz``, and ``conformal_residuals.npz``.
"""

from __future__ import annotations

import argparse
import logging
import math
import random
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import numpy as np
import numpy.typing as npt
import torch
from torch import Tensor

from data.synthetic.siips_generator import (
    DEFAULT_SERVICES,
    SyntheticDataset,
    generate_dataset,
)
from services.ml.world_model.action_channels import ACTION_CHANNEL_INDEX, ACTION_CHANNELS
from services.ml.world_model.config import RewardConfig, RSSMConfig, TrainConfig
from services.ml.world_model.rssm import HospitalRSSM, RSSMState
from services.ml.world_model.train import WorldModelTrainer


class AdmissionLike(Protocol):
    """Admission timestamp contract used for action alignment."""

    @property
    def admission_time(self) -> datetime:
        """Return the admission timestamp."""


class DischargeLike(Protocol):
    """Discharge timestamp contract used for action alignment."""

    @property
    def discharge_time(self) -> datetime:
        """Return the discharge timestamp."""


class ActionDatasetLike(Protocol):
    """Minimal event dataset contract required by ``build_action_matrix``."""

    @property
    def admissions(self) -> Sequence[AdmissionLike]:
        """Return admission events."""

    @property
    def discharges(self) -> Sequence[DischargeLike]:
        """Return discharge events."""

LOGGER = logging.getLogger(__name__)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for a synthetic RSSM training run."""
    parser = argparse.ArgumentParser(
        description="Train the CarePredict Hospital RSSM on synthetic SIIPS data."
    )
    parser.add_argument("--months", type=int, default=6, help="Synthetic data months to generate.")
    parser.add_argument(
        "--end-date", type=str, default=None, help="Exclusive ISO end date for generated data."
    )
    parser.add_argument(
        "--service-index",
        type=int,
        default=0,
        help="Index into data.synthetic.siips_generator.DEFAULT_SERVICES.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    parser.add_argument("--steps", type=int, default=300, help="Number of training steps.")
    parser.add_argument("--batch-size", type=int, default=16, help="Training batch size.")
    parser.add_argument(
        "--horizon",
        type=int,
        default=24,
        help="Future imagination horizon in hourly steps.",
    )
    parser.add_argument(
        "--history-length",
        type=int,
        default=48,
        help="Observed context window length in hourly steps.",
    )
    parser.add_argument("--lr", type=float, default=3e-4, help="Adam learning rate.")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts",
        help="Directory where checkpoint, scaler, and residual artifacts are written.",
    )
    parser.add_argument(
        "--device",
        choices=("cpu", "cuda", "mps"),
        default="cpu",
        help="Torch device to use for training.",
    )
    parser.add_argument(
        "--log-every",
        type=int,
        default=10,
        help="Log scalar losses every N training steps.",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Write a PNG of loss curves to the output directory.",
    )
    parser.add_argument(
        "--use-mlflow",
        action="store_true",
        help="Log parameters, metrics, and artifacts to MLflow if available.",
    )
    return parser.parse_args(argv)


def configure_logging() -> None:
    """Configure Python logging with a compact operator-friendly format."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def select_device(device_name: str) -> torch.device:
    """Validate and return the requested torch device."""
    if device_name == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA device requested but torch.cuda.is_available() is false")
    if device_name == "mps":
        mps_backend = getattr(torch.backends, "mps", None)
        if mps_backend is None or not mps_backend.is_available():
            raise ValueError("MPS device requested but torch.backends.mps is unavailable")
    return torch.device(device_name)


def set_reproducibility(seed: int) -> None:
    """Seed torch, NumPy, and Python random for repeatable training runs."""
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def extract_siips_series(
    dataset: SyntheticDataset,
) -> tuple[list[datetime], npt.NDArray[np.float64]]:
    """Return chronologically sorted care-load timestamps and SIIPS values."""
    records = sorted(dataset.care_load, key=lambda record: record.measured_at)
    timestamps = [record.measured_at for record in records]
    siips = np.asarray([float(record.siips_score) for record in records], dtype=np.float64)
    return timestamps, siips


def hour_bucket(timestamp: datetime) -> datetime:
    """Round a timestamp down to its hour bucket."""
    return timestamp.replace(minute=0, second=0, microsecond=0)


def build_action_matrix(
    dataset: ActionDatasetLike,
    timestamps: Sequence[datetime],
    action_dim: int,
) -> npt.NDArray[np.float32]:
    """Build hourly action counts aligned with the care-load grid.

    The action order is derived from ``ACTION_CHANNELS`` and must match the
    trained RSSM checkpoint: admissions, discharges, surgeries, transfers_in,
    transfers_out. The synthetic generator exposes admission and discharge
    events directly; other components are zero-filled because they are not
    materialized as explicit event records in the current synthetic dataset.
    """
    if action_dim != len(ACTION_CHANNELS):
        raise ValueError(f"Expected RSSM action_dim={len(ACTION_CHANNELS)}, got {action_dim}")
    hour_to_index = {hour_bucket(timestamp): index for index, timestamp in enumerate(timestamps)}
    actions = np.zeros((len(timestamps), action_dim), dtype=np.float32)
    for admission in dataset.admissions:
        index = hour_to_index.get(hour_bucket(admission.admission_time))
        if index is not None:
            actions[index, ACTION_CHANNEL_INDEX["admissions"]] += np.float32(1.0)
    for discharge in dataset.discharges:
        index = hour_to_index.get(hour_bucket(discharge.discharge_time))
        if index is not None:
            actions[index, ACTION_CHANNEL_INDEX["discharges"]] += np.float32(1.0)
    return actions


def save_scaler(output_dir: Path, mean: float, std: float) -> Path:
    """Persist SIIPS normalization parameters in the format used by serving."""
    output_dir.mkdir(parents=True, exist_ok=True)
    scaler_path = output_dir / "siips_scaler.npz"
    np.savez(
        scaler_path,
        mean=np.asarray(mean, dtype=np.float64),
        std=np.asarray(std, dtype=np.float64),
    )
    return scaler_path


def sample_batch(
    *,
    normalized_siips: npt.NDArray[np.float64],
    actions: npt.NDArray[np.float32],
    batch_size: int,
    history_length: int,
    horizon: int,
    device: torch.device,
    rng: np.random.Generator,
) -> dict[str, Tensor]:
    """Sample valid contiguous RSSM training windows as float32 tensors."""
    series_length = int(normalized_siips.shape[0])
    max_start_exclusive = series_length - history_length - horizon
    if max_start_exclusive <= 0:
        raise ValueError("Series is too short for the requested history and horizon")
    starts = rng.integers(0, max_start_exclusive, size=batch_size)
    history_obs_np = np.stack(
        [normalized_siips[start : start + history_length] for start in starts],
        axis=0,
    )
    history_actions_np = np.stack(
        [actions[start : start + history_length] for start in starts],
        axis=0,
    )
    future_actions_np = np.stack(
        [actions[start + history_length : start + history_length + horizon] for start in starts],
        axis=0,
    )
    future_targets_np = np.stack(
        [
            normalized_siips[start + history_length : start + history_length + horizon]
            for start in starts
        ],
        axis=0,
    )
    return {
        "history_obs": torch.tensor(
            history_obs_np[:, :, None],
            dtype=torch.float32,
            device=device,
        ),
        "history_actions": torch.tensor(
            history_actions_np,
            dtype=torch.float32,
            device=device,
        ),
        "future_actions": torch.tensor(
            future_actions_np,
            dtype=torch.float32,
            device=device,
        ),
        "future_siips_targets": torch.tensor(
            future_targets_np[:, :, None],
            dtype=torch.float32,
            device=device,
        ),
    }


def validate_losses(losses: dict[str, float], step: int) -> None:
    """Raise immediately if a loss component becomes NaN or Inf."""
    for name, value in losses.items():
        if not math.isfinite(value):
            raise RuntimeError(f"Non-finite loss at step {step}: {name}={value}")


def checkpoint_payload(
    *,
    model: HospitalRSSM,
    rssm_config: RSSMConfig,
    train_config: TrainConfig,
    reward_config: RewardConfig,
    steps: int,
    mean: float,
    std: float,
    p75: float,
    p90: float,
) -> dict[str, object]:
    """Create a primitive checkpoint payload compatible with torch weights-only load."""
    rssm_config_dict = asdict(rssm_config)
    return {
        "model_state_dict": model.state_dict(),
        "rssm_config": rssm_config_dict,
        "config": rssm_config_dict,
        "train_config": asdict(train_config),
        "reward_config": asdict(reward_config),
        "step": int(steps),
        "siips_mean": float(mean),
        "siips_std": float(std),
        "p75": float(p75),
        "p90": float(p90),
        "model_version": "rssm-synthetic-v1",
    }


def save_checkpoint(
    *,
    output_dir: Path,
    model: HospitalRSSM,
    rssm_config: RSSMConfig,
    train_config: TrainConfig,
    reward_config: RewardConfig,
    steps: int,
    mean: float,
    std: float,
    p75: float,
    p90: float,
) -> Path:
    """Save model weights and primitive metadata to ``rssm_checkpoint.pt``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "rssm_checkpoint.pt"
    torch.save(
        checkpoint_payload(
            model=model,
            rssm_config=rssm_config,
            train_config=train_config,
            reward_config=reward_config,
            steps=steps,
            mean=mean,
            std=std,
            p75=p75,
            p90=p90,
        ),
        checkpoint_path,
    )
    if not checkpoint_path.exists() or checkpoint_path.stat().st_size <= 0:
        raise RuntimeError(f"Checkpoint was not created: {checkpoint_path}")
    return checkpoint_path


@torch.inference_mode()
def rollout_residuals_for_start(
    *,
    model: HospitalRSSM,
    normalized_siips: npt.NDArray[np.float64],
    raw_siips: npt.NDArray[np.float64],
    actions: npt.NDArray[np.float32],
    start: int,
    history_length: int,
    horizon: int,
    mean: float,
    std: float,
    device: torch.device,
) -> npt.NDArray[np.float64]:
    """Compute absolute denormalized residuals for one held-out future window."""
    history_obs = torch.tensor(
        normalized_siips[start : start + history_length].reshape(1, history_length, 1),
        dtype=torch.float32,
        device=device,
    )
    history_actions = torch.tensor(
        actions[start : start + history_length].reshape(1, history_length, actions.shape[1]),
        dtype=torch.float32,
        device=device,
    )
    future_actions = torch.tensor(
        actions[start + history_length : start + history_length + horizon],
        dtype=torch.float32,
        device=device,
    )
    states, _priors, _posteriors = model.observe_sequence(history_obs, history_actions)
    if not states["h"] or not states["z"]:
        raise ValueError("Observed history did not produce an RSSM state")
    state: RSSMState = {"h": states["h"][-1], "z": states["z"][-1]}
    predictions: list[float] = []
    for step_index in range(horizon):
        state, _prior = model.imagine_step(
            state,
            future_actions[step_index : step_index + 1],
        )
        normalized_pred, _reward_pred = model.decode(state)
        pred_value = float(normalized_pred.reshape(-1)[0].detach().cpu().item()) * std + mean
        predictions.append(pred_value)
    truth = raw_siips[start + history_length : start + history_length + horizon]
    return cast(
        npt.NDArray[np.float64],
        np.abs(truth - np.asarray(predictions, dtype=np.float64)).astype(np.float64),
    )


def save_conformal_residuals(
    *,
    output_dir: Path,
    model: HospitalRSSM,
    normalized_siips: npt.NDArray[np.float64],
    raw_siips: npt.NDArray[np.float64],
    actions: npt.NDArray[np.float32],
    history_length: int,
    horizon: int,
    mean: float,
    std: float,
    p95: float,
    device: torch.device,
) -> Path:
    """Generate and persist split-conformal residual matrices for serving."""
    output_dir.mkdir(parents=True, exist_ok=True)
    residual_path = output_dir / "conformal_residuals.npz"
    model.eval()
    series_length = int(raw_siips.shape[0])
    max_start_exclusive = series_length - history_length - horizon
    if max_start_exclusive <= 0:
        raise ValueError("Series is too short to calibrate conformal residuals")
    tail_start = max(0, int(max_start_exclusive * 0.9))
    candidate_starts = np.arange(tail_start, max_start_exclusive, dtype=np.int64)
    if candidate_starts.size == 0:
        candidate_starts = np.arange(0, max_start_exclusive, dtype=np.int64)
    if candidate_starts.size < 50:
        repeats = int(np.ceil(50 / max(float(candidate_starts.size), 1.0)))
        candidate_starts = np.tile(candidate_starts, repeats)[:50]
    residual_columns = [
        rollout_residuals_for_start(
            model=model,
            normalized_siips=normalized_siips,
            raw_siips=raw_siips,
            actions=actions,
            start=int(start),
            history_length=history_length,
            horizon=horizon,
            mean=mean,
            std=std,
            device=device,
        )
        for start in candidate_starts
    ]
    residuals_per_step = np.stack(residual_columns, axis=1).astype(np.float64)
    np.savez(
        residual_path,
        residuals_per_step=residuals_per_step,
        residuals=residuals_per_step.T,
        service_p95_threshold=np.asarray(p95, dtype=np.float64),
    )
    return residual_path


def maybe_log_mlflow(
    *,
    enabled: bool,
    args: argparse.Namespace,
    history: Sequence[dict[str, float]],
    artifact_paths: Sequence[Path],
) -> None:
    """Log run metadata to MLflow when requested and available."""
    if not enabled:
        return
    try:
        import mlflow
    except ImportError:
        LOGGER.warning("mlflow not available, skipping logging")
        return
    try:
        mlflow.set_experiment("rssm_synthetic")
        with mlflow.start_run():
            mlflow.log_params(
                {
                    "months": int(args.months),
                    "service_index": int(args.service_index),
                    "seed": int(args.seed),
                    "steps": int(args.steps),
                    "batch_size": int(args.batch_size),
                    "horizon": int(args.horizon),
                    "history_length": int(args.history_length),
                    "lr": float(args.lr),
                    "device": str(args.device),
                }
            )
            for record in history:
                step = int(record["step"])
                mlflow.log_metrics(
                    {key: value for key, value in record.items() if key != "step"},
                    step=step,
                )
            for path in artifact_paths:
                mlflow.log_artifact(str(path))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("mlflow logging failed, continuing", exc_info=exc)


def maybe_plot_losses(
    *,
    enabled: bool,
    output_dir: Path,
    history: Sequence[dict[str, float]],
) -> Path | None:
    """Optionally render training loss curves to a PNG file."""
    if not enabled:
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    plot_path = output_dir / "training_curves.png"
    steps = [int(record["step"]) for record in history]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for axis, key, title in zip(
        axes,
        ("total_loss", "reconstruction_loss", "kl_loss"),
        ("Total loss", "Reconstruction loss", "KL loss"),
        strict=True,
    ):
        axis.plot(steps, [float(record[key]) for record in history])
        axis.set_title(title)
        axis.set_xlabel("step")
    fig.tight_layout()
    fig.savefig(plot_path)
    plt.close(fig)
    return plot_path


def build_training_dataset(
    args: argparse.Namespace,
) -> tuple[SyntheticDataset, list[datetime], npt.NDArray[np.float64]]:
    """Generate synthetic data and validate there is enough hourly history."""
    if not 0 <= int(args.service_index) < len(DEFAULT_SERVICES):
        raise ValueError(
            f"service-index must be between 0 and {len(DEFAULT_SERVICES) - 1}, "
            f"got {args.service_index}"
        )
    end_date = (
        datetime.fromisoformat(str(args.end_date)).replace(tzinfo=UTC)
        if args.end_date is not None
        else None
    )
    dataset = generate_dataset(
        months=int(args.months),
        services=[DEFAULT_SERVICES[int(args.service_index)]],
        seed=int(args.seed),
        end=end_date,
    )
    timestamps, siips = extract_siips_series(dataset)
    if end_date is not None:
        # generate_dataset uses whole days from start to exclusive end, so the last hour is < end.
        if not timestamps[-1] < end_date:
            raise AssertionError("last generated care_load timestamp must be before --end-date")
        LOGGER.info(
            "rssm_synthetic_end_date_exclusive end_date=%s last_hour=%s", end_date, timestamps[-1]
        )
    minimum_length = int(args.history_length) + int(args.horizon) + 100
    if siips.shape[0] < minimum_length:
        raise ValueError(
            "Synthetic SIIPS series is too short: "
            f"got {siips.shape[0]}, need at least {minimum_length}"
        )
    return dataset, timestamps, siips


def log_step_metrics(step: int, losses: dict[str, float]) -> None:
    """Log the core scalar loss components for a training step."""
    LOGGER.info(
        "rssm_train_step step=%s total_loss=%.6f recon_loss=%.6f kl_loss=%.6f reward_loss=%.6f",
        step,
        float(losses.get("total_loss", 0.0)),
        float(losses.get("reconstruction_loss", 0.0)),
        float(losses.get("kl_loss", 0.0)),
        float(losses.get("reward_loss", 0.0)),
    )


def print_summary(
    *,
    args: argparse.Namespace,
    history: Sequence[dict[str, float]],
    kl_collapsed: bool,
    checkpoint_path: Path,
    scaler_path: Path,
    residual_path: Path,
) -> None:
    """Print the final operator summary block."""
    print("======================================")
    print("RSSM Training Complete")
    print("======================================")
    print(f"Steps:          {int(args.steps)}")
    print(f"Final loss:     {history[-1]['loss']:.4f}")
    print(f"KL collapsed:   {kl_collapsed}")
    print("Artifacts:")
    print(f"  - {checkpoint_path}")
    print(f"  - {scaler_path}")
    print(f"  - {residual_path}")
    print("======================================")


def main(args: argparse.Namespace) -> list[dict[str, float]]:
    """Run synthetic RSSM training and return per-step scalar history."""
    configure_logging()
    device = select_device(str(args.device))
    set_reproducibility(int(args.seed))
    LOGGER.info("rssm_synthetic_training_start device=%s seed=%s", device, args.seed)

    output_dir = Path(str(args.output_dir))
    dataset, timestamps, siips = build_training_dataset(args)
    rssm_config = RSSMConfig()
    actions = build_action_matrix(dataset, timestamps, action_dim=rssm_config.action_dim)

    mean = float(np.mean(siips))
    std = float(np.std(siips) + 1e-8)
    normalized_siips = ((siips - mean) / std).astype(np.float64)
    scaler_path = save_scaler(output_dir, mean=mean, std=std)

    train_config = replace(
        TrainConfig(),
        lr=float(args.lr),
        imagination_horizon=int(args.horizon),
        batch_size=int(args.batch_size),
        seed=int(args.seed),
    )
    p75 = float(np.quantile(siips, 0.75))
    p90 = float(np.quantile(siips, 0.90))
    p95 = float(np.quantile(siips, 0.95))
    reward_config = RewardConfig(p75=p75, p90=p90)
    model = HospitalRSSM(config=rssm_config).to(device=device)
    trainer = WorldModelTrainer(
        model=model,
        train_config=train_config,
        reward_config=reward_config,
        device=device,
    )
    rng = np.random.default_rng(int(args.seed))
    history: list[dict[str, float]] = []
    kl_collapsed = False
    for step_index in range(int(args.steps)):
        step = step_index + 1
        batch = sample_batch(
            normalized_siips=normalized_siips,
            actions=actions,
            batch_size=int(args.batch_size),
            history_length=int(args.history_length),
            horizon=int(args.horizon),
            device=device,
            rng=rng,
        )
        losses = trainer.train_step(batch)
        validate_losses(losses, step=step)
        record = {"step": float(step), "loss": float(losses["total_loss"]), **losses}
        history.append(record)
        if int(args.log_every) > 0 and (step == 1 or step % int(args.log_every) == 0):
            log_step_metrics(step, losses)
        if step == 50:
            recent_kl = [float(item.get("kl_loss", 0.0)) for item in history[-30:]]
            kl_collapsed = bool(recent_kl and all(value < 1e-4 for value in recent_kl))
            if kl_collapsed:
                LOGGER.warning("kl_collapse_detected_consider_disabling_stochastic_latent")

    checkpoint_path = save_checkpoint(
        output_dir=output_dir,
        model=model,
        rssm_config=rssm_config,
        train_config=train_config,
        reward_config=reward_config,
        steps=int(args.steps),
        mean=mean,
        std=std,
        p75=p75,
        p90=p90,
    )
    residual_path = save_conformal_residuals(
        output_dir=output_dir,
        model=model,
        normalized_siips=normalized_siips,
        raw_siips=siips,
        actions=actions,
        history_length=int(args.history_length),
        horizon=int(args.horizon),
        mean=mean,
        std=std,
        p95=p95,
        device=device,
    )
    artifact_paths = [checkpoint_path, scaler_path, residual_path]
    plot_path = maybe_plot_losses(enabled=bool(args.plot), output_dir=output_dir, history=history)
    if plot_path is not None:
        artifact_paths.append(plot_path)
    maybe_log_mlflow(
        enabled=bool(args.use_mlflow),
        args=args,
        history=history,
        artifact_paths=artifact_paths,
    )
    print_summary(
        args=args,
        history=history,
        kl_collapsed=kl_collapsed,
        checkpoint_path=checkpoint_path,
        scaler_path=scaler_path,
        residual_path=residual_path,
    )
    return history


if __name__ == "__main__":
    main(parse_args())
