from copy import deepcopy
from pathlib import Path
import unittest
import numpy as np

from cible import engine
from cible.data import make_public
from hierarchie import trial
from hierarchie.model import load_model,WEIGHTS
from j7.episodes import first_week
from lot28 import simulator
from .identites import canon,file_sha
from .multiechelle import derive,checked_case


class DatedHierarchicalIntervention(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        e=simulator.episode(102001,0);cp=first_week(e,"partial",7);ctx=engine.prepare(e,"partial",7,cp)
        cls.p=make_public(e,"partiel",7,ctx);phys=engine.outcomes(e,ctx,cp)
        cls.w=load_model();cls.sha=file_sha(WEIGHTS);cls.decision=trial.decide(cls.p,cls.w,cls.sha)
        cls.issue={k:cls.decision[k] for k in ("site","episode","feed","history","actions","prefix_sha256","public_sha256","decision_sha256")}
        cls.issue.update(cost=phys.cost.tolist(),guards=phys.guards.tolist(),delivery=phys.delivery.tolist())

    def test_public_policy_is_rebuilt_before_the_future_is_revealed(self):
        a,g,pr,group,shares=derive(self.w,self.p)
        self.assertEqual(a,self.decision["choices"])
        self.assertEqual(len(group),g["n_fine"]);self.assertTrue(np.isclose(shares.sum(),1))
        checked_case(self.p,self.decision,self.issue,self.w,self.sha)
        p=deepcopy(self.p);p["truth"]=self.issue["cost"]
        with self.assertRaises(ValueError):derive(self.w,p)

    def test_signing_again_cannot_hide_wrong_timing_subgoal_or_choice(self):
        for issue in ("minute","waypoint","selected"):
            d=deepcopy(self.decision)
            if issue=="minute":d["minute"]+=20
            elif issue=="selected":d["choices"]["hierarchique"]=len(d["actions"])
            else:d["trace"]["waypoint"][0]+=.01
            d["decision_sha256"]=canon({k:v for k,v in d.items() if k!="decision_sha256"})
            y={**self.issue,"decision_sha256":d["decision_sha256"]}
            with self.assertRaises(ValueError):checked_case(self.p,d,y,self.w,self.sha)
