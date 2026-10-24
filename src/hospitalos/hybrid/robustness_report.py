"""Paired trajectory inference and tables generated from checked aggregates."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .continuous import Array


def paired_interval(values: Array, *, seed: int = 81001) -> list[float]:
    if len(values) < 30:
        raise ValueError("Confirmatory interval requires at least 30 independent trajectories")
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(values), (5000, len(values)))
    return [float(x) for x in np.quantile(values[draws].mean(axis=1), (0.025, 0.975))]


def summarize(rows: list[dict[str, Any]], *, inference: bool) -> dict[str, Any]:
    delta = np.array([r["delta_logistic"] for r in rows])
    gap = sum(r["reference_wait"] - r["oracle_wait"] for r in rows)
    by_seed: dict[int, list[float]] = defaultdict(list)
    attribution: dict[str, dict[str, float]] = {}
    for r in rows:
        by_seed[r["seed"]].append(r["delta_logistic"])
        item = attribution.setdefault(r["stage"], {"episodes": 0, "gain_vs_logistic": 0})
        item["episodes"] += 1
        item["gain_vs_logistic"] -= r["delta_logistic"]
    per_seed = np.array([np.mean(v) for _, v in sorted(by_seed.items())])
    regret = np.sort([r["wait"] - r["oracle_wait"] for r in rows])
    return {
        "episodes": len(rows),
        "seeds": len(by_seed),
        "better_equal_worse_vs_logistic": [
            int(np.sum(delta < -1e-8)),
            int(np.sum(np.abs(delta) <= 1e-8)),
            int(np.sum(delta > 1e-8)),
        ],
        "mean_waiting_patient_minutes": float(np.mean([r["wait"] for r in rows])),
        "mean_delta_vs_logistic": float(delta.mean()),
        "paired_trajectory_ci95": paired_interval(per_seed) if inference else None,
        "fraction_of_logistic_oracle_gap_closed": float(-delta.sum() / gap) if gap > 1e-8 else None,
        "oracle_gap_denominator": float(gap),
        "mean_regret": float(np.mean([r["wait"] - r["oracle_wait"] for r in rows])),
        "worst_decile_regret": float(regret[-max(1, int(np.ceil(len(regret) / 10))) :].mean()),
        "resource_regression_rate_vs_noop": float(
            np.mean([r["resource_regression"] for r in rows])
        ),
        "mean_staffing_exposure": float(np.mean([r["staffing"] for r in rows])),
        "mean_transport_exposure": float(np.mean([r["transport"] for r in rows])),
        "abstention_rate": float(np.mean([r["mode"].startswith("abstain") for r in rows])),
        "fallback_rate": float(np.mean([r["mode"].startswith("fallback") for r in rows])),
        "no_additional_request_rate": float(np.mean([r["action"] == 0 for r in rows])),
        "per_seed_mean_delta": {str(k): float(np.mean(v)) for k, v in sorted(by_seed.items())},
        "gain_decomposition": attribution,
    }


def table(report: dict[str, Any]) -> str:
    lines = [
        "| Flux | Politique | N | Meilleur / égal / pire vs logistique "
        "| Écart moyen (patients-min) | IC 95 % apparié |",
        "|---|---|---:|---|---:|---|",
    ]
    for stream, policies in report["post_change"].items():
        for name, value in policies.items():
            ci = value["paired_trajectory_ci95"]
            interval = "exploratoire" if ci is None else f"[{ci[0]:.2f}, {ci[1]:.2f}]"
            counts = " / ".join(str(x) for x in value["better_equal_worse_vs_logistic"])
            lines.append(
                f"| {stream} | {name} | {value['episodes']} | {counts} "
                f"| {value['mean_delta_vs_logistic']:.2f} | {interval} |"
            )
    return "\n".join(lines)


def validate_report(report: dict[str, Any]) -> None:
    if report["deployment_conclusion"] != "research_only_no_promotion":
        raise AssertionError("Synthetic result cannot authorize deployment")
    for policies in (*report["all_episodes"].values(), *report["post_change"].values()):
        for value in policies.values():
            if sum(value["better_equal_worse_vs_logistic"]) != value["episodes"]:
                raise AssertionError("Outcome counts do not reconcile")
            components = value["gain_decomposition"].values()
            if sum(x["episodes"] for x in components) != value["episodes"]:
                raise AssertionError("Attribution counts do not reconcile")
            gain = sum(x["gain_vs_logistic"] for x in components)
            if not np.isclose(gain, -value["mean_delta_vs_logistic"] * value["episodes"]):
                raise AssertionError("Attribution gains do not reconcile")
            if not np.isclose(
                np.mean(list(value["per_seed_mean_delta"].values())),
                value["mean_delta_vs_logistic"],
            ):
                raise AssertionError("Unbalanced trajectory aggregation")
    if report["markdown_table"] != table(report):
        raise AssertionError("Published table differs from its aggregates")


def validate_documented_conclusion(report: dict[str, Any], document: Path) -> None:
    marker = f"<!-- decision-v2-primary: {report['primary_result']} -->"
    if marker not in document.read_text():
        raise AssertionError("Documented primary conclusion differs from recomputed evidence")
