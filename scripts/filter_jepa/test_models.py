"""Regression checks for JEPA and residual projection."""
import unittest

import numpy as np
import torch

from cohort import EYE, filter_reports, simulate
from residual import ResidualInputs
from run import Experiment


class ResidualTests(unittest.TestCase):
    def test_zero_correction_matches_filter_and_ignores_future_observations(self):
        days, schedule, states, reports = simulate(101)
        posterior, _ = filter_reports(days, schedule, reports)
        inputs = ResidualInputs(posterior, days, schedule)
        model = Experiment()
        torch.nn.init.zeros_(model.graph.head_beds.weight)
        torch.nn.init.zeros_(model.graph.head_beds.bias)
        origins = np.array([31])
        actual, _, _ = inputs.rollout(model, origins, 7)
        torch.testing.assert_close(actual, inputs.nominal(origins, 7))
        inputs.unit[32:39] = 999.
        changed, _, _ = inputs.rollout(model, origins, 7)
        torch.testing.assert_close(actual, changed)
        self.assertFalse(any(p.requires_grad for p in model.target_unit.parameters()))

    def test_legacy_graph_output_unchanged(self):
        from hospitalos.howmint.models import GraphWM
        model = GraphWM(24)
        args = [torch.zeros(1,2,54),torch.zeros(1,3,10),torch.zeros(1,8),
                torch.ones(1,2,3),torch.zeros(1,2,2),torch.zeros(1,3,2,3),
                torch.zeros(1,3,3,3),torch.zeros(1,3,3),torch.ones(1,2)*32]
        legacy = model(*args)
        extended = model(*args,return_latents=True)
        self.assertEqual(len(legacy),3)
        self.assertEqual(len(extended),4)
        for old,new in zip(legacy,extended[:3],strict=True):
            torch.testing.assert_close(old,new)


if __name__=="__main__":
    torch.set_num_threads(1)
    unittest.main()
