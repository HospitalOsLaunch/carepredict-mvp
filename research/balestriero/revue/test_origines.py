"""Property checks on previous frozen weights and development-only synthetic states."""
from dataclasses import replace
from pathlib import Path
import unittest

import numpy as np

from lot28 import simulator
from lot28.config import OUT
from lot28.corpus import observation
from lot28.data import panel
from lot28.features import state_features,normalized,action_features
from lot28.model import load_model
from lot28.planning import empty


class BaseFrozenWorld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ep=simulator.episode(62001,1)
        cls.site=cls.ep.site
        cls.plans=panel(cls.site,np.random.default_rng(96),0,empty()[0],[])
        cls.plans=cls.plans[simulator.affordable(cls.site,cls.plans,[])]
        cls.h=(4,24,72)

    def forecasts(self,ep):
        view=observation(ep,0,"partial",history_days=7,census=ep.initial,minute=0)
        raw,state=simulator.rollout(ep.site,view.state,view.forecast,self.plans,self.h)
        m=normalized(ep.site,raw,state,self.h)
        f=action_features(ep.site,view,self.plans,m,0,self.h)
        x=state_features(ep.site,view.state)
        return np.stack([load_model("jepa",seed).predict(x,f,m) for seed in (19,37,71)]),raw

    def test_cf_boundary_rejects_foreign_first_week(self):
        from cf.experience import prepare
        from j7.episodes import first_week
        first=simulator.episode(115900,0);other=simulator.episode(115900,1)
        cp=first_week(first,"partial",7)
        with self.assertRaises(ValueError):prepare(other,cp,"partial",0)

    def test_future_truth_only_changes_target_not_present_forecast_in_either_seed(self):
        ep=self.ep
        tape=ep.truth.copy()
        tape[:72,:,simulator.ARR]+=12.
        other=replace(ep,truth=tape)
        p,phys=self.forecasts(ep);q,pp=self.forecasts(other)
        np.testing.assert_array_equal(p,q);np.testing.assert_array_equal(phys,pp)
        y,_=simulator.rollout(self.site,ep.initial,ep.truth,self.plans,self.h)
        yn,_=simulator.rollout(self.site,ep.initial,other.truth,self.plans,self.h)
        self.assertGreater(abs(y-yn).max(),1.)
        np.testing.assert_array_equal(y[:,0],np.broadcast_to(y[0,0],y[:,0].shape))
        np.testing.assert_allclose(p[:,:,0],np.broadcast_to(p[:,0:1,0],p[:,:,0].shape),rtol=0,atol=2e-7)
        self.assertTrue((np.array([k.stat().st_size for k in (OUT/"weights").glob("jepa_*.npz")])>0).all())
