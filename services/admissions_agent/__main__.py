"""Command line of the agent.

python -m services.admissions_agent check          # what is configured, nothing runs
python -m services.admissions_agent once           # one cycle, then exit (cron, tests)
python -m services.admissions_agent run            # loop forever
python -m services.admissions_agent calibrate --engine open_light --trials 10
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import httpx

from services.admissions_agent.api_client import HospitalOSClient
from services.admissions_agent.browser import BrowserSession
from services.admissions_agent.calibrate import calibrate
from services.admissions_agent.config import load_settings
from services.admissions_agent.engines.openai_vlm import OpenWeightsVision
from services.admissions_agent.runner import Agent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="admissions-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("once")
    sub.add_parser("run")
    cal = sub.add_parser("calibrate")
    cal.add_argument("--engine", required=True, choices=["open_light", "open_heavy"])
    cal.add_argument("--trials", type=int, default=10)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = load_settings()
    api = HospitalOSClient(
        httpx.Client(base_url=settings.api_url, timeout=30),
        settings.api_email,
        settings.api_password,
    )

    if args.command == "check":
        agent = Agent(settings, api)
        print(
            json.dumps(
                {
                    "agent_id": settings.agent_id,
                    "portal": settings.portal_url,
                    "allowed_hosts": settings.allowed_hosts,
                    "playbook": agent.playbook.name,
                    "engines": agent.engine_reports(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "calibrate":
        endpoint = settings.engines[args.engine]
        if not endpoint.base_url or not endpoint.model:
            print(
                f"{args.engine} : renseignez {args.engine.upper()}_URL "
                f"et {args.engine.upper()}_MODEL",
                file=sys.stderr,
            )
            return 1
        engine = OpenWeightsVision(
            args.engine,
            endpoint.model,
            httpx.Client(base_url=endpoint.base_url),
            endpoint.api_key,
            endpoint.coordinates,
        )
        with BrowserSession(
            settings.portal_url, ("calibration.invalid",), settings.viewport
        ) as session:
            result = calibrate(engine, session, args.trials)
        api.calibration(
            args.engine,
            endpoint.model,
            endpoint.coordinates,
            result.hit_rate_configured,
            result.trials,
        )
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        if result.best_convention != endpoint.coordinates:
            print(
                f"Conseil : {args.engine.upper()}_COORDINATES={result.best_convention}",
                file=sys.stderr,
            )
        return 0
    agent = Agent(settings, api)
    if args.command == "once":
        print(f"{agent.cycle()} tâche(s) traitée(s)")
        return 0
    agent.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
