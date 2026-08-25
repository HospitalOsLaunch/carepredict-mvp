#!/usr/bin/env python3
"""Diagnostique l'honnêteté du simulateur Phase A RS-JEPA."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_jepa.config import load_config  # noqa: E402 - import after local path bootstrap
from rs_jepa.diagnostics import (  # noqa: E402 - import after local path bootstrap
    run_diagnostic_for_seed,
    summarize_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnostic multi-seed du simulateur Phase A.")
    parser.add_argument("--config", default="configs/phaseA.yaml")
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    parser.add_argument("--ridge-alpha", type=float, default=1.0)
    parser.add_argument("--mae-cap", type=float, default=0.15)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    rows = [
        run_diagnostic_for_seed(
            cfg, seed, ridge_alpha=args.ridge_alpha, mae_cap=args.mae_cap, log=print
        )
        for seed in args.seeds
    ]

    print("\n=== SUMMARY ===")
    print(
        "seed | T1_median | T1_frac>0.3 | T2_|Delta kappa| | T3a_mean | hidden | "
        "bulk% | T3b_naive | T3b_cond | gain | STRUCT_ratio | low-site tags | PASS"
    )
    for row in rows:
        flags = (
            f"T1={'PASS' if row['t1_pass'] else 'FAIL'},"
            f"T2={'PASS' if row['t2_pass'] else 'FAIL'},"
            f"T3a={'PASS' if row['t3a_pass'] else 'FAIL'},"
            f"T3b={'PASS' if row['t3b_pass'] else 'FAIL'}"
        )
        print(
            f"{int(row['seed']):>4} | {row['t1_median']:.3f}     | {row['t1_frac']:.2f}         | "
            f"{row['t2']:.3f}   | {row['t3a_mean_r2']:.3f}    | {row['hidden_share']:.3f} | "
            f"{row['t3a_bulk_fraction']:.2f} | {row['t3b_naive_r2']:.3f} | "
            f"{row['t3b_cond_r2']:.3f} | {row['t3b_gain']:.3f} | {row['struct_ratio']:.3f} | "
            f"flat={int(row['flat_count'])},hole={int(row['hole_count'])} | {flags}"
        )

    print("\n=== GAIN vs STRUCT ===")
    for row in sorted(rows, key=lambda item: item["struct_ratio"]):
        print(
            f"seed={int(row['seed'])} STRUCT={row['struct_ratio']:.3f} "
            f"gain={row['t3b_gain']:.3f} naive={row['t3b_naive_r2']:.3f} "
            f"cond={row['t3b_cond_r2']:.3f}"
        )

    summary = summarize_rows(rows)
    print("\n=== STOP CRITERIA ===")
    for name, value in summary.items():
        if isinstance(value, bool) and name != "all_gates":
            print(f"[{'PASS' if value else 'FAIL'}] {name}")
    if summary["min_t3b_gain"] > 0.15:
        print("[T3b RESULT] static conditioning recovers OOD transfer")
    else:
        print(
            "[T3b RESULT] static conditioning insufficient for cold-start on moderate-OOD sites; "
            "dynamic (warm-mode) information likely required."
        )
    final = "BENCH HONEST & STABLE" if summary["all_gates"] else "GATES STILL UNSTABLE"
    print(f"\n[FINAL] {final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
