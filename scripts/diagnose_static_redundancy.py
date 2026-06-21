#!/usr/bin/env python3
"""Attribution brute static/dynamic pour expliquer l'ablation static RS-JEPA.

Le diagnostic ne charge aucun encodeur et n'entraîne aucun world model. Il teste
si les covariables statiques ajoutent de l'information linéaire au-dessus des
canaux dynamiques déjà normalisés par site.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np

from rs_jepa.config import load_config
from rs_jepa.probe import fit_linear_predict, r2_score
from rs_jepa.splits import CROSS_SITE_VAL, TEMPORAL_VAL, TRAIN
from rs_jepa.train import PhaseASite, build_phase_a_sites


def _parse_seeds(raw: str) -> list[int]:
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _cfg_for_seed(args: argparse.Namespace, seed: int):
    cfg = load_config(args.config)
    split = replace(cfg.split, seed=seed)
    synthetic = replace(cfg.synthetic, seed=seed)
    return replace(cfg, seed=seed, split=split, synthetic=synthetic)


def _stack_rows(
    sites: list[PhaseASite],
    split: str,
    *,
    include_dynamic: bool,
    include_static: bool,
) -> tuple[np.ndarray, np.ndarray]:
    features = []
    targets = []
    for site in sites:
        rows = np.where(site.split == split)[0]
        if len(rows) == 0:
            continue
        blocks = []
        if include_dynamic:
            blocks.append(site.features[rows])
        if include_static:
            static = np.repeat(site.static[None, :], len(rows), axis=0)
            blocks.append(static)
        if not blocks:
            raise ValueError("Au moins un bloc de features doit être activé.")
        features.append(np.concatenate(blocks, axis=1))
        targets.append(site.criticality[rows])
    if not targets:
        raise ValueError(f"Aucune ligne pour split={split}.")
    return np.concatenate(features, axis=0), np.concatenate(targets, axis=0)


def _eval_variant(
    train_sites: list[PhaseASite],
    eval_sites: list[PhaseASite],
    eval_split: str,
    *,
    include_dynamic: bool,
    include_static: bool,
) -> float:
    x_train, y_train = _stack_rows(
        train_sites,
        TRAIN,
        include_dynamic=include_dynamic,
        include_static=include_static,
    )
    x_eval, y_eval = _stack_rows(
        eval_sites,
        eval_split,
        include_dynamic=include_dynamic,
        include_static=include_static,
    )
    pred = fit_linear_predict(x_train, y_train, x_eval)
    return float(r2_score(y_eval, pred))


def _eval_split(
    seed: int,
    split_name: str,
    train_sites: list[PhaseASite],
    eval_sites: list[PhaseASite],
    eval_split: str,
) -> dict[str, float | int | str]:
    static_only = _eval_variant(
        train_sites,
        eval_sites,
        eval_split,
        include_dynamic=False,
        include_static=True,
    )
    dyn_only = _eval_variant(
        train_sites,
        eval_sites,
        eval_split,
        include_dynamic=True,
        include_static=False,
    )
    dyn_static = _eval_variant(
        train_sites,
        eval_sites,
        eval_split,
        include_dynamic=True,
        include_static=True,
    )
    return {
        "seed": seed,
        "split": split_name,
        "static_only": static_only,
        "dyn_only": dyn_only,
        "dyn_static": dyn_static,
        "incremental_static": dyn_static - dyn_only,
    }


def _print_table(rows: list[dict[str, float | int | str]]) -> None:
    print("seed | split | R2_static_only | R2_dyn_only | R2_dyn+static | incremental_static")
    print("---: | :---- | -------------: | ----------: | ------------: | -----------------:")
    for row in rows:
        print(
            f"{int(row['seed'])} | {row['split']} | "
            f"{float(row['static_only']):+.3f} | "
            f"{float(row['dyn_only']):+.3f} | "
            f"{float(row['dyn_static']):+.3f} | "
            f"{float(row['incremental_static']):+.3f}"
        )


def _summary(rows: list[dict[str, float | int | str]]) -> None:
    print("\nSummary means")
    for split in ("cross_site", "temporal"):
        split_rows = [row for row in rows if row["split"] == split]
        inc = np.asarray([float(row["incremental_static"]) for row in split_rows])
        static_only = np.asarray([float(row["static_only"]) for row in split_rows])
        dyn_only = np.asarray([float(row["dyn_only"]) for row in split_rows])
        dyn_static = np.asarray([float(row["dyn_static"]) for row in split_rows])
        print(
            f"{split}: static_only={static_only.mean():+.3f} "
            f"dyn_only={dyn_only.mean():+.3f} dyn+static={dyn_static.mean():+.3f} "
            f"incremental_mean={inc.mean():+.3f} min={inc.min():+.3f} max={inc.max():+.3f}"
        )

    all_inc = np.asarray([float(row["incremental_static"]) for row in rows])
    if float(all_inc.max()) <= 0.01:
        print(
            "\nVERDICT: REDUNDANT (cause B): dynamic channels already carry the site "
            "structure; static covariates add ~0 or negative linear value."
        )
    elif float(all_inc.mean()) > 0.02:
        print(
            "\nVERDICT: ENCODER-FUSION-BUG (cause A): raw static covariates add "
            "information, but the encoder probe loses it."
        )
    else:
        print(
            "\nVERDICT: MIXED / BORDERLINE: static adds only a small raw-feature "
            "increment; inspect before changing encoder.py."
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/phaseA.yaml"))
    parser.add_argument("--seeds", default="0,1,2,3,4")
    args = parser.parse_args()

    rows: list[dict[str, float | int | str]] = []
    for seed in _parse_seeds(args.seeds):
        cfg = _cfg_for_seed(args, seed)
        _sites, train_sites, cross_site_sites = build_phase_a_sites(cfg)
        rows.append(
            _eval_split(
                seed,
                "cross_site",
                train_sites,
                cross_site_sites,
                CROSS_SITE_VAL,
            )
        )
        rows.append(
            _eval_split(
                seed,
                "temporal",
                train_sites,
                train_sites,
                TEMPORAL_VAL,
            )
        )

    _print_table(rows)
    _summary(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
