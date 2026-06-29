#!/usr/bin/env python3
"""Generate the model-free age/diagnosis proxy audit for Gate 1-B."""

from __future__ import annotations

import argparse

from loaders.proxy_audit import write_proxy_audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit obvious SPARCS target proxies")
    parser.add_argument("--input", required=True, help="Real SPARCS CSV/Parquet extract")
    parser.add_argument("--out", default="runs/serialize")
    args = parser.parse_args()

    audit = write_proxy_audit(args.input, args.out)
    age = audit["age_proxy"]
    print(f"source_rows={audit['source_rows']}")
    print(f"baseline_prevalence={audit['baseline_prevalence']:.6f}")
    print(f"aval_rate_70_plus={age['seventy_plus']['aval_rate']:.6f}")
    print(f"aval_rate_other_ages={age['other_ages']['aval_rate']:.6f}")
    print(f"top10_drg_positive_share={audit['top10_drg_positive_share']:.6f}")
    print(f"drg_rule_auprc_floor={audit['drg_rule_auprc_floor']:.6f}")
    print(f"artifacts={args.out}")


if __name__ == "__main__":
    main()
