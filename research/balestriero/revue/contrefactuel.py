"""Independent recomputation from staged public forecasts, factual reports and paired simulator targets."""
import argparse
from pathlib import Path
import json
import numpy as np

from .identites import canon, file_sha

H=(1,4,8,12,24)
FEEDS=("full","partial","delayed")
MODELS=("physique","jepa19","jepa37","jepa71")
REGISTERED=tuple(range(116000,116064))
METH=("direct","ancre","copie","autre_episode")
EPS=1e-8


def unique_queries(grid,factual):
    grid=np.asarray(grid)
    if grid.ndim!=4 or grid.shape[1:]!=(7,4,3) or not np.issubdtype(grid.dtype,np.integer):
        raise ValueError("Plans must be integer seven-day portfolios with four slots")
    if type(factual) is not int or not 0<=factual<len(grid):
        raise ValueError("Invalid factual selection")
    seen={grid[factual].tobytes()};result=[]
    for i,row in enumerate(grid):
        signature=row.tobytes()
        if signature not in seen:
            result.append(i);seen.add(signature)
    if not result:raise ValueError("No distinct counterfactual action")
    return np.array(result,int)


def moments(y,forecasts,effect,estimated,missing,changed,linear_diff,invalid):
    """One equal-weight context. Levels and contrast have different variance denominators."""
    y=np.asarray(y,float);err=forecasts-y
    return dict(abs_error=np.abs(err).mean(axis=(1,2)),sq_error=np.square(err).mean(axis=(1,2)),
            mean_y=y.mean(),sq_y=np.square(y).mean(),effect_sq=np.square(effect).mean(),
            effect_mae=np.abs(effect-estimated).mean(),effect_zero=np.abs(effect).mean(),
            model_effect_sq=np.square(effect-estimated).mean(),observed_fraction=1-missing,
            true_changed_actions=changed.any(1).sum(),true_changed_coordinates=changed.sum(),
            named_alternatives=len(y),coord_count=y.size,changed_error_sum=np.abs(estimated-effect)[changed].sum(),
            changed_zero_error_sum=np.abs(effect)[changed].sum(),linear_difference=linear_diff,
            negative=int(invalid[0]),over_capacity=int(invalid[1]),coordinates=int(invalid[2]),ward_states=int(invalid[3]))


def event(p,y,reported,mask,foreign,p_foreign,factual,query,beds):
    """One model and one horizon. The foreign residual is supplied from the other episode's own action."""
    residual=np.where(mask,reported-p[factual],0.)
    if not np.isfinite(residual).all() or np.any(~np.isfinite(reported[mask])):
        raise ValueError("Nonfinite published factual observation")
    observed=mask.astype(float)
    anchored=p+residual[None]
    adj_foreign=np.where(foreign[1]&mask,foreign[0]-p_foreign,0.)
    copy=np.broadcast_to(p[factual]+residual,p.shape)
    estimate=np.stack((p,anchored,copy,p+adj_foreign[None]))
    truth=y[query][...,[2,4]].sum(-1)
    raw=estimate[:,query][...,[2,4]].sum(-1)
    effect=truth-y[factual][:,[2,4]].sum(axis=-1)[None]
    t=p[...,[2,4]].sum(-1)
    eff=t[query]-t[factual]
    # Relative preferences cannot change when the identical vector is added across every branch.
    check=(anchored[query]-anchored[factual])-(p[query]-p[factual])
    if np.max(np.abs(check))>1e-8:raise ValueError("Shared residual changed differences between actions")
    z=anchored[query]
    bad=(int((z < -EPS).sum()),int((z[...,1:].sum(-1)>beds+EPS).sum()),z.size,
         int(np.prod(z.shape[:-1])))
    r=moments(truth,raw,effect,eff,1.-observed[:,[2,4]].mean(),np.abs(effect)>EPS,np.max(abs(check)),bad)
    goals=[]
    t_all=y[...,[2,4]].sum(-1)
    for i in query:
        goal=t_all[i]
        if np.mean(abs(goal-t_all[factual]))>=.05 and not any(np.max(abs(goal-old))<=1e-7 for old in goals):
            goals.append(goal)
    r["goals"]=len(goals);r["goal_hits"]=np.zeros(3,int)
    picks=np.r_[factual,query]
    for goal in goals:
        for j,mat in enumerate(estimate[:3]):
            pr=mat[picks][...,[2,4]].sum(-1);selected=picks[np.argmin(np.sum((pr-goal)**2,axis=1))]
            r["goal_hits"][j]+=np.max(abs(t_all[selected]-goal))<=1e-7
    return r


def read_npz(root,stage,site,e,feed,offset):
    path=root/stage/f"{site}_{e}_{feed}_{offset}.npz"
    with np.load(path,allow_pickle=False) as obj:
        return {k:obj[k] for k in obj.files}


def _net(states,route,beds):
    unit=states/np.asarray(beds)[:,None]
    dest=np.asarray(route,int);w=len(dest)
    inbound=np.zeros_like(unit)
    for upstream,downstream in enumerate(dest):inbound[...,downstream,:]+=unit[...,upstream,:]
    cnt=np.maximum(1,np.bincount(dest,minlength=w))
    return np.concatenate((np.arcsinh(unit),np.arcsinh(unit[...,dest,:]),np.arcsinh(inbound/cnt[:,None])),axis=-1).astype("f")


def target_latent(states,route,beds,weights):
    xs=_net(states,route,beds)
    return np.tanh(np.clip((xs-weights["xm"])/weights["xs"],-8,8)@weights["ema_encoder"]+weights["ema_bias"])


def check_packets(pub,factual,truth):
    a=pub["actions"];grid=pub["grid"];beds=pub["beds"];route=pub["route"];p=pub["pred"];z=pub["latent_pred"]
    f=int(pub["factual"].item());q=unique_queries(grid,f)
    n,_,w,c=p.shape[1:]
    if (p.shape!=(4,n,len(H),w,5) or z.shape!=(3,n,len(H),w,24) or len(a)!=n or len(grid)!=n or
            beds.shape!=(w,) or len(route)!=w or not 4<=w<=8 or np.any(beds<=0) or not np.isfinite(p).all()
            or not np.isfinite(z).all() or not np.all(np.isin(route,range(w)))):
        raise ValueError("Mismatched frozen action, ward graph, horizons or forecast coordinates")
    y=truth["states"];m=truth["metrics"];reported=factual["reported"];mask=factual["mask"]
    if (y.shape!=(n,len(H),w,5) or not np.isfinite(y).all() or np.min(y)<-1e-8 or
            m.shape!=(n,len(H),w,14) or np.min(m)<-1e-7 or not np.isfinite(m).all() or
            reported.shape!=(len(H),w,5) or mask.shape!=reported.shape or not np.isin(mask,[0,1]).all()
            or np.any(np.isfinite(reported)!=mask.astype(bool)) or np.asarray(factual["available_hour"]).shape!=(len(H),)):
        raise ValueError("Incomplete factual reporting clock, hidden observation or physical outcome")
    if np.max(y[...,1:].sum(-1)-beds)>1e-7:raise ValueError("Impossible true bed occupancy")
    mask=mask.astype(bool)
    if not np.allclose(reported[mask],y[f][mask],rtol=0,atol=2e-5):
        raise ValueError("The archived factual report is not its outcome under the common event")
    if np.any(np.diff(m,axis=1)<-1e-7):raise ValueError("Physical cumulative quantities reverse time")
    # Equality of treatments is checked even when another named plan maps to the same commitments.
    groups={}
    for i,plan in enumerate(grid):
        tag=plan.tobytes()
        if tag in groups:
            j=groups[tag]
            if (np.max(abs(y[i]-y[j]))>EPS or np.max(abs(m[i]-m[j]))>EPS or np.max(abs(p[:,i]-p[:,j]))>2e-5):
                raise ValueError("Identical treatment with the common world changed outcome or forecast")
        else:groups[tag]=i
    return p.astype(float),y.astype(float),reported.astype(float),mask,f,q,beds,route


def _ci(x,draws):
    x=np.asarray(x,float)
    return {"value":float(x.mean()),"ci95":np.quantile(draws@x/len(x),[.025,.975]).tolist()}


def aggregate(items,draws):
    # Each item already averages the episodes/decision observations of one hospital.
    v={k:np.stack([s[k] for s in items]) for k in items[0]}
    levels={}
    variance=v["sq_y"].mean()-v["mean_y"].mean()**2
    for j,name in enumerate(METH):
        levels[name]={"mae_patients":_ci(v["abs_error"][:,j],draws),
                      "rmse_patients":float(np.sqrt(v["sq_error"][:,j].mean())),
                      "r2_niveau":float(1-v["sq_error"][:,j].mean()/variance) if variance>1e-14 else None}
    den=v["effect_sq"].mean()
    goals={}
    for j,k in enumerate(METH[:3]):
        valid=(draws@v["goals"])>0
        rates=(draws[valid]@v["goal_hits"][:,j])/(draws[valid]@v["goals"]) if valid.any() else np.array([])
        goals[k]=dict(value=float(v["goal_hits"][:,j].sum()/v["goals"].sum()) if v["goals"].sum()>0 else None,
                      ci95=np.quantile(rates,[.025,.975]).tolist() if len(rates) else [None,None])
    return dict(n_sites=len(items),niveau=levels,hindsight_goal_success=goals,
                gain_mae_ancre_sur_direct=_ci(v["abs_error"][:,0]-v["abs_error"][:,1],draws),
                gain_mae_ancre_sur_copie=_ci(v["abs_error"][:,2]-v["abs_error"][:,1],draws),
                gain_mae_ancre_sur_autre_episode=_ci(v["abs_error"][:,3]-v["abs_error"][:,1],draws),
                denominator_variance_niveau=float(variance),variance_effet_contre_zero=float(den),
                r2_effet_vs_zero=float(1-v["model_effect_sq"].mean()/den) if den>1e-14 else None,
                mae_effet_modele=_ci(v["effect_mae"],draws),mae_effet_nul=_ci(v["effect_zero"],draws),
                proportion_canaux_publies=float(v["observed_fraction"].mean()),
                part_alternatives_changent_transfert=float(v["true_changed_actions"].sum()/v["named_alternatives"].sum()),
                part_cellules_changent_transfert=float(v["true_changed_coordinates"].sum()/v["coord_count"].sum()),
                mae_effet_cellules_actives=float(v["changed_error_sum"].sum()/v["true_changed_coordinates"].sum()) if v["true_changed_coordinates"].sum() else None,
                mae_nulle_cellules_actives=float(v["changed_zero_error_sum"].sum()/v["true_changed_coordinates"].sum()) if v["true_changed_coordinates"].sum() else None,
                ecart_pairwise_max=float(v["linear_difference"].max()),
                fraction_stocks_ancres_negatifs=float(v["negative"].sum()/v["coordinates"].sum()),
                fraction_unites_ancres_saturees=float(v["over_capacity"].sum()/v["ward_states"].sum()))


def array_sha(a):
    import hashlib
    return hashlib.sha256(np.ascontiguousarray(a).view(np.uint8)).hexdigest()


def inspect_identity(root,key,p,f,y):
    sid,e,feed,offset=key;stem=f"{sid}_{e}_{feed}_{offset}.npz"
    for item in (p,f,y):
        if (int(item["site"]),int(item["episode"]),str(item["feed"]),int(item["offset"]))!=key:
            raise ValueError("Wrong site, episode, public feed or decision clock in a counterfactual packet")
    hour=168+offset;dates=np.asarray(H)+hour+(2 if feed=="delayed" else 0)
    if (int(p["source_hour"])!=hour or not np.array_equal(p["horizons"],H) or
            not np.array_equal(f["available_hour"],dates) or int(f["factual"])!=int(p["factual"]) or
            str(y["factual_sha"])!=file_sha(root/"factuel"/stem) or
            any(str(item["public_sha"])!=file_sha(root/"public"/stem) for item in (y,f)) or
            str(y["source_physical_sha"])!=str(f["source_physical_sha"]) or str(y["world_sha"])!=str(f["world_sha"])):
        raise ValueError("Wrong factual time, capture, source, world evidence or retrospective availability")
    a=np.asarray(p["actions"]);rg=np.random.default_rng([261118,sid,offset])
    kind=rg.choice((0,4,5,6) if offset==0 else (0,4,5))
    fidx=int(rg.choice(np.flatnonzero(a[:,0]==kind)))
    if fidx!=int(p["factual"]):raise ValueError("Factual action was not drawn before treatment")
    if offset==4 and (not np.isin(a[:,0],(0,4,5)).all() or np.any(p["grid"][:,0,:2]!=p["grid"][0,0,:2])):
        raise ValueError("Noon branch changed an already committed staff or downstream booking")


def reconstruct(ep,cp,feed,offset,p,f,y):
    from cf.experience import prepare
    from lot28 import features,model,simulator
    from lot28.corpus import _bedside,mask_index
    view,grid,actions,x=prepare(ep,cp,feed,offset);h0=168+offset
    tape=ep.truth[h0:h0+24]
    fields={}
    for name,value in vars(view).items():
        fields[name]=[value.dtype.str,list(value.shape),array_sha(value)] if isinstance(value,np.ndarray) else (
            value.item() if isinstance(value,np.generic) else value)
    if canon(fields)!=str(p["public_view_sha"]):raise ValueError("Published masks, clocks or covariates changed")
    if (not np.array_equal(p["grid"],grid) or not np.array_equal(p["actions"],actions)
            or view.asof!=7*1440+offset*60 or str(y["world_sha"])!=array_sha(tape)
            or str(y["source_physical_sha"])!=array_sha(x) or str(p["state_sha"])!=array_sha(view.state)
            or str(p["view_sha"])!=array_sha(view.forecast)):
        raise ValueError("The identity of the common initial state, disturbance or observable forecast failed to replay")
    physical,real=simulator.rollout(ep.site,x,tape,grid,H,start_hour=offset)
    np.testing.assert_allclose(real,y["states"],rtol=0,atol=1e-9)
    np.testing.assert_allclose(physical,y["metrics"],rtol=0,atol=1e-8)
    i=int(p["factual"]);masks=[]
    for k,hour in enumerate(H):
        _,m=_bedside(ep,7+(offset+hour)//24,mask_index(feed),real[i,k])
        masks.append(m)
    if not np.array_equal(f["mask"],masks):
        raise ValueError("A data source disclosed cells unavailable for this hospital and observation regime")
    projected,z=simulator.rollout(ep.site,view.state,view.forecast[offset:],grid,H,start_hour=offset)
    std=features.normalized(ep.site,projected,z,H)
    af=features.action_features(ep.site,view,grid,std,offset,H)
    xf=features.state_features(ep.site,view.state)
    np.testing.assert_allclose(z,p["pred"][0],atol=1e-9,rtol=0)
    for mi,seed in enumerate((19,37,71)):
        learned=_frozen(seed);aw=learned.w
        estimate=learned.predict(xf,af,std)[...,4:].astype(float)*ep.site.beds[:,None]
        latent=model.forward(aw,model.standard(xf,aw["xm"],aw["xs"]),model.standard(af,aw["am"],aw["as"]))[1]
        np.testing.assert_allclose(estimate,p["pred"][mi+1],atol=5e-6,rtol=0)
        np.testing.assert_allclose(latent,p["latent_pred"][mi],atol=1e-6,rtol=0)
    if np.any(physical[...,simulator.M_DONOR_VIOLATION]):
        raise ValueError("A shared-event counterfactual broke the donor floor")


from functools import lru_cache
@lru_cache(maxsize=3)
def _frozen(seed):
    from lot28.model import load_model
    return load_model("jepa",seed)


def run(root,weights_root,sites=REGISTERED,draws=20000,seed=261118,*,replay=True):
    locations={str(s):weights_root/f"jepa_{s}.npz" for s in (19,37,71)}
    params={}
    for s,path in locations.items():
        with np.load(path,allow_pickle=False) as f:params[s]={k:f[k] for k in ("xm","xs","ema_encoder","ema_bias")}
    summaries={};latent=[];negative_controls=0;context_count=0
    for site in sites:
        per_site={}
        if replay:
            from lot28 import simulator
            from j7.episodes import first_week
            episodes=[simulator.episode(site,e) for e in (0,1)]
        for feed in FEEDS:
            checkpoints=[first_week(ep,feed,7) for ep in episodes] if replay else []
            for offset in (0,4):
                packets=[]
                for e in (0,1):
                    pub,fact,truth=(read_npz(root,folder,site,e,feed,offset) for folder in ("public","factuel","verite"))
                    pack=check_packets(pub,fact,truth)
                    inspect_identity(root,(site,e,feed,offset),pub,fact,truth)
                    if replay:reconstruct(episodes[e],checkpoints[e],feed,offset,pub,fact,truth)
                    pack=(*pack,pub["latent_pred"])
                    packets.append(pack)
                    if offset==0:
                        for hi in (0,1):
                            if np.max(abs(pack[1][:,hi]-pack[1][pack[4],hi]))>EPS:
                                raise ValueError("A morning alternative took effect before any resource shift opened")
                            negative_controls+=1
                    context_count+=1
                for e,pack in enumerate(packets):
                    p,y,obs,mask,f,q,beds,route,z=pack
                    pp,_,foreign,othermask,f2,*_=packets[1-e]
                    for mi,name in enumerate(MODELS):
                        for hi,h in enumerate(H):
                            r=event(p[mi,:,hi],y[:,hi],obs[hi],mask[hi],(foreign[hi],othermask[hi]),
                                    pp[mi,f2,hi],f,q,beds)
                            per_site.setdefault((feed,offset,h,name),[]).append(r)
                    if feed=="full" and offset==4:
                        hi=1;zz=z[0,:,hi].astype(float)
                        real=target_latent(y[:,hi],route,beds,params["19"]).astype(float)
                        corrected=zz[q]+real[f]-zz[f]
                        latent.append([site,*[float(np.mean((v-real[q])**2)) for v in (zz[q],corrected,np.broadcast_to(real[f],real[q].shape))]])
        for key,group in per_site.items():
            av={k:np.mean([r[k] for r in group],axis=0) if k!="linear_difference"
                else np.max([r[k] for r in group]) for k in group[0]}
            summaries.setdefault(key,[]).append(av)
    n=len(sites);rep=np.random.default_rng(seed).multinomial(n,np.full(n,1/n),size=draws)
    results={f"{mask}/origine{offset}/h{h}/{model}":aggregate(values,rep) for (mask,offset,h,model),values in summaries.items()}
    l=np.array(latent);site_mse=np.stack([l[l[:,0]==s,1:].mean(0) for s in sites])
    return dict(site_count=n,events=context_count,physical_negative_control_horizons=negative_controls,
            replays_prevision_observation_monde=context_count if replay else 0,
            seeds_weights_sha256={s:file_sha(p) for s,p in locations.items()},bootstrap_sites=dict(draws=draws,seed=seed),
            primary=results["full/origine4/h4/jepa19"],physical_primary=results["full/origine4/h4/physique"],
            latent_full_midi_h4_jepa19={k:_ci(site_mse[:,j],rep) for j,k in enumerate(("pred_mse","ancre_mse","copie_mse"))},
            strata=results)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path("cf/resultats"));p.add_argument("--weights",type=Path,default=Path("base/parent/run/weights"))
    p.add_argument("--out",type=Path,required=True);args=p.parse_args()
    summary=run(args.root,args.weights);args.out.write_text(json.dumps(summary,indent=2,allow_nan=False)+"\n")
