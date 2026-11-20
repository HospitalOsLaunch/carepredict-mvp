"""Paired synthetic trajectories and as-of observation snapshots."""
import functools
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'filter_pipeline'))
from common import A, L, W, key, refresh_private, uncovered
from representation import representation

CFG = json.loads(Path(__file__).with_name('protocol.json').read_text())
OUT = Path('evidence/plan48')
# Reserve resources in the morning or after the noon update. Coordination
# includes advancing transport requests and prioritising compatible beds.
PLANS = [(morning, midday) for morning, options in {
    'none':['cl','tr','av_staff','coord_cl','coord_tr','coord_av_staff'],
    'coord':['cl','tr','av_staff'], 'av':['staff','coord_staff'],
    'cl':['none','coord'], 'tr':['none','coord']
}.items() for midday in options]
METRICS = ['boarding','transfer','care','saturation','onset_h','staff']


def cache_arrivals(prov):
    # INT-1 arrivals depend only on provider, unit and hour. Reuse across
    # counterfactuals; requests themselves are constructed by each engine.
    original = prov.arrivals
    cached = functools.lru_cache(None)(lambda unit, hour: original(None, unit, hour))
    prov.arrivals = lambda eng, unit, hour: cached(unit, hour)
    return prov


def apply(eng, recipe, prov, start):
    units = list(eng.units)
    for kind in recipe.split('_'):
        action = next(a for a in A.catalogue(eng, units)
                      if a['kind'] == kind and a['slot'] in (0,1)
                      and (kind != 'staff' or a['unit']==units[len(units)//2]))
        if not A.admissible(eng, action, len(units), start):
            raise ValueError(f'Inadmissible {recipe} at {eng.tick}')
        A.apply(eng, action, W._Cal(prov, eng.spec_meta['drop']))


def queues(eng):
    return [(sum(not r.rid.startswith('T') for r in eng.queue.get(u, [])),
             sum(r.rid.startswith('T') for r in eng.queue.get(u, []))) for u in eng.units]


def snapshot(eng):
    features = []
    for unit, (admission, transfer) in zip(eng.units, queues(eng)):
        beds = [eng.beds[b] for b in eng.units[unit].beds]
        stays = [s for s in eng.stays.values() if s.unit==unit and s.departed is None]
        features.extend([len(beds),len(eng.free_beds(unit)),sum(b.state=='dirty' for b in beds),
                         sum(b.state=='cleaning' for b in beds),admission,transfer,
                         sum(s.ready for s in stays),sum(s.authorised for s in stays),
                         sum(s.tr_req is not None for s in stays)])
    return features+[eng.base_c_cl, eng.base_c_tr, len(eng.aval_blocked), len(eng.tr_service)]


def advance(eng, prov, steps):
    """Compact tick-level data; a same-tick placement still counts as a released bed."""
    window = []
    callback = eng.on_event
    released = set()
    def observe(tick, kind, subject, value):
        if kind=='cleaning_done':
            released.add(value['unit'])
        if callback:
            callback(tick, kind, subject, value)
    eng.on_event = observe
    for _ in range(steps):
        released.clear()
        eng.step(prov)
        queue = queues(eng)
        window.append(([q[0] for q in queue], [q[1] for q in queue],
                       [u in released for u in eng.units],
                       [len(eng.free_beds(u)) for u in eng.units]))
    eng.on_event = callback
    return window


def outcome(trace, eng, start):
    q, transfers, releases, free = map(np.asarray,zip(*trace))
    pressure = q.sum(1)>=4
    hits = np.flatnonzero(np.convolve(pressure.astype(int), np.ones(4,dtype=int),'valid')>=4)
    onset = (hits[0]+1)/4 if len(hits) else len(q)/4
    first = [np.argmax(x)/4+.25 if x.any() else len(q)/4 for x in releases.T]
    hours = range(start//4,eng.tick//4)
    # Unit forecast outputs: external queue at end, first cleaning completion
    # (right-censored at horizon), and available beds at endpoint.
    return list(map(float,[q.sum()*15,transfers.sum()*15,uncovered(eng,hours),
                       bool(len(hits)),onset,A.used_hours(eng)[1],*q[-1],*first,*free[-1]]))


def public_forecast(spec, pe, draw):
    # Fixed independent structural template; only public static fields are copied.
    prior=W.n_unit_structure('PLAN48_PUBLIC_PRIOR',0,4,regime='fragile',
                             bottlenecks=('cleaning','transport','aval','transfer'))
    prior.ekey=key('PLAN48_PROJECTION', pe.tick,draw)
    prior.beds={u:len(v.beds) for u,v in pe.units.items()}
    prior.nominal=dict(spec.nominal)  # static public observation
    prior.aval_slots_per_day=pe.spec_meta['aval_slots']
    prior.c_cl,prior.c_tr=pe.base_c_cl,pe.base_c_tr
    prior.drop=dict(pe.spec_meta['drop'])
    prov=cache_arrivals(W.ProvN(prior,draw))
    state=pe.clone()
    refresh_private(state,W._Cal(prov,prior.drop))
    return state,prov


def branches(eng, prov, morning, start, prefix=None):
    rows={}
    for first,second in PLANS:
        if first!=morning:
            continue
        work=eng.clone()
        work.on_event=None
        apply(work,second,prov,start)
        trace=advance(work,prov,176)
        rows[second]=outcome(trace,work,start+16)
        if prefix is not None:
            rows[second]=[rows[second],outcome(prefix+trace,work,start)]
        assert A.used_hours(work)[1]==16
    return rows


def forecast_morning(spec,pe):
    start=pe.tick
    state,prov=public_forecast(spec,pe,10001)
    forecasts=[]
    for morning in dict(PLANS):
        work=state.clone()
        apply(work,morning,prov,start)
        trace=advance(work,prov,16)
        for _,full in branches(work,prov,morning,start,trace).values():
            forecasts.append(full)
    return forecasts


def generate(job):
    split,idx=job
    sp=W.n_unit_structure('PLAN48_A_'+split,idx,4,regime='fragile',
                          bottlenecks=('cleaning','transport','aval','transfer'))
    sp=W.episode(sp,0)
    sp.theta['lag_min']=180
    pre=L.prefix(sp,56)
    start=pre['t0']
    ps,pe=L.public_view(pre,W.Recorder(sp,0),start)
    _,public_provider=public_forecast(sp,pe,10003)
    initial_latents=representation(sp,ps,pe,public_provider)
    proj=forecast_morning(sp,pe)
    cases=[]
    for draw in CFG['futures']:
        rows=[]
        for morning in dict(PLANS):
            eng,prov,rec=L.start_future(pre,sp,draw)
            cache_arrivals(prov)
            apply(eng,morning,prov,start)
            trace=advance(eng,prov,16)
            visible,noon=L.public_view(pre,rec,eng.tick)
            predicted,pp=public_forecast(sp,noon,10002)
            latents=representation(sp,visible,noon,pp)
            forecasts=branches(predicted,pp,morning,start)
            results=branches(eng,prov,morning,start,trace)
            for second,(remaining,full) in results.items():
                rows.append(dict(noon=snapshot(noon),latents=latents,future=remaining,full=full,
                                 midday_forecast=forecasts[second],observed_4h=outcome(trace,eng,start)))
        cases.append(dict(draw=draw,rows=rows))
    return dict(split=split,hospital=idx,morning=snapshot(pe),latents=initial_latents,forecast=proj,cases=cases)


def dataset(split):
    OUT.mkdir(parents=True,exist_ok=True)
    jobs=[(split,i) for i in range(CFG['structures'][split])]
    with ProcessPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(generate,jobs))
    (OUT/(split+'.json')).write_text(json.dumps(rows,separators=(',',':')))
    return rows


if __name__=='__main__':
    dataset(sys.argv[1])
