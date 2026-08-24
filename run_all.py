"""Exécution courte : ingestion → quantile → CQR."""

from __future__ import annotations

import argparse

from carepredict_cqr import run_pipeline


def main() -> None:
    """Lance le pipeline complet et affiche le tableau de couverture."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--synthetic", action="store_true", help="utiliser le générateur hors-ligne"
    )
    parser.add_argument("--dep", nargs="*", default=None, help="codes départements à garder")
    parser.add_argument("--surge-weight", type=float, default=12.0)
    args = parser.parse_args()
    report = run_pipeline(synthetic=args.synthetic, deps=args.dep, surge_weight=args.surge_weight)
    print("\n[run_all] tableau final")
    print(report.to_string(index=False, float_format=lambda x: f"{x:.3f}"))


if __name__ == "__main__":
    main()
