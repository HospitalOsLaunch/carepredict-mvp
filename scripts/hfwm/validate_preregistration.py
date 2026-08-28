"""Validate the frozen HFWM-R0 preregistration without producing artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse validation-only CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path("docs/research/hfwm"),
        help="directory containing the frozen preregistration",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Validate and print a deterministic JSON result to stdout."""
    from hfwm.evaluation.preregistration import validate_preregistration

    args = parse_args(argv)
    result = validate_preregistration(args.directory)
    print(
        json.dumps(
            {
                "valid": result.valid,
                "main_runs_authorized": result.main_runs_authorized,
                "errors": result.errors,
                "manifest": result.manifest,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if result.valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
