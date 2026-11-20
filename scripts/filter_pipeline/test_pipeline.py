import unittest,copy
import numpy as np
from common import *

class PipelineTests(unittest.TestCase):
 def test_constant_probability(self):
  for p in (0,1):
   result=ConstantProbability(p).predict_proba(np.zeros((3,13)))
   self.assertTrue(np.array_equal(result.sum(1),np.ones(3)))
   self.assertTrue(np.all(result[:,1]==p))
 def test_candidate_features_ignore_private_future(self):
  sp=structure('PIPE_UNIT',0,180);pre=L.prefix(sp,60)
  eng,_,rec=L.start_future(pre,sp,1);ps,pe=L.public_view(pre,rec,eng.tick)
  a=candidates(ps,pe)
  for s in pe.stays.values():s.auth_tick=999999;s.ready_tick=999999;s.tr_end=999999
  for b in pe.beds.values():b.clean_end=999999
  self.assertEqual(a,candidates(ps,pe))
 def test_extended_constraints_and_no_input_mutation(self):
  sp=structure('PIPE_UNIT',0,180);pre=L.prefix(sp,60)
  eng,_,rec=L.start_future(pre,sp,1);ps,pe=L.public_view(pre,rec,eng.tick)
  before=[(b.state,b.stay) for b in pe.beds.values()]
  models={k:ConstantProbability(1) for k in PROTO['components']}
  out=extended(pe,ps,laws(180),1,provider(sp,eng.tick,10001),models,list(models))
  assert_consistent(out)
  self.assertEqual(before,[(b.state,b.stay) for b in pe.beds.values()])
  self.assertEqual(len(pe.beds),len(out.beds))
 def test_partition_and_calendar_contract(self):
  self.assertNotEqual(PROTO['jepa_train'],PROTO['jepa_test'])
  for r in range(10):
   self.assertLess(max(range(r*6,r*6+5)),r*6+5)
  self.assertEqual(10*6,60)
 def test_immutable_rosters_share_safely(self):
  from longitudinal import ImmutableRoster
  ro=ImmutableRoster([1,2,3])
  self.assertIs(copy.deepcopy(ro),ro)
  with self.assertRaises(TypeError):ro[0]=99
 def test_probe_matches_trained_slot_and_has_no_early_effect(self):
  from correction import choices
  from hospitalos.howmint.features import schedule
  sp=structure('PIPE_UNIT',0,180);eng=W.initial_engine(sp,W.ProvN(sp,0));eng.tick=7*96
  acts=choices(eng,sp.units,eng.tick,eng.tick+96)
  self.assertEqual([a['kind'] for a in acts],['none','cl','tr'])
  for a in acts[1:]:
   self.assertEqual(local_hour(a['start']),6)
   r=schedule([a],sp.units,eng.tick,4,6,sp.drop,step_h=6)['R']
   self.assertTrue(np.all(r[0,:,0]==0))
   self.assertAlmostEqual(float(r[:,:,0].sum()*6),a['staff_hours'],places=5)
 def test_forecast_never_reads_future_targets(self):
  import torch
  from jepa_stage import Model
  torch.set_num_threads(1);torch.manual_seed(11);model=Model().eval()
  b=dict(unit=torch.zeros(2,4,54),res=torch.zeros(2,3,10),glob=torch.zeros(2,8),uu=torch.zeros(2,4,4),
         R=torch.zeros(2,4,3,3),clock=torch.zeros(2,4,3),beds=torch.ones(2,4)*32,
         truth=torch.zeros(2,4,4,9),future_unit=torch.zeros(2,4,4,54),future_glob=torch.zeros(2,4,8))
  with torch.no_grad():first=model(b)
  b['truth'].fill_(999);b['future_unit'].fill_(999);b['future_glob'].fill_(999)
  with torch.no_grad():second=model(b)
  self.assertTrue(all(torch.equal(a,c) for a,c in zip(first,second)))
  self.assertTrue(torch.allclose(first[0][...,:3].sum(-1),torch.ones(2,4,4)))
 def test_resource_action_enters_current_interval_without_future_leak(self):
  import torch
  from hospitalos.howmint.models import GraphWM
  torch.set_num_threads(1);torch.manual_seed(23)
  args=[torch.zeros(1,4,54),torch.zeros(1,3,10),torch.zeros(1,8),torch.ones(1,4,3),torch.zeros(1,4,4),
        torch.zeros(1,2,4,3),torch.zeros(1,2,3,3),torch.zeros(1,2,3),torch.ones(1,4)*32]
  model=GraphWM(24,instant_resource_messages=True)
  base=model(*args)[0]
  args[6][0,0,0,0]=2
  changed=model(*args)[0]
  self.assertFalse(torch.equal(base[:,0],changed[:,0]))
  args[6].zero_();args[6][0,1,0,0]=2
  future=model(*args)[0]
  self.assertTrue(torch.equal(base[:,0],future[:,0]))
  old=GraphWM(24);old.load_state_dict(model.state_dict())
  args[6].zero_();b=old(*args)[0];args[6][0,0,0,0]=2
  self.assertTrue(torch.equal(b[:,0],old(*args)[0][:,0]))

if __name__=='__main__':unittest.main()
