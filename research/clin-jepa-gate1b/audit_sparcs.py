#!/usr/bin/env python3
"""CLI for the SPARCS Gate 1-B mapping and feature audit."""

from __future__ import annotations

import argparse
import logging

from loaders.sparcs_adapter import write_audit_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit SPARCS 2024 mapping and feature leakage")
    parser.add_argument("--input", required=True, help="Real SPARCS feature CSV/Parquet extract")
    parser.add_argument(
        "--disposition-input",
        help="Optional exhaustive disposition-only CSV/Parquet used for population audit",
    )
    parser.add_argument("--out", default="runs/sparcs_adapter")
    parser.add_argument(
        "--include-apr",
        action="store_true",
        help="Exploratory ablation: include APR Severity and APR Risk of Mortality",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    result = write_audit_artifacts(
        source_path=args.input,
        disposition_path=args.disposition_input,
        output_dir=args.out,
        include_apr=args.include_apr,
    )
    mapping = result["mapping_audit"]
    distribution = result["class_distribution"]
    print(f"unmapped_count={mapping['unmapped_count']}")
    print(f"unmapped_rate={mapping['unmapped_rate']:.6f}")
    print(f"mapping_decision={mapping['decision']}")
    print(f"aval_institu_rate={distribution['aval_institu_rate']:.6f}")
    print(f"baseline_auprc_prevalence={distribution['baseline_auprc_prevalence']:.6f}")
    print(f"feature_configuration={result['feature_audit']['active_configuration']}")
    print(f"artifacts={args.out}")


if __name__ == "__main__":
    main()
