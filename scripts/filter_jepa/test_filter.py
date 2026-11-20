"""Regression checks for exact delayed reports. Run with unittest discovery."""
import unittest
from datetime import timedelta

import numpy as np

from cohort import EYE, START, filter_reports, transitions


class DelayedReports(unittest.TestCase):
    def setUp(self):
        self.days = [START + timedelta(days=d) for d in range(4)]
        self.schedule = [0, 1, 0, 1]

    def test_late_report_replayed_from_event_date(self):
        reports = [[], [], [(0, 0, 0, 2)], []]
        posterior, _ = filter_reports(self.days, self.schedule, reports)
        p = EYE[2]
        for i in (1, 2):
            p = p @ transitions(self.days[i], 0, self.schedule[i], nominal=True)
        np.testing.assert_allclose(posterior[2, 0, 0], p)
        np.testing.assert_allclose(posterior.sum(axis=-1), 1)
        prefix, _ = filter_reports(self.days[:2], self.schedule[:2], reports[:2])
        np.testing.assert_array_equal(prefix, posterior[:2])

    def test_stale_report_does_not_overwrite_newer_report(self):
        reports = [[], [(1, 1, 5, 1)], [(0, 1, 5, 2)], []]
        posterior, latest = filter_reports(self.days, self.schedule, reports)
        np.testing.assert_array_equal(latest[2, 1, 5], EYE[1])
        np.testing.assert_allclose(posterior[2, 1, 5], EYE[1] @ transitions(self.days[2], 1, 0, nominal=True))
