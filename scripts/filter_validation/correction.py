"""Lifecycle correction and decision audit; independent holdout, no fitted test parameters."""
import argparse
import copy
import json
from pathlib import Path

import numpy as np
import campaign as C
from campaign import W, L, A, P
from hospitalos.howm.history import PublicStream
from hospitalos.howm.keys import key
from service_filter import ServiceLaw

PROTOCOL = json.loads(Path(__file__).with_name("correction_protocol.json").read_text())


class LegacyPublicStream(W.PublicStreamN):
    """The exact pre-correction same-tick behavior, solely for paired ablation."""
    _bed = PublicStream._bed

    def _apply(self, o):
        ev, _, kind, _, _, v = o
        if kind == "departure" and v.get("bed") in self.beds:
            es = self.beds[v["bed"]]
            keep = dict(es.data) if es.data.get("state") == "cleaning" and es.data.get("since") == ev else None
            super()._apply(o)
            if keep is not None:
                es.data = keep
            return
        super()._apply(o)


def view(pre, rec, tick, legacy=False):
    cls = LegacyPublicStream if legacy else W.PublicStreamN
    ps = cls([o for o in pre["obs"] + rec.obs if o[1] < tick * 15])
    ps.advance(tick * 15 - 1)
    return ps, ps.to_engine_n(tick)


def reconcile_placements(eng, provider):
    """Complete a sampled current state with feasible public-queue placements.

    This is a constrained approximation, not an exact historical posterior.
    Inferred placements use the previous tick; private future attributes are
    independent samples, refreshed by the planner. No new arrivals are invented.
    """
    now = eng.tick
    eng.tick = max(0, now - 1)
    try:
        for unit, queue in eng.queue.items():
            for request in list(queue):
                if request.arrival >= now:
                    continue
                free = eng.free_beds(unit)
                compatible = ([b for b in free if b.iso] if request.iso
                              else sorted(free, key=lambda b: (b.iso, b.bed_id)))
                if not compatible:
                    continue
                bed = min(compatible, key=lambda b: b.bed_id) if request.iso else compatible[0]
                queue.remove(request)
                eng.place(request, bed, provider)
    finally:
        eng.tick = now
    assert_consistent(eng)
    return eng


def assert_consistent(eng):
    occupants = []
    for bed in eng.beds.values():
        if bed.state == "occ":
            stay = eng.stays[bed.stay]
            assert stay.departed is None and stay.bed == bed.bed_id
            assert not stay.iso or bed.iso
            occupants.append(stay.sid)
        else:
            assert bed.stay is None
    assert len(occupants) == len(set(occupants))
    assert all(s.bed in eng.beds and eng.beds[s.bed].stay == s.sid
               for s in eng.stays.values() if s.departed is None)
    assert not ({"S" + q.rid[1:] for queue in eng.queue.values() for q in queue} & set(occupants))


def posterior(pe, ps, laws, draw, provider):
    return reconcile_placements(C.sampled_engine(pe, ps, laws, draw), provider)


def counts(eng, unit):
    beds = [eng.beds[b] for b in eng.units[unit].beds]
    return {"free_beds": len(eng.free_beds(unit)),
            "cleaning": sum(b.state == "cleaning" for b in beds),
            "transport": sum(eng.stays[s].unit == unit for s in eng.tr_service),
            "occupied": sum(b.state == "occ" for b in beds),
            "queue": len(eng.queue.get(unit, []))}


def calibration(sp, pre, realisation, laws):
    eng, prov, rec = L.start_future(pre, sp, realisation)
    rows = []
    while eng.tick < pre["t0"] + 96:
        if eng.tick % 4 == 0:
            ps, pe = view(pre, rec, eng.tick)
            _, old = view(pre, rec, eng.tick, legacy=True)
            naive_free, naive_clean, naive_tr, _ = C.estimates(ps, pe, laws, eng.tick * 15)
            planning_spec = copy.deepcopy(sp)
            planning_spec.ekey = key("FILTER_V3_CALIBRATION", sp.part, sp.idx, eng.tick)
            particles = [posterior(pe, ps, laws, d, W.ProvN(planning_spec, d))
                         for d in PROTOCOL["calibration_draws"]]
            for unit in eng.units:
                truth, public, legacy = counts(eng, unit), counts(pe, unit), counts(old, unit)
                sample_counts = [counts(p, unit) for p in particles]
                naive = dict(public, free_beds=naive_free[unit], cleaning=naive_clean[unit], transport=naive_tr[unit])
                for metric in truth:
                    rows.append(dict(tick=eng.tick, unit=unit, metric=metric, truth=truth[metric],
                                     legacy=legacy[metric], public=public[metric], service_only=naive[metric],
                                     lifecycle=float(np.mean([v[metric] for v in sample_counts]))))
        eng.step(prov)
    return rows


def choices(pe, units, start, end):
    """Include abstention; never buy a slot extending beyond measured follow-up."""
    cat = A.catalogue(pe, units)
    eligible = [a for a in cat if a["kind"] in ("cl", "tr") and a["end"] <= end
                and A.admissible(pe, a, len(units), start)]
    if not eligible:
        return [cat[0]]
    earliest = min(a["start"] for a in eligible)
    return [cat[0]] + [a for a in eligible if a["start"] == earliest]


def run_policy(sp, pre, realisation, laws, arm):
    eng, prov, rec = L.start_future(pre, sp, realisation)
    tracker = L.Tracker(eng)
    start, end = eng.tick, eng.tick + 96
    logs = []
    while eng.tick < end:
        if (eng.tick - start) % 24 == 0:
            ps, pe = view(pre, rec, eng.tick, legacy=arm == "legacy")
            actions = choices(pe, sp.units, start, end)
            costs = np.zeros(len(actions))
            planning_spec = copy.deepcopy(sp)
            planning_spec.ekey = key("FILTER_V3_PLANNING", sp.part, sp.idx, eng.tick)
            for draw in PROTOCOL["planning_draws"]:
                if arm == "true_state":
                    initial = eng.clone()
                elif arm == "lifecycle":
                    initial = posterior(pe, ps, laws, draw, W.ProvN(planning_spec, draw))
                else:
                    initial = pe
                for i, action in enumerate(actions):
                    costs[i] += P.sim_rollout(initial, W.ProvN(planning_spec, draw), [action],
                                              (end - eng.tick) // 4, 6, sp.n, start)
            costs /= len(PROTOCOL["planning_draws"])
            chosen = actions[P.choose(costs, [[a] for a in actions])]
            assert A.admissible(eng, chosen, sp.n, start)
            assert chosen["end"] <= end
            A.apply(eng, chosen, W._Cal(prov, sp.drop))
            logs.append(dict(tick=eng.tick, action=chosen["id"], start=chosen["start"], end=chosen["end"],
                             candidates=[a["id"] for a in actions], costs=costs.tolist(),
                             predicted_gain_vs_none=float(costs[0] - min(costs))))
        eng.step(prov)
        tracker.tick(eng)
    result = tracker.result(eng)
    result["decisions"] = logs
    return result


def evaluate(out, index, partition):
    params = json.loads(Path(PROTOCOL["frozen_fit"]).read_text())
    for delay in PROTOCOL["delays"]:
        sp = C.structure(partition, index, delay)
        pre = L.prefix(sp, PROTOCOL["origin_hours"])
        laws = {k: ServiceLaw(**v["law"]) for k, v in params[str(delay)].items()}
        futures = []
        for realisation in PROTOCOL["futures"]:
            states = calibration(sp, pre, realisation, laws)
            arms = {a: run_policy(sp, pre, realisation, laws, a) for a in PROTOCOL["arms"]}
            futures.append(dict(realisation=realisation, states=states, arms=arms))
        (out / f"structure_{index:02d}_delay_{delay}.json").write_text(
            json.dumps(dict(structure=index, delay=delay, partition=partition, futures=futures)) + "\n")
        print("Completed", partition, index, delay, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    evaluate(args.out, args.index, PROTOCOL["dev_partition" if args.dev else "test_partition"])
