"""Run the local dynamic cockpit with ?source=simulator; no hospital connector."""

from __future__ import annotations

import argparse

import uvicorn

from hospitalos.simulator.session import DemoSession
from services.api.simulator_app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    if not 0 <= args.seed <= 1_000_000_000:
        parser.error("seed must be between 0 and 1000000000")
    session = DemoSession(args.seed)
    try:
        uvicorn.run(create_app(session), host="127.0.0.1", port=args.port)
    finally:
        session.close()


if __name__ == "__main__":
    main()
