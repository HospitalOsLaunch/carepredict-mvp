"""Register, assign, reveal and evaluate matched operational decisions."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl
import json
import multiprocessing as mp
from pathlib import Path
import numpy as np

from cible.data import conditions, fingerprint, key, make_public, operator_files, paired, rows, sha_file, valid_sha, world_sha, write_rows
from cible.engine import prepare,outcomes
from cible.study import write_json
from j7.episodes import first_week
from lot28 import simulator as sim
from .model import ARMS, CAL, FIT, HOURS, OUT, ROOT, TOL, WEIGHTS, choices, incumbent, load_model, public_case

BASE=ROOT.parent/"base"
TEST=tuple(range(116000,116064))
FILES={"assign":("public_test.jsonl.gz","affectations.jsonl.gz"),"reveal":("issues.jsonl.gz",)}
PREVIOUS_ARCHIVE="7adb566b03fb48661984bab010be9965360ab3195a43281f54c9128a790d1c15"
PRIMARY="hierarchique"
EXPECTED={s:tuple((s,e,f,h) for e,_,f,h in conditions()) for s in TEST}


@contextmanager
def exclusive():
    OUT.mkdir(exist_ok=True)
    with (OUT/".execution.lock").open("a+b") as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        yield


def decide(packet,weights,weight_sha):
    c=public_case(packet)
    selected,traces=choices(weights,c)
    rec={k:packet[k] for k in ("site","episode","feed","history","prefix_sha256","public_sha256","actions")}
    rec.update(minute=10080,choices=selected,trace=traces,p_safe=c.p_safe.tolist(),model_sha256=weight_sha)
    return {**rec,"decision_sha256":fingerprint(rec)}


def dependencies():
    required=set(ROOT.glob("*.py"))|{ROOT/"PROTOCOLE.md",WEIGHTS,OUT/"ajustement.json",OUT/"validation_dev.json"}
    required.update(operator_files())
    required.update(BASE/k for k in ("cible/model.py","executabilite/regle.py","cible/study.py",
                                       "cible_resultats/modele_cible.npz"))
    required.update(BASE/"cible_resultats"/(k+"_"+split+".jsonl.gz") for k in ("paires","public") for split in ("train","dev"))
    return {p.relative_to(ROOT.parent).as_posix():sha_file(p) for p in sorted(required)}


def seal():
    with exclusive():
        reserved={"gel.json","gel.sha256","recu_assign.json","recu_reveal.json","verdict.json","public_test.jsonl.gz",
                  "affectations.jsonl.gz","issues.jsonl.gz","shards_assign","shards_reveal"}
        if any((OUT/f).exists() for f in reserved):raise ValueError("Existing holdout material precludes a prospective lock")
        if set(TEST)&(set(FIT)|set(CAL)|set(range(102000,102032))):raise ValueError("Overlapping site cohorts")
        record={"registered_utc":datetime.now(timezone.utc).isoformat(),"parent_archive_sha256":PREVIOUS_ARCHIVE,
                "sites":list(TEST),"conditions_per_hospital":18,"widths":[8,4],"horizons":list(HOURS),
                "primary_horizon":72,"arms":list(ARMS),"inputs":dependencies()}
        write_json(OUT/"gel.json",record)
        digest=sha_file(OUT/"gel.json");(OUT/"gel.sha256").write_text(digest+"\n")
        return digest


def verify(lock):
    if not valid_sha(lock) or sha_file(OUT/"gel.json")!=lock or (OUT/"gel.sha256").read_text().strip()!=lock:
        raise ValueError("Foreign study lock")
    record=json.loads((OUT/"gel.json").read_text())
    if record["inputs"]!=dependencies() or record["sites"]!=list(TEST) or record["parent_archive_sha256"]!=PREVIOUS_ARCHIVE:
        raise ValueError("Frozen policies, data, or target panel changed")
    return record


def verify_receipt(stage,expected,lock,parents):
    path=OUT/("recu_"+stage+".json")
    if not valid_sha(expected) or sha_file(path)!=expected:raise ValueError("Incorrect prospectively retained stage receipt")
    spec=dict(stage=stage,lock=lock,parents=parents,contexts=18*len(TEST),files={k:sha_file(OUT/k) for k in FILES[stage]})
    if json.loads(path.read_text())!=spec:raise ValueError("Stage files, chronology or population changed")


def _run_site(task):
    stage,sid,models_sha=task
    episodes={e:sim.episode(sid,e) for e in (0,1)}
    xout=[];values=[];weights=load_model()
    decisions=None
    if stage=="reveal":decisions=list(rows(OUT/"shards_assign"/(str(sid)+"_v.gz")))
    for n,(eid,mask,feed,hist) in enumerate(conditions()):
        ep=episodes[eid]
        cp=first_week(ep,mask,hist);ctx=prepare(ep,mask,hist,cp)
        packet=make_public(ep,feed,hist,ctx)
        assignment=decide(packet,weights,models_sha)
        if stage=="assign":
            xout.append(packet);values.append(assignment)
        else:
            if assignment!=decisions[n]:raise ValueError("An assignment failed blind replay before reading a future")
            physical=outcomes(ep,ctx,cp)
            d={k:assignment[k] for k in ("site","episode","feed","history","public_sha256","prefix_sha256","actions","decision_sha256")}
            values.append({**d,"world_sha256":world_sha(ep),"cost":physical.cost.tolist(),
                           "guards":physical.guards.tolist(),"delivery":physical.delivery.tolist()})
    folder=OUT/("shards_"+stage)
    if stage=="assign":write_rows(folder/(str(sid)+"_p.gz"),xout)
    write_rows(folder/(str(sid)+"_v.gz"),values)
    return sid


def _merge(stage,article,output):
    def gen():
        for site in TEST:
            for line,ident in zip(rows(OUT/("shards_"+stage)/(str(site)+"_"+article+".gz")),EXPECTED[site],strict=True):
                if key(line)!=ident:raise ValueError("Missing, foreign or duplicated hospital context")
                yield line
    write_rows(OUT/output,gen())


def run(stage,lock,assigned=None,workers=6):
    with exclusive():
        verify(lock)
        parents={}
        if stage=="reveal":
            verify_receipt("assign",assigned,lock,{})
            parents={"assign":assigned}
            # The sealed aggregate, not an orphan shard, is the source of staged decisions.
            by_site={sid:[] for sid in TEST}
            for line in rows(OUT/"affectations.jsonl.gz"):by_site[line["site"]].append(line)
            for sid,z in by_site.items():
                if [key(x) for x in z]!=list(EXPECTED[sid]):raise ValueError("Incomplete prospective assignment file")
                write_rows(OUT/"shards_assign"/(str(sid)+"_v.gz"),z)
        receipt=OUT/("recu_"+stage+".json")
        if receipt.exists():
            found=sha_file(receipt);verify_receipt(stage,found,lock,parents)
            return found
        if workers<1:raise ValueError("Need at least one worker")
        incumbent();sim._kernel()
        (OUT/("shards_"+stage)).mkdir(exist_ok=True)
        with ProcessPoolExecutor(workers,mp_context=mp.get_context("fork")) as pool:
            for n,sid in enumerate(pool.map(_run_site,[(stage,sid,sha_file(WEIGHTS)) for sid in TEST]),1):
                if n in (1,16,32,48,64):print(f"{stage} {n}/{len(TEST)}",flush=True)
        for article,name in zip(("p","v") if stage=="assign" else ("v",),FILES[stage],strict=True):_merge(stage,article,name)
        verify(lock)
        r=dict(stage=stage,lock=lock,parents=parents,contexts=18*len(TEST),files={k:sha_file(OUT/k) for k in FILES[stage]})
        write_json(receipt,r)
        return sha_file(receipt)


def _interval(values,bootstrap):
    x=np.asarray(values,float)
    return dict(mean=float(x.mean()),cluster_95=np.quantile(bootstrap@x/len(x),[.025,.975]).tolist())


def assess(records):
    all_sites={}
    catalog=[];routing=[];raw_agree=0;active_upper=0;delivery_logged=False
    for d,actual in records:
        sid,eid,feed,h=key(d)
        if key(actual)!=key(d) or actual["actions"]!=d["actions"] or d["prefix_sha256"]!=actual["prefix_sha256"]:
            raise ValueError("Crossed context or option labels")
        v=np.asarray(actual["cost"],float);a=np.asarray(d["actions"])
        if not np.isfinite(v).all() or v.shape!=(len(a),3,len(a)//4,4) or np.any(v< -TOL):
            raise ValueError("Unexpected paired outcomes")
        if "decision_sha256" in actual and actual["decision_sha256"]!=d["decision_sha256"]:raise ValueError("Outcomes relabelled")
        if d["decision_sha256"]!=fingerprint({k:z for k,z in d.items() if k!="decision_sha256"}):raise ValueError("Broken decision fingerprint")
        w=v.shape[2];effects=v-v[:1];margins=effects[...,1:]-.01*v[None,0,...,1:]
        delivery_logged |= "delivery" in actual
        if "guards" in actual and np.asarray(actual["guards"]).any():raise ValueError("Hard simulator violation")
        trace=d["trace"];catalog.append([trace["n_catalogue"],trace["n_eligible"],trace["n_macros"],trace["n_fine"]])
        raw_agree+=d["choices"]["plat_brut"]==d["choices"]["hierarchique_brut"]
        active_upper+=trace["macro_kind"]!=0
        if trace["macro_kind"]:routing.append(trace["n_fine"])
        if sid not in all_sites:
            all_sites[sid]={q:dict(count=0,gains=np.zeros(3),deltas=np.zeros((3,4)),
                                   harms=np.zeros(3,int),by_role=np.zeros((3,3),int),
                                   margin_sums=np.zeros((3,w,3)),kinds=np.zeros(7,int),
                                   zero_effect=np.zeros(3,int),delivered=np.zeros(3,int)) for q in (*ARMS,"oracle")}
        for arm,z in all_sites[sid].items():
            if arm=="oracle":
                # One hindsight comparator at each horizon.
                good=(margins<=TOL).all((2,3));g=-effects[...,0].sum(2)
                indices=np.argmax(np.where(good,g,-np.inf),axis=0)
            else:indices=np.full(3,d["choices"][arm])
            hrs=np.arange(3)
            result=effects[indices,hrs];actual_margin=margins[indices,hrs]
            z["count"]+=1;z["gains"]-=result[:,:,0].sum(1)
            z["deltas"]+=result.sum(1)
            z["harms"]+=(actual_margin>TOL).any((1,2))
            z["by_role"]+=(actual_margin>TOL).any(1)
            z["margin_sums"]+=actual_margin
            ix=int(indices[1]);z["kinds"][a[ix,0]]+=1
            z["zero_effect"]+=(abs(result)<=TOL).all((1,2))
            if ix and "delivery" in actual:
                delivery=actual["delivery"][ix]
                z["delivered"]+=np.asarray([1,delivery[3]>0,delivery[0]==1],int)
    n=len(all_sites)
    if not n:raise ValueError("Empty cohort")
    b=np.random.default_rng(700063).multinomial(n,np.full(n,1/n),size=20000)
    reports={};gains={}
    for arm in (*ARMS,"oracle"):
        z=[all_sites[sid][arm] for sid in sorted(all_sites)]
        gains[arm]=np.array([r["gains"]/r["count"] for r in z])
        names=("24","72","168")
        sr={}
        for j,name in enumerate(names):
            local=[r["margin_sums"][j]/r["count"]>TOL for r in z]
            hit=np.concatenate(local)
            sr[name]={"gain_transfer_h":_interval(gains[arm][:,j],b),"harmful_contexts":int(sum(r["harms"][j] for r in z)),
                      "harmful_contexts_bed_ide_as":sum(r["by_role"][j] for r in z).tolist(),
                      "site_ward_role_breaches":int(hit.sum()),"site_ward_breaches":int(hit.any(1).sum()),
                      "sites_with_any_ward_breach":int(sum(m.any() for m in local)),
                      "ward_role_breaches_bed_ide_as":hit.sum(0).tolist(),
                      "unchanged_all_ward_costs":int(sum(r["zero_effect"][j] for r in z)),
                      "mean_cost_delta_transfer_bed_ide_as":np.mean([r["deltas"][j]/r["count"] for r in z],axis=0).tolist()}
        reports[arm]={"horizon":sr,"choice_counts_by_kind_0_4_5_6":sum(r["kinds"] for r in z)[[0,4,5,6]].tolist(),
                      "active_delivered_ge_1h_already_planned":sum(r["delivered"] for r in z).tolist() if delivery_logged else None}
    contrasts={}
    for selected,ref in (("hierarchique","horaire"),("hierarchique","j7_livre"),("hierarchique","plat"),
                         ("plat","j7_livre"),("hierarchique_brut","plat_brut"),("hierarchique_brut","horaire")):
        contrasts[selected+"_vs_"+ref]=_interval(gains[selected][:,1]-gains[ref][:,1],b)
    primary=reports[PRIMARY]["horizon"]["72"]
    return {"sites":n,"contexts":len(catalog),"n_site_wards":sum(all_sites[s]["horaire"]["margin_sums"].shape[1] for s in all_sites),
            "means_catalogue_eligible_families_lower_candidates":np.mean(catalog,axis=0).tolist(),
            "total_nonzero_catalogue_offers":int(np.asarray(catalog)[:,0].sum()-len(catalog)),
            "raw_same_primitive":raw_agree,"raw_nonzero_upper":active_upper,
            "mean_lower_refinements_when_active":float(np.mean(routing)) if routing else None,
            "arms":reports,"paired_cluster_contrasts_h72":contrasts,
            "demonstrated_operational_improvement":bool(primary["site_ward_role_breaches"]==0 and
                 all(contrasts["hierarchique_vs_"+ref]["cluster_95"][0]>0 for ref in ("horaire","j7_livre","plat"))),
            "method":"Two-sided percentile intervals, 20000 hospital-cluster resamples, 18 matched contexts per hospital."}


def dev():
    w=load_model();weights=sha_file(WEIGHTS)
    def records():
        for p,y in paired("dev"):
            yield decide(p,w,weights),y
    report=assess(records());write_json(OUT/"validation_dev.json",report)
    return report


def verdict(lock,assigned,revealed):
    verify(lock);verify_receipt("assign",assigned,lock,{})
    verify_receipt("reveal",revealed,lock,{"assign":assigned})
    report=assess(zip(rows(OUT/"affectations.jsonl.gz"),rows(OUT/"issues.jsonl.gz"),strict=True))
    if report["sites"]!=len(TEST) or report["contexts"]!=len(TEST)*18:raise ValueError("Incomplete held-out panel")
    report["provenance"]={"lock":lock,"assign":assigned,"reveal":revealed}
    write_json(OUT/"verdict.json",report);return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage",choices=("dev","seal","assign","reveal","verdict"))
    p.add_argument("--workers",type=int,default=6);p.add_argument("--lock");p.add_argument("--assign");p.add_argument("--reveal")
    a=p.parse_args()
    if a.stage=="dev": print(dev()["paired_cluster_contrasts_h72"],flush=True)
    elif a.stage=="seal":print(seal(),flush=True)
    elif a.stage in FILES:print(run(a.stage,a.lock,a.assign,a.workers),flush=True)
    else:print(verdict(a.lock,a.assign,a.reveal)["paired_cluster_contrasts_h72"],flush=True)
if __name__=="__main__":main()
