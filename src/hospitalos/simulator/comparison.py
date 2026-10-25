"""Paired, isolated episodes. Policies see declarations; scoring sees completed journals."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt

from hospitalos.hybrid.live_models import PlanningOptions
from hospitalos.hybrid.simulation import Assumptions
from hospitalos.operational.contract import Closed

from .engine import START, TruthEvent, indexed_duration
from .evaluation import Evaluation, evaluate
from .session import CommandReceipt, DecisionRequest, DemoSession

CADENCE_SECONDS = 300
Policy = Literal["accept", "refuse", "disabled"]


class ComparisonRequest(Closed):
    seed: Annotated[StrictInt, Field(ge=0, le=2**31 - 1)] = 7
    horizon_minutes: Annotated[StrictInt, Field(ge=1, le=180)] = 180
    policy: Policy = "accept"


class DecisionTrace(Closed):
    second: float
    snapshot_fingerprint: str
    plan_id: str | None
    decision: str
    action: str | None
    bed_id: str | None
    patient_id: str | None
    reasons: tuple[str, ...]
    request_id: str | None


class EpisodeResult(Closed):
    evaluation: Evaluation
    installed_during_episode: int
    solicitation_seconds_requested: int
    decisions: tuple[DecisionTrace, ...]
    commands: tuple[CommandReceipt, ...]
    truth_journal: tuple[TruthEvent, ...]


class ComparisonManifest(Closed):
    scenario_version: str = "geriatric-three-beds-1"
    engine_version: str = "DYNAMIC_DEMO_1"
    baseline_policy: str = "observed-cleaning-bed-id-and-compatible-fifo-1"
    recommendation_policy: str = "hybrid-every-300s-from-30s-1"
    scorer_version: str = "truth-wait-integral-1"
    config: ComparisonRequest
    starts_at: datetime = START
    ends_at: datetime
    first_assessment_second: int = 30
    assessment_interval_seconds: int = CADENCE_SECONDS
    solicitation_seconds_per_command: int = 30
    planning_options: PlanningOptions
    initial_state: dict[str, Any]
    exogenous_primitives: dict[str, int]
    source_sha256: dict[str, str]
    runtime_versions: dict[str, str]


class ComparisonResult(Closed):
    schema_version: Literal["PAIRED_DEMO_1"] = "PAIRED_DEMO_1"
    comparison_id: str
    scope: Literal["fictional_scenario_only_no_effectiveness_claim"] = (
        "fictional_scenario_only_no_effectiveness_claim"
    )
    manifest: ComparisonManifest
    a0: EpisodeResult
    a1: EpisodeResult
    waiting_patient_minutes_saved: float
    waiting_patient_hours_saved: float
    physical_trajectories_identical: bool


def planning_options() -> PlanningOptions:
    # Planner hypotheses/seed are independent of realized world primitives.
    return PlanningOptions(
        horizon_minutes=120,
        scenarios=16,
        seed=7,
        assumptions=Assumptions(cleaning_minutes=(15, 20, 25), load_multipliers=(1,)),
    )


def source_hashes() -> dict[str, str]:
    """Content identities also work in downloaded archives without a Git checkout."""
    package = Path(__file__).resolve().parents[1]
    files = [package / "operational" / "contract.py"]
    for name in ("simulator", "hybrid"):
        files.extend(sorted((package / name).rglob("*.py")))
    return {
        str(path.relative_to(package)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def runtime_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        **{name: version(name) for name in ("simpy", "pydantic", "numpy", "scikit-learn")},
    }


_LOADED_SOURCE_HASHES = source_hashes()
_LOADED_RUNTIME_VERSIONS = runtime_versions()


class ComparisonEnvironmentChanged(ValueError):
    """A running process must not attribute its results to newly edited source files."""


def _check_environment() -> None:
    if source_hashes() != _LOADED_SOURCE_HASHES or runtime_versions() != _LOADED_RUNTIME_VERSIONS:
        raise ComparisonEnvironmentChanged(
            "Le code ou les dépendances ont changé : arrêter puis redémarrer la démo."
        )


def _assess(session: DemoSession, policy: Policy, index: int) -> DecisionTrace:
    offered = session.assess(planning_options())
    view = session.view()
    plan = offered.assessment.plan
    request_id = None
    if view.can_apply and plan is not None:
        request_id = f"paired-decision-{index}"
        session.decide(
            DecisionRequest(
                run_id=view.run_id,
                revision=view.revision,
                request_id=request_id,
                plan_id=plan.plan_id,
                snapshot_fingerprint=view.snapshot.semantic_fingerprint,
                accept=policy == "accept",
            )
        )
    return DecisionTrace(
        second=session.engine.second,
        snapshot_fingerprint=view.snapshot.semantic_fingerprint,
        plan_id=plan.plan_id if plan else None,
        decision=plan.decision if plan else "blocked",
        action=plan.selected.kind if plan else None,
        bed_id=plan.selected.bed_id if plan else None,
        patient_id=plan.selected.patient_id if plan else None,
        reasons=plan.reasons if plan else offered.assessment.gate_reasons,
        request_id=request_id,
    )


def _episode(config: ComparisonRequest, policy: Policy) -> EpisodeResult:
    session = DemoSession(config.seed, monotonic=lambda: 0)
    decisions: list[DecisionTrace] = []
    until = config.horizon_minutes * 60
    try:
        # Both branches have the same event ordering and observation schedule.
        # Only A1 submits recommendations; A0's built-in staff policy still runs.
        while session.engine.second < until:
            if policy != "disabled":
                decisions.append(_assess(session, policy, len(decisions)))
            session.engine.advance(min(CADENCE_SECONDS, until - session.engine.second))
        journal = tuple(session.engine.journal)
        result = evaluate(journal, until)
        return EpisodeResult(
            evaluation=result,
            installed_during_episode=sum(e.kind == "installed" for e in journal),
            solicitation_seconds_requested=30 * result.coordination_tasks,
            decisions=tuple(decisions),
            commands=tuple(session.commands.values()),
            truth_journal=journal,
        )
    finally:
        session.close()


def compare(config: ComparisonRequest) -> ComparisonResult:
    """Run from scenario origin, never from (or into) the interactive session."""
    _check_environment()
    initial = DemoSession(config.seed, monotonic=lambda: 0)
    try:
        initial_state = {
            "beds": [asdict(b) for b in initial.engine.beds.values()],
            "patients": [asdict(p) for p in initial.engine.patients.values()],
            "cleaning_teams": 1,
            "coordinators": 1,
            "observation_interval_seconds": 60,
            "observation_delivery_seconds": 30,
            "first_cleaning_dispatch_second": 120,
            "installation_seconds": 60,
        }
    finally:
        initial.close()
    a0 = _episode(config, "disabled")
    a1 = _episode(config, config.policy)
    _check_environment()
    manifest = ComparisonManifest(
        config=config,
        ends_at=START + timedelta(minutes=config.horizon_minutes),
        planning_options=planning_options(),
        initial_state=initial_state,
        exogenous_primitives={
            **{
                f"demo-world-1|{config.seed}|cleaning|{bed}|0": indexed_duration(
                    config.seed, "cleaning", bed, (900, 1200, 1500)
                )
                for bed in ("G01", "G02", "G03")
            },
            "arrival:P-G02:0:second": 600,
            "departure:P-G00:0:second": 2400,
        },
        source_sha256=dict(_LOADED_SOURCE_HASHES),
        runtime_versions=dict(_LOADED_RUNTIME_VERSIONS),
    )
    saved = a0.evaluation.waiting_patient_minutes - a1.evaluation.waiting_patient_minutes
    physical = {
        "initial_admitted",
        "initial_waiting",
        "arrived",
        "departed",
        "reserved",
        "installed",
        "cleaning_started",
        "cleaning_finished",
        "installation_failed",
    }
    result = ComparisonResult(
        comparison_id="pending",
        manifest=manifest,
        a0=a0,
        a1=a1,
        waiting_patient_minutes_saved=saved,
        waiting_patient_hours_saved=saved / 60,
        physical_trajectories_identical=tuple(e for e in a0.truth_journal if e.kind in physical)
        == tuple(e for e in a1.truth_journal if e.kind in physical),
    )
    payload = result.model_dump(mode="json", exclude={"comparison_id"})
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return result.model_copy(update={"comparison_id": digest})


def replay(exported: ComparisonResult) -> ComparisonResult:
    if exported.manifest.source_sha256 != source_hashes():
        raise ValueError("Le code diffère de l'export : utiliser la révision d'origine.")
    if exported.manifest.runtime_versions != runtime_versions():
        raise ValueError("Les versions Python ou des dépendances diffèrent de l'export.")
    result = compare(exported.manifest.config)
    if result != exported:
        raise ValueError("Le rejeu diffère de l'export : résultat ou journal non reproduit.")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Comparaison locale A0/A1, sur scénario fictif.")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--horizon-minutes", type=int)
    parser.add_argument("--policy", choices=("accept", "refuse", "disabled"))
    parser.add_argument("--replay", type=Path, help="vérifier et rejouer un export JSON complet")
    parser.add_argument("--output", type=Path, help="écrire le résultat JSON dans ce fichier")
    args = parser.parse_args(argv)
    if args.replay and any(v is not None for v in (args.seed, args.horizon_minutes, args.policy)):
        parser.error("--replay ne se combine pas avec de nouveaux paramètres")
    try:
        if args.replay:
            result = replay(ComparisonResult.model_validate_json(args.replay.read_text()))
        else:
            config = ComparisonRequest.model_validate(
                {
                    key: value
                    for key, value in vars(args).items()
                    if key in {"seed", "horizon_minutes", "policy"} and value is not None
                }
            )
            result = compare(config)
        content = result.model_dump_json(indent=2) + "\n"
        if args.output:
            args.output.write_text(content)
        else:
            print(content, end="")
    except (OSError, ValueError) as error:
        print(f"Comparaison impossible : {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
