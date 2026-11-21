"""Prospective, hospital-paired comparison of the short and long action-conditioned latent planners."""
import argparse
import json
from pathlib import Path
import numpy as np

from cible import audit as acquired
from cible import model as old_model
from j7.review import contrast,rows
from hierarchie import model as impl
from .identites import file_sha,canon

NAMES=("horaire","j7_livre","physique","plat","hierarchique","plat_brut","hierarchique_brut","j7_initial")
SITES=tuple(range(116000,116064))
TOL=1e-8
SEED=700063


def summaries(p,actions):
    d=p-p[:1]
    ii=np.arange(len(d))
    tar=d[ii,np.maximum(actions[:,1],0)]
    don=d[ii,np.maximum(actions[:,2],0)]*(actions[:,0,None]==6)
    return np.column_stack((d.sum(1),d.min(1),d.max(1),tar,don))


def goal_index(v,goal,t,eligible):
    dd=np.sum((v-goal)**2,axis=1)
    keep=eligible&(t< -TOL)&(dd<dd[0]-1e-10);keep[0]=True
    return int(np.argmin(np.where(keep,dd,np.inf)))


def derive(w,p):
    actions,phys=acquired.read_public(p)
    raw=old_model.describe(p);up=impl.incumbent().predict(p)
    prob=np.asarray(up["p_safe"])
    past=acquired.expected_choices(actions,phys,np.asarray(up["transfer"]),prob,up["cutoff"])
    usable=(np.array(p["projection_delivery"])[:,[2,3,7]]>TOL).all(1)
    feasible=(prob>=.5)&usable;feasible[0]=True
    arr=np.asarray(raw.x,float)
    centered=np.clip((np.sign(arr)*np.log1p(abs(arr))-w["center"])/w["input_scale"],-8,8)
    phi=np.column_stack((centered@w["linear"]/np.sqrt(w["linear"].shape[1]),np.tanh(centered@w["nonlinear"]+w["phase"])))
    x=phi-phi[0]
    obs=np.stack([summaries(phys[:,j],actions) for j in (0,1)],axis=1)
    pn=obs/w["scale"]
    fhead=pn@w["flat_enc"]+(x@w["flat_pred"]).reshape(len(x),2,-1)
    linear=(fhead[:,1]@w["flat_decoder"])*w["scale"][1,0]
    flat=goal_index(fhead[:,1],w["flat_goal"],linear,feasible)
    groups=[np.flatnonzero(feasible&(actions[:,0]==k)) for k in (0,6,4,5)]
    family_ids=[int(actions[g[0],0]) for g in groups if len(g)]
    groups=[g for g in groups if len(g)]
    shares=[];xx=[];pp=[]
    for g in groups:
        val=-obs[g,1,0]
        t=np.exp(np.clip((val-val.max())/max(8.,val.std()),-7.,0.))
        weight=t/t.sum();shares.append(weight);xx.append(weight@x[g]);pp.append(np.tensordot(weight,pn[g],axes=(0,0)))
    ec=w["fine_enc"]@w["coarse_from_fine"]
    zr=(np.array(pp)@ec)+(np.array(xx)@w["coarse_pred"]).reshape(len(xx),2,-1)
    ctr=(zr[:,1]@w["coarse_decoder"])*w["scale"][1,0]
    macro=goal_index(zr[:,1],w["coarse_goal"],ctr,np.ones(len(groups),bool))
    g=groups[macro];way=zr[macro,0]
    fine=(pn[:,0]@w["fine_enc"]+x@w["fine_pred"])@w["coarse_from_fine"]
    distance=np.square(fine[g]-way).sum(1);hi=int(g[np.argmin(distance)])
    original=past["appris_calibre"]
    arms=dict(horaire=0,j7_initial=original,j7_livre=original if original and usable[original] else 0,
              physique=past["physique"],plat_brut=flat,hierarchique_brut=hi,
              plat=flat if flat and prob[flat]>float(w["cutoff_plat"]) else 0,
              hierarchique=hi if hi and prob[hi]>float(w["cutoff_hierarchique"]) else 0)
    info=dict(n_catalogue=len(actions),n_eligible=int(feasible.sum()),n_macros=len(groups),n_fine=len(g),
              macro_kind=family_ids[macro],waypoint=way,tracking_distance=distance.min(),
              flat_transfer_prediction_h=linear[flat],macro_transfer_prediction_h=ctr[macro],plat=flat,hierarchique=hi)
    return arms,info,prob,g,shares[macro]


def calibrated(root,w):
    train=root.parent.parent/"base/cible_resultats" # root = etude/hierarchie/resultats
    seen=set();maxima={name:{s:-1. for s in range(101096,101128)} for name in ("plat","hierarchique")}
    for p,y in zip(rows(train/"public_train.jsonl.gz"),rows(train/"paires_train.jsonl.gz"),strict=True):
        key=acquired.identity(p)
        if key[0] not in maxima["plat"]:continue
        if key!=acquired.identity(y) or p["actions"]!=y["actions"] or p["public_sha256"]!=y["public_sha256"] or key in seen:
            raise ValueError("The calibration label does not match its published action")
        seen.add(key);arms,_,prob,_,_=derive(w,p)
        c=np.array(y["cost"])[:,1];safe=((c[:,:,1:]-c[0,:,1:]-.01*c[0,:,1:])<=TOL).all((1,2))
        for arm,m in maxima.items():
            j=arms[arm+"_brut"]
            if j and not safe[j]:m[key[0]]=max(m[key[0]],float(prob[j]))
    expected={(s,e,f,h) for s in maxima["plat"] for e in (0,1) for f in acquired.FEEDS for h in acquired.HISTORY}
    if seen!=expected:raise ValueError("Missing calibration hospital, episode or information condition")
    report={k:float(sorted(m.values())[29]) for k,m in maxima.items()}
    if any(abs(v-float(w["cutoff_"+k]))>1e-12 for k,v in report.items()):
        raise ValueError("The two cutoffs do not reproduce on 32 held-out calibration hospitals")
    return report


def checked_case(p,d,y,w,sha):
    key=acquired.identity(p)
    if (key!=acquired.identity(d) or key!=acquired.identity(y) or d["actions"]!=p["actions"] or y["actions"]!=p["actions"]
            or any(z["public_sha256"]!=p["public_sha256"] or z["prefix_sha256"]!=p["prefix_sha256"] for z in (d,y))
            or y["decision_sha256"]!=d["decision_sha256"] or d["model_sha256"]!=sha or d["minute"]!=10080):
        raise ValueError("Prospective decision identity, point of intervention or paired result differs")
    acquired.check_hash(d,"decision_sha256")
    arms,expected,pr,family,shares=derive(w,p)
    if d["choices"]!=arms:raise ValueError("Prospective architecture or reference differs from independent ranking")
    if set(d["choices"])!=set(NAMES) or any(type(v) is not int for v in d["choices"].values()):
        raise ValueError("Malformed policy allocation")
    if not np.allclose(d["p_safe"],pr,rtol=0,atol=1e-12):raise ValueError("Frozen safety predictor changed")
    info=d["trace"]
    for k,v in expected.items():
        if np.shape(info[k])!=np.shape(v) or not np.allclose(info[k],v,atol=1e-7,rtol=1e-11):
            raise ValueError("Family selection, search budget, subgoal or transfer readout shifted: "+k)
    a=np.array(p["actions"]);wcount=len(p["route"]);s=len(a)
    cost=acquired.numeric(y["cost"],(s,3,wcount,4),nonnegative=True)
    hard=acquired.numeric(y["guards"],(s,3),integer=True,nonnegative=True)
    delivery=acquired.numeric(y["delivery"],(s,11))
    if (np.diff(cost,axis=1)<-1e-7).any() or np.any(delivery[:,3]>delivery[:,2]) or np.any(delivery[:,2]>delivery[:,1]):
        raise ValueError("Impossible cumulative physical trajectory or realized availability")
    return arms,cost,hard,delivery,expected,family,shares


def run(root,sites=SITES,replay=False):
    weights=impl.load_model();sha=file_sha(root/"poids.npz")
    n=len(sites);idx={s:i for i,s in enumerate(sites)};n_arms=len(NAMES)
    cases={(s,e,f,h) for s in sites for e in (0,1) for f in acquired.FEEDS for h in acquired.HISTORY}
    if set(SITES)&set(sites) and tuple(sites)!=SITES:raise ValueError("Incomplete reserved hospital panel")
    seen=set();width=np.zeros(n,int);sums=np.zeros((n,n_arms,3,8,4));hard_sum=np.zeros((n_arms,3),int)
    active=np.zeros((n,n_arms,7));trace=np.zeros((n,7));disturbance={}
    regs=np.zeros((n,n_arms));invent=np.zeros(3,int);replays=0;h_phys=0.
    # Prespecified physical reconstruction every eighth hospital, both episodes, full history in partial data.
    paths=("public_test.jsonl.gz","affectations.jsonl.gz","issues.jsonl.gz")
    for p,d,y in zip(*(rows(root/f) for f in paths),strict=True):
        key=acquired.identity(p)
        if key in seen or key not in cases:raise ValueError("Duplicate or foreign prospective context")
        seen.add(key);s=idx[key[0]];w=len(p["route"]);width[s]=w
        arms,cost,hard,hours,reported,family,shares=checked_case(p,d,y,weights,sha)
        tape=acquired.checked_sha(y["world_sha256"])
        if disturbance.setdefault(key[:2],tape)!=tape:raise ValueError("Hospital episode or disturbance changed")
        if replay and s%8==0 and key[2:] == ("partiel",28):
            from cible import engine
            from cible.data import make_public,world_sha
            from j7.episodes import first_week
            from lot28.simulator import episode
            ep=episode(key[0],key[1]);cp=first_week(ep,"partial",28);ctx=engine.prepare(ep,"partial",28,cp)
            if make_public(ep,key[2],28,ctx)!=p or world_sha(ep)!=tape:
                raise ValueError("Source data or shocks did not reproduce from the registered site")
            phys=engine.outcomes(ep,ctx,cp)
            delta=float(np.max(abs(cost-phys.cost)));h_phys=max(h_phys,delta)
            if delta>1e-8 or not np.array_equal(hard,phys.guards) or not np.allclose(hours,phys.delivery,atol=1e-8,rtol=0):
                raise ValueError("Independent physical replay differs")
            replays+=1
        phys=cost[:,1];t=phys[:,:,0].sum(1)-phys[0,:,0].sum()
        feasible=acquired.feasible_at(phys,0,hard)
        oracle=int(np.argmin(np.where(feasible,t,np.inf)))
        invent+=hard.sum(0)
        for i,arm in enumerate(NAMES):
            j=arms[arm];sums[s,i,:,:w]+=cost[j];hard_sum[i]+=hard[j]
            active[s,i]+=[j!=0,hours[j,2]>0,hours[j,3]>0,not feasible[j],bool(j and t[j]< -TOL and feasible[j]),
                          hours[j,1],hours[j,3]]
            regs[s,i]+=t[j]-t[oracle]
        f=arms["plat_brut"];h=arms["hierarchique_brut"]
        trace[s]+=[reported["n_catalogue"],reported["n_eligible"],reported["n_macros"],reported["n_fine"],
                   abs(reported["flat_transfer_prediction_h"]-t[f]),
                   abs(reported["macro_transfer_prediction_h"]-np.dot(shares,t[family])),
                   abs(reported["macro_transfer_prediction_h"]-t[h])]
    if seen!=cases:raise ValueError("Missing held-out sites or paired information regimes")
    if len(set(disturbance.values()))!=n*2:raise ValueError("Episode worlds are not independent")
    sums/=18;regs/=18;trace/=18
    bs=np.random.default_rng(SEED).multinomial(n,np.full(n,1/n),size=20000)
    def ci(v):return dict(value=float(v.mean()),ci95=np.quantile(bs@v/n,[.025,.975]).tolist())
    audited={};promos=[]
    comps=[(a,"horaire") for a in NAMES if a!="horaire"]+[("hierarchique",r) for r in ("plat","j7_livre")]+[("hierarchique_brut","plat_brut")]
    for hi,h in enumerate((24,72,168)):
        frame=sums[:,:,hi];total=frame[:,:,:,0].sum(2);local=np.moveaxis(frame[:,:,:,1:],-1,2)
        tab={}
        for alt,ref in comps:
            a=NAMES.index(alt);r=NAMES.index(ref)
            g=contrast(total[:,r],total[:,a],local[:,r],local[:,a],width,sites,bs,tolerance=TOL)
            passed=g["conditions"]["gain_transfert_strict"] and g["conditions"]["chaque_unite_sous_marge"] and not hard_sum[a].any()
            tab[alt+"_vs_"+ref]=dict(gain_heures=g["transfert"],garde_unites=g["unites"],conditions=g["conditions"],
                                    promotion=bool(passed))
            if h==72 and alt=="hierarchique" and ref in ("horaire","plat","j7_livre"):promos.append(passed)
        audited[str(h)]=tab
    primary=audited["72"]["hierarchique_vs_horaire"]
    all_gains=all(audited["72"]["hierarchique_vs_"+r]["conditions"]["gain_transfert_strict"]
                  for r in ("horaire","plat","j7_livre"))
    declared=all_gains and primary["conditions"]["chaque_unite_sous_marge"] and not hard_sum[NAMES.index("hierarchique")].any()
    activity={}
    for i,k in enumerate(NAMES):
        a=active[:,i].sum(0)
        activity[k]=dict(choices=int(a[0]),sites_with_choice=int((active[:,i,0]>0).sum()),with_available=int(a[1]),
                        with_delivered=int(a[2]),context_harm=int(a[3]),safe_improving=int(a[4]),
                        hours_scheduled=float(a[5]),hours_delivered=float(a[6]),
                        regret_h_vs_safe_per_scenario_oracle=ci(regs[:,i]),physical_violations=hard_sum[i].tolist())
    return dict(hospitals=n,physical_wards=int(width.sum()),matched_cases=len(seen),seen_worlds=len(disturbance),
        active_inventory_violations=invent.tolist(),contrast=audited,activity=activity,
        superiorite_hierarchique=bool(declared),garde_contre_chacun_des_trois_temoins=bool(len(promos)==3 and all(promos)),
        applied_cutoffs=calibrated(root,weights),model_sha=sha,
        policy_budget_and_delta_forecasting={k:ci(trace[:,i]) for i,k in enumerate(("catalogue","eligible","macro_visits","fine_candidates_in_chosen_macro",
                                  "flat_mae_vs_selected_action_h","coarse_mae_vs_weighted_family_h","coarse_mae_vs_selected_action_h"))},
        direct_physical_reconstructions=replays,maximum_replay_error=h_phys,seed=SEED,draws=20000)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path("hierarchie/resultats"));p.add_argument("--out",type=Path,required=True)
    a=p.parse_args();out=run(a.root,replay=True);a.out.write_text(json.dumps(out,indent=2,allow_nan=False)+"\n")
