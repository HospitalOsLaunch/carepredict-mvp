"""Parity with the recorded held-out trajectories, using only public features at inference."""

import gzip
import json
import unittest

import numpy as np

from scripts.action_effects.fit import refit
from scripts.action_effects.predict import ACTIONS, EVIDENCE, predict_effect


class FrozenPredictionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(EVIDENCE / "examples.json.gz", "rt") as stream:
            cls.examples = json.load(stream)
        cls.weights = json.loads((EVIDENCE / "effect_model.json").read_text())

    def test_predictions_match_held_out_archive_after_refit(self):
        test = [row for row in self.examples if row["split"] == "TEST"]
        fitted = refit(self.examples, self.weights["alpha"])
        archived = json.loads((EVIDENCE / "test_effects.json").read_text())
        for weights in (fitted, self.weights):
            for row, expected in zip(test, archived, strict=True):
                for action, target in zip(ACTIONS[1:], expected, strict=True):
                    result = predict_effect(row["features"], action, weights)
                    values = [[e["delta_wait_patient_minutes"], e["delta_uncovered_care_minutes"]]
                              for e in result["effects"]]
                    np.testing.assert_allclose(values, target, atol=1e-8)

    def test_reference_and_invalid_inputs(self):
        features = self.examples[0]["features"]
        result = predict_effect(features, "none", self.weights)
        for effect in result["effects"]:
            self.assertEqual(effect["delta_wait_patient_minutes"], 0.0)
            self.assertEqual(effect["delta_uncovered_care_minutes"], 0.0)
        for bad in ([], [float("nan")] * len(features)):
            with self.assertRaises(ValueError):
                predict_effect(bad, "transport", self.weights)
        with self.assertRaises(ValueError):
            predict_effect(features, "click", self.weights)
