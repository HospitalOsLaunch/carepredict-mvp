"""Causal and probabilistic regression checks."""
import unittest
import numpy as np
from service_filter import ServiceLaw, records, candidates


class ServiceTests(unittest.TestCase):
    def test_zero_reporting_delay(self):
        law=ServiceLaw(60,.4,0)
        for age in (1,15,60,180):
            self.assertAlmostEqual(law.unfinished(age),1.)

    def test_completed_but_unreported_posterior(self):
        law=ServiceLaw(60,.4,180)
        self.assertEqual(law.unfinished(15),1.)
        self.assertLess(law.unfinished(180),.05)
        self.assertTrue(all(0<=law.unfinished(age)<=1 for age in range(1,500)))

    def test_censoring_and_availability(self):
        obs=[(0,0,"cleaning_start","bed","A",{}),(30,90,"cleaning_done","bed","A",{})]
        self.assertEqual(records(obs,60,"cleaning"),[(60,None)])
        self.assertEqual(records(obs,90,"cleaning"),[(90,None)])
        self.assertEqual(records(obs,91,"cleaning"),[(91,(30,60))])
        future=obs+[(120,120,"cleaning_start","bed","A",{}),(180,200,"cleaning_done","bed","A",{})]
        self.assertEqual(records(obs,91,"cleaning"),records(future,91,"cleaning"))

    def test_discrete_survival_matches_enumeration(self):
        law=ServiceLaw(60,.4,180)
        for age in (15,16,60,61,120):
            d=np.arange(15,6000,15)
            pmf=law.mass(d)
            unfinished=pmf[d>=age].sum()
            arrived_late=(pmf[d<age]*np.exp(-(age-d[d<age])/law.lag)).sum()
            self.assertAlmostEqual(law.unfinished(age),unfinished/(unfinished+arrived_late),places=9)


if __name__=="__main__":
    unittest.main()
