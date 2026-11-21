"""Run the released hourly finite-bed kernel and the frozen action-conditioned JEPA on CPU."""

from __future__ import annotations

import ctypes
import hashlib
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
HORIZON = 4
START_OFFSET = 4  # Midday, four hours after the 08:00 census.


class ModelUnavailable(RuntimeError):
    """The configured research model could not be loaded or run."""


def verified(path: Path, expected: str) -> Path:
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ModelUnavailable(f"Model artifact unavailable: {path.name}") from exc
    if digest != expected:
        raise ModelUnavailable(f"Model artifact failed verification: {path.name}")
    return path


@lru_cache(maxsize=1)
def _kernel(expected: str) -> Any:
    source = verified(HERE / "flow_kernel.cpp", expected)
    compiler = shutil.which("c++")
    if not compiler:
        raise ModelUnavailable("Le moteur de flux requiert un compilateur C++17.")
    with tempfile.TemporaryDirectory(prefix="hospitalos-kernel-") as tmp:
        library = Path(tmp) / "flow.so"
        try:
            subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-O3",
                    "-shared",
                    "-fPIC",
                    str(source),
                    "-o",
                    str(library),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            function = ctypes.CDLL(str(library)).roll28
        except (OSError, subprocess.SubprocessError) as exc:
            raise ModelUnavailable("Le moteur de flux n’a pas pu démarrer.") from exc
    function.argtypes = [ctypes.c_int] * 5 + [ctypes.c_void_p] * 8
    function.restype = None
    return function


def rollout(
    data: dict[str, np.ndarray],
    initial: np.ndarray,
    drivers: np.ndarray,
    schedules: np.ndarray,
    kernel_sha: str,
    *,
    start_offset: int = START_OFFSET,
    hours: int = HORIZON,
) -> tuple[np.ndarray, np.ndarray]:
    """One four-hour forecast from noon. All inputs come from verified local artifacts."""
    beds = np.ascontiguousarray(data["beds"], dtype=np.float64)
    route = np.ascontiguousarray(data["route"], dtype=np.int32)
    n = len(beds)
    plans = np.ascontiguousarray(schedules, dtype=np.int32)
    state = np.ascontiguousarray(initial, dtype=np.float64)
    tape = np.ascontiguousarray(drivers, dtype=np.float64)
    if (
        not 1 <= hours <= HORIZON
        or not START_OFFSET <= start_offset <= START_OFFSET + HORIZON - hours
        or not 4 <= n <= 8
        or beds.shape != (n,)
        or route.shape != (n,)
        or np.any((route < 0) | (route >= n))
        or np.any(beds <= 0)
        or not np.isfinite(beds).all()
        or state.shape != (n, 5)
        or not np.isfinite(state).all()
        or np.any(state < -1e-8)
        or np.any(state[:, 1:].sum(axis=1) > beds + 1e-7)
        or tape.shape != (hours, n, 17)
        or not np.isfinite(tape).all()
        or np.any(tape < 0)
        or plans.ndim != 4
        or plans.shape[1:] != (1, 4, 3)
        or not len(plans)
    ):
        raise ModelUnavailable("Les entrées de simulation sont incohérentes.")
    kinds, wards, donors = (plans[..., i] for i in range(3))
    slots = np.array([0, 0, 0, 1, 2, 3, 0])
    if np.any((kinds < 0) | (kinds >= len(slots))):
        raise ModelUnavailable("Type d’affectation inconnu.")
    active = kinds != 0
    loans = kinds == 6
    if (
        np.any(active & ((wards < 0) | (wards >= n) | (slots[kinds] != np.arange(4))))
        or np.any(loans & ((donors < 0) | (donors >= n)))
        or np.any(active & ~loans & (donors != -1))
    ):
        raise ModelUnavailable("Affectation incompatible avec l’unité ou la ressource.")
    endpoints = np.array([hours], dtype=np.int32)
    metrics = np.empty((len(plans), n, 14), dtype=np.float64)
    stocks = np.empty((len(plans), n, 5), dtype=np.float64)
    buffers = (endpoints, beds, route, state, tape, plans, metrics, stocks)
    _kernel(kernel_sha)(n, len(plans), 1, start_offset, 1, *(a.ctypes.data for a in buffers))
    if not np.isfinite(stocks).all() or not np.isfinite(metrics).all():
        raise ModelUnavailable("La prévision contient une valeur non finie.")
    return metrics, stocks


@lru_cache(maxsize=1)
def _weights(expected: str) -> dict[str, np.ndarray]:
    with np.load(verified(DATA / "jepa_19.npz", expected), allow_pickle=False) as artifact:
        return dict(artifact)


def learned_stocks(
    data: dict[str, np.ndarray], metrics: np.ndarray, stocks: np.ndarray, weights_sha: str
) -> np.ndarray:
    """Use the physical rollout as the covariate baseline for the trained JEPA."""
    beds = data["beds"][:, None]
    costs = np.stack(
        (metrics[..., 0], metrics[..., 1], metrics[..., 2] + metrics[..., 3], metrics[..., 7]),
        axis=-1,
    )
    baseline = np.concatenate(
        (costs / (HORIZON * beds * [1.0, 1.0, 5.0, 0.1]), stocks / beds), axis=-1
    ).astype(np.float32)
    controls = data["controls"].copy()
    start = int(data["base_column"])
    controls[..., start : start + 9] = baseline
    w = _weights(weights_sha)
    state = np.clip((data["state_features"] - w["xm"]) / w["xs"], -8.0, 8.0)
    action = np.clip((controls - w["am"]) / w["as"], -8.0, 8.0)
    encoded = np.tanh(state @ w["encoder"] + w["e_bias"])
    hidden = np.tanh(encoded @ w["dynamics"] + action @ w["controls"] + w["d_bias"])
    correction = (hidden @ w["readout"] + w["r_bias"]) * w["ys"] + w["ym"]
    result = np.maximum(0.0, baseline + float(w["blend"]) * correction)
    result[..., 5:9] /= np.maximum(1.0, result[..., 5:9].sum(-1, keepdims=True))
    return np.asarray(result[..., 4:].astype(float) * beds)
