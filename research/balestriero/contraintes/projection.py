"""Minimum-distance physical correction of per-ward census estimates after a factual readout."""
import numpy as np

from cf.mesures import anchored


def _lits(values,capacity):
    """Project any nonempty set of unknown bed categories onto its remaining capacity."""
    desc=np.sort(values,axis=-1)[...,::-1]
    thresholds=(np.cumsum(desc,axis=-1)-np.asarray(capacity)[...,None])/np.arange(1,desc.shape[-1]+1)
    count=(desc>thresholds).sum(-1,keepdims=True)
    tau=np.take_along_axis(thresholds,np.maximum(count-1,0),axis=-1)
    return np.where(np.asarray(capacity)[...,None]>0,np.maximum(values-np.maximum(tau,0.),0.),0.)


def rendre_faisable(census,beds):
    """Project the external queue onto R+ and the four bed states onto the capped simplex, per ward."""
    a=np.asarray(census,dtype=np.float64)
    limits=np.asarray(beds,dtype=np.float64)
    if a.ndim<2 or a.shape[-1]!=5 or limits.shape!=(a.shape[-2],) or not np.isfinite(a).all():
        raise ValueError("Expected finite five-component ward census and one bed count per ward")
    if not np.isfinite(limits).all() or np.any(limits<=0):
        raise ValueError("Every ward needs a positive capacity")
    out=np.maximum(a,0.)
    out[...,1:]=_lits(a[...,1:],limits)
    return out


def reconstruire(predictions,index_factuel,releve,masque,capacites,*,heure_consultation,heure_publication):
    """Public after-action API. No simulated alternative or true future is needed on this entry point."""
    x=np.asarray(predictions,dtype=np.float64);y=np.asarray(releve,dtype=np.float64)
    visible=np.asarray(masque);caps=np.asarray(capacites,dtype=np.float64)
    if (x.ndim!=3 or x.shape[-1]!=5 or y.shape!=x.shape[1:] or visible.shape!=y.shape
        or visible.dtype!=np.bool_ or caps.shape!=(y.shape[0],)):
        raise ValueError("Unmatched observed wards and model scenarios")
    if (isinstance(index_factuel,(bool,np.bool_)) or not isinstance(index_factuel,(int,np.integer))
        or not 0<=index_factuel<len(x) or not np.isfinite([heure_consultation,heure_publication]).all()):
        raise ValueError("Unknown factual assignment or unavailable clock")
    if not np.isfinite(x).all() or not np.isfinite(caps).all() or np.any(caps<=0):
        raise ValueError("Unusable baseline or capacity")
    if heure_consultation<heure_publication:
        return rendre_faisable(x,caps)
    if np.any(y[visible]<-1.e-7) or np.any(np.where(visible[:,1:],y[:,1:],0.).sum(-1)>caps+1.e-7):
        raise ValueError("Published census conflicts with unit capacity")
    raw=anchored(x,y,visible,int(index_factuel),heure_consultation,heure_publication)
    out=rendre_faisable(raw,caps)
    # Only the actually executed action has observations that must remain exact.
    # Preserve its reported bed categories and reconcile any imputed categories with the remaining beds.
    factual=out[index_factuel]
    factual[visible]=np.maximum(y[visible],0.)
    for ward,known in enumerate(visible[:,1:]):
        if known.any() and not known.all():
            left=max(0.,caps[ward]-factual[ward,1:][known].sum())
            factual[ward,1:][~known]=_lits(raw[index_factuel,ward,1:][~known],left)
    return out
