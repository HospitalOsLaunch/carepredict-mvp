"""Metrics and action inputs shared by replay and new research runs."""
import numpy as np


def intervention_errors(frame):
    """The reference compared with itself carries no effect-error information."""
    error = (frame.predicted_effect - frame.true_effect).abs()
    return error.where(frame.action != "none")


def monthly_resource_plan(raw):
    """The monthly adapter trains only on extra staffing in channel zero."""
    plan = raw.copy()
    plan[..., 1:] = 0
    return plan
