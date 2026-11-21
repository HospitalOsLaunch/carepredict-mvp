import unittest

import numpy as np

from contraintes.projection import reconstruire, rendre_faisable


class ProjectionTest(unittest.TestCase):
    def test_simplex_caps_only_the_beds(self):
        x=np.array([[-1,9,5,2,-1],[27,1,1,-3,1]],float)
        np.testing.assert_allclose(rendre_faisable(x,[8,4]),[[0,6,2,0,0],[27,1,1,0,1]])
        np.testing.assert_array_equal(x[0],[-1,9,5,2,-1])

    def test_identity_idempotence_and_distance_to_feasible_points(self):
        rng=np.random.default_rng(556)
        cap=np.array([10,13])
        truth=rng.uniform(0,2,(11,2,5))
        raw=truth+rng.normal(2,6,truth.shape)
        z=rendre_faisable(raw,cap)
        np.testing.assert_allclose(rendre_faisable(truth,cap),truth)
        np.testing.assert_allclose(rendre_faisable(z,cap),z,atol=1e-12)
        self.assertTrue((np.square(z-truth).sum(-1)<=np.square(raw-truth).sum(-1)+1e-9).all())
        self.assertTrue((z>=0).all() and (z[...,1:].sum(-1)<=cap+1e-12).all())

    def test_partial_factual_report_remains_exact(self):
        x=np.full((2,1,5),2.)
        y=np.array([[np.nan,9,np.nan,np.nan,np.nan]])
        obs=np.isfinite(y)
        z=reconstruire(x,0,y,obs,[10],heure_consultation=16,heure_publication=16)
        np.testing.assert_allclose(z[0,0],[2,9,1/3,1/3,1/3])
        np.testing.assert_allclose(z[1,0],[2,7.75,.75,.75,.75])

    def test_factual_full_census_matches_measurement(self):
        x=np.full((3,2,5),2.)
        y=np.array([[3,0,1,1,0],[0,7,1,0,0]],float)
        z=reconstruire(x,1,y,np.ones_like(y,bool),[5,8],heure_consultation=18,heure_publication=16)
        np.testing.assert_array_equal(z[1],y)

    def test_missing_and_not_yet_published_cannot_influence_output(self):
        x=np.full((2,1,5),3.);m=np.full((1,5),np.nan)
        expected=rendre_faisable(x,[8])
        for y,now in ((m,18),(np.full((1,5),99.),16)):
            z=reconstruire(x,0,y,np.isfinite(y),[8],heure_consultation=now,heure_publication=18)
            np.testing.assert_array_equal(z,expected)

    def test_fully_occupied_factual_unit_evicts_imputed_beds(self):
        x=np.ones((2,1,5)); y=np.array([[np.nan,4,np.nan,2,np.nan]])
        z=reconstruire(x,0,y,np.isfinite(y),[6],heure_consultation=17,heure_publication=16)
        np.testing.assert_array_equal(z[0],[ [1,4,0,2,0] ])

    def test_invalid_inputs_and_impossible_published_measurement(self):
        x=np.ones((2,1,5)); y=np.ones((1,5)); mask=np.isfinite(y)
        for idx,report,observed,caps in ((True,y,mask,[5]),(3,y,mask,[5]),(0,y,mask,[0]),
                                          (0,y,mask,[3]),(0,y,~mask,[5]),(0,-y,mask,[5])):
            with self.subTest(idx=idx,caps=caps),self.assertRaises(ValueError):
                reconstruire(x,idx,report,observed,caps,heure_consultation=16,heure_publication=16)
