"""Command-line entrypoint for the RS-JEPA pipeline scaffold."""

from __future__ import annotations

import argparse
from pathlib import Path

from rs_jepa.config import load_config
from rs_jepa.seed import set_global_seed
from rs_jepa.splits import add_validation_splits
from rs_jepa.synthetic import SyntheticHospitalSimulator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="train", description="RS-JEPA hospital dynamics pipeline")
    parser.add_argument("--config", type=Path, required=True, help="YAML config path")
    parser.add_argument("--stage", type=int, choices=(1, 2), required=True, help="Training stage")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    set_global_seed(cfg.seed, deterministic=cfg.stage1.deterministic)
    if cfg.phase.upper() != "A":
        raise NotImplementedError("Phase B loaders are intentionally scaffold-only at this gate.")

    data = SyntheticHospitalSimulator(cfg.synthetic).generate()
    split_frame, summary = add_validation_splits(data.temporal[["site_id", "timestamp"]], cfg.split)
    counts = split_frame["split"].value_counts().to_dict()
    print("RS-JEPA Phase A scaffold")
    print(f"sites_total={cfg.synthetic.n_sites}")
    print(f"train_sites={len(summary.train_sites)} cross_site_val_sites={len(summary.cross_site_val_sites)}")
    print(f"temporal_holdout_start={summary.temporal_holdout_start}")
    print(f"split_counts={counts}")
    print(f"temporal_features={list(data.temporal_feature_columns)}")
    print(f"static_features={list(data.static_feature_columns)}")
    print(
        "criticality_range="
        f"({data.temporal['criticality'].min():.3f}, {data.temporal['criticality'].max():.3f})"
    )
    if args.stage == 1:
        print("Stage 1 model/training begins at gate 3; steps 1-2 scaffold validated.")
    else:
        print("Stage 2 heads are scaffolded conceptually and train only after the Stage-1 gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
