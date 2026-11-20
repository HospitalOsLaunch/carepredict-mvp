"""Verify the saved corpus and reproduce final-month checkpoint predictions."""
import hashlib,json
import numpy as np
import torch
from common import ROOT,PROTO
from jepa_stage import Model,batch,tensor

if __name__=='__main__':
 torch.set_num_threads(1)
 manifest=json.loads((ROOT/'corpus_manifest.json').read_text())
 for item in manifest['files']:
  p=ROOT/'corpus'/item['path']
  assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256'],p
 d={k:tensor(v.copy()) for k,v in np.load(ROOT/'corpus'/PROTO['jepa_test']/'00'/'59.npz').items()}
 for seed in PROTO['model_seeds']:
  for variant in ('physical','physical_jepa'):
   saved=torch.load(ROOT/'jepa'/f'{variant}_{seed}.pt',map_location='cpu',weights_only=True)
   assert saved['completed_rounds']==10
   model=Model();model.load_state_dict(saved['model']);model.eval()
   with torch.no_grad():pred=model(batch([(d,0,len(d['truth'])-1)]))[0][0].numpy()
   expected=np.array(json.loads((ROOT/'jepa'/f'forecast_{seed}_{variant}_10.json').read_text())[0]['predicted'])
   assert np.isfinite(pred).all() and np.allclose(pred,expected,atol=1e-7)
   print(seed,variant,'verified',float(np.max(np.abs(pred-expected))))
