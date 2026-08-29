"""Train and measure the single bounded HFWM-R0 M1B candidate."""

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/hfwm/r0_m1b_minimal.yaml"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/hfwm-r0/backbone"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from hfwm.candidate import MinimalCandidateConfig, train_minimal_candidate

    args = parse_args(argv)
    config_path = args.config.resolve(strict=True)
    config = MinimalCandidateConfig.load(config_path)
    result = train_minimal_candidate(
        config,
        repository_root=REPOSITORY_ROOT,
        config_path=config_path,
    )
    paths = result.export(args.output_dir)
    test_teacher = result.metrics["teacher_forcing"]
    test_rollout = result.metrics["free_running"]
    assert isinstance(test_teacher, dict) and isinstance(test_rollout, dict)
    print(
        json.dumps(
            {
                "free_running_test": test_rollout["test"],
                "model_hash": result.model_hash,
                "outputs": [path.as_posix() for path in paths],
                "status": "HFWM_R0_BACKBONE_READY_FOR_REVIEW",
                "teacher_forcing_test": test_teacher["test"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
