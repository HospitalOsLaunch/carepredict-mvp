"""Score paired end states, action effects and hindsight goal matching separately."""
import argparse
import json
from collections import defaultdict
import numpy as np
from cible.study import write_json
from lot28 import simulator as sim
from .experience import (CLOCKS,DEV,FEEDS,H,OUT,SEEDS,TEST,alternatives,encode_target,
                         models,payload,record_name,verify_all)


COLS=("y","y2","base_mae","anchor_mae","copy_mae","placebo_mae","ontime_mae",
      "base_mse","anchor_mse","copy_mse","placebo_mse","contrast_mae","contrast_mse","null_contrast_mae",
      "null_contrast_mse","contrast_invariance","ed_mae_base","ed_mae_anchor","dirty_mae_base","dirty_mae_anchor",
      "state_mae_base","state_mae_anchor","state_mae_copy","anchor_invalid_frac","max_violation",
      "observed_fraction","transfer_pair_observed","changed_ratio","changed_contrast_error","changed_null_error",
      "changed_level_base_error","changed_level_anchor_error","changed_level_copy_error","goals",
      "goal_hits_base","goal_hits_anchor","goal_hits_copy","guard_recalled_ratio",
      "guard_recalled_error","guard_recalled_null","sse_latent_base","sse_latent_anchor","sse_latent_copy",
      "latent_mean_square_target","latent_mean_coord2","available_lag","rank_diff","sse_latent_contrast")
MODEL_NAMES=("ssm","jepa19","jepa37","jepa71")
METHODS=("base","anchor","copy","placebo")


def anchored(pred,reported,mask,factual,now,published_at):
    """One measured factual endpoint only. Missing, delayed components receive no correction."""
    if pred.ndim!=3 or reported.shape!=pred.shape[1:] or mask.shape!=reported.shape or mask.dtype!=bool:
        raise ValueError("Incompatible factual measurement or prediction matrix")
    if not np.isfinite(pred).all() or not np.array_equal(np.isfinite(reported),mask):
        raise ValueError("Missing endpoint must remain unobserved")
    observed=mask if now>=published_at else np.zeros_like(mask)
    return pred + np.where(observed,reported-pred[factual],0.)[None]


def stock(x):
    return x[...,2]+x[...,4]


def hindsight(q,y,fact,alt):
    """Infer the command for a synthetic reachable target queue, using only predicted candidates and that goal."""
    choices=np.r_[fact,alt]
    actual=y[choices]
    goals=[]
    for idx in alt:
        g=y[idx]
        if np.mean(np.abs(g-y[fact]))<.05:continue
        if not any(np.allclose(g,old,rtol=0,atol=1e-7) for old in goals):goals.append(g)
    if not goals:return np.zeros(4)
    goals=np.asarray(goals)
    ret=[len(goals)]
    for values in q:
        hypothetical=values[choices]
        nearest=np.argmin(((hypothetical[None]-goals[:,None])**2).mean(-1),axis=1)
        ret.append(int((abs(actual[nearest]-goals).max(-1)<=1e-7).sum()))
    return np.asarray(ret,float)


def rate_est(num,den,bs):
    n=num.mean();d=den.mean()
    if d<=0:return dict(value=None,ci95=None)
    a=bs@num;b=bs@den;valid=b>0
    return dict(value=float(n/d),ci95=np.quantile(a[valid]/b[valid],[.025,.975]).tolist() if valid.any() else None)


def scalar(x,bs):
    return dict(value=float(x.mean()),ci95=np.quantile(bs@x,[.025,.975]).tolist())


def describe(p,f,y,p2,f2):
    fact=int(p["factual"]);other=int(p2["factual"]);alt=alternatives(p["grid"],fact)
    if (int(p["site"])!=int(p2["site"]) or int(p["episode"])==int(p2["episode"]) or
        str(p["feed"])!=str(p2["feed"]) or int(p["offset"])!=int(p2["offset"])):
        raise ValueError("Placebo must use the other episode of the same site and information condition")
    w=p["beds"].size; hospital=sim.site(int(p["site"]))
    if not np.array_equal(hospital.beds,p["beds"]) or not np.array_equal(hospital.route,p["route"]):
        raise ValueError("Physical hospital identity drift")
    factmask=f["mask"]
    latent_available=str(p["feed"])=="full"
    true_z=[encode_target(hospital,y["states"],m) for m in models()] if latent_available else []
    entries=[]
    for hi,hour in enumerate(H):
        end=int(p["source_hour"])+hour;arrival=int(f["available_hour"][hi]);m=factmask[hi]
        obs=f["reported"][hi];truth=y["states"][:,hi];target=stock(truth);dtrue=target-target[fact]
        active=np.abs(dtrue[alt])>=.05
        changed=float(active.mean())
        recall=y["metrics"][:,hi,:,sim.M_RECALL].sum(1)>0
        recalled=recall[alt]|recall[fact]
        for idx,name in enumerate(MODEL_NAMES):
            raw=p["pred"][idx,:,hi]
            anch=anchored(raw,obs,m,fact,arrival,arrival)
            punctual=anchored(raw,obs,m,fact,end,arrival)
            same=np.broadcast_to(anch[fact],anch.shape)
            placebo=raw+np.where(f2["mask"][hi]&m,f2["reported"][hi]-p2["pred"][idx,other,hi],0.)[None]
            q=(stock(raw),stock(anch),stock(same),stock(placebo))
            errors=[pred[alt]-target[alt] for pred in q]
            dc=(q[0]-q[0][fact])[alt]-dtrue[alt]
            invariant=float(np.max(abs((q[1]-q[1][fact])[alt]-(q[0]-q[0][fact])[alt])))
            if invariant>1e-8:raise ValueError("An additive correction changed the estimated action contrast")
            # Sorting a scalar linear objective can change only on floating-point ties.
            pair=q[0].sum(1)[:,None]-q[0].sum(1)[None,:]
            pa=q[1].sum(1)[:,None]-q[1].sum(1)[None,:]
            if np.any(np.sign(pair[abs(pair)>1e-8])!=np.sign(pa[abs(pair)>1e-8])):
                raise ValueError("Transfer minimization ranks changed under a shared additive shift")
            phys_v=np.maximum(np.maximum(0.,-anch[alt].min(-1)),np.maximum(0.,anch[alt,:,1:].sum(-1)-p["beds"]))
            absbase=abs(raw[alt]-truth[alt]);absanchor=abs(anch[alt]-truth[alt])
            gt=hindsight(q[:3],target,fact,alt)
            z=(0.,)*6
            if idx>0 and latent_available:
                pred_z=p["latent_pred"][idx-1,:,hi].astype(float);true=true_z[idx-1][:,hi].astype(float)
                residual=true[fact]-pred_z[fact]
                obs_z=pred_z+residual
                # z_y is available in the factual branch only after its census is observed.
                z=(np.square(pred_z[alt]-true[alt]).mean(),np.square(obs_z[alt]-true[alt]).mean(),
                   np.square(true[fact]-true[alt]).mean(),np.square(true[alt]).mean(),
                   np.square(true[alt].mean(axis=(0,1))).mean(),np.square((pred_z[alt]-pred_z[fact])-(true[alt]-true[fact])).mean())
            vals=(target[alt].mean(),np.square(target[alt]).mean(),
                  *(abs(a).mean() for a in errors),abs(stock(punctual)[alt]-target[alt]).mean(),
                  *(np.square(a).mean() for a in errors),abs(dc).mean(),np.square(dc).mean(),
                  abs(dtrue[alt]).mean(),np.square(dtrue[alt]).mean(),invariant,
                  absbase[...,0].mean(),absanchor[...,0].mean(),absbase[...,3].mean(),absanchor[...,3].mean(),
                  absbase.mean(),absanchor.mean(),abs(same[alt]-truth[alt]).mean(),
                  (phys_v>1e-7).mean(),phys_v.max(),m.mean(),(m[:,2]&m[:,4]).mean(),
                  changed,(abs(dc)*active).mean(),(abs(dtrue[alt])*active).mean(),
                  *( (abs(err)*active).mean() for err in errors[:3]),*gt,
                  recalled.mean(),(abs(dc)*recalled[:,None]).mean(),(abs(dtrue[alt])*recalled[:,None]).mean(),
                  *z[:5],arrival-end,0.,z[5])
            if len(vals)!=len(COLS):raise AssertionError((len(vals),len(COLS)))
            entries.append(np.asarray(vals,float))
    return np.stack(entries).reshape(len(H),len(MODEL_NAMES),-1),len(alt)


def evaluate(folder,sites):
    arr=np.empty((len(sites),2,len(FEEDS),len(CLOCKS),len(H),len(MODEL_NAMES),len(COLS)))
    counts=np.zeros((len(sites),2,len(FEEDS),len(CLOCKS)),int)
    for si,s in enumerate(sites):
        for fi,feed in enumerate(FEEDS):
            for ji,offset in enumerate(CLOCKS):
                names=[record_name(s,e,feed,offset) for e in (0,1)]
                p=[payload(folder/"public"/name) for name in names]
                fact=[payload(folder/"factuel"/name) for name in names]
                for e in (0,1):
                    y=payload(folder/"verite"/names[e])
                    arr[si,e,fi,ji],counts[si,e,fi,ji]=describe(p[e],fact[e],y,p[1-e],fact[1-e])
    return arr,counts


def summaries(arr,counts,sites):
    n=len(sites)
    bs=np.random.default_rng(261118).multinomial(n,[1/n]*n,size=20000)/n
    by={};columns={k:i for i,k in enumerate(COLS)}
    for fi,feed in enumerate(FEEDS):
        for ti,offset in enumerate(CLOCKS):
            for hi,h in enumerate(H):
                for mi,model in enumerate(MODEL_NAMES):
                    x=arr[:,:,fi,ti,hi,mi].mean(axis=1)
                    c=lambda k:x[:,columns[k]]
                    z={k:float(c(k).mean()) for k in COLS}
                    z["max_invariance"]=float(arr[:,:,fi,ti,hi,mi,columns["contrast_invariance"]].max())
                    z["maximum_physical_violation"]=float(arr[:,:,fi,ti,hi,mi,columns["max_violation"]].max())
                    z["mae_factual_copy_minus_anchor"]=scalar(c("copy_mae")-c("anchor_mae"),bs)
                    z["mae_base_minus_anchor"]=scalar(c("base_mae")-c("anchor_mae"),bs)
                    z["mae_placebo_minus_anchor"]=scalar(c("placebo_mae")-c("anchor_mae"),bs)
                    z["mae_null_effect_minus_predicted_effect"]=scalar(c("null_contrast_mae")-c("contrast_mae"),bs)
                    var=c("y2").mean()-c("y").mean()**2
                    z["level_r2"]={k:float(1-c(k+"_mse").mean()/var) for k in METHODS} if var>1e-12 else None
                    z["effect_skill"]=float(1-c("contrast_mse").mean()/c("null_contrast_mse").mean()) if c("null_contrast_mse").mean()>1e-14 else None
                    z["conditional_mae_effect_changed"]=rate_est(c("changed_contrast_error"),c("changed_ratio"),bs)
                    z["conditional_null_effect_changed"]=rate_est(c("changed_null_error"),c("changed_ratio"),bs)
                    z["conditional_delta_anchor_vs_copy_changed"]=rate_est(c("changed_level_copy_error")-c("changed_level_anchor_error"),c("changed_ratio"),bs)
                    z["mae_effect_given_recall"]=rate_est(c("guard_recalled_error"),c("guard_recalled_ratio"),bs)
                    z["goal_hit_rate"]={a:rate_est(c("goal_hits_"+a),c("goals"),bs) for a in ("base","anchor","copy")}
                    z["goal_count"]=int(round(c("goals").sum()*2))
                    if model!="ssm" and feed=="full":
                        z["latent_rmse"]={a:float(np.sqrt(c("sse_latent_"+a).mean())) for a in ("base","anchor","copy")}
                        z["latent_skill_over_copy"]=float(1-c("sse_latent_anchor").mean()/c("sse_latent_copy").mean()) if c("sse_latent_copy").mean()>1e-14 else None
                    by[f"{feed}/{8+offset:02d}/{h}/{model}"]=z
    return dict(sites=n,contexts=int(counts.size),unique_alternative_queries=int(counts.sum()),
                horizons=list(H),seeds=list(SEEDS),primary=by["full/12/4/jepa19"],by_condition=by)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("lock","public","factuel","verite"):parser.add_argument("--"+name)
    parser.add_argument("--dev",action="store_true");parser.add_argument("--directory",type=type(OUT))
    a=parser.parse_args()
    if a.dev:
        if a.directory is None or a.directory.resolve()==OUT.resolve():raise ValueError("Expected development directory")
        folder=a.directory;sites=DEV
    else:
        verify_all(a.lock,a.public,a.factuel,a.verite);folder=OUT;sites=TEST
    arr,counts=evaluate(folder,sites)
    report=summaries(arr,counts,sites)
    report["receipts"]=dict(design=a.lock,public=a.public,factual=a.factuel,truth=a.verite)
    with (folder/"mesures_par_site.npz").open("wb") as f:
        np.savez_compressed(f,measures=arr,unique_counts=counts,columns=np.array(COLS),sites=sites)
    write_json(folder/"resultats.json",report)
    primary=report["primary"]
    print({k:primary[k] for k in ("base_mae","anchor_mae","copy_mae","level_r2","effect_skill")})


if __name__=="__main__":main()
