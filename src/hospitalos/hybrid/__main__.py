"""Run a plan from a JSON request or inspect the fictional demonstrator."""

from __future__ import annotations

import argparse
from pathlib import Path

from .demo import demo_request
from .planning import PlanRequest, plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true")
    source.add_argument("--request", type=Path)
    parser.add_argument("--show-input", action="store_true")
    args = parser.parse_args()
    request = (
        demo_request() if args.demo else PlanRequest.model_validate_json(args.request.read_text())
    )
    result = request if args.show_input else plan(request)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
