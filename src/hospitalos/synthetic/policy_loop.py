"""Synthetic policy environment: reset, observe, act, advance; never operates a real SI."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import StrictBool, model_validator

from .asof import AsOfCursor, AsOfRow, replay
from .cohort import _runtime, _sha, _write
from .config import FrozenConfig, HospitalConfig, load_config
from .engine import _HS, _RUN, SimulationResult, advance_checked, build_simulation
from .generate import _jsonl, export_result, source_hashes, timestamp
from .observations import Count
from .online import OnlineSnapshots
from .policy import (
    LEVER_NAMES,
    NoRecommendationPolicy,
    ObservedRulePolicy,
    Policy,
    PolicyContext,
    PolicyDescriptor,
    PolicySite,
    Probability,
    RecommendationBatch,
    SiteUnit,
)


class DecisionRecord(FrozenConfig):
    decision_id: str
    hospital_id: str
    pole_id: str
    unit_id: str
    decision_h: Count
    context_sha256: str
    descriptor: PolicyDescriptor
    lever: Literal[
        "anticipation_sorties", "lits_supplementaires", "renfort_soignant", "acceleration_aval"
    ]
    recommendation_probability: Probability
    recommendation_vector_probability: Probability
    recommended: StrictBool
    exposure_probability: Probability
    exposed: StrictBool
    approval: Literal["approved", "rejected", "not_presented", "not_recommended"]
    action_origin: Literal["approved_recommendation", "cadre_initiative", "none"]
    requested: StrictBool
    execution: Literal["not_requested", "applied", "partially_applied", "failed", "not_applicable"]
    reason: str
    affected_count: Count
    affected_unit: Literal["patient_plans", "beds_activated", "staff_shifts_confirmed"]
    confirmed_shift_starts_h: tuple[int, ...] = ()
    response_h: Count

    @model_validator(mode="after")
    def chain(self) -> Self:
        presented = self.recommended and self.exposed
        expected_approval = (
            ("approved" if self.requested else "rejected")
            if presented
            else ("not_presented" if self.recommended else "not_recommended")
        )
        expected_origin = (
            ("approved_recommendation" if presented else "cadre_initiative")
            if self.requested
            else "none"
        )
        if self.approval != expected_approval or self.action_origin != expected_origin:
            raise ValueError("Recommendation/approval/action chain is inconsistent")
        if self.response_h != self.decision_h:
            raise ValueError("This synthetic gateway responds synchronously")
        if not self.requested and (self.execution != "not_requested" or self.affected_count):
            raise ValueError("An unrequested action cannot execute")
        if self.requested and self.execution == "not_requested":
            raise ValueError("Missing execution result")
        if (self.execution in ("applied", "partially_applied")) != (self.affected_count > 0):
            raise ValueError("Execution status disagrees with affected count")
        expected_unit = {
            "renfort_soignant": "staff_shifts_confirmed",
            "lits_supplementaires": "beds_activated",
        }.get(self.lever, "patient_plans")
        if self.affected_unit != expected_unit:
            raise ValueError("Execution count has the wrong unit")
        if self.lever == "renfort_soignant":
            if (
                len(self.confirmed_shift_starts_h) != self.affected_count
                or self.affected_count > 2
                or len(set(self.confirmed_shift_starts_h)) != self.affected_count
                or any(h <= self.decision_h for h in self.confirmed_shift_starts_h)
            ):
                raise ValueError("Invalid reinforcement confirmations")
            expected = (
                "not_requested"
                if not self.requested
                else (
                    "failed"
                    if not self.affected_count
                    else "partially_applied"
                    if self.affected_count == 1
                    else "applied"
                )
            )
            if self.execution != expected:
                raise ValueError("Reinforcement result is inconsistent")
        elif self.confirmed_shift_starts_h or self.execution in ("failed", "partially_applied"):
            raise ValueError("Unexpected staffing execution fields")
        return self


def execute_lever(sim: Any, state: Any, unit: int, lever: int, hour: int) -> dict[str, Any]:
    """Privileged gateway applies an approved/initiated request, not the recommendation."""
    slots = (3 * (hour // 24) + 2, 3 * (hour // 24 + 1) + 1) if lever == 2 else ()
    before = {sid: state.renfort.get((unit, sid), 0) for sid in slots}
    affected = int(sim.appliquer(state, unit, lever, hour))
    confirmed = tuple(
        ((sid - 1) // 3) * 24 + (7 if (sid - 1) % 3 == 0 else 15) - sim.h0_rec
        for sid in slots
        if state.renfort.get((unit, sid), 0) > before[sid]
    )
    if lever == 2:
        status = "applied" if affected == 2 else "partially_applied" if affected else "failed"
        reason = "shifts_confirmed" if affected == 2 else "staffing_not_fully_filled"
        count_unit = "staff_shifts_confirmed"
    else:
        status = "applied" if affected else "not_applicable"
        reason = (
            "plan_or_capacity_changed"
            if affected
            else ("extra_beds_already_active" if lever == 1 else "no_eligible_plan_changed")
        )
        count_unit = "beds_activated" if lever == 1 else "patient_plans"
    return {
        "execution": status,
        "reason": reason,
        "affected_count": affected,
        "affected_unit": count_unit,
        "confirmed_shift_starts_h": confirmed,
    }


class PolicyEnvironment:
    """Trusted host; a plugin receives PolicySite/PolicyContext only, never this object."""

    def __init__(
        self, config: HospitalConfig, descriptor: PolicyDescriptor, *, stale_after_h: float = 6.0
    ):
        if config.partition == "test":
            raise ValueError("Policy development cannot open the reserved test partition")
        if not 0 < stale_after_h < math.inf:
            raise ValueError("Invalid staleness threshold")
        self.config, self.descriptor, self.stale_after_h = config, descriptor, stale_after_h
        self.run_id = hashlib.sha256(
            json.dumps(
                {
                    "config": config.fingerprint,
                    "policy": descriptor.model_dump(),
                    "stale_after_h": stale_after_h,
                    "source": source_hashes(),
                    "runtime": _runtime(),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()[:24]
        self.site = PolicySite(
            hospital_id=config.hospital_id,
            start=config.start,
            units=tuple(
                SiteUnit(
                    unit_id=u.unit_id, pole_id=config.unit_poles[u.unit_id], specialty=u.template
                )
                for u in config.units
            ),
        )
        self._context: PolicyContext | None = None
        self._initialized = False

    def reset(self) -> PolicyContext:
        self.sim = build_simulation(self.config)
        self.state = _HS.State(self.sim.x)
        self.journal = _RUN.Journal(self.sim)
        self.stream = OnlineSnapshots(self.config, self.sim.x)
        self.cursor = AsOfCursor(self.config, run_id=self.run_id, stale_after_h=self.stale_after_h)
        self.checks: Counter[str] = Counter()
        self.resources: list[dict[str, Any]] = []
        self.resource_pools: list[dict[str, Any]] = []
        self.features: list[AsOfRow] = []
        self.contexts: list[PolicyContext] = []
        self.batches: list[RecommendationBatch] = []
        self.ledger: list[DecisionRecord] = []
        self.human_audit: list[dict[str, Any]] = []
        self._acted_at = -1
        self._last_batch: RecommendationBatch | None = None
        self._last_records: tuple[DecisionRecord, ...] = ()
        # Common inherited warm-up. The external policy starts at recorded boundary zero.
        for h in range(self.sim.h0_rec):
            self._step(h, inherited_policy=True)
        self.hour = 0
        self._initialized = True
        self._context = self._snapshot()
        return self._context

    def _step(self, absolute_h: int, *, inherited_policy: bool) -> None:
        resource, pools = advance_checked(
            self.sim, self.state, absolute_h, self.journal, self.checks, politique=inherited_policy
        )
        self.stream.push(absolute_h, self.journal.etats[-len(self.config.units) :])
        if absolute_h >= self.sim.h0_rec:
            self.resources.append(resource)
            self.resource_pools.extend(pools)

    def _snapshot(self) -> PolicyContext:
        rows = self.cursor.advance(self.hour, self.stream.receive(self.hour))
        self.features.extend(rows)
        return PolicyContext(
            decision_h=self.hour, timestamp=timestamp(self.config, self.hour), observations=rows
        )

    def observe(self) -> PolicyContext | None:
        if not self._initialized:
            raise ValueError("Reset the environment first")
        return self._context

    def act(self, batch: RecommendationBatch) -> tuple[DecisionRecord, ...]:
        context = self.observe()
        # Revalidate even objects made using model_copy/model_construct by a Python plugin.
        batch = RecommendationBatch.model_validate_json(batch.model_dump_json())
        if context is None or self.hour % 24 != 9:
            raise ValueError("Recommendations are accepted only at a live 09:00 boundary")
        if (
            batch.decision_h != self.hour
            or batch.context_sha256 != context.fingerprint
            or batch.descriptor != self.descriptor
        ):
            raise ValueError("Stale context or policy version mismatch")
        names = [r.unit_id for r in batch.units]
        if len(names) != len(set(names)) or set(names) != set(self.config.unit_poles):
            raise ValueError("Recommendation batch must cover each unit exactly once")
        if self._acted_at == self.hour:
            if batch == self._last_batch:
                return self._last_records  # Exact retry: no repeated staffing or capacity change.
            raise ValueError("A different decision is already committed at this boundary")
        # All plugin output is validated before any simulation mutation.
        by_unit = {r.unit_id: r for r in batch.units}
        absolute_h = self.hour + self.sim.h0_rec
        day = absolute_h // 24
        records = []
        for u, unit in enumerate(self.config.units):
            recommendation = by_unit[unit.unit_id]
            q = recommendation.probabilities
            rec = [int(self.sim.x.u_reco[u, day, k] < q[k]) for k in range(4)]
            exposed = bool(self.sim.x.u_expo[u, day] < _HS.P["p_exposition"])
            # Cadre remains a distinct actor with its own private current information.
            f = self.sim.caracteristiques(self.state, u, absolute_h)
            z = float(self.sim.x.z_cache[u, day])
            pa = self.sim.proba_action(f, z, rec, exposed)
            acts = [int(self.sim.x.u_politique[u, day, k] < pa[k]) for k in range(4)]
            results = [
                execute_lever(self.sim, self.state, u, k, absolute_h)
                if acts[k]
                else {
                    "execution": "not_requested",
                    "reason": "cadre_did_not_request",
                    "affected_count": 0,
                    "affected_unit": (
                        "staff_shifts_confirmed"
                        if k == 2
                        else "beds_activated"
                        if k == 1
                        else "patient_plans"
                    ),
                    "confirmed_shift_starts_h": (),
                }
                for k in range(4)
            ]
            counts = [r["affected_count"] for r in results]
            self.state.derniere[u] = (tuple(rec), int(exposed), tuple(acts), tuple(counts))
            self.journal.action(absolute_h, u, f, q, rec, int(exposed), pa, z, acts, counts)
            self.journal.event(
                absolute_h,
                "RECOMMANDATION",
                u,
                None,
                exposee=exposed,
                **dict(zip(LEVER_NAMES, rec, strict=True)),
            )
            self.journal.event(
                absolute_h, "DECISION", u, None, **dict(zip(LEVER_NAMES, acts, strict=True))
            )
            self.human_audit.append(
                {
                    "decision_h": self.hour,
                    "unit_id": unit.unit_id,
                    "actor_version": "legacy_cadre_v1",
                    "private_current_state": f,
                    "hidden_z": z,
                    "conditional_action_probabilities": pa,
                }
            )
            joint_q = math.prod(p if chosen else 1 - p for p, chosen in zip(q, rec, strict=True))
            for k, lever in enumerate(LEVER_NAMES):
                presented, requested = bool(rec[k] and exposed), bool(acts[k])
                record = DecisionRecord.model_validate(
                    {
                        "decision_id": f"{self.run_id}:{unit.unit_id}@{self.hour}:{lever}",
                        "hospital_id": self.config.hospital_id,
                        "pole_id": self.config.unit_poles[unit.unit_id],
                        "unit_id": unit.unit_id,
                        "decision_h": self.hour,
                        "context_sha256": context.fingerprint,
                        "descriptor": self.descriptor,
                        "lever": lever,
                        "recommendation_probability": q[k],
                        "recommendation_vector_probability": joint_q,
                        "recommended": bool(rec[k]),
                        "exposure_probability": float(_HS.P["p_exposition"]),
                        "exposed": exposed,
                        "approval": ("approved" if requested else "rejected")
                        if presented
                        else ("not_presented" if rec[k] else "not_recommended"),
                        "action_origin": (
                            "approved_recommendation" if presented else "cadre_initiative"
                        )
                        if requested
                        else "none",
                        "requested": requested,
                        **results[k],
                        "response_h": self.hour,
                    }
                )
                records.append(record)
                self.journal.event(
                    absolute_h,
                    "ACTION_EXECUTION",
                    u,
                    None,
                    decision_id=record.decision_id,
                    lever=lever,
                    execution=record.execution,
                    affected_count=record.affected_count,
                    affected_unit=record.affected_unit,
                )
        self._acted_at, self._last_batch, self._last_records = self.hour, batch, tuple(records)
        self.contexts.append(context)
        self.batches.append(batch)
        self.ledger.extend(records)
        return self._last_records

    def advance(self) -> PolicyContext | None:
        if self.observe() is None:
            raise ValueError("Environment is finished")
        if self.hour % 24 == 9 and self._acted_at != self.hour:
            raise ValueError("Submit a recommendation or explicit abstention before advancing")
        self._step(self.hour + self.sim.h0_rec, inherited_policy=False)
        self.hour += 1
        if self.hour == self.config.days * 24:
            self.stream.receive(self.hour)  # Extraction cutoff: never export later receipts.
            self._context = None
        else:
            self._context = self._snapshot()
        return self._context


def validate_run(env: PolicyEnvironment) -> dict[str, Any]:
    if env.observe() is not None:
        raise ValueError("Cannot export an incomplete policy run")
    violations = {k: v for k, v in env.checks.items() if k != "heures_controlees" and v}
    if violations:
        raise ValueError(f"Simulation invariant violations: {violations}")
    expected = env.config.days * len(env.config.units) * len(LEVER_NAMES)
    if len(env.ledger) != expected or len({r.decision_id for r in env.ledger}) != expected:
        raise ValueError("Decision ledger is incomplete or duplicated")
    contexts = {c.decision_h: c for c in env.contexts}
    if len(contexts) != env.config.days or any(h % 24 != 9 for h in contexts):
        raise ValueError("Decision context grid mismatch")
    expected_ids = {
        f"{env.run_id}:{unit.unit_id}@{h}:{lever}"
        for h in range(9, env.config.days * 24, 24)
        for unit in env.config.units
        for lever in LEVER_NAMES
    }
    if {r.decision_id for r in env.ledger} != expected_ids:
        raise ValueError("Ledger decision grid mismatch")
    batches = {b.decision_h: b for b in env.batches}
    if len(env.batches) != env.config.days or set(batches) != set(contexts):
        raise ValueError("Recommendation batch grid mismatch")
    actions = {(r["h"] - env.sim.h0_rec, r["u"]): r for r in env.journal.actions}
    indexes = {u.unit_id: i for i, u in enumerate(env.config.units)}
    if len(actions) != env.config.days * len(indexes):
        raise ValueError("Physical action journal grid mismatch")
    for row in env.ledger:
        DecisionRecord.model_validate_json(row.model_dump_json())
        if (
            row.context_sha256 != contexts[row.decision_h].fingerprint
            or row.descriptor != env.descriptor
            or row.hospital_id != env.config.hospital_id
            or env.config.unit_poles.get(row.unit_id) != row.pole_id
            or row.decision_id != f"{env.run_id}:{row.unit_id}@{row.decision_h}:{row.lever}"
        ):
            raise ValueError("Ledger context/version/identity provenance mismatch")
        batch = batches[row.decision_h]
        if batch.descriptor != row.descriptor or batch.context_sha256 != row.context_sha256:
            raise ValueError("Recommendation provenance mismatch")
        unit = next(r for r in batch.units if r.unit_id == row.unit_id)
        action = actions[row.decision_h, indexes[row.unit_id]]
        joint = math.prod(
            p if action[f"r_{name}"] else 1 - p
            for name, p in zip(LEVER_NAMES, unit.probabilities, strict=True)
        )
        if (
            row.recommendation_probability != unit.probabilities[LEVER_NAMES.index(row.lever)]
            or row.recommendation_vector_probability != joint
            or row.recommended != bool(action[f"r_{row.lever}"])
            or row.exposed != bool(action["exposition"])
            or row.requested != bool(action[f"a_{row.lever}"])
            or row.affected_count != action[f"n_concernes_{row.lever}"]
        ):
            raise ValueError("Ledger disagrees with recommendation or physical action journal")
    # Replay every hourly feature independently from released receipts.
    replayed = replay(
        env.stream.delivered, env.config, run_id=env.run_id, stale_after_h=env.stale_after_h
    )
    if any(a != b for a, b in zip(env.features, replayed, strict=True)):
        raise ValueError("Online/offline as-of reconstruction mismatch")
    return {
        "physical": dict(env.checks),
        "online_replay_equal": True,
        "decision_records": len(env.ledger),
        "decision_contexts": len(contexts),
        "executions": dict(Counter(r.execution for r in env.ledger)),
        "approvals": dict(Counter(r.approval for r in env.ledger)),
        "action_origins": dict(Counter(r.action_origin for r in env.ledger)),
    }


def run_policy(config: HospitalConfig, policy: Policy, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(output)
    env = PolicyEnvironment(config, policy.descriptor)
    context = env.reset()
    policy.reset(env.site)
    current: PolicyContext | None = context
    while current is not None:
        if current.decision_h % 24 == 9:
            if policy.descriptor != env.descriptor:
                raise ValueError("Policy changed version during the run")
            env.act(policy.recommend(current))
        current = env.advance()
    checks = validate_run(env)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".policy-", dir=output.parent) as temporary:
        staging = Path(temporary) / "run"
        staging.mkdir()
        truth = export_result(
            config,
            SimulationResult(
                env.sim, env.journal, env.resources, dict(env.checks), env.resource_pools
            ),
            staging / "simulation",
            policy_description="observation-only recommender; separate legacy cadre",
        )
        for directory in ("observed", "features", "decisions", "truth"):
            (staging / directory).mkdir()
        _jsonl(
            staging / "observed/unit_states.jsonl.gz",
            (r.model_dump(mode="json") for r in env.stream.delivered),
        )
        _jsonl(
            staging / "features/asof.jsonl.gz", (r.model_dump(mode="json") for r in env.features)
        )
        _jsonl(
            staging / "decisions/contexts.jsonl.gz",
            (r.model_dump(mode="json") for r in env.contexts),
        )
        _jsonl(
            staging / "decisions/recommendations.jsonl.gz",
            (r.model_dump(mode="json") for r in env.batches),
        )
        _jsonl(
            staging / "decisions/ledger.jsonl.gz", (r.model_dump(mode="json") for r in env.ledger)
        )
        _jsonl(staging / "truth/cadre_private.jsonl.gz", env.human_audit)
        _write(staging / "policy.json", env.descriptor.model_dump(mode="json"))
        _write(staging / "config.json", config.model_dump(mode="json"))
        manifest = {
            "status": "complete",
            "schema_version": "0.1",
            "synthetic_only": True,
            "data_role": "closed_loop_observed_policy",
            "run_id": env.run_id,
            "hospital_id": config.hospital_id,
            "partition": config.partition,
            "policy": env.descriptor.model_dump(mode="json"),
            "config_sha256": config.fingerprint,
            "source_sha256": source_hashes(),
            "runtime": _runtime(),
            "checks": checks,
            "test_opened": False,
            "truth_manifest_sha256": _sha(staging / "simulation/manifest.json"),
            "settings": {
                "stale_after_h": env.stale_after_h,
                "decision_hour": 9,
                "warmup": "common inherited policy",
                "observation_profile": "v041_snapshot_stream_v1",
            },
            "counts": {
                "features": len(env.features),
                "deliveries": len(env.stream.delivered),
                "truth_events": truth["counts"]["events_including_warmup"],
            },
            "assumptions": {
                "cadre": "current state and next-24h-arrival latent z; truth audit only",
                "execution": "synchronous synthetic requests; no network or real SI actions",
                "reinforcement": "two shifts confirmed at request time; no simulated no-show",
                "discharges": "changed patient plans, not actual discharges or effect estimates",
                "recommendations": "independent lever Bernoulli; shared unit/day exposure",
                "probabilities": "recommendation q is not the propensity of executed actions",
                "plugin_boundary": "typed data boundary for trusted code, not a security sandbox",
                "learning": "use emitted live observations; never re-noise the truth",
            },
            "files_sha256": {
                str(p.relative_to(staging)): _sha(p)
                for p in sorted(staging.rglob("*"))
                if p.is_file()
            },
        }
        _write(staging / "manifest.json", manifest)
        staging.rename(output)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--policy", choices=("observed_rules", "no_recommendation"), default="observed_rules"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.days is not None:
            config = HospitalConfig.model_validate({**config.model_dump(), "days": args.days})
        policy = (
            ObservedRulePolicy() if args.policy == "observed_rules" else NoRecommendationPolicy()
        )
        result = run_policy(config, policy, args.output)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Policy loop failed: {exc}\n")
    print(
        json.dumps({"run_id": result["run_id"], "checks": result["checks"], "test_opened": False})
    )


if __name__ == "__main__":
    main()
