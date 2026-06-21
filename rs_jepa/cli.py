"""Command-line entrypoint for the RS-JEPA pipeline scaffold."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from rs_jepa.config import load_config
from rs_jepa.seed import set_global_seed
from rs_jepa.splits import add_validation_splits
from rs_jepa.synthetic import SyntheticHospitalSimulator
from rs_jepa.train import run_checkpoint_probe, run_stage1_training
from rs_jepa.train_stage2 import run_stage2_training


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="train", description="RS-JEPA hospital dynamics pipeline")
    parser.add_argument("--config", type=Path, required=True, help="YAML config path")
    parser.add_argument("--stage", type=int, choices=(1, 2), required=True, help="Training stage")
    parser.add_argument("--checkpoint", type=Path, help="Load a saved encoder and run probe only")
    parser.add_argument(
        "--save-checkpoint",
        type=Path,
        help="Override encoder checkpoint output path",
    )
    parser.add_argument("--max-epochs", type=int, help="Override stage-1 max epochs")
    parser.add_argument("--steps-per-epoch", type=int, help="Override stage-1 steps per epoch")
    return parser


def apply_cli_overrides(cfg, args):
    training = cfg.training
    if args.max_epochs is not None:
        training = replace(training, max_epochs=args.max_epochs)
    if args.steps_per_epoch is not None:
        training = replace(training, steps_per_epoch=args.steps_per_epoch)
    if args.save_checkpoint is not None:
        training = replace(training, checkpoint_path=str(args.save_checkpoint))
    return replace(cfg, training=training)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    cfg = apply_cli_overrides(cfg, args)
    set_global_seed(cfg.seed, deterministic=cfg.stage1.deterministic)
    if cfg.phase.upper() != "A":
        raise NotImplementedError("Phase B loaders are intentionally scaffold-only at this gate.")
    if args.stage == 1 and args.checkpoint is not None:
        run_checkpoint_probe(args.checkpoint, log=True)
        return 0

    data = SyntheticHospitalSimulator(cfg.synthetic).generate()
    split_frame, summary = add_validation_splits(data.temporal[["site_id", "timestamp"]], cfg.split)
    counts = split_frame["split"].value_counts().to_dict()
    print("RS-JEPA Phase A scaffold")
    print(f"sites_total={cfg.synthetic.n_sites}")
    print(
        f"train_sites={len(summary.train_sites)} "
        f"cross_site_val_sites={len(summary.cross_site_val_sites)}"
    )
    print(f"temporal_holdout_start={summary.temporal_holdout_start}")
    print(f"split_counts={counts}")
    print(f"temporal_features={list(data.temporal_feature_columns)}")
    print(f"static_features={list(data.static_feature_columns)}")
    print(
        "criticality_range="
        f"({data.temporal['criticality'].min():.3f}, {data.temporal['criticality'].max():.3f})"
    )
    if args.stage == 1:
        artifacts = run_stage1_training(cfg, log=True)
        rank_trace = ",".join(f"{row['effective_rank']:.2f}" for row in artifacts.history)
        print("effective_rank_trace=" + rank_trace)
        print(
            "cross_site_probe_r2="
            f"{artifacts.probes['cross_site'].latent_r2_with_static:.3f} "
            f"without_static={artifacts.probes['cross_site'].latent_r2_without_static:.3f} "
            f"rank={artifacts.probes['cross_site'].effective_rank_with_static:.2f} "
            f"ceiling={artifacts.probes['cross_site'].ceiling_r2:.3f} "
            f"raw_baseline={artifacts.probes['cross_site'].raw_r2:.3f} "
            f"mean_baseline={artifacts.probes['cross_site'].mean_baseline_r2:.3f}"
        )
    else:
        checkpoint = args.checkpoint or Path(cfg.training.checkpoint_path)
        run_stage2_training(checkpoint, cfg, log=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
