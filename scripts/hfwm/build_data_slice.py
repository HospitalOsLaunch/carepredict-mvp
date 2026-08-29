"""Build and export the deterministic HFWM-R0 point-in-time data slice."""

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
    """Parse the single bounded export destination."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/hfwm-r0/data-slice"),
        help="directory receiving the four deterministic JSON artifacts",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build once, export, and print only the content identity summary."""

    from hfwm.data_slice import build_point_in_time_data_slice

    args = parse_args(argv)
    result = build_point_in_time_data_slice()
    paths = result.export(args.output_dir)
    print(
        json.dumps(
            {
                "dataset_hash": result.dataset_hash,
                "outputs": [path.as_posix() for path in paths],
                "row_count": result.dataset_manifest["row_count"],
                "status": "HFWM_R0_DATA_FOUNDATION_READY",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
