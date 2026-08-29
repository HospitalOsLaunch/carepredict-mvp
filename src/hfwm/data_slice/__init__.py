"""Minimal deterministic point-in-time dataset slice for HFWM-R0."""

from .builder import (
    DATA_SLICE_ID,
    DataSliceBuild,
    build_point_in_time_data_slice,
)

__all__ = [
    "DATA_SLICE_ID",
    "DataSliceBuild",
    "build_point_in_time_data_slice",
]
