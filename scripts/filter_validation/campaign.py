"""Run the frozen two-stage validation on the existing hospital engine."""
import argparse
import copy
from dataclasses import asdict
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"))
from hospitalos.howmint import world as W, loop as L, actions as A, planners as P
from hospitalos.howm.keys import key, u
from service_filter import candidates, fit

PROTOCOL=json.loads(Path(__file__).with_name("protocol.json").read_text())


def structure(part,index,delay):
    sp=W.n_unit_structure(part,index,4,regime="fragile",bottlenecks=("cleaning","transport"))
    sp.theta["lag_min"]=delay
    return W.episode(sp,0)


def train(out):
    from service_filter import records
    fitted={}
    for delay in PROTOCOL["report_delay_means_minutes"]:
        pooled={k:[] for k in ("cleaning","transport")}
        for index in range(PROTOCOL["training_structures_per_delay"]):
            sp=structure(PROTOCOL["training_partition"],index,delay)
            pre=L.prefix(sp,PROTOCOL["training_cutoff_hours"])
            for kind in pooled:
                pooled[kind].extend(records(pre["obs"],pre["t0"]*15,kind))
        fitted[str(delay)]={}
        for kind,items in pooled.items():
            law,diag=fit(items,zero_lag=delay==0)
            fitted[str(delay)][kind]={"law":asdict(law),**diag}
        print("Fitted",delay,fitted[str(delay)],flush=True)
    (out/"fit.json").write_text(json.dumps(fitted,indent=2)+"\n")


def estimates(ps,pe,laws,now):
    tasks=candidates(ps,laws,now)
    free={unit:float(len(pe.free_beds(unit))) for unit in pe.units}
    clean={unit:float(sum(pe.beds[b].state=="cleaning" for b in pe.units[unit].beds)) for unit in pe.units}
    tr={unit:float(sum(sid in pe.tr_service and pe.stays[sid].unit==unit for sid in pe.stays)) for unit in pe.units}
    for kind,ref,_,prob in tasks:
        if kind=="cleaning":
            unit=pe.beds[ref].unit
            free[unit]+=1-prob
            clean[unit]-=1-prob
        else:
            tr[pe.stays[ref].unit]-=1-prob
    return free,clean,tr,tasks


def calibration(sp,pre,realisation,laws):
    eng,prov,rec=L.start_future(pre,sp,realisation)
    rows,services=[],[]
    end=eng.tick+24*4
    while eng.tick<end:
        if eng.tick%4==0:
            ps,pe=L.public_view(pre,rec,eng.tick)
            free,clean,tr,tasks=estimates(ps,pe,laws,eng.tick*15)
            for unit in eng.units:
                for name,estimate,raw,truth in [
                    ("free_beds",free[unit],len(pe.free_beds(unit)),len(eng.free_beds(unit))),
                    ("cleaning",clean[unit],sum(pe.beds[b].state=="cleaning" for b in pe.units[unit].beds),sum(eng.beds[b].state=="cleaning" for b in eng.units[unit].beds)),
                    ("transport",tr[unit],sum(pe.stays[s].unit==unit for s in pe.tr_service),sum(eng.stays[s].unit==unit for s in eng.tr_service))]:
                    rows.append(dict(tick=eng.tick,unit=unit,metric=name,filtered=estimate,reported=raw,truth=truth))
            for kind,ref,start,prob in tasks:
                if kind=="cleaning":
                    bed=eng.beds[ref]
                    truth=int(bed.state=="cleaning" and bed.clean_start==start//15)
                else:
                    truth=int(ref in eng.tr_service)
                services.append(dict(tick=eng.tick,kind=kind,ref=ref,start=start,prob=prob,truth=truth))
        eng.step(prov)
    return rows,services


def sampled_engine(pe,ps,laws,draw):
    """Apply sampled unreported completions to a public engine, preserving bed/stay constraints."""
    eng=pe.clone()
    eng.on_event=None
    for kind,ref,start,prob in candidates(ps,laws,eng.tick*15):
        if u("FILTER_V2_POSTERIOR",draw,eng.tick,kind,ref,start)<prob:
            continue
        if kind=="cleaning":
            bed=eng.beds[ref]
            bed.state="free"
            bed.clean_start=bed.clean_end=bed.dirty_tick=None
        else:
            stay=eng.stays[ref]
            eng.tr_service.remove(ref)
            stay.tr_end=eng.tick-1
            eng.depart(stay)
    return eng


def choose_candidates(pe,units,t_start):
    cat=A.catalogue(pe,units)
    for slot in range(1,5):
        pair=[a for a in cat if a["kind"] in ("cl","tr") and a["slot"]==slot
              and A.admissible(pe,a,len(units),t_start)]
        if len(pair)==2:
            return pair
    return [cat[0]]


def run_policy(sp,pre,realisation,laws,arm):
    eng,prov,rec=L.start_future(pre,sp,realisation)
    tracker=L.Tracker(eng)
    start=eng.tick
    logs=[]
    while eng.tick<start+24*4:
        if (eng.tick-start)%(6*4)==0:
            ps,pe=L.public_view(pre,rec,eng.tick)
            choices=choose_candidates(pe,sp.units,start)
            costs=None
            if arm=="workload_rule":
                dirty=sum(b.state in ("dirty","cleaning") for b in pe.beds.values())
                transport=sum(s.ready and s.transport and s.departed is None and s.tr_end is None
                              for s in pe.stays.values())+len(pe.tr_service)
                score={"cl":dirty*laws["cleaning"].median/max(1,pe.base_c_cl),
                       "tr":transport*laws["transport"].median/max(1,pe.base_c_tr),"none":0.}
                chosen=max(choices,key=lambda a:score[a["kind"]])
            else:
                costs=np.zeros(len(choices))
                for draw in PROTOCOL["planning_realisations"]:
                    if arm=="true_state_planner":
                        initial=eng.clone()
                    elif arm=="filtered_planner":
                        initial=sampled_engine(pe,ps,laws,draw)
                    else:
                        initial=pe
                    # Same structural parameters for all arms, fresh future and no true regime anchor.
                    planning_spec=copy.deepcopy(sp)
                    planning_spec.ekey=key("FILTER_V2_PLANNING",sp.part,sp.idx,eng.tick)
                    for i,action in enumerate(choices):
                        provider=W.ProvN(planning_spec,draw)
                        costs[i]+=P.sim_rollout(initial,provider,[action],24,6,sp.n,start)
                costs/=len(PROTOCOL["planning_realisations"])
                chosen=choices[int(np.argmin(costs))]
            if not A.admissible(eng,chosen,sp.n,start):
                raise AssertionError("Selected action is inadmissible in true engine")
            A.apply(eng,chosen,W._Cal(prov,sp.drop))
            logs.append(dict(tick=eng.tick,action=chosen["id"],predicted_costs=None if costs is None else costs.tolist(),
                             candidates=[a["id"] for a in choices]))
        eng.step(prov)
        tracker.tick(eng)
    result=tracker.result(eng)
    result["decisions"]=logs
    return result


def evaluate(out,index):
    from service_filter import ServiceLaw
    params=json.loads((out/"fit.json").read_text())
    for delay in PROTOCOL["report_delay_means_minutes"]:
        laws={kind:ServiceLaw(**record["law"]) for kind,record in params[str(delay)].items()}
        sp=structure(PROTOCOL["test_partition"],index,delay)
        pre=L.prefix(sp,PROTOCOL["origin_hours"])
        result=dict(structure=index,delay=delay,futures=[])
        for realisation in PROTOCOL["future_realisations"]:
            states,tasks=calibration(sp,pre,realisation,laws)
            arms={}
            for arm in PROTOCOL["policies"]:
                arms[arm]=run_policy(sp,pre,realisation,laws,arm)
            budgets=[r["staff_hours"] for r in arms.values()]
            assert len(set(budgets))==1,budgets
            result["futures"].append(dict(realisation=realisation,states=states,tasks=tasks,arms=arms))
        path=out/f"structure_{index:02d}_delay_{delay}.json"
        path.write_text(json.dumps(result)+"\n")
        print("Completed",index,delay,flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=["fit","evaluate"])
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--index",type=int,default=0)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    if args.mode=="fit":
        train(args.out)
    else:
        evaluate(args.out,args.index)
