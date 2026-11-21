"""Independent algebra and paired-hospital calculations for hindsight and prospective evaluation."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np


def canon(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def anchored(forecast,factual_index,observed,mask=None):
    forecast=np.asarray(forecast,float)
    observed=np.asarray(observed,float)
    if (forecast.ndim<2 or type(factual_index) is not int or not 0<=factual_index<len(forecast)
            or observed.shape!=forecast.shape[1:] or not np.isfinite(forecast).all()):
        raise ValueError("Invalid event, action or factual shapes")
    mask=np.ones(observed.shape,bool) if mask is None else np.asarray(mask)
    if mask.dtype!=np.bool_ or mask.shape!=observed.shape or not np.isfinite(observed[mask]).all():
        raise ValueError("A published value must be finite and described by the dated mask")
    residual=np.zeros_like(observed)
    residual[mask]=observed[mask]-forecast[factual_index][mask]
    return forecast+residual[None]


def cluster_interval(site_means,draws=20000,seed=28112619):
    v=np.asarray(site_means,float)
    if v.ndim!=1 or len(v)<2 or not np.isfinite(v).all() or type(draws) is not int or draws<200:
        raise ValueError("A paired scalar per independent hospital is required")
    n=len(v);rng=np.random.default_rng(seed)
    w=rng.multinomial(n,np.full(n,1./n),size=draws)
    return dict(mean=float(v.mean()),ci95=np.quantile(w@v/n,[.025,.975]).tolist(),hospitals=n,draws=draws,seed=seed)


def score_event(forecast,actual,factual,observed=None,tol=1e-8,mask=None):
    p=np.asarray(forecast,float);y=np.asarray(actual,float)
    if p.shape!=y.shape or y.ndim<2 or len(y)<2 or not np.isfinite(y).all():
        raise ValueError("Paired actual and forecast rows must contain multiple actions")
    z=anchored(p,factual,y[factual] if observed is None else observed,mask)
    usable=np.arange(len(y))!=factual
    effect=y-y[factual]
    predicted=p-p[factual]
    change=abs(effect)>tol
    effect_energy=float(np.mean(effect[usable]**2))
    preference=(np.diff(p,axis=0)-np.diff(z,axis=0))
    per={
       "forecast_level_mae":np.mean(np.abs(p[usable]-y[usable])),
       "anchored_level_mae":np.mean(np.abs(z[usable]-y[usable])),
       "no_action_level_mae":np.mean(np.abs(y[factual]-y[usable])),
       "forecast_effect_mae":np.mean(np.abs(predicted[usable]-effect[usable])),
       "zero_effect_mae":np.mean(np.abs(effect[usable])),
       "squared_error_effect":np.mean((predicted[usable]-effect[usable])**2),
       "squared_energy_effect":effect_energy,
       "max_change_linear_pairwise_difference":np.max(np.abs(preference)),
       "changed_coordinates":np.sum(change[usable]),
       "inspected_coordinates":change[usable].size,
    }
    return {k:int(v) if k in ("changed_coordinates","inspected_coordinates") else float(v) for k,v in per.items()}


def no_spurious_contrast(physical,reference,unused,tol=1e-8):
    truth=np.asarray(physical);unused=np.asarray(unused)
    if unused.shape!=(len(truth),) or unused.dtype!=np.bool_ or not unused[reference]:
        raise ValueError("A same-treatment identity test must include the factual reference")
    if not np.isfinite(truth).all() or np.max(np.abs(truth[unused]-truth[reference]))>tol:
        raise ValueError("An arm with an identical effective treatment changed the causal result")
