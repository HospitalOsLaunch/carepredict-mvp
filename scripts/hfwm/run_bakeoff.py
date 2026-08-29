"""Execute the frozen HFWM-R0 M2B bake-off and persist complete local evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hfwm.bakeoff.m2b import execute_bakeoff


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--preregistration-dir",
        type=Path,
        default=Path("docs/research/hfwm"),
    )
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = (
        "PYTHONPATH=src python scripts/hfwm/run_bakeoff.py "
        f"--repository-root {args.repository_root} "
        f"--preregistration-dir {args.preregistration_dir} "
        f"--output-dir {args.output_dir}"
    )
    result = execute_bakeoff(
        repository_root=args.repository_root,
        preregistration_dir=args.preregistration_dir,
        output_dir=args.output_dir,
        reproduction_command=command,
    )
    print(
        json.dumps(
            {
                "final_status": result["final_status"],
                "crash_count": result["crash_count"],
                "output_dir": str(args.output_dir),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
