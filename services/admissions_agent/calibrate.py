"""Pointing calibration of an open-weight vision engine.

Before the router lets an open model click in a real portal, it must hit labelled
targets on a synthetic page. The model's raw coordinates are scored under both
conventions (0-1000 normalised, and screenshot pixels), which tells which one the
deployed model follows; the hit rate under the configured convention is what the
router checks against the policy threshold.
"""

from __future__ import annotations

import ast
import random
from dataclasses import dataclass

from services.admissions_agent.browser import BrowserSession
from services.admissions_agent.engines.base import Goal
from services.admissions_agent.engines.openai_vlm import OpenWeightsVision


@dataclass(frozen=True)
class Target:
    label: str
    x: int
    y: int
    w: int = 150
    h: int = 44

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.w and self.y <= py <= self.y + self.h


@dataclass(frozen=True)
class CalibrationResult:
    trials: int
    hit_rate_configured: float
    hit_rate_by_convention: dict[str, float]
    best_convention: str


def layout(rng: random.Random, width: int, height: int, n: int = 8) -> list[Target]:
    targets: list[Target] = []
    while len(targets) < n:
        t = Target(
            f"Cible {len(targets) + 1}", rng.randint(20, width - 180), rng.randint(20, height - 70)
        )
        if all(abs(t.x - o.x) > 170 or abs(t.y - o.y) > 60 for o in targets):
            targets.append(t)
    return targets


def page_html(targets: list[Target]) -> str:
    buttons = "".join(
        f"<button style='position:absolute;left:{t.x}px;top:{t.y}px;width:{t.w}px;height:{t.h}px'>"
        f"{t.label}</button>"
        for t in targets
    )
    return f"<html><body style='margin:0;font:16px Arial'>{buttons}</body></html>"


def raw_clicks(trace: list[str]) -> list[tuple[float, float]]:
    out = []
    for line in trace:
        if line.startswith("click "):
            args = ast.literal_eval(line[len("click ") :])
            out.append((float(args["x"]), float(args["y"])))
    return out


def calibrate(
    engine: OpenWeightsVision, session: BrowserSession, trials: int = 10, seed: int = 7
) -> CalibrationResult:
    rng = random.Random(seed)
    w, h = session.viewport
    hits = {"normalized_1000": 0, "pixels": 0}
    for _ in range(trials):
        targets = layout(rng, w, h)
        session.page.set_content(page_html(targets))
        target = rng.choice(targets)
        goal = Goal(
            "calibration",
            f"Clique une seule fois au centre du bouton « {target.label} », puis appelle finish "
            "avec <resultat>TERMINE</resultat>.",
            expects_json=False,
        )
        result = engine.run(session, goal, max_steps=3, budget_usd=1.0)
        clicks = raw_clicks(result.trace)
        if not clicks:
            continue
        x, y = clicks[0]
        if target.contains(x / 1000 * w, y / 1000 * h):
            hits["normalized_1000"] += 1
        if target.contains(x, y):
            hits["pixels"] += 1
    rates = {k: v / trials for k, v in hits.items()}
    best = max(rates, key=lambda k: rates[k])
    return CalibrationResult(trials, rates[engine.convention], rates, best)
