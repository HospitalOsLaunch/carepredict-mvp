import unittest
import numpy as np
from run import action_choice, arrays


class DecisionTests(unittest.TestCase):
    def test_care_constraint_eliminates_wait_winner(self):
        values = np.array([[0, 0], [-50, 8], [-20, -3]])
        self.assertEqual(action_choice(values), 1)
        self.assertEqual(action_choice(values, guard=True), 2)
        values[2, 1] = 4
        self.assertEqual(action_choice(values, guard=True), 0)

    def test_paired_target_is_invariant_to_common_future_cost(self):
        outcomes = np.arange(18).reshape(3, 3, 2)
        def target(values):
            return arrays([dict(features=[1], truth=values.tolist())])[1]
        offset = np.array([[[1000, 600], [2100, 400], [4000, 900]]])
        np.testing.assert_equal(target(outcomes), target(outcomes + offset))

    def test_tied_effects_prefer_abstention(self):
        self.assertEqual(action_choice(np.zeros((3, 2)), guard=True), 0)
