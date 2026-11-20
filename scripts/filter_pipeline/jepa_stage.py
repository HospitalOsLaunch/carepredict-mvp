"""Matched GraphWM +/- JEPA on held-out monthly INT-1 trajectories."""
import copy,json
from pathlib import Path
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from common import ROOT,PROTO
from hospitalos.howmint.models import GraphWM


def tensor(x):return torch.as_tensor(x,dtype=torch.float32)
class Model(nn.Module):
 def __init__(self):
  super().__init__();self.graph=GraphWM(PROTO['jepa_width'],instant_resource_messages=True)
  self.predictor=nn.Linear(PROTO['jepa_width'],PROTO['jepa_width']);self.care=nn.Linear(PROTO['jepa_width'],1)
  self.target_u=copy.deepcopy(self.graph.unit_enc).requires_grad_(False)
  self.target_g=copy.deepcopy(self.graph.glob_enc).requires_grad_(False)
 def encode(self,u,g,target=False):
  return torch.tanh((self.target_u if target else self.graph.unit_enc)(u)+(self.target_g if target else self.graph.glob_enc)(g).unsqueeze(-2))
 @torch.no_grad()
 def ema(self):
  for a,b in ((self.graph.unit_enc,self.target_u),(self.graph.glob_enc,self.target_g)):
   for p,q in zip(a.parameters(),b.parameters(),strict=True):q.lerp_(p,.02)
 def forward(self,b):
  B,n=b['unit'].shape[:2];h=b['R'].shape[1]
  s,c,_,z=self.graph(b['unit'],b['res'],b['glob'],torch.ones(B,n,3),b['uu'],torch.zeros(B,h,n,3),b['R'],b['clock'],b['beds'],return_latents=True)
  return s,c,F.softplus(self.care(z)[...,0]),self.predictor(z)


def load(part):
 return {(i,m):{k:tensor(v.copy()) for k,v in np.load(ROOT/'corpus'/part/f'{i:02d}'/f'{m:02d}.npz').items()}
         for i in range(PROTO['jepa_structures_per_partition']) for m in range(60)}

def batch(items):
 # item=(monthly episode, origin, horizon). No transition crosses a reset.
 b={}
 for k in ('unit','res','glob','uu') :b[k]=torch.stack([d[k][o] for d,o,h in items])
 for k in ('R','clock'):b[k]=torch.stack([d[k][o:o+h] for d,o,h in items])
 for k in ('truth','cost','care'):b[k]=torch.stack([d[k][o+1:o+h+1] for d,o,h in items])
 b['future_unit']=torch.stack([d['unit'][o+1:o+h+1] for d,o,h in items])
 b['future_glob']=torch.stack([d['glob'][o+1:o+h+1] for d,o,h in items])
 b['beds']=torch.stack([d['beds'] for d,o,h in items]);return b


def train_round(model,opt,train,round_id,rng,jepa):
 losses=[]
 months=range(round_id*6,round_id*6+5)
 for update in range(PROTO['updates_per_round']):
  h=int(rng.choice(PROTO['train_horizons_steps']));items=[]
  for j in range(PROTO['batch_size']):
   i=int(rng.integers(PROTO['jepa_structures_per_partition']));m=int(rng.choice(list(months)));d=train[i,m]
   o=int(rng.integers(len(d['truth'])-h));items.append((d,o,h))
  b=batch(items);s,c,care,z=model(b)
  physical=F.smooth_l1_loss(s,b['truth'],beta=.05)+F.smooth_l1_loss(c,b['cost'],beta=.05)+F.smooth_l1_loss(care,b['care'],beta=.05)
  loss=physical;latent=torch.tensor(0.);variance=torch.tensor(0.)
  if jepa:
   with torch.no_grad():target=model.encode(b['future_unit'],b['future_glob'],True)
   latent=F.mse_loss(F.layer_norm(z,(z.shape[-1],)),F.layer_norm(target,(target.shape[-1],)))
   online=model.encode(b['future_unit'],b['future_glob'])
   variance=F.relu(.1-online.flatten(0,-2).std(dim=0,unbiased=False)).mean()
   loss=loss+PROTO['jepa_weight']*latent+.05*variance
  opt.zero_grad();loss.backward();nn.utils.clip_grad_norm_(model.parameters(),1.);opt.step();model.ema()
  losses.append(dict(physical=float(physical.detach()),latent=float(latent.detach()),variance_penalty=float(variance.detach())))
 return losses


@torch.no_grad()
def evaluate(model,test,train,seed,variant,r):
 rows=[];forecasts=[];decisions=[];model.eval();m=r*6+5
 # A common physical reference uses TRAIN truth only, not held-out history.
 past=torch.cat([train[i,mm]['truth'][1:] for i in range(PROTO['jepa_structures_per_partition']) for mm in range(r*6,r*6+5)])
 past_mean=past.mean((0,1))
 for i in range(PROTO['jepa_structures_per_partition']):
  d=test[i,m];h=len(d['truth'])-1;b=batch([(d,0,h)])
  s,c,care,z=model(b);s=s[0];c=c[0];care=care[0]
  actual=d['truth'][1:];beds=d['beds'];target=model.encode(b['future_unit'],b['future_glob'],True)
  init=torch.cat([d['unit'][0,:, [3,4,6]],d['unit'][0,:,8:14]],-1)
  # Common frozen physical target: latent error alone cannot establish quality.
  for steps,name in [(1,'6h'),(2,'12h'),(4,'24h'),(h,'month')]:
   sel=slice(0,h) if name=='month' else slice(steps-1,steps)
   free=lambda x:float(((x-actual[sel])[...,1].abs()*beds).mean())
   state=float(((s[sel]-actual[sel]).abs()*beds[None,:,None]).mean())
   cc=(c[:steps]*beds*360).sum();tc=(d['cost'][1:steps+1]*beds*360).sum()
   ca=(care[:steps]*beds*360).sum();ta=(d['care'][1:steps+1]*beds*360).sum()
   rows.append(dict(seed=seed,variant=variant,round=r+1,structure=i,month=m,horizon=name,
     free_mae=free(s[sel]),state_mae=state,queue_mae=float(((s[sel]-actual[sel])[...,3].abs()*beds).mean()),
     persistence_free_mae=free(init[None]),train_mean_free_mae=free(past_mean[None,None]),
     wait_absolute_error=float(abs(cc-tc)),care_absolute_error=float(abs(ca-ta)),
     latent_mse=float(F.mse_loss(F.layer_norm(z[:,sel],(z.shape[-1],)),F.layer_norm(target[:,sel],(target.shape[-1],)))),
     target_variance=float(target[:,sel].flatten(0,-2).var(0,unbiased=False).mean())))
  forecasts.append(dict(structure=i,month=m,predicted=s.numpy().tolist(),truth=actual.numpy().tolist(),predicted_cost=c.numpy().tolist(),truth_cost=d['cost'][1:].numpy().tolist(),beds=beds.numpy().tolist()))
  pb=batch([(d,0,4)]*3);pb['R']=d['probe_R'];pb['clock']=d['probe_clock'][None].repeat(3,1,1)
  ss,cc,ca,_=model(pb)
  for hi,steps in enumerate((1,2,4)):
   pp=torch.stack([(ss[:,steps-1,:,1]*beds).mean(-1),(ss[:,steps-1,:,3]*beds).mean(-1),
       (cc[:,:steps]*beds*360).sum((1,2)),(ca[:,:steps]*beds*360).sum((1,2))],-1)
   tt=d['probe_truth'][:,hi]
   chosen=min(range(3),key=lambda a:(round(float(pp[a,2]),6),float(d['probe_staff'][a]),a))
   decisions.append(dict(seed=seed,variant=variant,round=r+1,structure=i,horizon=steps*6,
    choice=chosen,regret=float(tt[chosen,2]-tt[:,2].min()),actual_wait=float(tt[chosen,2]),
    actual_care=float(tt[chosen,3]),staff=float(d['probe_staff'][chosen]),
    predicted=pp.numpy().tolist(),truth=tt.numpy().tolist()))
 model.train();return rows,forecasts,decisions


def run(seed):
 torch.set_num_threads(1);train=load(PROTO['jepa_train']);test=load(PROTO['jepa_test'])
 out=ROOT/'jepa';out.mkdir(exist_ok=True);all_rows=[];all_losses=[];all_decisions=[]
 for variant in ('physical','physical_jepa'):
  torch.manual_seed(seed);rng=np.random.default_rng(seed);model=Model();opt=torch.optim.AdamW(model.parameters(),lr=.001)
  for r in range(10):
   logs=train_round(model,opt,train,r,rng,variant=='physical_jepa')
   if r==0:frozen=copy.deepcopy(model)
   rows,forecasts,dd=evaluate(model,test,train,seed,variant,r);all_rows.extend(rows);all_decisions.extend(dd)
   frozen_rows,_,dd=evaluate(frozen,test,train,seed,variant+'_frozen_round1',r);all_rows.extend(frozen_rows);all_decisions.extend(dd)
   all_losses.append(dict(seed=seed,variant=variant,round=r+1,updates=logs))
   (out/f'forecast_{seed}_{variant}_{r+1:02d}.json').write_text(json.dumps(forecasts)+'\n')
   print('JEPA',seed,variant,r+1,'monthly free MAE',np.mean([x['free_mae'] for x in rows if x['horizon']=='month']),flush=True)
  torch.save(dict(model=model.state_dict(),optimizer=opt.state_dict(),seed=seed,variant=variant,completed_rounds=10,protocol=PROTO),out/f'{variant}_{seed}.pt')
 (out/f'metrics_{seed}.json').write_text(json.dumps(all_rows,indent=2)+'\n')
 (out/f'losses_{seed}.json').write_text(json.dumps(all_losses)+'\n')
 (out/f'decisions_{seed}.json').write_text(json.dumps(all_decisions)+'\n')

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--seed',type=int,required=True);run(p.parse_args().seed)
