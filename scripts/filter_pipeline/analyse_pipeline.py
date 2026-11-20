"""Cluster summaries; never treat hourly samples as independent hospitals."""
import json
from pathlib import Path
import pandas as pd
import numpy as np
from common import ROOT,PROTO


def ci(frame,col,clusters=('structure',)):
 g=frame.groupby(list(clusters))[col].mean().to_numpy();rng=np.random.default_rng(PROTO['bootstrap_seed'])
 boot=g[rng.integers(len(g),size=(PROTO['bootstrap_repetitions'],len(g)))].mean(1)
 return dict(mean=float(g.mean()),ci95=np.quantile(boot,[.025,.975]).tolist(),clusters=len(g))

def crossed(frame,col):
 matrix=frame.groupby(['seed','structure'])[col].mean().unstack().to_numpy()
 rng=np.random.default_rng(PROTO['bootstrap_seed']);n=PROTO['bootstrap_repetitions']
 a=rng.integers(matrix.shape[0],size=(n,matrix.shape[0]));b=rng.integers(matrix.shape[1],size=(n,matrix.shape[1]))
 draws=matrix[a[:,:,None],b[:,None,:]].mean((1,2))
 return np.quantile(draws,[.025,.975]).tolist()

def base():
 r=json.loads((ROOT/'filter_test.json').read_text());f=pd.DataFrame(r['states']);rows=[]
 for (delay,metric),g in f.groupby(['delay','metric']):
  g=g.copy();g['gain']=(g.guarded-g.truth).abs()-(g.extended-g.truth).abs()
  rows.append(dict(delay=int(delay),metric=metric,**ci(g,'gain')))
 tasks=[]
 for (delay,kind),g in pd.DataFrame(r['rows']).groupby(['delay','kind']):
  g=g.copy();g['gain']=g.truth-(g.p-g.truth)**2
  tasks.append(dict(delay=int(delay),kind=kind,n=len(g),baseline_brier=float(g.truth.mean()),brier=float(((g.p-g.truth)**2).mean()),gain=ci(g,'gain')))
 cr=json.loads((ROOT/'consequences.json').read_text());f=pd.DataFrame(cr['rows']);f['error']=(f.predicted-f.truth).abs();f['effect_error']=(f.predicted_effect-f.true_effect).abs()
 forecasts=[]
 for (delay,horizon,metric),g in f.groupby(['delay','horizon','metric']):
  for col in ('error','effect_error'):
   p=g.pivot(index=['structure','action'],columns='arm',values=col).reset_index();p['gain']=p.guarded-p.extended
   forecasts.append(dict(delay=int(delay),horizon=int(horizon),metric=metric,error=col,**ci(p,'gain')))
 (ROOT/'paired_summary.json').write_text(json.dumps(dict(filter=rows,probabilities=tasks,consequences=forecasts),indent=2)+'\n')

def jepa():
 rows=sum([json.loads(p.read_text()) for p in sorted((ROOT/'jepa').glob('metrics_*.json'))],[])
 dec=sum([json.loads(p.read_text()) for p in sorted((ROOT/'jepa').glob('decisions_*.json'))],[])
 f=pd.DataFrame(rows);d=pd.DataFrame(dec)
 metrics=['free_mae','queue_mae','state_mae','wait_absolute_error','care_absolute_error','latent_mse','target_variance','persistence_free_mae','train_mean_free_mae']
 means=f.groupby(['variant','horizon'])[metrics].mean().reset_index().to_dict('records')
 rounds=f.query("horizon=='month'").groupby(['variant','round'])[['free_mae','state_mae','latent_mse','target_variance']].mean().reset_index().to_dict('records')
 comparisons=[]
 for h,g in f.groupby('horizon'):
  for metric in ('free_mae','queue_mae','state_mae','wait_absolute_error','care_absolute_error'):
   p=g.pivot(index=['seed','structure','round'],columns='variant',values=metric).reset_index();p['gain']=p.physical-p.physical_jepa
   comparisons.append(dict(horizon=h,metric=metric,**ci(p,'gain'),ci95_seed_structure=crossed(p,'gain'),per_seed=p.groupby('seed').gain.mean().to_dict()))
 # Bootstrap structures, averaging seeds and months inside each structure.
 # With only three held-out structures, these are exploratory intervals.
 decision_means=d.groupby(['variant','horizon'])[['regret','actual_wait','actual_care','staff']].mean().reset_index().to_dict('records')
 paired=[]
 for h,g in d.groupby('horizon'):
  for metric in ('regret','actual_wait','actual_care','staff'):
   p=g.pivot(index=['seed','structure','round'],columns='variant',values=metric).reset_index();p['gain']=p.physical-p.physical_jepa
   paired.append(dict(horizon=int(h),metric=metric,**ci(p,'gain'),ci95_seed_structure=crossed(p,'gain'),per_seed=p.groupby('seed').gain.mean().to_dict()))
 fixed=[]
 for row in dec:
  pred=np.asarray(row['predicted']);truth=np.asarray(row['truth'])
  action=1+int(np.argmin(pred[1:,2]))
  fixed.append(dict(seed=row['seed'],structure=row['structure'],round=row['round'],horizon=row['horizon'],variant=row['variant'],
    wait=truth[action,2],care=truth[action,3],regret=truth[action,2]-truth[1:,2].min(),
    effect_mae=float(np.mean(np.abs((pred[1:,2]-pred[0,2])-(truth[1:,2]-truth[0,2]))))))
 fixed_means=pd.DataFrame(fixed).groupby(['variant','horizon'])[['wait','care','regret','effect_mae']].mean().reset_index().to_dict('records')
 result=dict(means=means,rounds=rounds,paired=comparisons,decisions=decision_means,decision_paired=paired,equal_budget_diagnostic=fixed_means,heldout_structures=3,seeds=3,rounds_per_seed=10)
 (ROOT/'jepa_summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['base','jepa']);a=p.parse_args();base() if a.mode=='base' else jepa()
