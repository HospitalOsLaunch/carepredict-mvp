"""Independent supplemental test of physical census projection, with externally retained stage receipts."""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl
import json
from pathlib import Path
import numpy as np

from cf import experience as original
from cf import mesures
from cible.study import write_json
from .projection import reconstruire

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"contraintes/resultats"
SITES=tuple(range(117000,117032))
PARENT=("fb18eefc9b03a2877c8fb0745050ee635dc98785787a4c040b39c9a5664ab693",
        "b4b287c16940c22899fa2cf0daba3e838b9a70418955451861634dcd5a5fa2bc",
        "a5e5a7a28b0077193017e22aef261807c8ba68971e2d9c23eae380833e85b200",
        "100f06fc7416b7df70605a6bb24d737c00a126b7d21539298c17c464699f3f4f")
COLS=("base_mae","copy_mae","raw_mae","projected_mae","raw_effect_mae","projected_effect_mae",
      "raw_invalid","projected_invalid","raw_state_mse","projected_state_mse","max_change_contrast",
      "reversed_comparable","comparable_order_pairs","invalid_at_cutoff","mae_at_cutoff","max_l2_increase")


def design():
    return dict(sites=list(SITES),parent_receipts=list(PARENT),endpoints=original.settings(),method="Euclidean census projection",
                primary="outside fraction then MAE: full feed, 12:00, four hours, historical JEPA seed 19",seed=261119,draws=20000)


def dependencies():
    names=[*(ROOT/"contraintes").glob("*.py"),*(ROOT/"contraintes/tests").glob("*.py"),
           ROOT/"contraintes/PROTOCOLE.md",original.OUT/"resultats.json"]
    return {p.relative_to(ROOT).as_posix():original.sha(p) for p in sorted(names)}


@contextmanager
def hold():
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/".lock").open("a+b") as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        yield


def seal():
    with hold():
        if any(x.name!=".lock" for x in OUT.iterdir()):raise ValueError("Panel already begun")
        original.verify_all(*PARENT)
        if set(SITES)&set(original.TEST):raise ValueError("Prior hospital reused")
        write_json(OUT/"gel.json",dict(registered_utc=datetime.now(timezone.utc).isoformat(),design=design(),files=dependencies()))
        return original.sha(OUT/"gel.json")


def verify(lock):
    if original.sha(OUT/"gel.json")!=lock:raise ValueError("External projection lock differs")
    r=json.loads((OUT/"gel.json").read_text())
    if r["design"]!=design() or r["files"]!=dependencies():raise ValueError("Projection trial changed")
    original.verify_all(*PARENT)


def stage(which,lock,ancres,workers):
    with hold():
        verify(lock);last=None
        for previous,receipt in zip(original.STAGES[:original.STAGES.index(which)],ancres):
            original.receipt(OUT,previous,lock,last,receipt,SITES);last=receipt
        if not (OUT/("recu_"+which+".json")).exists() and any((OUT/n).exists() for n in original.STAGES[original.STAGES.index(which)+1:]):
            raise ValueError("Later stage already exists")
        return original.generate(which,OUT,lock,last,SITES,workers)


def bad(z,beds):
    return (z.min(-1)<-1.e-7)|(z[...,1:].sum(-1)>beds+1.e-7)


def row(x,t,report,mask,a,beds,idx,hour,published):
    after=mesures.anchored(x,report,mask,idx,published,published)
    constrained=reconstruire(x,idx,report,mask,beds,heure_consultation=published,heure_publication=published)
    now=reconstruire(x,idx,report,mask,beds,heure_consultation=hour,heure_publication=published)
    q=mesures.stock
    z=q(t);raw=q(after);out=q(constrained)
    actual=z[a]-z[idx];draw=raw[a]-raw[idx];dout=out[a]-out[idx]
    raw_dist=np.square(after[a]-t[a]).sum(-1);out_dist=np.square(constrained[a]-t[a]).sum(-1)
    increase=float(np.max(out_dist-raw_dist))
    if increase>1.e-6 or bad(constrained,beds).any():raise ValueError("Projection failed physical distance invariant")
    order=raw.sum(1);next_order=out.sum(1);u=np.r_[idx,a];i,j=np.triu_indices(len(u),1)
    diff=order[u[i]]-order[u[j]];diff2=next_order[u[i]]-next_order[u[j]]
    comparison=(abs(diff)>1e-8)&(abs(diff2)>1e-8)
    return [np.abs(q(x)[a]-z[a]).mean(),np.abs(raw[idx]-z[a]).mean(),np.abs(raw[a]-z[a]).mean(),
            np.abs(out[a]-z[a]).mean(),np.abs(draw-actual).mean(),np.abs(dout-actual).mean(),
            bad(after[a],beds).mean(),bad(constrained[a],beds).mean(),raw_dist.mean()/5,out_dist.mean()/5,
            np.max(abs(draw-dout)),int((comparison&(diff*diff2<0)).sum()),int(comparison.sum()),
            bad(now[a],beds).mean(),abs(q(now)[a]-z[a]).mean(),increase]


def run_analysis(lock,ancres):
    verify(lock);last=None
    for previous,h in zip(original.STAGES,ancres,strict=True):
        original.receipt(OUT,previous,lock,last,h,SITES);last=h
    arr=np.empty((len(SITES),2,3,2,5,4,len(COLS)))
    for si,s in enumerate(SITES):
        for e in (0,1):
            for fi,feed in enumerate(original.FEEDS):
                for oi,offset in enumerate(original.CLOCKS):
                    name=original.record_name(s,e,feed,offset)
                    p,f,y=(original.payload(OUT/k/name) for k in original.STAGES)
                    idx=int(p["factual"]);a=original.alternatives(p["grid"],idx)
                    for hi,h in enumerate(original.H):
                        for mi in range(4):
                            arr[si,e,fi,oi,hi,mi]=row(p["pred"][mi,:,hi],y["states"][:,hi],f["reported"][hi],
                               f["mask"][hi],a,p["beds"],idx,int(p["source_hour"])+h,int(f["available_hour"][hi]))
    n=len(SITES);rep=np.random.default_rng(261119).multinomial(n,[1/n]*n,size=20000)/n
    col={name:i for i,name in enumerate(COLS)}
    detail={}
    for fi,feed in enumerate(original.FEEDS):
        for oi,offset in enumerate(original.CLOCKS):
            for hi,h in enumerate(original.H):
                for mi,model in enumerate(mesures.MODEL_NAMES):
                    values=arr[:,:,fi,oi,hi,mi];by_site=values.mean(1)
                    v={k:float(by_site[:,i].mean()) for k,i in col.items()}
                    v["lower_mae_vs_anchor"]=mesures.scalar(by_site[:,col["raw_mae"]]-by_site[:,col["projected_mae"]],rep)
                    v["lower_mae_vs_copy"]=mesures.scalar(by_site[:,col["copy_mae"]]-by_site[:,col["projected_mae"]],rep)
                    v["strict_rank_reversals"]=int(values[...,col["reversed_comparable"]].sum())
                    v["strict_pairs_compared"]=int(values[...,col["comparable_order_pairs"]].sum())
                    v["largest_action_contrast_change"]=float(values[...,col["max_change_contrast"]].max())
                    detail[f"{feed}/{8+offset:02d}/{h}/{model}"]=v
    write_json(OUT/"verdict.json",dict(sites=n,contexts=n*12,conditions=detail,primary=detail["full/12/4/jepa19"],
               any_invalid_after_projection=bool(np.any(arr[...,col["projected_invalid"]])),
               anchors=[lock,*ancres]))
    print(detail["full/12/4/jepa19"]["lower_mae_vs_anchor"])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("stage",choices=("seal",*original.STAGES,"score"))
    for label in ("lock","public","factuel","verite"):p.add_argument("--"+label)
    p.add_argument("--workers",type=int,default=4);a=p.parse_args();ancres=(a.public,a.factuel,a.verite)
    if a.stage=="seal":print(seal())
    elif a.stage=="score":run_analysis(a.lock,ancres)
    else:print(stage(a.stage,a.lock,ancres,a.workers))


if __name__=="__main__":main()
