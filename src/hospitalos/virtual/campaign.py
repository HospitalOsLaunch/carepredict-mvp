"""Offline paired campaigns. Never mounted in the product API or navigation."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from hospitalos.simulator.comparison import runtime_versions, source_hashes
from hospitalos.simulator.evaluation import evaluate

from .config import HospitalConfig, hospitals
from .runtime import Decision, HospitalRuntime

Policy = Literal["accept", "refuse", "disabled"]
CADENCE = 300


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def sources() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    return {
        **source_hashes(),
        **{
            f"virtual/{p.name}": hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.glob("*.py"))
        },
    }


def episode(config: HospitalConfig, seed: int, policy: Policy, hours: int) -> dict[str, Any]:
    hospital = HospitalRuntime(config, seed, clock_rate=1)
    horizon = hours * 3600
    next_decision = float(config.delivery_seconds)
    assessments: list[dict[str, Any]] = []
    try:
        while hospital.engine.second < horizon:
            if hospital.engine.second >= next_decision:
                if policy != "disabled":
                    hospital.assess(force=True)
                    view = hospital.view()
                    plan = view.episode.assessment.plan if view.episode else None
                    assessments.append(
                        {
                            "second": hospital.engine.second,
                            "snapshot_fingerprint": view.snapshot.semantic_fingerprint,
                            "decision": plan.decision if plan else "blocked",
                            "action": plan.selected.model_dump() if plan else None,
                        }
                    )
                    if view.can_decide and plan:
                        hospital.decide(
                            Decision(
                                hospital_id=config.hospital_id,
                                run_id=view.run_id,
                                request_id=f"campaign-{len(assessments)}",
                                revision=view.revision,
                                plan_id=plan.plan_id,
                                snapshot_fingerprint=view.snapshot.semantic_fingerprint,
                                accept=policy == "accept",
                                reason="politique de refus" if policy == "refuse" else "",
                            )
                        )
                next_decision += CADENCE
            hospital.advance(min(next_decision, horizon) - hospital.engine.second, plan=False)
        journal = hospital.engine.journal
        score = evaluate(journal, horizon)
        return {
            "evaluation": score.model_dump(),
            "installed": sum(e.kind == "installed" for e in journal),
            "solicitation_seconds_requested": 30 * score.coordination_tasks,
            "assessments": assessments,
            "commands": [r.model_dump(mode="json") for r in hospital.records.values()],
            "journal": [asdict(e) for e in journal],
            "primitives": hospital.engine.primitives,
        }
    finally:
        hospital.close()


def pair(
    config: HospitalConfig, seed: int, policy: Policy = "accept", hours: int = 6
) -> dict[str, Any]:
    if not 1 <= hours <= 24 or not 0 <= seed <= 1_000_000_000:
        raise ValueError("campaign_hours_1_to_24_and_nonnegative_seed_required")
    a0, a1 = episode(config, seed, "disabled", hours), episode(config, seed, policy, hours)
    common = a0["primitives"].keys() & a1["primitives"].keys()
    if any(a0["primitives"][key] != a1["primitives"][key] for key in common):
        raise ValueError("uncoupled_exogenous_primitives")
    if policy == "disabled" and a0 != a1:
        raise ValueError("neutrality_failed")
    result: dict[str, Any] = {
        "schema_version": "VIRTUAL_PAIR_1",
        "scope": "fictional_hospital_only",
        "config": config.model_dump(),
        "seed": seed,
        "hours": hours,
        "policy": policy,
        "assessment_cadence_seconds": CADENCE,
        "a0": a0,
        "a1": a1,
        "waiting_patient_minutes_saved": a0["evaluation"]["waiting_patient_minutes"]
        - a1["evaluation"]["waiting_patient_minutes"],
    }
    return {**result, "result_id": digest(result)}


def atomic_json(path: Path, content: Any) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n")
    pending.replace(path)


def run(
    output: Path,
    seeds: tuple[int, ...] = tuple(range(10)),
    hours: int = 6,
    policy: Policy = "accept",
    configs: tuple[HospitalConfig, ...] | None = None,
) -> dict[str, Any]:
    selected = configs if configs is not None else hospitals()
    if (
        not selected
        or len({c.hospital_id for c in selected}) != len(selected)
        or not 1 <= len(seeds) <= 50
        or len(set(seeds)) != len(seeds)
        or any(not 0 <= s <= 1_000_000_000 for s in seeds)
        or not 1 <= hours <= 24
    ):
        raise ValueError("invalid_campaign_configuration")
    identity = {
        "schema_version": "VIRTUAL_CAMPAIGN_1",
        "configs": [c.model_dump(mode="json") for c in selected],
        "seeds": list(seeds),
        "hours": hours,
        "policy": policy,
        "sources": sources(),
        "runtime_versions": runtime_versions(),
        "cadence_seconds": CADENCE,
        "replicates_fixed_before_execution": True,
    }
    manifest = {**identity, "campaign_id": digest(identity)}
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise ValueError("campaign_directory_has_different_manifest")
    atomic_json(manifest_path, manifest)
    total = len(selected) * len(seeds)
    results: list[dict[str, Any]] = []
    summaries = []
    for i, config in enumerate(selected):
        regime_results = []
        for seed in seeds:
            path = output / f"hospital-{i:02d}-seed-{seed}.json"
            try:
                if path.exists():
                    result = json.loads(path.read_text())
                    expected_hash = result.pop("result_id")
                    if (
                        digest(result) != expected_hash
                        or result["config"] != config.model_dump(mode="json")
                        or result["seed"] != seed
                        or result["hours"] != hours
                        or result["policy"] != policy
                    ):
                        raise ValueError("corrupt_campaign_result")
                    result["result_id"] = expected_hash
                else:
                    result = pair(config, seed, policy, hours)
                    atomic_json(path, result)
                results.append(result)
                regime_results.append(result)
                atomic_json(
                    output / "progress.json",
                    {"status": "running", "completed": len(results), "total": total},
                )
                print(
                    json.dumps(
                        {
                            "event": "paired_episode_completed",
                            "hospital": config.hospital_id,
                            "seed": seed,
                            "completed": len(results),
                            "total": total,
                        }
                    ),
                    flush=True,
                )
            except Exception:
                atomic_json(
                    output / "progress.json",
                    {
                        "status": "failed",
                        "completed": len(results),
                        "total": total,
                        "hospital": config.hospital_id,
                        "seed": seed,
                    },
                )
                raise
        effects = [r["waiting_patient_minutes_saved"] for r in regime_results]
        summaries.append(
            {
                "hospital": config.hospital_id,
                "regime": config.regime,
                "replicates": len(effects),
                "mean_saved": statistics.mean(effects),
                "median_saved": statistics.median(effects),
                "min_saved": min(effects),
                "max_saved": max(effects),
                "stdev_saved": statistics.stdev(effects) if len(effects) > 1 else None,
                "improved": sum(v > 0 for v in effects),
                "unchanged": sum(v == 0 for v in effects),
                "degraded": sum(v < 0 for v in effects),
            }
        )
    if sources() != manifest["sources"]:
        raise ValueError("code_changed_during_campaign")
    report = {
        "manifest": manifest,
        "scope": "fictional_hospitals_no_real_effectiveness_claim",
        "summaries": summaries,
        "replicates": [
            {
                "hospital": r["config"]["hospital_id"],
                "seed": r["seed"],
                "result_id": r["result_id"],
                "a0": r["a0"]["evaluation"],
                "a1": r["a1"]["evaluation"],
                "saved": r["waiting_patient_minutes_saved"],
            }
            for r in results
        ],
    }
    atomic_json(output / "report.json", report)
    atomic_json(
        output / "progress.json", {"status": "completed", "completed": total, "total": total}
    )
    lines = [
        "# Campagne sur hôpitaux virtuels",
        "",
        "Résultats fictifs ; aucune preuve de bénéfice hospitalier.",
        "",
        "| Hôpital | Réplications | Écart moyen A0 − A1 (min-patients) "
        "| Min | Max | Dégradations |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in summaries:
        lines.append(
            f"| {s['hospital']} | {s['replicates']} | {s['mean_saved']:.2f} "
            f"| {s['min_saved']:.2f} | {s['max_saved']:.2f} | {s['degraded']} |"
        )
    (output / "report.md").write_text("\n".join(lines) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", default=",".join(map(str, range(10))))
    parser.add_argument("--hours", type=int, default=6)
    parser.add_argument("--policy", choices=("accept", "refuse", "disabled"), default="accept")
    parser.add_argument(
        "--config", type=Path, help="JSON array of versioned hospital configurations"
    )
    args = parser.parse_args()
    try:
        configs = (
            tuple(HospitalConfig.model_validate(c) for c in json.loads(args.config.read_text()))
            if args.config
            else None
        )
        run(
            args.output,
            tuple(int(s.strip()) for s in args.seeds.split(",")),
            args.hours,
            args.policy,
            configs,
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
