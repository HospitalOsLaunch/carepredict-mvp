"""Whitened low-rank tabular JEPAs with two distinct time scales and a top-down planner."""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.linalg import eigh, solve
from scipy.special import softmax

from cible import model as original
from cible.data import CAL, FIT, OUT as BASE_OUT, TOL, paired, sha_file
from executabilite.regle import CHECKS, MODEL_SHA256

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"resultats"
WEIGHTS=OUT/"poids.npz"
KINDS=(0,6,4,5)
HOURS=(24,72,168)
SEED=71983
LINEAR=32
NONLINEAR=64
FINE=8
COARSE=4
RIDGE=.018
ARMS=("horaire","j7_livre","physique","plat","hierarchique","plat_brut","hierarchique_brut","j7_initial")
PUBLIC_FIELDS=frozenset(("site","episode","feed","history","prefix_sha256","route","x","actions",
                         "projection","projection_delivery","public_sha256"))

@lru_cache(maxsize=1)
def incumbent():
    model=original.load_model()
    if model.weight_sha!=MODEL_SHA256:raise ValueError("Wrong operational comparator")
    return model


def summary(level,actions):
    """Effects of an assignment at one horizon, in 20 permutation-invariant/role-based coordinates."""
    delta=level-level[:1]
    ids=np.arange(len(actions))
    dest=np.maximum(0,actions[:,1]);donor=np.maximum(0,actions[:,2])
    receiver=delta[ids,dest]
    source=delta[ids,donor]*(actions[:,0]==6)[:,None]
    return np.column_stack((delta.sum(1),delta.min(1),delta.max(1),receiver,source))


@dataclass(frozen=True)
class Public:
    fields:np.ndarray
    projected:np.ndarray                 # A,2,20. Only the calendar available at 08:00.
    actions:np.ndarray
    p_safe:np.ndarray
    feasible:np.ndarray
    original:int
    deployed:int
    physics:int
    identity:tuple

def public_case(packet):
    if set(packet)!=PUBLIC_FIELDS:raise ValueError("Only the datestamped public packet is admissible")
    c=original.describe(packet)
    p=np.asarray(packet["projection"],float);acts=np.asarray(packet["actions"],int)
    f=incumbent().infer(c)
    choices=original.choice_map(c,f)
    prob=np.asarray(f["p_safe"],float)
    delivery=np.asarray(packet["projection_delivery"],float)
    deliverable=(delivery[:,[2,3,7]]>TOL).all(1)
    mask=deliverable & (prob>=original.MIN_PROB);mask[0]=True
    orig=choices["appris_calibre"]
    deployed=orig if orig and deliverable[orig] else 0
    return Public(c.x,np.stack([summary(p[:,k],acts) for k in (0,1)],axis=1),
                  acts,prob,mask,orig,deployed,choices["physique"],c.identity)


def train_labels(actual,actions):
    cost=np.asarray(actual,float)
    if cost.ndim!=4 or cost.shape[:2]!=(len(actions),3) or cost.shape[3]!=4:
        raise ValueError("Incorrect paired ward costs")
    targets=np.stack([summary(cost[:,j],actions) for j in (0,1)],axis=1)
    delta=cost[:,1]-cost[0,1]
    safe=(delta[:,:,1:]-.01*cost[0,1,:,1:]<=TOL).all((1,2))
    return targets,safe


def _signed_log(x):
    return np.sign(x)*np.log1p(abs(x))

def _metric_fit(packets):
    x=_signed_log(np.concatenate([c.fields for c,_,_ in packets]).astype(float))
    center=x.mean(0);scale=np.maximum(x.std(0),.05)
    x=np.clip((x-center)/scale,-8.,8.)
    _,directions=eigh(x.T@x/len(x),check_finite=False)
    basis=directions[:,-LINEAR:];rng=np.random.default_rng(SEED)
    return dict(center=center,input_scale=scale,linear=basis,nonlinear=rng.normal(size=(x.shape[1],NONLINEAR))/np.sqrt(x.shape[1]),
                phase=rng.uniform(-1,1,NONLINEAR))


def public_design(weights,c):
    v=np.clip((_signed_log(c.fields.astype(float))-weights["center"])/weights["input_scale"],-8,8)
    f=np.column_stack((v@weights["linear"]/np.sqrt(LINEAR), np.tanh(v@weights["nonlinear"]+weights["phase"])))
    # An explicit action-conditioned displacement makes holding the reference identically zero.
    return f-f[:1]


def macro(c, features, projected, actual=None):
    """A high-level intention mixes executable locations of one resource family.

    Weights depend only on the public 72 h projection at J7. Each family always
    uses the same weights to pool predictor features, projected views and (for
    training only) realized targets. The resulting 24 h target may represent
    several feasible locations, which the lower planner must resolve.
    """
    kinds=[];members=[];fp=[];yp=[];truth=[]
    for kind in KINDS:
        group=np.flatnonzero((c.actions[:,0]==kind)&c.feasible)
        if not len(group):continue
        raw=-c.projected[group,1,0]
        weights=softmax(np.clip((raw-np.max(raw))/max(8.,float(np.std(raw))),-7.,0.))
        kinds.append(kind);members.append(group)
        fp.append(weights@features[group]);yp.append(np.einsum("a,ahd->hd",weights,projected[group]))
        if actual is not None: truth.append(np.einsum("a,ahd->hd",weights,actual[group]))
    return np.asarray(kinds),members,np.asarray(fp),np.asarray(yp),np.asarray(truth)


def _weighted_fit(x,y,weights):
    w=weights/weights.sum()
    cov=x.T@(x*w[:,None])
    cross=x.T@(y*w[:,None])
    return solve(cov+RIDGE*np.eye(cov.shape[0]),cross,assume_a="pos",check_finite=False)


def embedding(x,y,weights,rank):
    """Predictive reduced-rank regression under a regularized unit-covariance constraint.

    The learned encoder maximizes covariance of predictable future coordinates
    under a whitened target metric. A constant encoder cannot satisfy that metric.
    """
    w=weights/weights.sum()
    yy=y.T@(y*w[:,None])
    cov=x.T@(x*w[:,None]);cross=x.T@(y*w[:,None])
    predictive=cross.T@solve(cov+RIDGE*np.eye(cov.shape[0]),cross,assume_a="pos")
    e,v=eigh(yy,check_finite=False)
    whitening=(v*(1/np.sqrt(np.maximum(e,0)+.015)))@v.T
    signal,q=eigh(whitening@predictive@whitening,check_finite=False)
    return whitening@q[:,::-1][:,:rank],signal[::-1][:rank]


def _decoder(z,y,weights):
    w=weights/weights.sum();return solve(z.T@(z*w[:,None])+.001*np.eye(z.shape[1]),z.T@(y*w),assume_a="pos")


def _total_goal(examples,scales):
    # Equal weight per hospital for realizable safe improvements observed on FIT only.
    goals={}
    for c,y,safe in examples:
        valid=safe & c.feasible
        i=int(np.argmin(np.where(valid,y[:,1,0],np.inf)))
        if y[i,1,0] < -TOL:
            goals.setdefault(c.identity[0],[]).append(y[i,1]/scales[1])
    if not goals:raise ValueError("No beneficial reachable control in training")
    return np.mean([np.mean(v,axis=0) for v in goals.values()],axis=0)


def fit_parameters(examples):
    w=_metric_fit(examples)
    raw=np.concatenate([y[c.feasible] for c,y,_ in examples])
    scale=np.sqrt(np.mean(raw**2,axis=0))
    w["scale"]=np.maximum(scale,np.array([.10,.10,.25,.25]*5))
    w["goal"]=_total_goal(examples,w["scale"])
    primitive=[];top=[]
    for c,y,_ in examples:
        feat=public_design(w,c);truth=y/w["scale"];pred=c.projected/w["scale"]
        sel=c.feasible
        primitive.append((feat[sel],truth[sel],pred[sel],np.full(sel.sum(),1/sel.sum())))
        _,_,fm,pm,ym=macro(c,feat,pred,truth)
        top.append((fm,ym,pm,np.full(len(fm),1/len(fm))))
    x,y,p,weights=(np.concatenate(a) for a in zip(*primitive,strict=True))
    mx,my,mp,mw=(np.concatenate(a) for a in zip(*top,strict=True))
    eflat,w["spectrum_flat"]=embedding(np.tile(x,(2,1)),np.concatenate((y[:,0],y[:,1])),
                                         np.tile(weights,2),FINE)
    ef,w["spectrum_fine"]=embedding(x,y[:,0],weights,FINE)
    coarse,w["spectrum_coarse"]=embedding(mx,my[:,1]@ef,mw,COARSE)
    if min(w["spectrum_coarse"])<=1e-8:raise ValueError("Collapsed upper predictive embedding")
    ec=ef@coarse
    w.update(flat_enc=eflat,fine_enc=ef,coarse_from_fine=coarse)
    # Both arms have exactly sixteen learned prediction outputs for a 96-wide
    # common feature bank. Public physical rollouts form the same residual baseline.
    d=(y-p)@eflat
    w["flat_pred"]=_weighted_fit(x,d.reshape(len(x),-1),weights)
    w["fine_pred"]=_weighted_fit(x,(y[:,0]-p[:,0])@ef,weights)
    d=(my-mp)@ec
    w["coarse_pred"]=_weighted_fit(mx,d.reshape(len(mx),-1),mw)
    w["flat_decoder"]=_decoder(y[:,1]@eflat,y[:,1,0],weights)
    w["coarse_decoder"]=_decoder(my[:,1]@ec,my[:,1,0],mw)
    w["flat_goal"]=w["goal"]@eflat;w["coarse_goal"]=w["goal"]@ec
    return w


def _goal_choice(z,goal,transfer,allowed):
    distance=np.square(z-goal).sum(1)
    # Keep the reference on a tied improvement or an adverse predicted transfer.
    valid=allowed&(distance<distance[0]-1e-10)&(transfer< -TOL)
    valid[0]=True
    return int(np.argmin(np.where(valid,distance,np.inf)))


def raw_policy(w,c):
    x=public_design(w,c)
    projected=c.projected/w["scale"]
    flat=projected@w["flat_enc"]+(x@w["flat_pred"]).reshape(len(x),2,FINE)
    ft=(flat[:,1]@w["flat_decoder"])*w["scale"][1,0]
    fi=_goal_choice(flat[:,1],w["flat_goal"],ft,c.feasible)
    fine=projected[:,0]@w["fine_enc"]+x@w["fine_pred"]
    kinds,members,mx,mp,_=macro(c,x,projected)
    ec=w["fine_enc"]@w["coarse_from_fine"]
    coarse=mp@ec+(mx@w["coarse_pred"]).reshape(len(mx),2,COARSE)
    ct=(coarse[:,1]@w["coarse_decoder"])*w["scale"][1,0]
    hi=_goal_choice(coarse[:,1],w["coarse_goal"],ct,np.ones(len(kinds),bool))
    group=members[hi]
    waypoint=coarse[hi,0]
    distance=np.square(fine[group]@w["coarse_from_fine"]-waypoint).sum(1)
    elementary=int(group[np.argmin(distance)])
    return dict(plat=fi,hierarchique=elementary,macro_kind=int(kinds[hi]),n_macros=len(kinds),
                n_fine=int(len(group)),n_eligible=int(c.feasible.sum()),n_catalogue=len(c.actions),
                waypoint=waypoint.tolist(),tracking_distance=float(distance.min()),
                macro_transfer_prediction_h=float(ct[hi]),flat_transfer_prediction_h=float(ft[fi]))


def choices(w,c):
    if not all("cutoff_"+k in w for k in ("plat","hierarchique")):raise ValueError("Uncalibrated policy")
    raw=raw_policy(w,c)
    sel=dict(horaire=0,j7_livre=c.deployed,physique=c.physics,j7_initial=c.original)
    for arm in ("plat","hierarchique"):
        i=raw[arm];sel[arm+"_brut"]=i
        cutoff=float(w["cutoff_"+arm])
        if not np.isfinite(cutoff) or not (cutoff==-1 or 0<=cutoff<=1):raise ValueError("Invalid site calibration cutoff")
        sel[arm]=i if i and c.p_safe[i]>cutoff else 0
    return {k:int(sel[k]) for k in ARMS},raw


def learn():
    fit=[];cal=[]
    for pub,out in paired("train"):
        c=public_case(pub); y,safe=train_labels(out["cost"],c.actions)
        (fit if c.identity[0] in FIT else cal).append((c,y,safe))
    if set(c.identity[0] for c,_,_ in fit)!=set(FIT) or set(c.identity[0] for c,_,_ in cal)!=set(CAL):
        raise ValueError("Hospital separation failed")
    w=fit_parameters(fit)
    calibr={k:{sid:-1. for sid in CAL} for k in ("plat","hierarchique")}
    for c,_,safe in cal:
        r=raw_policy(w,c)
        for arm,sites in calibr.items():
            i=r[arm]
            if i and not safe[i]:
                sites[c.identity[0]]=max(sites[c.identity[0]],float(c.p_safe[i]))
    rank=int(np.ceil((len(CAL)+1)*.90))
    for arm,sites in calibr.items():
        w["cutoff_"+arm]=np.array(sorted(sites.values())[rank-1],dtype=float)
    w["format"]=np.array("hierarchical_hospital_j7_v1")
    OUT.mkdir(exist_ok=True)
    np.savez_compressed(WEIGHTS,**w)
    info={"fit_sites":list(FIT),"calibration_sites":list(CAL),"fit_contexts":len(fit),"calibration_contexts":len(cal),
          "dimensions":{"fine":FINE,"coarse":COARSE,"flat_shared":FINE,"common_features":LINEAR+NONLINEAR},
          "learned_prediction_coefficients":{"flat":w["flat_pred"].size,
                    "hierarchical":w["fine_pred"].size+w["coarse_pred"].size},
          "encoder_coefficients":{"flat":w["flat_enc"].size,"hierarchical":w["fine_enc"].size+w["coarse_from_fine"].size},
          "spectra":{k:w["spectrum_"+k].tolist() for k in ("flat","fine","coarse")},
          "conformal":{"confidence":.90,"rank":rank,"ties":"strictly greater","empty_site":-1,"site_maxima":calibr},
          "cutoffs":{k:float(w["cutoff_"+k]) for k in calibr},"weights_sha256":sha_file(WEIGHTS)}
    (OUT/"ajustement.json").write_text(json.dumps(info,indent=2,allow_nan=False)+"\n")
    return info


def load_model():
    with np.load(WEIGHTS,allow_pickle=False) as f:
        out={k:f[k] for k in f.files}
    if str(out["format"])!="hierarchical_hospital_j7_v1" or not all(np.isfinite(a).all() for k,a in out.items() if k!="format"):
        raise ValueError("Invalid learned weights")
    return out


if __name__=="__main__":
    print(json.dumps(learn()["cutoffs"]))
