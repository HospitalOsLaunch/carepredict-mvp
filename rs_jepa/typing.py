"""Shared NumPy typing aliases for arrays whose dtype is data-dependent."""

from __future__ import annotations

from typing import Any, TypeAlias

from numpy.typing import NDArray

Array: TypeAlias = NDArray[Any]
