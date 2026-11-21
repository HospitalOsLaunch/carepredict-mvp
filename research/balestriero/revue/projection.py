"""Independent Euclidean projection oracle. Iteratively solve the KKT equations by bisection."""
import argparse
from pathlib import Path
import json

import numpy as np

from .contrefactuel import H,unique_queries,read_npz,check_packets,inspect_identity,reconstruct
from .identites import file_sha

TOL=1e-8


def physical_domain(states,beds,tol=TOL):
    x=np.asarray(states);b=np.asarray(beds)
    if x.shape[-1]!=5:raise ValueError("Expected five census coordinates")
    return (np.min(x,axis=-1)>=-tol)&(x[...,1:].sum(-1)<=b+tol)


def project(states,beds):
    x=np.asarray(states,float)
    b=np.asarray(beds,float)
    if x.ndim<2 or x.shape[-1]!=5 or b.shape!=(x.shape[-2],) or not np.isfinite(x).all() or not np.isfinite(b).all() or (b<0).any():
        raise ValueError("Expected finite states and nonnegative ward bed capacities")
    v=x[...,1:]
    b=np.broadcast_to(b,x.shape[:-1])
    excess=np.maximum(0.,v).sum(-1)>b
    if not excess.any():return np.maximum(x,0.)
    lo=np.zeros_like(b);hi=np.maximum(0,np.max(v,axis=-1))
    for _ in range(54):
        mid=(hi+lo)*.5
        more=np.maximum(v-mid[...,None],0).sum(-1)>b
        lo=np.where(more,mid,lo);hi=np.where(more,hi,mid)
    lam=np.where(excess,hi,0.)
    clipped=np.maximum(v-lam[...,None],0.)
    z=np.concatenate((np.maximum(x[...,:1],0.),clipped),axis=-1)
    if (not physical_domain(z,b).all() or np.any(lam<0)
            or np.any(abs((clipped.sum(-1)-b)[excess])>1.e-9)):
        raise ValueError("Projected states fail nonnegativity, capacity or complementary slackness")
    return z


def fixed_factual(raw,obs,mask,fi,beds):
    z=project(raw,beds)
    for u,m in enumerate(mask):
        if m[0]:z[fi,u,0]=obs[u,0]
        fixed=m[1:]
        z[fi,u,1:][fixed]=obs[u,1:][fixed]
        left=beds[u]-np.sum(obs[u,1:][fixed])
        if left < -1e-7:raise ValueError("Observed beds exceed physical capacity")
        if (~fixed).any():
            v=raw[fi,u,1:][~fixed]
            padded=np.zeros((1,5));padded[0,1:1+len(v)]=v
            z[fi,u,1:][~fixed]=project(padded,np.array([max(0.,left)]))[0,1:1+len(v)]
    if not physical_domain(z,beds).all() or np.max(abs(z[fi][mask]-obs[mask]),initial=0)>1e-8:
        raise ValueError("Projection cannot preserve the published factual census")
    return z


def score(p,y,obs,mask,fi,qs,beds,registered_projection=None):
    resid=np.where(mask,obs-p[fi],0.);raw=p+resid
    ordinary=project(raw,beds)
    constrained=fixed_factual(raw,obs,mask,fi,beds)
    if registered_projection is not None:
        np.testing.assert_allclose(constrained,registered_projection,rtol=0,atol=1.e-9)
    np.testing.assert_allclose(project(constrained,beds),constrained,rtol=0,atol=1e-12)
    if mask.all():np.testing.assert_allclose(constrained[fi],y[fi],rtol=0,atol=1e-8)
    for j in (*qs,fi):
        # The nearest feasible point cannot increase squared distance to a feasible truth in the full state space.
        gap=np.square(raw[j]-y[j]).sum(-1)-np.square(constrained[j]-y[j]).sum(-1)
        if np.min(gap)<-1e-8:raise ValueError("Projection increased full-state squared distance to a feasible target")
    exact=y[...,2]+y[...,4]
    r=raw[...,2]+raw[...,4];pr=constrained[...,2]+constrained[...,4]
    dr=r-r[fi];dc=pr-pr[fi];de=exact-exact[fi]
    idx=np.r_[fi,qs]
    a,b=np.triu_indices(len(idx),1)
    first=r[idx].sum(1);second=pr[idx].sum(1)
    orig=first[a]-first[b];rounded=second[a]-second[b]
    valid=(np.abs(orig)>TOL)&(np.abs(rounded)>TOL)
    flipped=valid&(np.sign(orig)!=np.sign(rounded))
    zm=np.abs((constrained[fi]-obs)[mask]) if mask.any() else np.array([0.])
    unconditioned=np.abs((ordinary[fi]-obs)[mask]) if mask.any() else np.array([0.])
    return dict(mae_raw_level=float(np.abs(r[qs]-exact[qs]).mean()),
                mae_projected_level=float(np.abs(pr[qs]-exact[qs]).mean()),
                mae_copy=float(np.abs(exact[fi]-exact[qs]).mean()),
                mae_raw_effect=float(np.abs(dr[qs]-de[qs]).mean()),
                mae_projected_effect=float(np.abs(dc[qs]-de[qs]).mean()),
                max_change_estimated_effect=float(np.max(np.abs(dc[qs]-dr[qs]))),
                state_rmse_raw=float(np.square(raw[qs]-y[qs]).mean()),
                state_rmse_projected=float(np.square(constrained[qs]-y[qs]).mean()),
                out_raw=1.-float(physical_domain(raw[qs],beds,1e-7).mean()),
                out_projected=1.-float(physical_domain(constrained[qs],beds,1e-7).mean()),
                naive_max_observed_factual_drift=float(np.max(unconditioned)),
                rows_with_rank_reversal=int(flipped.any()),substantive_pair_reversals=int(flipped.sum()),
                n_comparable_pairs=int(valid.sum()),max_known_factual_change=float(np.max(zm)),
                masked_factual_stocks_changed=int((zm>TOL).sum()),masked_factual_stocks=int(mask.sum()))


def summarize(entries,seed=261119,draws=20000):
    by={}
    for sid,record in entries:
        by.setdefault(sid,[]).append(record)
    sites=sorted(by);n=len(sites)
    bs=np.random.default_rng(seed).multinomial(n,np.full(n,1/n),size=draws)
    res={}
    raw={k:np.asarray([np.mean([p[k] for p in by[s]]) for s in sites]) for k in entries[0][1]}
    for k,v in raw.items():
        if k.startswith("max_") or k=="naive_max_observed_factual_drift":
            res[k]=float(max(p[k] for _,p in entries))
        else:
            res[k]=dict(value=float(v.mean()),ci95=np.quantile(bs@v/n,[.025,.975]).tolist())
    for name,key in (("gain_mae_level","level"),("gain_mae_effect","effect")):
        gain=raw["mae_raw_"+key]-raw["mae_projected_"+key]
        res[name]=dict(value=float(gain.mean()),ci95=np.quantile(bs@gain/n,[.025,.975]).tolist())
    res["n_contexts"]=len(entries);res["sites"]=n
    return res


def run(root,sites=tuple(range(117000,117032)),seed=261119,draws=20000):
    from contraintes.projection import reconstruire
    from lot28.simulator import episode
    from j7.episodes import first_week
    buckets={};worst=0.;targeted=0
    for si,s in enumerate(sites):
        for e in (0,1):
            ep=episode(s,e)
            for feed in ("full","partial","delayed"):
                cp=first_week(ep,feed,7) if si%8==0 else None
                for offset in (0,4):
                    public,factual,y=(read_npz(root,k,s,e,feed,offset) for k in ("public","factuel","verite"))
                    p,real,obs,mask,fi,qs,beds,_=check_packets(public,factual,y)
                    inspect_identity(root,(s,e,feed,offset),public,factual,y)
                    if cp is not None:
                        reconstruct(ep,cp,feed,offset,public,factual,y);targeted+=1
                    for i,h in enumerate(H):
                        ready=int(factual["available_hour"][i]);now=168+offset+h
                        for m,name in enumerate(("physique","jepa19","jepa37","jepa71")):
                            x=p[m,:,i]
                            published=reconstruire(x,fi,obs[i],mask[i],beds,heure_consultation=ready,heure_publication=ready)
                            out=score(x,real[:,i],obs[i],mask[i],fi,qs,beds,published)
                            if now<ready:
                                before=reconstruire(x,fi,obs[i],mask[i],beds,heure_consultation=now,heure_publication=ready)
                                diff=float(abs(before-project(x,beds)).max())
                                if diff>1e-8:raise ValueError("An unpublished future value influenced the early reconstruction")
                                worst=max(worst,diff)
                            buckets.setdefault((feed,offset,h,name),[]).append((s,out))
    results={f"{f}/origine{o}/h{h}/{m}":summarize(rows,seed=seed,draws=draws) for (f,o,h,m),rows in buckets.items()}
    return dict(sites=len(sites),primary=results["full/origine4/h4/jepa19"],strata=results,
                physical_reconstructions=targeted,max_unpublished_effect=worst,draws=draws,seed=seed)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--root",type=Path,default=Path("contraintes/resultats"))
    p.add_argument("--out",type=Path,required=True);a=p.parse_args()
    r=run(a.root);a.out.write_text(json.dumps(r,indent=2,allow_nan=False)+"\n")
