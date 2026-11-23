"""Held-out action consequences, paired futures, 6/12/24h and decision regret."""
import pickle,json
import pandas as pd
from common import *
from correction import choices
from review_metrics import intervention_errors


def project(initial,prov,action,refresh=True):
 eng=initial.clone();eng.on_event=None;eng.emit_log=False
 if refresh:refresh_private(eng,W._Cal(prov,eng.spec_meta['drop']))
 start=eng.tick;tracker=L.Tracker(eng)
 A.apply(eng,action,W._Cal(prov,eng.spec_meta['drop']))
 result={}
 while eng.tick<start+96:
  eng.step(prov);tracker.tick(eng)
  h=(eng.tick-start)/4
  if h in PROTO['horizons_hours']:
   score=tracker.result(eng)
   result[int(h)]=dict(free_beds=sum(len(eng.free_beds(un)) for un in eng.units)/len(eng.units),
     queue=sum(len(q) for q in eng.queue.values())/len(eng.units),
     wait_patient_min=score['wait_patient_min'],uncovered_care_min=score['uncovered_care_min'],
     rejected=score['rejected'],staff_hours=score['staff_hours'])
 return result


def run():
 models=pickle.loads((ROOT/'filter_models.pkl').read_bytes())
 selected=json.loads((ROOT/'filter_selection.json').read_text())['enabled']
 rows,decisions=[],[]
 for idx in range(PROTO['consequence_structures']):
  for delay in PROTO['delays']:
   sp=structure(PROTO['consequence_test'],idx,delay);pre=L.prefix(sp,PROTO['consequence_origin_hours'])
   # Origin is identical across evaluation futures. No future reports enter planning.
   eng,_,rec=L.start_future(pre,sp,1);ps,pe=L.public_view(pre,rec,eng.tick)
   acts=choices(pe,sp.units,eng.tick,eng.tick+96)
   actual={a['id']:[] for a in acts}
   for draw in PROTO['truth_draws']:
    truth,tp,_=L.start_future(pre,sp,draw)
    for act in acts:actual[act['id']].append(project(truth,tp,act,refresh=False))
   target={aid:{h:{m:float(np.mean([v[h][m] for v in vv])) for m in vv[0][h]} for h in PROTO['horizons_hours']} for aid,vv in actual.items()}
   for arm in ('public','guarded','extended','true_state'):
    estimates={a['id']:[] for a in acts}
    for draw in PROTO['planning_draws']:
     pp=provider(sp,eng.tick,draw)
     initial=eng if arm=='true_state' else pe
     if arm=='guarded':initial=guarded(pe,ps,laws(delay),draw,pp)
     if arm=='extended':initial=extended(pe,ps,laws(delay),draw,pp,models,selected)
     for act in acts:estimates[act['id']].append(project(initial,provider(sp,eng.tick,draw),act))
    predicted={aid:{h:{m:float(np.mean([v[h][m] for v in vv])) for m in vv[0][h]} for h in PROTO['horizons_hours']} for aid,vv in estimates.items()}
    for h in PROTO['horizons_hours']:
     for act in acts:
      aid=act['id']
      for m in ('free_beds','queue','wait_patient_min','uncovered_care_min'):
       rows.append(dict(structure=idx,delay=delay,arm=arm,horizon=h,action=aid,metric=m,predicted=predicted[aid][h][m],truth=target[aid][h][m],
        predicted_effect=predicted[aid][h][m]-predicted['none'][h][m],true_effect=target[aid][h][m]-target['none'][h][m]))
     best=min(acts,key=lambda a:(round(predicted[a['id']][h]['wait_patient_min'],6),a['staff_hours'],a['id']))['id']
     optimal=min(target,key=lambda aid:target[aid][h]['wait_patient_min'])
     decisions.append(dict(structure=idx,delay=delay,arm=arm,horizon=h,choice=best,
      regret=target[best][h]['wait_patient_min']-target[optimal][h]['wait_patient_min'],
      **target[best][h]))
  print('Consequences',idx,flush=True)
 (ROOT/'consequences.json').write_text(json.dumps(dict(rows=rows,decisions=decisions))+'\n')
 f=pd.DataFrame(rows);f['mae']=(f.predicted-f.truth).abs();f['effect_mae']=intervention_errors(f)
 summary=f.groupby(['delay','arm','horizon','metric'])[['mae','effect_mae']].mean().reset_index().to_dict('records')
 d=pd.DataFrame(decisions).groupby(['delay','arm','horizon'])[['regret','wait_patient_min','uncovered_care_min','staff_hours','rejected']].mean().reset_index().to_dict('records')
 (ROOT/'consequence_summary.json').write_text(json.dumps(dict(forecasts=summary,decisions=d),indent=2)+'\n')

if __name__=='__main__':run()
