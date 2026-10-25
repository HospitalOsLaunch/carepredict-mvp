"""Launch virtual hospitals behind the normal cockpit, with an owned background clock."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import structlog
import uvicorn

from hospitalos.virtual.campus import CampusFleet
from hospitalos.virtual.config import HospitalConfig
from hospitalos.virtual.runtime import VirtualFleet
from services.api.virtual_app import create_app


def main() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--clock-rate", type=float, default=1)
    parser.add_argument("--state-dir", type=Path, default=Path(".hospitalos-campus"))
    parser.add_argument("--config", type=Path, help="liste JSON de configurations développeur")
    args = parser.parse_args()
    if not 0 <= args.seed <= 1_000_000_000:
        parser.error("seed must be between 0 and 1000000000")
    try:
        configs = (
            tuple(HospitalConfig.model_validate(c) for c in json.loads(args.config.read_text()))
            if args.config
            else None
        )
        if configs is None and args.clock_rate != 1:
            raise ValueError("product_clock_rate_must_be_one")
        fleet = (
            CampusFleet(args.state_dir, args.seed)
            if configs is None
            else VirtualFleet(args.state_dir, args.seed, args.clock_rate, configs)
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    uvicorn.run(create_app(fleet), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
