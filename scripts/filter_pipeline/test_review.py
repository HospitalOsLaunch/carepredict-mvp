import unittest
import numpy as np
import pandas as pd
from review_metrics import intervention_errors, monthly_resource_plan


class ReviewTests(unittest.TestCase):
    def test_abstention_does_not_dilute_error(self):
        frame = pd.DataFrame(dict(action=['none', 'cl', 'tr'],
                                  predicted_effect=[0, 2, -4], true_effect=[0, 0, 0]))
        self.assertEqual(intervention_errors(frame).mean(), 3)

    def test_only_training_channels_reach_monthly_model(self):
        raw = np.ones((3, 4, 3, 3))
        projected = monthly_resource_plan(raw)
        np.testing.assert_equal(projected[..., 0], raw[..., 0])
        self.assertFalse(projected[..., 1:].any())
        self.assertTrue(raw[..., 1:].all())
