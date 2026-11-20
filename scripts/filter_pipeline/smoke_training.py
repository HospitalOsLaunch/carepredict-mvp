"""Validate data/action/gradient wiring on a separate DEV episode."""
import pickle
import numpy as np
import torch
from common import *
from longitudinal import generate_episode
from jepa_stage import Model,batch,tensor

torch.set_num_threads(1)
PROTO['jepa_test']='PIPE_JEPA_SMOKE_20261120'
models=pickle.loads((ROOT/'filter_models.pkl').read_bytes())
enabled=json.loads((ROOT/'filter_selection.json').read_text())['enabled']
d={k:tensor(v) for k,v in generate_episode(PROTO['jepa_test'],0,5,models,enabled).items()}
assert d['probe_truth'].shape==(3,3,4)
assert d['probe_R'].shape==(3,4,3,3)
b=batch([(d,2,4)]*2)
m=Model();out=m(b)
loss=sum(x.square().mean() for x in out);loss.backward()
assert torch.isfinite(loss)
assert all(torch.isfinite(p.grad).all() for p in m.parameters() if p.grad is not None)
print('PASS: DEV monthly data, action branches, shapes and finite backward',float(loss.detach()))
