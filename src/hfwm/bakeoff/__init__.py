"""Preregistered offline execution harness for HFWM-R0."""

from hfwm.bakeoff.contracts import (
    BakeoffAuthorizationError,
    BakeoffResult,
    ComparatorForecast,
    ExternalComparator,
    RunProfile,
)
from hfwm.bakeoff.runner import run_bakeoff

__all__ = [
    "BakeoffAuthorizationError",
    "BakeoffResult",
    "ComparatorForecast",
    "ExternalComparator",
    "RunProfile",
    "run_bakeoff",
]
