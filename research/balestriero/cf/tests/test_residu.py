"""Regression tests for information cutoffs, post-event algebra and hospital identities."""
from dataclasses import replace
from unittest import TestCase
import numpy as np
from cf import experience as exp
from cf import mesures as scores
from lot28 import simulator as sim
from lot28.corpus import observation


class ResidualTests(TestCase):
    def test_masks_and_delay(self):
        x=np.ones((3,2,5));x[2]+=.5
        report=np.full((2,5),4.);report[1,4]=np.nan;m=np.isfinite(report)
        before=scores.anchored(x,report,m,0,4,6)
        after=scores.anchored(x,report,m,0,6,6)
        np.testing.assert_array_equal(before,x)
        np.testing.assert_equal(after[2,1,4],x[2,1,4])
        np.testing.assert_equal(after[2,1,2],4.5)
        np.testing.assert_allclose(after-after[0],x-x[0])

    def test_copy_and_common_bias_are_exact_under_additivity_but_scaling_the_command_breaks_it(self):
        f=np.arange(3,dtype=float)[:,None,None]*np.ones((1,2,5))
        m=np.ones((2,5),bool)
        actual=f+3.
        corrected=scores.anchored(f,actual[1],m,1,4,4)
        np.testing.assert_allclose(corrected,actual)
        actual=3+2*f
        corrected=scores.anchored(f,actual[1],m,1,4,4)
        self.assertGreater(abs(corrected[2]-actual[2]).mean(),.1)

    def test_duplicate_plans_and_identity_do_not_score(self):
        g=np.array([[1,2],[3,4],[1,2],[5,6],[3,4]])
        self.assertEqual(exp.alternatives(g,2).tolist(),[1,3])
        self.assertEqual(exp.alternatives(g,4).tolist(),[0,3])
        with self.assertRaises(ValueError):exp.alternatives(g[:1],0)

    def test_goal_metric_counts_physical_equivalence_and_distinct_targets(self):
        y=np.array([[0.,0.],[2.,3.],[2.,3.],[.001,0.]])
        q=(y,y,np.zeros_like(y))
        np.testing.assert_equal(scores.hindsight(q,y,0,np.array([1,2,3])),[1,1,1,0])

    def test_source_hash_binds_the_date_and_the_mask(self):
        ep=sim.episode(115900,0);v=observation(ep,0,"full")
        self.assertNotEqual(exp.view_digest(v),exp.view_digest(replace(v,minute=v.minute+1)))
        self.assertNotEqual(exp.view_digest(v),exp.view_digest(replace(v,known=~v.known)))

    def test_episode_prefix_cannot_cross_episode(self):
        a=sim.episode(115900,0);b=sim.episode(115900,1);cp=exp.first_week(a,"full",7)
        with self.assertRaises(ValueError):exp.prepare(b,cp,"full",0)

    def test_scalar_rank_invariant_but_goal_distance_can_change(self):
        x=np.array([1.,4.,6.])
        np.testing.assert_equal(np.argsort(x),np.argsort(x+4))
        self.assertNotEqual(np.argmin(abs(x-6)),np.argmin(abs(x+4-6)))
