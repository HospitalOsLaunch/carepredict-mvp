#!/usr/bin/env python3
"""Generate preregistered Gate 1-B hard-case evaluation indexes."""

from __future__ import annotations

import argparse

from loaders.eval_views import write_eval_view_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Build proxy-controlled evaluation views")
    parser.add_argument("--input", required=True, help="Real SPARCS CSV/Parquet extract")
    parser.add_argument("--proxy-audit", default="runs/serialize/proxy_audit.json")
    parser.add_argument("--out", default="runs/serialize")
    args = parser.parse_args()

    payloads = write_eval_view_artifacts(args.input, args.proxy_audit, args.out)
    sweep = payloads["threshold_sweep"]
    print("threshold | n_after | loss_rate_positive | prevalence_after | n_strata")
    for row in sweep["thresholds"]:
        print(
            f"{row['min_per_class']:>9} | {row['n_after']:>7} | "
            f"{row['loss_rate_positive']:.6f} | "
            f"{row['positive_prevalence_after']:.6f} | {row['n_strata_after']}"
        )
    print(f"min_per_class_selected={sweep['min_per_class_selected']}")
    print(f"blocking_warning={sweep['blocking_warning']}")
    for name in ("hard_case_stratified_index", "hard_case_matched_index"):
        view = payloads[name]
        print(
            f"{view['view']}: n={view['n_total_before']}->{view['n_total_after']} "
            f"classes={view['class_counts_after']} "
            f"loss_positive={view['loss_rate_positive']:.6f} "
            f"prevalence={view['positive_prevalence_after']:.6f}"
        )
    print(f"artifacts={args.out}")


if __name__ == "__main__":
    main()
