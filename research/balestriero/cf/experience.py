"""Commit public forecasts, a single factual readout, and then the paired alternatives."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from datetime import datetime,timezone
from functools import lru_cache
from hashlib import sha256,file_digest
import json
import os
from pathlib import Path
import tempfile
import fcntl
import multiprocessing as mp

import numpy as np
from cible import engine
from cible.study import write_json
from j7.episodes import first_week
from lot28 import features as feat,model as native,planning,simulator as sim
from lot28.corpus import _bedside,observation,mask_index
from renforts.evaluate import model as donor_model
from renforts.options import shared


ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"cf/resultats"
H=(1,4,8,12,24)
SEEDS=(19,37,71)
FEEDS=("full","partial","delayed")
CLOCKS=(0,4)
TEST=tuple(range(116000,116064))
DEV=(115900,115901)
STAGES=("public","factuel","verite")
PARENT="7adb566b03fb48661984bab010be9965360ab3195a43281f54c9128a790d1c15"
FIELDS=("ED","ACTIVE","READY_SMR","DIRTY","INTERNAL_READY")


def sha(path):
    with Path(path).open("rb") as stream:return file_digest(stream,"sha256").hexdigest()


def stable(value):
    return sha256(json.dumps(value,separators=(",",":"),sort_keys=True,allow_nan=False).encode()).hexdigest()


def payload(src):
    with np.load(src,allow_pickle=False) as read:return dict(read)


def record_name(s,e,feed,offset):
    return f"{s}_{e}_{feed}_{offset}.npz"


def settings():
    return dict(parent=PARENT,sites=list(TEST),dev=list(DEV),episodes=[0,1],feeds=list(FEEDS),history_days=7,
                clocks=list(CLOCKS),horizons=list(H),day=7,seeds=list(SEEDS),primary_seed=19,
                primary="12:00, H+4 (16:00), full observation, post-receipt: per-ward transfer stock MAE",
                design="At 08:00: one atomic staff or mobile logistics change. At noon: logistics only. Fixed public continuation.",
                factual="balance reference and active action families without looking at outcomes, same draw across episodes",
                uncertainty="20000 paired site bootstrap resamples, seed 261118",
                lag_hours={"full":0,"partial":0,"delayed":2},indices=list(FIELDS))


def inputs():
    files=list((ROOT/"cf").glob("*.py"))+[ROOT/"cf/PROTOCOLE.md",ROOT/"base/MANIFESTE_SHA256.txt"]
    files+=list((ROOT/"cf/tests").glob("*.py"))
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files)}


def verify_base():
    root=ROOT/"base"
    for line in (root/"MANIFESTE_SHA256.txt").read_text().splitlines():
        expected,name=line.split("  ",1)
        if sha(root/name)!=expected:raise ValueError(f"Changed HospitalOS release file: {name}")


@contextmanager
def hold():
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/".run.lock").open("a+b") as f:
        fcntl.flock(f,fcntl.LOCK_EX)
        yield


def seal():
    with hold():
        if any(p.name!=".run.lock" for p in OUT.iterdir()):raise ValueError("Study already opened")
        verify_base()
        write_json(OUT/"gel.json",dict(registered_utc=datetime.now(timezone.utc).isoformat(),
                                       design=settings(),files=inputs()))
        return sha(OUT/"gel.json")


def verify_lock(lock):
    if sha(OUT/"gel.json")!=lock:raise ValueError("Study identifier mismatch")
    frozen=json.loads((OUT/"gel.json").read_text())
    if frozen["files"]!=inputs() or frozen["design"]!=settings():raise ValueError("Frozen specification changed")
    verify_base()


def panel_keys(sites):
    return ((s,e,f,k) for s in sites for e in (0,1) for f in FEEDS for k in CLOCKS)


def receipt(folder,stage,lock,parent,expected,sites):
    path=folder/f"recu_{stage}.json"
    if sha(path)!=expected:raise ValueError("External receipt mismatch")
    value=json.loads(path.read_text())
    if (value["stage"],value["lock"],value["parent"])!=(stage,lock,parent):
        raise ValueError("Stage provenance mismatch")
    actual={p.name:sha(p) for p in sorted((folder/stage).glob("*.npz"))}
    if actual!=value["files"] or set(actual)!={record_name(*k) for k in panel_keys(sites)}:
        raise ValueError("Missing, changed or extraneous episode records")
    return value


def verify_all(lock,public,factuel,verite):
    verify_lock(lock)
    previous=None
    for stage,h in zip(STAGES,(public,factuel,verite),strict=True):
        receipt(OUT,stage,lock,previous,h,TEST)
        previous=h


def digest_array(a):
    v=np.ascontiguousarray(a)
    return sha256(v.view(np.uint8)).hexdigest()


def view_digest(view):
    fields={}
    for name,value in vars(view).items():
        if isinstance(value,np.ndarray):
            fields[name]=(value.dtype.str,list(value.shape),digest_array(value))
        elif isinstance(value,np.generic):
            fields[name]=value.item()
        else:
            fields[name]=value
    return stable(fields)


@lru_cache(maxsize=1)
def models():
    return tuple(native.load_model("jepa",seed) for seed in SEEDS)


def encode_target(site,states,model):
    w=model.w
    x=native.standard(feat.state_features(site,states),w["xm"],w["xs"])
    return np.tanh(x@w["ema_encoder"]+w["ema_bias"])


def predictors(site,view,grid,offset):
    """This boundary receives a dated public view. It cannot access an episode's true drivers."""
    measures,states=sim.rollout(site,view.state,view.forecast[offset:],grid,H,start_hour=offset)
    base=feat.normalized(site,measures,states,H)
    features=feat.action_features(site,view,grid,base,offset,H)
    x=feat.state_features(site,view.state)
    preds=[states]
    latents=[]
    for model in models():
        w=model.w
        scores=model.predict(x,features,base)
        preds.append(scores[...,4:].astype(float)*np.asarray(site.beds)[:,None])
        std_x=native.standard(x,w["xm"],w["xs"])
        std_action=native.standard(features,w["am"],w["as"])
        latents.append(native.forward(w,std_x,std_action)[1])
    return np.stack(preds).astype(np.float64),np.stack(latents).astype(np.float32)


def factual_choice(actions,site,offset):
    families=(0,4,5,6) if offset==0 else (0,4,5)
    rg=np.random.default_rng([261118,site,offset])
    kind=rg.choice(families)
    return int(rg.choice(np.flatnonzero(actions[:,0]==kind)))


def alternatives(grid,fact):
    seen={grid[fact].tobytes()}
    unique=[]
    for i,g in enumerate(grid):
        ident=g.tobytes()
        if ident not in seen:
            seen.add(ident);unique.append(i)
    if not unique:raise ValueError("No distinct alternative")
    return np.asarray(unique,dtype=int)


def prepare(ep,cp,feed,offset):
    site=ep.site;day=7
    engine._check_prefix(ep,feed,7,cp)
    ledger=cp.records[0][-6:]
    if offset==0:
        x=cp.state
        view=observation(ep,day,feed,history_days=7,census=x,minute=0)
        anchor=engine._hourly(site,view,day,ledger,0,None,cp.seed)
    elif offset==4:
        _,anchor,_,x,_,contact=engine._open_noon(ep,day,feed,7,cp.state,ledger,cp.seed)
        view=observation(ep,day,feed,contact,7,census=x,minute=240)
    else:
        raise ValueError("Unregistered decision time")
    if view.asof != day*1440+offset*60:raise ValueError("Undated public state")
    actions=engine._candidates(site)
    if offset:actions=actions[np.isin(actions[:,0],(0,4,5))]
    grid=engine._override(anchor,actions)
    if not sim.affordable(site,grid,ledger).all():raise ValueError("Unaffordable intervention")
    if offset and not np.array_equal(grid[:,0,:2],np.broadcast_to(anchor[0,:2],grid[:,0,:2].shape)):
        raise ValueError("Changed a locked noon booking")
    return view,grid,actions,x


def published_endpoint(ep,feed,states,offset):
    arr=[];masks=[]
    for h,x in zip(H,states,strict=True):
        day=7+(h+offset)//24
        _,m=_bedside(ep,day,mask_index(feed),x)
        arr.append(np.where(m,x,np.nan));masks.append(m)
    available=np.asarray(H)+7*24+offset+(2 if feed=="delayed" else 0)
    return np.stack(arr),np.stack(masks),available


def save_file(path,fields):
    with path.open("wb") as stream:np.savez_compressed(stream,**fields)


def produce(stage,paths,folder,key,ep,cp):
    sid,e,feed,offset=key
    name=record_name(*key);view,grid,actions,x=prepare(ep,cp,feed,offset)
    fact=factual_choice(actions,sid,offset);when=7*24+offset
    identity=dict(site=sid,episode=e,feed=feed,offset=offset)
    if stage=="public":
        pred,latent=predictors(ep.site,view,grid,offset)
        data=dict(**identity,pred=pred,latent_pred=latent,grid=grid,actions=actions,
                  factual=fact,beds=ep.site.beds,route=ep.site.route,source_hour=when,horizons=np.array(H),
                  view_sha=digest_array(view.forecast),state_sha=digest_array(view.state),public_view_sha=view_digest(view))
    else:
        pub=payload(folder/"public"/name)
        if not (np.array_equal(pub["grid"],grid) and np.array_equal(pub["actions"],actions) and
            int(pub["factual"])==fact and int(pub["source_hour"])==when and pub["state_sha"]==digest_array(view.state)
            and pub["view_sha"]==digest_array(view.forecast) and pub["public_view_sha"]==view_digest(view)):
            raise ValueError("Public snapshot or action has changed")
        suffix=ep.truth[when:when+max(H)]
        common=dict(**identity,world_sha=digest_array(suffix),source_physical_sha=digest_array(x),public_sha=sha(folder/"public"/name))
        if stage=="factuel":
            physical,st=sim.rollout(ep.site,x,suffix,grid[fact:fact+1],H,start_hour=offset)
            report,mask,dates=published_endpoint(ep,feed,st[0],offset)
            data=dict(**common,reported=report,mask=mask,available_hour=dates,factual=fact)
        elif stage=="verite":
            obs=payload(folder/"factuel"/name)
            physical,st=sim.rollout(ep.site,x,suffix,grid,H,start_hour=offset)
            report,mask,dates=published_endpoint(ep,feed,st[fact],offset)
            if (not np.array_equal(report,obs["reported"],equal_nan=True) or not np.array_equal(mask,obs["mask"])
                    or not np.array_equal(dates,obs["available_hour"]) or common["world_sha"]!=str(obs["world_sha"])
                    or common["source_physical_sha"]!=str(obs["source_physical_sha"])):
                raise ValueError("Factual outcome not reproduced under the same realized disturbance")
            if np.any(physical[...,sim.M_DONOR_VIOLATION]) or not np.isfinite(st).all():
                raise ValueError("Realized world violated a hard constraint")
            data=dict(**common,states=st,metrics=physical,factual_sha=sha(folder/"factuel"/name))
        else:raise ValueError(stage)
    save_file(paths/name,data)


def worker(args):
    stage,s,folder,temp=args
    for eid in (0,1):
        ep=sim.episode(s,eid)
        for f in FEEDS:
            cp=first_week(ep,f,7)
            for offset in CLOCKS:
                produce(stage,Path(temp),Path(folder),(s,eid,f,offset),ep,cp)
    return s


def generate(stage,folder,lock,parent,sites,workers):
    donor_model();shared();sim._kernel();models()
    dest=folder/stage
    marker=folder/f"recu_{stage}.json"
    with tempfile.TemporaryDirectory(dir=folder,prefix="reprise_") as tmp:
        jobs=((stage,s,str(folder),tmp) for s in sites)
        with ProcessPoolExecutor(workers,mp_context=mp.get_context("fork")) as pool:
            for i,_ in enumerate(pool.map(worker,jobs),1):
                if i%16==0:print(stage,i,flush=True)
        sources={p.name:sha(p) for p in sorted(Path(tmp).glob("*.npz"))}
        if set(sources)!={record_name(*k) for k in panel_keys(sites)}:raise ValueError("Incomplete generation")
        info=dict(stage=stage,lock=lock,parent=parent,files=sources)
        if marker.exists() and json.loads(marker.read_text())!=info:raise ValueError("Nonidentical stage replay")
        if dest.exists() and any(sha(f)!=sources.get(f.name) for f in dest.iterdir()):raise ValueError("Divergent reserved data")
        dest.mkdir(exist_ok=True)
        for name in sources:
            if not (dest/name).exists():os.replace(Path(tmp)/name,dest/name)
        if not marker.exists():write_json(marker,info)
        h=sha(marker);receipt(folder,stage,lock,parent,h,sites)
        return h


def run(stage,lock,public,factuel,workers):
    if workers<1:raise ValueError("Expected a positive worker count")
    with hold():
        verify_lock(lock)
        parent=None
        for previous,h in zip(STAGES[:STAGES.index(stage)],(public,factuel)):
            receipt(OUT,previous,lock,parent,h,TEST)
            parent=h
        if not (OUT/f"recu_{stage}.json").exists() and any((OUT/s).exists() for s in STAGES[STAGES.index(stage)+1:]):
            raise ValueError("A later stage has already begun")
        return generate(stage,OUT,lock,parent,TEST,workers)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("stage",choices=("gel","dev",*STAGES))
    p.add_argument("--lock");p.add_argument("--public");p.add_argument("--factuel");p.add_argument("--workers",type=int,default=6)
    p.add_argument("--directory",type=Path)
    a=p.parse_args()
    if a.stage=="gel":print(seal())
    elif a.stage=="dev":
        if a.directory is None or a.directory.resolve()==OUT.resolve():raise ValueError("Separate development directory required")
        a.directory.mkdir(parents=True,exist_ok=True);prev=None
        for stage in STAGES:prev=generate(stage,a.directory,"development",prev,DEV,a.workers)
    else:print(run(a.stage,a.lock,a.public,a.factuel,a.workers))


if __name__=="__main__":main()
