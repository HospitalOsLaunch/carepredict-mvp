"""Summarize frozen validation with cluster bootstrap and fixed calibration bins."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def interval(frame,column):
    means=frame.groupby("structure")[column].mean().to_numpy()
    rng=np.random.default_rng(20261120)
    boot=means[rng.integers(len(means),size=(2000,len(means)))].mean(1)
    return dict(mean=float(means.mean()),ci95=np.quantile(boot,[.025,.975]).tolist(),structures=len(means))


def analyse(root):
    states,tasks,decisions,initial=[],[],[],[]
    files=sorted(root.glob("structure_*.json"))
    if len(files)!=24:
        raise ValueError(f"Expected 24 structure-delay files, found {len(files)}")
    for f in files:
        r=json.loads(f.read_text())
        common=dict(structure=r["structure"],delay=r["delay"])
        for future in r["futures"]:
            meta=dict(**common,future=future["realisation"])
            states.extend(dict(**meta,**v) for v in future["states"])
            tasks.extend(dict(**meta,**v) for v in future["tasks"])
            arms=future["arms"]
            for arm,result in arms.items():
                for metric in ("wait_patient_min","uncovered_care_min","staff_hours","terminal_queue","rejected"):
                    decisions.append(dict(**meta,arm=arm,metric=metric,value=result[metric]))
            first=arms["observed_planner"]["decisions"][0]
            costs=first["predicted_costs"]
            initial.append(dict(**meta,candidate_gap=abs(costs[0]-costs[1]) if len(costs)==2 else None,
                                filtered_differs=[a["action"] for a in arms["filtered_planner"]["decisions"]]!=[a["action"] for a in arms["observed_planner"]["decisions"]],
                                changed_actions=sum(a["action"]!=b["action"] for a,b in zip(arms["filtered_planner"]["decisions"],arms["observed_planner"]["decisions"],strict=True)),
                                oracle_changed_actions=sum(a["action"]!=b["action"] for a,b in zip(arms["true_state_planner"]["decisions"],arms["observed_planner"]["decisions"],strict=True))))
    s,t,d=pd.DataFrame(states),pd.DataFrame(tasks),pd.DataFrame(decisions)
    s["reported_error"]=(s.reported-s.truth).abs()
    s["filtered_error"]=(s.filtered-s.truth).abs()
    s["gain"]=s.reported_error-s.filtered_error
    t["reported_brier"]=(1-t.truth)**2
    t["filtered_brier"]=(t.prob-t.truth)**2
    t["gain"]=t.reported_brier-t.filtered_brier
    t["bin"]=np.minimum(9,np.floor(t.prob*10)).astype(int)
    calibration=t.groupby(["delay","kind","bin"]).agg(count=("truth","size"),probability=("prob","mean"),frequency=("truth","mean")).reset_index()
    calibration.to_csv(root/"calibration.csv",index=False)
    state_summary=[]
    for (delay,metric),frame in s.groupby(["delay","metric"]):
        state_summary.append(dict(delay=int(delay),metric=metric,reported_mae=float(frame.reported_error.mean()),filtered_mae=float(frame.filtered_error.mean()),gain=interval(frame,"gain")))
    task_summary=[]
    for (delay,kind),frame in t.groupby(["delay","kind"]):
        bins=calibration.query("delay==@delay and kind==@kind")
        ece=float(((bins.probability-bins.frequency).abs()*bins["count"]).sum()/bins["count"].sum())
        task_summary.append(dict(delay=int(delay),kind=kind,count=len(frame),reported_brier=float(frame.reported_brier.mean()),filtered_brier=float(frame.filtered_brier.mean()),ece=ece,gain=interval(frame,"gain")))
    outcomes=[]
    for (delay,metric),frame in d.groupby(["delay","metric"]):
        pivot=frame.pivot(index=["structure","future"],columns="arm",values="value").reset_index()
        for reference in ("workload_rule","observed_planner","true_state_planner"):
            pivot["gain"]=pivot[reference]-pivot.filtered_planner
            outcomes.append(dict(delay=int(delay),metric=metric,reference=reference,
                                 reference_mean=float(pivot[reference].mean()),filtered_mean=float(pivot.filtered_planner.mean()),gain=interval(pivot,"gain")))
    result=dict(state=state_summary,services=task_summary,outcomes=outcomes,action_diagnostics=initial)
    (root/"summary.json").write_text(json.dumps(result,indent=2)+"\n")
    for frame,name in ((s,"states"),(t,"services"),(d,"outcomes")):
        frame.to_csv(root/(name+".csv"),index=False)
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("directory",type=Path)
    analyse(parser.parse_args().directory)
