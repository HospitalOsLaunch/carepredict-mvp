"""Shared causal inputs for the three-stage synthetic experiment."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'filter_validation'))
from correction import W,L,A,P,C,counts,assert_consistent,reconcile_placements
from guarded_filter import posterior as guarded
from hospitalos.howm.keys import u,key
from hospitalos.howm.generator import refresh_private
from hospitalos.howm.world import local_hour,uncovered
from service_filter import ServiceLaw
import json,copy
import numpy as np

ROOT=Path('evidence/filter_pipeline')
PROTO=json.loads(Path(__file__).with_name('protocol.json').read_text())
PARAMS=json.loads(Path('evidence/filter_validation/run/fit.json').read_text())

class ConstantProbability:
 def __init__(self,p):self.p=float(p)
 def predict_proba(self,x):return np.tile([1-self.p,self.p],(len(x),1))

def laws(delay):return {k:ServiceLaw(**v['law']) for k,v in PARAMS[str(delay)].items()}
def structure(part,index,delay):return C.structure(part,index,delay)
def provider(sp,tick,draw,tag='PIPE_PLAN'):
 s=copy.deepcopy(sp);s.ekey=key(tag,sp.part,sp.idx,tick)
 return W.ProvN(s,draw)

def candidates(ps,pe):
 """Binary candidate events, with public-only covariates and no privileged fields."""
 now=pe.tick;hour=local_hour(now)
 common=[np.sin(2*np.pi*hour/24),np.cos(2*np.pi*hour/24),pe.base_c_cl,pe.base_c_tr,
         sum(b.state=='dirty' for b in pe.beds.values()),sum(b.state=='cleaning' for b in pe.beds.values()),len(pe.tr_service)]
 out=[]
 for sid,s in pe.stays.items():
  if s.departed is not None:continue
  pub=ps.stays[sid]
  features=common+[min(30,(now-s.placed_tick)/96),float(s.iso),s.acuity,len(pe.queue.get(s.unit,[])),
    min(24,(now*15-pub.get('ready',now*15))/60),min(24,(now*15-pub.get('transport_accepted',now*15))/60)]
  if s.ready and not getattr(s,'dest',None) and not getattr(s,'aval',False) and (not s.transport or 'transport_done' in pub):
   out.append(('departure',sid,features))
  if s.ready and s.tr_accepted and s.tr_start is None:
   out.append(('transport_start',sid,features))
 for bid,b in pe.beds.items():
  if b.state=='dirty':
   out.append(('cleaning_start',bid,common+[min(30,(now-(b.dirty_tick or now))/96),float(b.iso),0,len(pe.queue.get(b.unit,[])),
      min(24,(now-(b.dirty_tick or now))/4),0]))
 return out

def truth_label(kind,ref,eng):
 if kind=='departure':return int(ref not in eng.stays or eng.stays[ref].departed is not None)
 if kind=='cleaning_start':return int(eng.beds[ref].state=='cleaning')
 return int(ref in eng.tr_service)

def extended(pe,ps,law,draw,prov,models,enabled):
 eng=pe.clone();eng.on_event=None
 probs=[(kind,ref,float(models[kind].predict_proba(np.asarray([f]))[0,1])) for kind,ref,f in candidates(ps,pe) if kind in enabled]
 for kind,ref,p in probs:
  if kind=='departure' and u('PIPE_FILTER',draw,pe.tick,kind,ref)<p:
   eng.depart(eng.stays[ref])
 eng=guarded(eng,ps,law,draw,prov)
 for kind,ref,p in probs:
  if kind=='departure' or u('PIPE_FILTER',draw,pe.tick,kind,ref)>=p:continue
  if kind=='cleaning_start':
   b=eng.beds[ref]
   cap=eng.base_c_cl+eng.active_extra('cl',eng.tick)-prov.cleaning_capacity_drop(eng,eng.tick)
   if b.state=='dirty' and 6<=local_hour(eng.tick-1)<22 and sum(x.state=='cleaning' for x in eng.beds.values())<cap:
    b.state='cleaning';b.clean_start=eng.tick-1;b.clean_end=10**9
  else:
   s=eng.stays.get(ref)
   if s is not None and s.departed is None and s.tr_start is None and len(eng.tr_service)<eng.base_c_tr+eng.active_extra('tr',eng.tick):
    s.tr_start=eng.tick-1;s.tr_end=10**9;eng.tr_service.append(ref)
 assert_consistent(eng)
 return eng
