"""Tests de sensibilité du témoin de transport. Aucune modification du dépôt."""

from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import mean
from unittest.mock import patch

from hospitalos.hybrid import simulation
from hospitalos.hybrid.innovations import draw
from hospitalos.hybrid.models import Action, bundle_errors
from hospitalos.hybrid.multiday import paired_future
from hospitalos.hybrid.planning import PlanRequest
from hospitalos.hybrid.scoring import score

from flux import SHA, verify_revision


def delay_preparation(pid, load, lag, convention):
    """Fixed-lag sensitivity through the target's indexed preparation duration."""

    def shifted(support, seed, scenario, mechanism, entity):
        value = draw(support, seed, scenario, mechanism, entity)
        if mechanism != "exit" or entity != pid:
            return value
        minutes = value * load
        delayed = max(minutes, lag) if convention == "parallele" else minutes + lag
        assert delayed % load == 0
        return delayed // load

    return shifted


def objective(areas, weight):
    worst = sorted(areas, reverse=True)[: max(1, math.ceil(len(areas) / 10))]
    return (1 - weight) * mean(areas) + weight * mean(worst)


def fixture_test():
    data = json.loads(Path("web/src/fixtures/scenario-nominal.json").read_text())
    plan = data["plan"]
    req = PlanRequest.model_validate(data["request"])
    chosen = Action.model_validate(plan["selected"])
    assert chosen.kind == "request_transport" and not plan["bundle"]
    req = req.model_copy(update={"horizon_minutes": plan["horizon_minutes"]})
    state = req.state()
    assert state.fingerprint == plan["state_fingerprint"]
    assert (
        req.preparation is None and req.future is None and req.horizon_minutes == 1440
    )
    assert not plan["candidates_truncated"]
    options = [Action.model_validate(c["action"]) for c in plan["candidates"]]
    no_op = next(a for a in options if a.kind == "no_op")
    output = {}
    for lag, convention in [(None, "reference")] + [
        (m, c) for m in (0, 30, 60, 120) for c in ("successif", "parallele")
    ]:
        results = {}
        for act in options:
            areas, pressures, halves = [], [], []
            for n in range(req.scenarios):
                tape = paired_future(
                    state, req.future, req.seed, n, req.horizon_minutes, multiday=False
                )
                # For an alternative decision, background transport is still prepared.
                # A booking at D with delayed activation has identical logistical consequences
                # on this fixture: resources are first claimed at the transport start.
                active_fallback = lag is not None and act != chosen
                actions = tuple(x for x in (act,) if x != no_op)
                if active_fallback:
                    actions += (chosen,)
                assert not bundle_errors(state, actions)
                load = draw(
                    req.assumptions.load_multipliers,
                    req.seed,
                    n,
                    "load",
                    state.hospital_id,
                )
                innovation = (
                    delay_preparation(chosen.patient_id, load, lag, convention)
                    if active_fallback
                    else draw
                )
                with patch.object(simulation, "draw", innovation):
                    log = simulation.simulate(
                        state,
                        actions,
                        req.assumptions,
                        seed=req.seed,
                        scenario=n,
                        horizon_minutes=1440,
                        future=tape,
                    )
                s = score(state, log, expected_future=tape, actions=actions)
                assert not s.violations, s.violations
                areas.append(s.waiting_patient_minutes)
                pressures.append(s.pressure.components())
                prefix = simulation.Trajectory(
                    720, tuple(e for e in log.events if e.minute <= 720)
                )
                half = score(state, prefix, expected_future=tape, actions=actions)
                assert not half.violations
                halves.append(half.waiting_patient_minutes)
            results[act.key] = {"waiting": areas, "h12": halves, "pressure": pressures}
        base = results[no_op.key]
        shortlist = []
        for act in options:
            x = results[act.key]
            veto = any(
                a > b
                for observed, ref in zip(x["pressure"], base["pressure"], strict=True)
                for a, b in zip(observed, ref, strict=True)
            )
            shortlist.append(
                {
                    "id": act.key,
                    "attente": mean(x["waiting"]),
                    "objectif": objective(x["waiting"], req.tail_weight),
                    "veto": veto,
                }
            )
        best = min(
            (x for x in shortlist if not x["veto"]),
            key=lambda x: (x["objectif"], x["id"] != no_op.key, x["id"]),
        )
        intervention = results[chosen.key]
        gain24 = mean(base["waiting"]) - mean(intervention["waiting"])
        gain12 = mean(base["h12"]) - mean(intervention["h12"])
        output[f"{convention}_{lag}"] = {
            "temoin": mean(base["waiting"]),
            "transport_immediat": mean(intervention["waiting"]),
            "gain_H24": gain24,
            "gain_H12": gain12,
            "ajout_gain_entre_12_et_24": gain24 - gain12,
            "premier_geste_isole": best["id"],
            "classement_gestes_isoles": shortlist,
        }
    for case in output["reference_None"]["classement_gestes_isoles"]:
        published = next(
            c
            for c in plan["candidates"]
            if Action.model_validate(c["action"]).key == case["id"]
        )
        assert published["mean_waiting_patient_minutes"] == case["attente"]
        assert published["objective"] == case["objectif"]
    assert output["reference_None"]["gain_H24"] == next(
        w["saved_wait"] for w in plan["windows"] if w["minutes"] == 1440
    )
    assert all(output[f"{m}_0"]["gain_H24"] == 0 for m in ("successif", "parallele"))
    return {
        "revision": SHA,
        "plan": plan["plan_id"],
        "scenarios": req.scenarios,
        "cas": output,
    }


if __name__ == "__main__":
    verify_revision()
    print(json.dumps(fixture_test(), ensure_ascii=False, indent=2))
