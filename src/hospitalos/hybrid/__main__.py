"""Run a plan from a JSON request or inspect the fictional demonstrator."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .demo import demo_request, future_request, pathway_request
from .models import Action
from .planning import PlanRequest, plan
from .scenarios import sample_future
from .scoring import score
from .simulation import simulate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true")
    source.add_argument("--demo-pathway", action="store_true")
    source.add_argument("--demo-future", action="store_true")
    source.add_argument("--demo-learned", action="store_true")
    source.add_argument("--request", type=Path)
    parser.add_argument("--show-input", action="store_true")
    parser.add_argument(
        "--show-trace",
        action="store_true",
        help="Include paired scenario 0 logs and independent scores",
    )
    args = parser.parse_args()
    if args.demo_learned:
        from .learning_demo import learned_request

        learned = learned_request()
    request = (
        learned
        if args.demo_learned
        else demo_request()
        if args.demo
        else pathway_request()
        if args.demo_pathway
        else future_request()
        if args.demo_future
        else PlanRequest.model_validate_json(args.request.read_text())
    )
    if args.show_trace and not args.show_input:
        proposal = plan(request)
        traces = {}
        external_events = []
        if proposal.decision != "abstain":
            state = request.state()
            future = sample_future(state, request.future, request.seed, 0)
            external_events = [e.model_dump(mode="json") for e in future.events]
            for name, action in (
                ("baseline", Action(kind="no_op")),
                ("selected", proposal.selected),
            ):
                trace = simulate(
                    state,
                    action,
                    request.assumptions,
                    seed=request.seed,
                    scenario=0,
                    horizon_minutes=request.horizon_minutes,
                    future=future,
                    preparation=request.preparation,
                )
                traces[name] = {
                    "trajectory": asdict(trace),
                    "score": asdict(score(state, trace, expected_future=future)),
                }
        print(
            json.dumps(
                {
                    "plan": proposal.model_dump(mode="json"),
                    "external_events_scenario_0": external_events,
                    "paired_scenario_0": traces,
                },
                indent=2,
            )
        )
        return
    result = request if args.show_input else plan(request)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
