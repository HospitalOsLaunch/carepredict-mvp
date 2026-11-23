"""Five calendar years, 60 independently initialized monthly INT-1 episodes.

Each month has seven days of warmup. Events stay causal. Monthly boundaries
are explicit and excluded from training transitions. No 5-year continuity claim.
"""
import calendar,datetime as dt,heapq,pickle,time
from common import *
from hospitalos.howm.world import SKILLS
from review_metrics import monthly_resource_plan

class ImmutableRoster(tuple):
 """Share immutable calendars between particles without copying 40 days each time."""
 def __deepcopy__(self,memo):return self

def freeze_rosters(eng):
 for unit in eng.units.values():
  unit.roster={k:ImmutableRoster(v) for k,v in unit.roster.items()}


def prune(eng,ps):
 cutoff=eng.tick-7*96
 keep=set(eng.transfer_pending.values())|set(eng.tr_service)|set(eng.aval_blocked)
 eng.stays={sid:s for sid,s in eng.stays.items() if s.departed is None or s.departed>=cutoff or sid in keep}
 eng.demand={k:v for k,v in eng.demand.items() if k[2]>=eng.tick//4-48}
 eng.capacity={k:v for k,v in eng.capacity.items() if k[2]>=eng.tick//4-48}
 eng.hourly=[];eng.log=[]
 eng.commitments=[c for c in eng.commitments if c['end']>=cutoff]
 # Public entity joins are retained within each monthly episode. Never prune
 # unseen pending events or infer their contents. Observations are incremental.


def graph_inputs(eng,sp,month):
 n=sp.n;unit=np.zeros((n,54),np.float32);res=np.zeros((3,10),np.float32)
 for i,un in enumerate(sp.units):
  s=L.unit_state(eng,un);b=sp.beds[un]
  unit[i,0]=b/64;unit[i,1]=sp.nominal[un]/64;unit[i,2]=sp.iso_beds[un]/64
  unit[i,[3,4,6]]=s[:3]
  unit[i,7]=sum(eng.beds[bid].state=='cleaning' for bid in eng.units[un].beds)/b
  unit[i,8:14]=np.asarray(s[3:])/b
  unit[i,14]=sum(x.ready and x.departed is None for x in eng.stays.values() if x.unit==un)/b
  unit[i,22]=eng.units[un].roster['IDE'][eng.tick//4]/16
 res[0,:3]=[eng.base_c_cl/8,sum(b.state=='cleaning' for b in eng.beds.values())/8,sum(b.state=='dirty' for b in eng.beds.values())/64]
 res[1,:3]=[eng.base_c_tr/8,len(eng.tr_service)/8,sum(s.ready and s.transport and not W.transport_started(s) and s.departed is None for s in eng.stays.values())/64]
 res[2,8:10]=[eng.aval_cap(eng.tick)/8,eng.aval_used.get(eng.tick//96,0)/8]
 hr=local_hour(eng.tick)
 glob=np.array([np.sin(2*np.pi*hr/24),np.cos(2*np.pi*hr/24),np.sin(2*np.pi*(month%12)/12),np.cos(2*np.pi*(month%12)/12),1,1,0,n/12],np.float32)
 uu=np.zeros((n,n),np.float32)
 for s in eng.stays.values():
  dest=getattr(s,'dest',None)
  if s.departed is None and dest in sp.units:uu[sp.units.index(s.unit),sp.units.index(dest)]+=1
 return unit,res,glob,uu


def generate_episode(part,index,month,models,enabled,probe_only=False):
 year=2020+month//12;mo=month%12+1;days=calendar.monthrange(year,mo)[1]
 sp=structure(part,index,180);sp.ekey=key('PIPE_MONTH',sp.skey,month)
 sp.theta['arr_mult']*=1+.1*np.sin(2*np.pi*month/12)
 sp.start_utc=(dt.date(year,mo,1)-dt.timedelta(days=7)).isoformat()+'T00:00:00+01:00'
 prov=W.ProvN(sp,0);eng=W.initial_engine(sp,prov,roster_hours=41*24);eng.emit_log=False
 freeze_rosters(eng)
 ps=W.PublicStreamN(W.static_obs(eng,sp));ps.advance(0)
 rec=W.Recorder(sp,0);eng.on_event=rec;pending=[];serial=0
 data={k:[] for k in ('unit','res','glob','uu','truth','cost','care','R','clock')}
 previous_wait={un:0 for un in sp.units}
 # Entire exogenous daily intervention calendar is known at forecast origin.
 scheduled={d:('none','cl','tr')[int(u(sp.ekey,0,'schedule',d)*3)] for d in range(days+7)}
 scheduled[7]='none'  # reserve first test-day afternoon for a paired action probe
 probe={}
 def drain():
  nonlocal serial
  for o in rec.obs:
   heapq.heappush(pending,(o[1],o[0],o[2],o[3],serial,o));serial+=1
  rec.obs=[]
  while pending and pending[0][0]<eng.tick*15:ps._apply(heapq.heappop(pending)[-1])
  ps.t=eng.tick*15-1
 while eng.tick<=(days+7)*96:
  if eng.tick%24==0 and eng.tick>=7*96:
   drain();pe=ps.to_engine_n(eng.tick);freeze_rosters(pe)
   # Same selected estimator as stage 1; four paired particles.
   gs=[]
   for draw in range(20001,20001+PROTO['particles']):
    particle=extended(pe,ps,laws(180),draw,provider(sp,eng.tick,draw,'PIPE_DATA_FILTER'),models,enabled)
    gs.append(graph_inputs(particle,sp,month))
   for k,j in [('unit',0),('res',1),('glob',2),('uu',3)]:data[k].append(np.mean([g[j] for g in gs],axis=0))
   states=np.array([L.unit_state(eng,un) for un in sp.units],np.float32)
   states[:,3:]/=np.array([sp.beds[un] for un in sp.units])[:,None]
   data['truth'].append(states)
   costs=[];cares=[]
   for un in sp.units:
    costs.append((eng.waiting_ticks.get(un,0)-previous_wait[un])*15/(360*sp.beds[un]))
    previous_wait[un]=eng.waiting_ticks.get(un,0)
    care=sum(max(0,eng.demand.get((un,sk,h),0)-60*eng.capacity.get((un,sk,h),0)) for h in range(eng.tick//4-6,eng.tick//4) for sk in SKILLS)
    cares.append(care/(360*sp.beds[un]))
   data['cost'].append(costs);data['care'].append(cares)
   # Schedule for the next six hours; aligned as interval starting at origin.
   R=np.zeros((3,3),np.float32)
   for t in range(eng.tick,eng.tick+24):
    d=t//96;k=scheduled.get(d,'none')
    if k!='none' and 6<=local_hour(t)<14:R[0 if k=='cl' else 1,0]+=A.intensity(sp.n)/24
   data['R'].append(R)
   hr=local_hour(eng.tick);data['clock'].append([np.sin(2*np.pi*hr/24),np.cos(2*np.pi*hr/24),(month%12)/12])
   if part==PROTO['jepa_test'] and month%6==5 and eng.tick==7*96:
    from consequences import project
    from correction import choices
    from hospitalos.howmint.features import schedule
    actions=choices(eng,sp.units,eng.tick,eng.tick+96)
    assert [a['kind'] for a in actions]==['none','cl','tr']
    probe['probe_R']=monthly_resource_plan(np.array([schedule([a],sp.units,eng.tick,4,6,sp.drop,step_h=6)['R'] for a in actions]))
    probe['probe_clock']=np.array([[np.sin(2*np.pi*((6*k)%24)/24),np.cos(2*np.pi*((6*k)%24)/24),(month%12)/12] for k in range(4)])
    probe['probe_staff']=np.array([a['staff_hours'] for a in actions])
    outcomes=[]
    for a in actions:
     futures=[]
     for draw in (1,2):
      pp=W.ProvN(sp,draw,regime_anchor=W.regime_anchor(prov,eng.tick))
      rr=project(eng,pp,a)
      futures.append([[rr[h][m] for m in ('free_beds','queue','wait_patient_min','uncovered_care_min')] for h in (6,12,24)])
     outcomes.append(np.mean(futures,axis=0))
    probe['probe_truth']=np.array(outcomes)
    if probe_only:return {k:np.asarray(v,dtype=np.float32) for k,v in probe.items()}
  if eng.tick==(days+7)*96:break
  if eng.tick%96==16:
   kind=scheduled[eng.tick//96]
   if kind!='none':
    action=next(a for a in A.catalogue(eng,sp.units) if a['kind']==kind and a['slot']==1)
    assert A.admissible(eng,action,sp.n,(eng.tick//96)*96)
    A.apply(eng,action,W._Cal(prov,sp.drop))
  eng.step(prov);drain()
  if eng.tick%96==0:prune(eng,ps)
 data={k:np.asarray(v,dtype=np.float32) for k,v in data.items()}
 data['cost'][0]=0;data['care'][0]=0
 data['beds']=np.array([sp.beds[un] for un in sp.units],np.float32)
 data['month']=np.array(month);data['days']=np.array(days)
 data.update({k:np.array(v,dtype=np.float32) for k,v in probe.items()})
 return data


def run(part,index,limit=60):
 models=pickle.loads((ROOT/'filter_models.pkl').read_bytes());enabled=json.loads((ROOT/'filter_selection.json').read_text())['enabled']
 out=ROOT/'corpus'/part/f'{index:02d}';out.mkdir(parents=True,exist_ok=True)
 for month in range(limit):
  t=time.time();data=generate_episode(part,index,month,models,enabled)
  np.savez_compressed(out/f'{month:02d}.npz',**data)
  print('Corpus',part,index,month,'steps',len(data['truth'])-1,'seconds',round(time.time()-t,2),flush=True)

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--part',required=True);p.add_argument('--index',type=int,required=True);p.add_argument('--limit',type=int,default=60)
 a=p.parse_args();run(a.part,a.index,a.limit)
