import unittest
from dataclasses import replace
import numpy as np

from cible.data import OUT as BASE_OUT, rows
from cible.model import allocation
from executabilite.regle import proposition
from hierarchie import model as m
from hierarchie.trial import decide

class HospitalHierarchy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w=m.load_model()
        cls.packet=next(rows(BASE_OUT/"public_dev.jsonl.gz"))
        cls.c=m.public_case(cls.packet)

    def test_shared_options_budget_and_distinct_horizon_spaces(self):
        w=self.w
        self.assertEqual(w["flat_pred"].size,w["fine_pred"].size+w["coarse_pred"].size)
        self.assertEqual((20,8),w["fine_enc"].shape)
        self.assertEqual((8,4),w["coarse_from_fine"].shape)
        self.assertEqual(4,np.linalg.matrix_rank(w["fine_enc"]@w["coarse_from_fine"]))
        self.assertTrue((w["spectrum_coarse"]>0).all())

    def test_matched_final_policy_and_named_eight_branches(self):
        c=self.c
        historic=allocation(self.packet,m.incumbent(),m.MODEL_SHA256)
        self.assertEqual(c.deployed,proposition(self.packet,historic)["choice"])
        choices,trace=m.choices(self.w,c)
        self.assertEqual(set(choices),set(m.ARMS))
        self.assertTrue(c.feasible[choices["plat_brut"]])
        self.assertTrue(c.feasible[choices["hierarchique_brut"]])
        self.assertEqual(c.actions[choices["hierarchique_brut"],0],trace["macro_kind"])

    def test_other_world_or_future_outcome_cannot_become_an_input_feature(self):
        bad={**self.packet,"cost":np.ones((1,3,4,4)).tolist()}
        with self.assertRaises(ValueError):m.public_case(bad)
        r=m.raw_policy(self.w,self.c)
        # Identifiers are metadata only, with identical covariates and menu.
        self.assertEqual(r,m.raw_policy(self.w,replace(self.c,identity=(111111,9,"unused",0))))
        c=self.c;design=m.public_design(self.w,c);forecast=c.projected/self.w["scale"]
        a=m.macro(c,design,forecast,np.zeros_like(forecast));b=m.macro(c,design,forecast,np.ones_like(forecast))
        for i in (0,2,3):np.testing.assert_array_equal(a[i],b[i])
        self.assertFalse(np.array_equal(a[4],b[4]))

    def test_lower_level_really_minimizes_distance_to_selected_upper_subgoal(self):
        examined=changed=0
        for p in rows(BASE_OUT/"public_dev.jsonl.gz"):
            c=m.public_case(p);trace=m.raw_policy(self.w,c)
            if not trace["macro_kind"] or trace["n_fine"]<2:continue
            mask=np.flatnonzero(c.feasible&(c.actions[:,0]==trace["macro_kind"]))
            f=m.public_design(self.w,c)
            z=(c.projected[:,0]/self.w["scale"][0])@self.w["fine_enc"]+f@self.w["fine_pred"]
            z=z@self.w["coarse_from_fine"]
            dist=np.square(z[mask]-trace["waypoint"]).sum(1)
            self.assertEqual(mask[np.argmin(dist)],trace["hierarchique"])
            self.assertAlmostEqual(dist.min(),trace["tracking_distance"])
            changed+=int(trace["hierarchique"]!=mask[0]);examined+=1
            if examined>=5 and changed:break
        self.assertGreater(examined,0);self.assertGreater(changed,0)

    def test_foreign_calibration_is_rejected_and_ties_abstain(self):
        with self.assertRaises(ValueError):m.choices({**self.w,"cutoff_plat":-2.},self.c)
        q,_=m.choices({**self.w,"cutoff_plat":1.,"cutoff_hierarchique":1.},self.c)
        self.assertEqual(q["plat"],0);self.assertEqual(q["hierarchique"],0)

if __name__=="__main__":
    unittest.main()
