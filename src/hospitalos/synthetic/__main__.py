"""Run with python -m hospitalos.synthetic --config ... --output ... ."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from .config import HospitalConfig, load_config, validate_partition_isolation
from .generate import generate


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic hospital: shared multi-pole simulation")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int, help="Override recorded days for a quick run")
    parser.add_argument(
        "--check-cohort",
        type=Path,
        nargs="*",
        default=[],
        help="Other configs to check for hospital overlap across partitions",
    )
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.days is not None:
            config = HospitalConfig.model_validate({**config.model_dump(), "days": args.days})
        validate_partition_isolation([config, *(load_config(path) for path in args.check_cohort)])
        manifest = generate(config, args.output)
    except (ValueError, ValidationError, FileExistsError, RuntimeError) as exc:
        parser.exit(1, f"Generation failed: {exc}\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "counts": manifest["counts"],
                "checks": manifest["checks"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
