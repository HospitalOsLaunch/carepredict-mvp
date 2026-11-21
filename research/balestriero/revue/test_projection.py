from unittest import TestCase
import numpy as np
from .projection import project,physical_domain,score


class FeasibleState(TestCase):
    def test_kkt_projection_is_nearest_preserves_factual_and_rejects_nonfinite(self):
        b=np.array([4.,0.])
        x=np.array([[-1,8,1,-3,7],[2,-.2,4,3,-1.]])
        z=project(x,b)
        np.testing.assert_allclose(z,[[0,2.5,0,0,1.5],[2,0,0,0,0]],rtol=0,atol=1e-12)
        np.testing.assert_array_equal(z,project(z,b))
        self.assertTrue(np.all(physical_domain(z,b)))
        with self.assertRaises(ValueError):project(np.full((2,5),np.nan),b)

    def test_nonlinear_projection_changes_effect_and_partial_factual_coordinates(self):
        y=np.array([[[0,0,8,2,0]],[[0,0,5,5,0]]],float)
        p=np.array([[[0,5,4,2,0]],[[0,4,1,5,0]]],float)
        mask=np.array([[True,False,True,False,True]])
        obs=np.where(mask,y[0],np.nan)
        z=score(p,y,obs,mask,0,np.array([1]),np.array([10.]))
        self.assertGreater(z["naive_max_observed_factual_drift"],0)
        self.assertEqual(z["max_known_factual_change"],0)
        self.assertGreater(z["max_change_estimated_effect"],0)
        self.assertEqual(z["out_projected"],0)
