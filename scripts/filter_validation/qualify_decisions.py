"""DEV-only timing diagnostic. Never select individual TEST outcomes."""
import json
from pathlib import Path
import copy
import numpy as np
from correction import C, W, L, P, choices, view, posterior, ServiceLaw, key


def run():
    params = json.loads(Path("evidence/filter_validation/run/fit.json").read_text())
    laws = {k: ServiceLaw(**v["law"]) for k, v in params["180"].items()}
    rows = []
    for index in range(4):
        sp = C.structure("FILTER_V3_TIMING_DEV_20261120", index, 180)
        for origin in (52, 58, 60, 66, 68):
            pre = L.prefix(sp, origin)
            eng, _, rec = L.start_future(pre, sp, 1)
            ps, pe = view(pre, rec, eng.tick)
            acts = choices(pe, sp.units, eng.tick, eng.tick + 96)
            planning_spec = copy.deepcopy(sp)
            planning_spec.ekey = key("FILTER_V3_TIMING_PLAN", sp.part, sp.idx, eng.tick)
            scores, selected = {}, {}
            for arm in ("public", "lifecycle", "true_state"):
                costs = np.zeros(len(acts))
                for draw in range(10001, 10010):
                    initial = eng if arm == "true_state" else (pe if arm == "public" else
                              posterior(pe, ps, laws, draw, W.ProvN(planning_spec, draw)))
                    for i, action in enumerate(acts):
                        costs[i] += P.sim_rollout(initial, W.ProvN(planning_spec, draw), [action], 24, 6, sp.n, eng.tick)
                costs /= 9
                scores[arm] = costs.tolist()
                selected[arm] = acts[P.choose(costs, [[a] for a in acts])]["id"]
            rows.append(dict(index=index, origin=origin, candidates=[a["id"] for a in acts],
                             selected=selected, scores=scores,
                             public_cleaning=sum(b.state == "cleaning" for b in pe.beds.values()),
                             true_cleaning=sum(b.state == "cleaning" for b in eng.beds.values()),
                             public_transport=len(pe.tr_service), true_transport=len(eng.tr_service)))
        print("Timing DEV", index, flush=True)
    out = Path("evidence/filter_correction/timing_dev.json")
    out.write_text(json.dumps(dict(partition="FILTER_V3_TIMING_DEV_20261120", planning_draws=list(range(10001, 10010)),
                                  rows=rows), indent=2) + "\n")


if __name__ == "__main__":
    run()
