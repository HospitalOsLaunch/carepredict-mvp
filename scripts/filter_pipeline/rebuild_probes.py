"""Align action probes with the 06-14h intervention support before model testing.

Only probe arrays are replaced. Monthly trajectories and inference inputs remain
unchanged. This corrects the original 14-22h probe's unseen intervention timing.
"""
import pickle
from common import *
from longitudinal import generate_episode

if __name__=='__main__':
 models=pickle.loads((ROOT/'filter_models.pkl').read_bytes())
 enabled=json.loads((ROOT/'filter_selection.json').read_text())['enabled']
 for i in range(3):
  for month in range(5,60,6):
   path=ROOT/'corpus'/PROTO['jepa_test']/f'{i:02d}'/f'{month:02d}.npz'
   data={k:v.copy() for k,v in np.load(path).items()}
   probe=generate_episode(PROTO['jepa_test'],i,month,models,enabled,probe_only=True)
   data.update(probe);np.savez_compressed(path,**data)
  print('Rebuilt action probes',i,flush=True)
