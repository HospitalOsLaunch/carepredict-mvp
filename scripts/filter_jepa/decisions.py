"""Exploratory closed-loop test on the existing INT-1 engine, four units, 24 hours.

Service and notification delays are fitted from public training episodes.
Compare the same workload rule using reported or posterior unfinished workload.
Both choose cleaning or transport in the earliest jointly admissible slot.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"src"))
from hospitalos.howmint import loop as L, world as W


def fit_service(prefixes, kind):
    durations, delays = [], []
    for pre in prefixes:
        start = {}
        for event, avail, name, subject, _, _ in sorted(pre["obs"]):
            if avail >= pre["t0"]*15:
                continue
            if name == kind+"_start":
                start[subject] = event
            elif name == kind+"_done" and subject in start:
                durations.append(max(1, event-start.pop(subject)))
                delays.append(max(1, avail-event))
    if not durations:
        raise ValueError("No completed training services")
    return float(np.mean(durations)), float(np.mean(delays)), len(durations)


def unfinished(age, mean_service, mean_delay):
    """P(service unfinished | completion report has not arrived), exponential delays."""
    age = max(0, age)
    a, b = 1/mean_service, 1/mean_delay
    if abs(a-b) < 1e-8:
        return 1/(1+a*age)
    # Survival of the sum of independent service and notification times.
    service = math.exp(-a*age)
    survival = (b*service-a*math.exp(-b*age))/(b-a)
    return min(1., max(0., service/max(survival, 1e-300)))


def policy(params, filtered):
    def choose(**kw):
        ps, eng, tick = kw["ps"], kw["peng"], kw["t"]
        scores = {}
        clean = 0.
        for bed in ps.beds.values():
            status = bed.data.get("state")
            if status in ("dirty", "cleaning"):
                weight = 1.
                if filtered and status == "cleaning":
                    weight = unfinished(tick*15-bed.data["since"], *params["cleaning"][:2])
                clean += weight
        transport = 0.
        for stay in ps.present_stays().values():
            if "ready" in stay and stay.get("transport") and "transport_done" not in stay:
                weight = 1.
                if filtered and "transport_start" in stay:
                    weight = unfinished(tick*15-stay["transport_start"], *params["transport"][:2])
                transport += weight
        scores["cl"] = clean*params["cleaning"][0]/max(1,eng.base_c_cl)
        scores["tr"] = transport*params["transport"][0]/max(1,eng.base_c_tr)
        # Same slot and same cost in both arms. Choose resource by estimated workload.
        for slot in range(1,5):
            candidates = [a for a, ok in zip(kw["cat"],kw["adm"],strict=True)
                          if ok and a["kind"] in ("cl","tr") and a["slot"]==slot]
            if len(candidates)==2:
                return max(candidates,key=lambda a:scores[a["kind"]])
        return kw["cat"][0]
    return choose


def run(out):
    out.mkdir(parents=True,exist_ok=True)
    train = [L.prefix(W.episode(W.n_unit_structure("FILTER_SERVICE_TRAIN",i,4,regime="fragile"),0),72)
             for i in range(12)]
    params = {k:fit_service(train,k) for k in ("cleaning","transport")}
    rows = []
    for i in range(12):
        spec = W.episode(W.n_unit_structure("FILTER_DECISION_TEST",i,4,regime="fragile"),0)
        pre = L.prefix(spec,48)
        for future in (1,2):
            pair = {}
            for arm in ("reported","filtered"):
                result = L.closed_loop(spec,pre,future,policy(params,arm=="filtered"),4,6,24)
                pair[arm] = result
            assert pair["reported"]["staff_hours"] == pair["filtered"]["staff_hours"]
            rows.append(dict(structure=i,future=future,**pair))
    (out/"decisions.json").write_text(json.dumps({"fitted":params,"pairs":rows},indent=2)+"\n")


if __name__=="__main__":
    run(Path(sys.argv[1]))
