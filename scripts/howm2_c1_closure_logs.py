#!/usr/bin/env python3
"""C1 closure (decision n.6): exploratory reading of the ALREADY RECORDED train/CVAL logs (state.json
of each run) and of the recorded timings. No model pass, no new value, selection and verdict unchanged.
Post hoc reading (after the C1 result is known)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TR = ROOT / "evidence/howm2_c1/train"
OUT = ROOT / "evidence/howm2_c1_closure"


def main() -> int:
    runs = {}
    for d in sorted(TR.iterdir()):
        m = json.loads((d / "state.json").read_text())
        st = m["state"]
        runs[d.name] = {
            "system": m["config"]["system"], "N": m["config"]["N"], "seed": m["config"]["seed"],
            "updates": st["step"], "best_step_retained": st["best_step"], "last_step": st["step"],
            "retained_equals_last": st["best_step"] == st["step"],
            "curve": [{"step": e["step"], "cval_total": e["cval_total"], "cval_by_family": e["cval_means"],
                       "train_by_family_since_previous_eval": e["train_means_since_last_eval"]} for e in m["log"]],
            "seconds_logged": st["seconds"]}
    end = {}
    for k, r in runs.items():
        c = r["curve"]
        if len(c) >= 2:
            end[k] = {"cval_total_change_last_interval": c[-1]["cval_total"] - c[-2]["cval_total"],
                      "cval_total_change_from_first_eval": c[-1]["cval_total"] - c[0]["cval_total"]}
        else:
            end[k] = {"note": "a single CVAL evaluation (N=100: 150 updates, evaluated at the end only)"}
    pilot = json.loads((ROOT / "evidence/howm2_c1/PILOT.json").read_text())
    c2a = {k: v for k, v in runs.items() if v["system"] == "C.2a"}
    measured = [v["seconds_logged"] / v["updates"] for v in c2a.values()]
    cost = {
        "pilot_step_s_C2a": pilot["timing"]["C.2a"]["step_s_mean"],
        "pilot_conditions": "12 steps, 3 pilot processes concurrently (one per system), 1 thread each",
        "measured_s_per_update_C2a_N100": measured,
        "measured_conditions": "full runs, 3 C.2a processes concurrently (2 after OOM kills), 1 thread each; includes the final CVAL evaluation",
        "one_seed_N1000_single_thread_s": {"from_pilot_13.03x1500": round(pilot["timing"]["C.2a"]["step_s_mean"] * 1500),
                                           "from_measured_mean": round(sum(measured) / len(measured) * 1500),
                                           "plus_3_CVAL_evals_estimate": round(3 * 72 * pilot["timing"]["C.2a"]["fwd_batch_s"])},
        "three_seeds_cumulative_cpu_s": {"from_pilot": round(3 * pilot["timing"]["C.2a"]["step_s_mean"] * 1500),
                                         "from_measured_mean": round(3 * sum(measured) / len(measured) * 1500)},
        "wall_time_realisable": {
            "memory_constraint": "C.2a pilot max RSS 4.4 GB; 3 concurrent processes on 15 GB without swap were OOM-killed (C1 ledger #17, #18, #31)",
            "two_concurrent_two_waves_s": round(2 * sum(measured) / len(measured) * 1500),
            "three_concurrent_one_wave_s_if_no_OOM": round(sum(measured) / len(measured) * 1500),
            "note": "dividing the cumulative CPU by 4 cores (as in the C1 report, ~4 h 30) is NOT a measured speed-up and is withdrawn; 4 concurrent C.2a processes do not fit in memory"}}
    out = {"status": "exploratory, post hoc, recorded values only; no selection/verdict change", "runs": runs,
           "end_of_training": end, "c2a_N1000_cost_correction": cost,
           "caveat_100_vs_1000": "N=100 vs N=1000 mixes data diversity (100 vs 1000 establishments) and number of updates (150 vs 1500): the comparison does not isolate either factor"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "C1_LOGS_EXPLORATORY.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"cost": cost, "end": end}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
