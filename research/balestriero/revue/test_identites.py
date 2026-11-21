"""Algebraic falsifications that apply before opening any study sites."""
from unittest import TestCase
import numpy as np
from .identites import anchored,cluster_interval,no_spurious_contrast,score_event


class ResidualChecks(TestCase):
    def test_placebo_and_common_shock_do_not_create_an_action_contrast(self):
        p=np.array([[1.,4.],[2.,1.],[.5,7.]])
        y=p+[11.,-3.];z=anchored(p,0,y[0])
        np.testing.assert_array_equal(z,y)
        np.testing.assert_array_equal(z[1]-z[2],p[1]-p[2])
        r=score_event(p,y,0);self.assertEqual(r["forecast_effect_mae"],0.);self.assertGreater(r["forecast_level_mae"],0.)
        self.assertEqual(r["anchored_level_mae"],0.);self.assertEqual(r["max_change_linear_pairwise_difference"],0.)

    def test_threshold_interaction_makes_an_anchored_prediction_incorrect(self):
        p=np.array([[0.],[3.]])
        y=np.array([[6.],[6.]]) # donor cannot release the alternative resource in this event
        s=score_event(p,y,0)
        self.assertEqual(s["anchored_level_mae"],3.)
        self.assertEqual(s["forecast_effect_mae"],3.)
        self.assertEqual(s["zero_effect_mae"],0.)
        self.assertEqual(s["squared_energy_effect"],0.)

    def test_mask_has_finite_public_values_and_hidden_nan_cannot_influence_result(self):
        p=np.arange(6.).reshape(3,2);m=np.array([True,False])
        a=anchored(p,1,np.array([10.,-1e8]),m);b=anchored(p,1,np.array([10.,np.nan]),m)
        np.testing.assert_array_equal(a,b)
        np.testing.assert_array_equal(a[:,1],p[:,1])
        with self.assertRaises(ValueError):anchored(p,1,[np.nan,10.],m)

    def test_replacing_coupled_noise_with_another_events_residual_fails(self):
        p=np.array([[2.,3.],[3.,0.]])
        truth=p+[20.,-2.]
        true=anchored(p,0,truth[0]);wrong=anchored(p,0,p[0]+[-20.,2.])
        self.assertFalse(np.array_equal(wrong,truth));np.testing.assert_array_equal(true,truth)

    def test_repeated_h0_contexts_do_not_create_independent_hospitals(self):
        np.testing.assert_array_equal(cluster_interval([0.,0.])["ci95"],[0.,0.])
        self.assertEqual(cluster_interval([-1.,1.])["hospitals"],2)
        with self.assertRaises(ValueError):cluster_interval([-1.])

    def test_identical_treatment_has_exact_zero_future_effect(self):
        no_spurious_contrast([[1.,2.],[1.,2.],[3.,4.]],0,np.array([True,True,False]))
        with self.assertRaises(ValueError):
            no_spurious_contrast([[1.,2.],[1.,8.],[3.,4.]],0,np.array([True,True,False]))
