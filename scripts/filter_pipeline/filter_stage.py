import argparse,json,pickle
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from common import *


def collect(part,n,models=None,enabled=()):
 rows,states=[],[]
 for idx in range(n):
  for delay in PROTO['delays']:
   sp=structure(part,idx,delay);pre=L.prefix(sp,48)
   eng,prov,rec=L.start_future(pre,sp,1)
   while eng.tick<=92*4:
    if eng.tick//4 in PROTO['origins_hours'] and eng.tick%4==0:
     ps,pe=L.public_view(pre,rec,eng.tick)
     for kind,ref,features in candidates(ps,pe):
      row=dict(structure=idx,delay=delay,tick=eng.tick,kind=kind,truth=truth_label(kind,ref,eng),features=features)
      if models is not None:row['p']=float(models[kind].predict_proba(np.array([features]))[0,1])
      rows.append(row)
     if models is not None:
      samples={name:[] for name in ('guarded','extended')}
      for draw in range(20001,20001+PROTO['particles']):
       pp=provider(sp,eng.tick,draw)
       samples['guarded'].append(guarded(pe,ps,laws(delay),draw,pp))
       samples['extended'].append(extended(pe,ps,laws(delay),draw,pp,models,enabled))
      for unit in eng.units:
       for metric,truth in counts(eng,unit).items():
        states.append(dict(structure=idx,delay=delay,tick=eng.tick,unit=unit,metric=metric,truth=truth,
          **{name:float(np.mean([counts(p,unit)[metric] for p in ss])) for name,ss in samples.items()}))
    eng.step(prov)
  print('Filter',part,idx,flush=True)
 return rows,states


def main(mode):
 ROOT.mkdir(parents=True,exist_ok=True)
 if mode=='fit':
  rows,_=collect(PROTO['filter_train'],PROTO['filter_train_structures'])
  models={}
  for kind in PROTO['components']:
   rr=[r for r in rows if r['kind']==kind];y=np.array([r['truth'] for r in rr])
   if not len(y):raise RuntimeError(f'No candidates for {kind}')
   if len(set(y))<2:
    models[kind]=ConstantProbability(y[0])
   else:
    models[kind]=HistGradientBoostingClassifier(max_iter=40,max_leaf_nodes=7,min_samples_leaf=20,l2_regularization=1,random_state=11).fit([r['features'] for r in rr],y)
  (ROOT/'filter_models.pkl').write_bytes(pickle.dumps(models))
  (ROOT/'filter_train.json').write_text(json.dumps(rows)+'\n')
 elif mode=='select':
  models=pickle.loads((ROOT/'filter_models.pkl').read_bytes())
  rows,_=collect(PROTO['filter_dev'],PROTO['filter_dev_structures'],models,())
  scores={k:float(np.mean([r['truth']-(r['p']-r['truth'])**2 for r in rows if r['kind']==k])) for k in models}
  enabled=[k for k,v in scores.items() if v>0]
  _,states=collect(PROTO['filter_dev'],PROTO['filter_dev_structures'],models,enabled)
  gain=np.mean([abs(r['guarded']-r['truth'])-abs(r['extended']-r['truth']) for r in states])
  selected=dict(candidate_brier_gains=scores,proposed=enabled,combined_dev_count_gain=float(gain),enabled=enabled if gain>0 else [])
  (ROOT/'filter_selection.json').write_text(json.dumps(selected,indent=2)+'\n')
  (ROOT/'filter_dev.json').write_text(json.dumps(dict(rows=rows,states=states))+'\n')
  print(selected,flush=True)
 else:
  models=pickle.loads((ROOT/'filter_models.pkl').read_bytes());sel=json.loads((ROOT/'filter_selection.json').read_text())
  rows,states=collect(PROTO['filter_test'],PROTO['filter_test_structures'],models,sel['enabled'])
  (ROOT/'filter_test.json').write_text(json.dumps(dict(rows=rows,states=states))+'\n')
  result=[]
  for (d,m),f in pd.DataFrame(states).groupby(['delay','metric']):
   e0=(f.guarded-f.truth).abs();e1=(f.extended-f.truth).abs()
   result.append(dict(delay=int(d),metric=m,guarded_mae=float(e0.mean()),extended_mae=float(e1.mean()),gain=float((e0-e1).mean())))
  (ROOT/'filter_summary.json').write_text(json.dumps(result,indent=2)+'\n');print(result,flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['fit','select','test']);main(p.parse_args().mode)
