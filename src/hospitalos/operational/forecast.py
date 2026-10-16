"""Small shared-weight topology forecaster, not a completed JEPA/world model.

All learned targets are conditional means. Summation therefore has a defined
estimand; no sums of marginal medians, calibrated intervals or action effects.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import torch
from numpy.typing import NDArray
from torch import nn

from .contract import Cursor, Node, Observation, Topology

FEATURES = (
    "occupancy",
    "open_beds",
    "ed_waiting",
    "nurse_count",
    "aide_count",
    "care_workload_proxy",
)
TARGETS = ("occupancy", "ed_waiting", "care_workload_proxy")
LAGS = (0, 6, 24, 48, 168)
TARGET_NORMALIZERS = np.array([1.0, 0.1, 15.0])
FEATURE_NORMALIZERS = np.array([1.0, 1.0, 0.1, 0.1, 0.1, 15.0])
FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class Inputs:
    topology: Topology
    nodes: tuple[Node, ...]
    origins: tuple[dt.datetime, ...]
    x: FloatArray
    scales: FloatArray
    persistence: FloatArray
    daily: FloatArray
    ages: FloatArray
    target_hours: NDArray[np.int64]
    peer_matrix: FloatArray


def peer_matrix(topology: Topology, nodes: Sequence[Node]) -> FloatArray:
    # Same-parent context. At hospital-only granularity, this is the node itself.
    groups = [n.parent_id or n.entity_id for n in nodes]
    result = np.array([[a == b for b in groups] for a in groups], dtype=float)
    return cast(FloatArray, result / result.sum(axis=1, keepdims=True))


def build_inputs(
    topology: Topology,
    observations: Sequence[Observation],
    entities: Sequence[str],
    start: dt.datetime,
    hours: int,
    *,
    timezone: dt.tzinfo,
    horizon: int = 24,
    stride: int = 6,
) -> Inputs:
    """No labels, HospitalConfig, hidden mechanism parameter or synthetic seed enters here."""
    nodes = topology.frontier(entities)
    if any(n.capacity_beds is None or n.capacity_beds <= 0 for n in nodes):
        raise ValueError("This first forecaster requires a known positive nominal bed capacity")
    if hours <= max(LAGS) + horizon or stride < 1 or horizon < 1:
        raise ValueError("Insufficient history or invalid forecast schedule")
    if {o.entity_id for o in observations} - set(entities):
        raise ValueError("A coarse stream must not contain hidden fine observations")
    capacities = np.array([n.capacity_beds for n in nodes], dtype=float)
    ordered = sorted(observations, key=lambda o: (o.available_at, o.event_id, o.version))
    cursor, position = Cursor(timezone), 0
    history: list[FloatArray] = []
    xs, persists, daily_rows, ages, origins, target_hours = [], [], [], [], [], []
    for hour in range(hours - horizon + 1):
        at = start + dt.timedelta(hours=hour)
        begin = position
        while position < len(ordered) and ordered[position].available_at <= at:
            position += 1
        cursor.advance(at, ordered[begin:position], topology)
        state = np.full((len(nodes), len(FEATURES)), np.nan)
        age = np.full(len(nodes), np.nan)
        for j, node in enumerate(nodes):
            obs = cursor.latest.get(node.entity_id)
            if obs is not None:
                state[j] = [
                    obs.values.get(k) if obs.values.get(k) is not None else np.nan for k in FEATURES
                ]
                age[j] = (at - obs.event_time).total_seconds() / 3600
        normalized = state / capacities[:, None] / FEATURE_NORMALIZERS
        history.append(
            np.concatenate(
                (
                    np.nan_to_num(normalized),
                    np.isfinite(state).astype(float),
                    np.nan_to_num(np.minimum(age, 168), nan=168)[:, None] / 168,
                ),
                axis=1,
            )
        )
        if hour < max(LAGS) or hour % stride:
            continue
        target = at + dt.timedelta(hours=horizon)
        local = target.astimezone(timezone)
        calendar = np.tile(
            [
                np.sin(2 * np.pi * local.hour / 24),
                np.cos(2 * np.pi * local.hour / 24),
                np.sin(2 * np.pi * local.weekday() / 7),
                np.cos(2 * np.pi * local.weekday() / 7),
            ],
            (len(nodes), 1),
        )
        static = np.array(
            [
                [
                    np.log1p(capacities[j]) / 8,
                    (n.isolation_beds or 0) / capacities[j],
                    (n.oxygen_beds or 0) / capacities[j],
                    float(n.isolation_beds is not None),
                    float(n.oxygen_beds is not None),
                    float(n.level == "unit"),
                    float(n.level == "pole"),
                    float(n.level == "hospital"),
                ]
                for j, n in enumerate(nodes)
            ]
        )
        xs.append(
            np.concatenate([*[history[hour - lag] for lag in LAGS], static, calendar], axis=1)
        )
        persists.append(state[:, [FEATURES.index(k) for k in TARGETS]])
        day = np.full((len(nodes), len(TARGETS)), np.nan)
        for j, n in enumerate(nodes):
            obs = cursor.same_clock_hour(n.entity_id, target)
            if obs is not None:
                day[j] = [
                    obs.values.get(k) if obs.values.get(k) is not None else np.nan for k in TARGETS
                ]
        daily_rows.append(day)
        ages.append(age)
        origins.append(at)
        target_hours.append(local.hour)
    scales = capacities[:, None] * TARGET_NORMALIZERS
    return Inputs(
        topology,
        nodes,
        tuple(origins),
        np.asarray(xs),
        scales,
        np.asarray(persists),
        np.asarray(daily_rows),
        np.asarray(ages),
        np.asarray(target_hours, dtype=np.int64),
        peer_matrix(topology, nodes),
    )


class TopologyForecaster(nn.Module):
    """Shared node encoder with peer/global context, independent of node order/count."""

    def __init__(self, features: int, width: int = 32):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(features, width), nn.SiLU(), nn.Linear(width, width), nn.SiLU()
        )
        self.head = nn.Sequential(
            nn.Linear(width * 3, width), nn.SiLU(), nn.Linear(width, len(TARGETS)), nn.Softplus()
        )

    def forward(self, x: torch.Tensor, peers: torch.Tensor) -> torch.Tensor:
        if x.ndim != 3 or peers.shape != (x.shape[1], x.shape[1]):
            raise ValueError("Expected [batch,nodes,features] and a node adjacency matrix")
        h = self.encoder(x)
        local = torch.einsum("ij,bjd->bid", peers, h)
        global_context = h.mean(dim=1, keepdim=True).expand_as(h)
        return cast(torch.Tensor, self.head(torch.cat((h, local, global_context), dim=-1)))


def fit(
    inputs: Sequence[Inputs],
    labels: Sequence[FloatArray],
    *,
    epochs: int,
    seed: int,
    learning_rate: float,
    batch_size: int,
) -> tuple[TopologyForecaster, list[float]]:
    if not inputs or len(inputs) != len(labels):
        raise ValueError("Missing training data")
    torch.manual_seed(seed)
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    rng = np.random.default_rng(seed)
    model = TopologyForecaster(inputs[0].x.shape[-1])
    optimizer = torch.optim.AdamW(  # type: ignore[attr-defined]
        model.parameters(), lr=learning_rate, weight_decay=0.001
    )
    tensors = []
    for data, y in zip(inputs, labels, strict=True):
        if (
            y.shape != (len(data.origins), len(data.nodes), len(TARGETS))
            or not np.isfinite(y).all()
        ):
            raise ValueError("Training target mismatch")
        tensors.append(
            (
                torch.tensor(data.x, dtype=torch.float32),
                torch.tensor(y / data.scales, dtype=torch.float32),
                torch.tensor(data.peer_matrix, dtype=torch.float32),
            )
        )
    losses = []
    model.train()
    for _ in range(epochs):
        total = 0.0
        # One equally weighted update per hospital/frontier each epoch.
        for i in rng.permutation(len(tensors)):
            x, y, peers = tensors[i]
            ix = rng.choice(len(x), size=min(batch_size, len(x)), replace=False)
            optimizer.zero_grad()
            predicted = model(x[ix], peers)
            loss = torch.mean((predicted - y[ix]) ** 2)
            loss.backward()  # type: ignore[no-untyped-call]
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
            total += float(loss.detach())
        losses.append(total / len(tensors))
    model.eval()
    return model, losses


def predict(model: TopologyForecaster, data: Inputs) -> FloatArray:
    model.eval()
    with torch.no_grad():
        values = model(
            torch.tensor(data.x, dtype=torch.float32),
            torch.tensor(data.peer_matrix, dtype=torch.float32),
        ).numpy()
    return np.asarray(values, dtype=float) * data.scales


def load_frozen_model(path: Path) -> TopologyForecaster:
    """Reload a reviewed state dictionary; reject altered weights or feature definitions."""
    config = json.loads((path / "model_config.json").read_text())
    if (
        config["features"] != list(FEATURES)
        or config["lags_h"] != list(LAGS)
        or config["targets"] != list(TARGETS)
    ):
        raise ValueError("Model feature contract mismatch")
    weights = path / "model.pt"
    if hashlib.sha256(weights.read_bytes()).hexdigest() != config["weights_sha256"]:
        raise ValueError("Model weights checksum mismatch")
    model = TopologyForecaster(config["input_width"])
    state = torch.load(weights, map_location="cpu", weights_only=True)
    model.load_state_dict(state, strict=True)
    model.eval()
    return model


def climatology(inputs: Sequence[Inputs], labels: Sequence[FloatArray]) -> FloatArray:
    # Equal weight per hospital/frontier; rates, not absolute counts from a larger site.
    bins: list[list[FloatArray]] = [[] for _ in range(24)]
    for data, target in zip(inputs, labels, strict=True):
        rates = target / data.scales
        for h in np.unique(data.target_hours):
            bins[int(h)].append(rates[data.target_hours == h].mean(axis=(0, 1)))
    global_mean = np.mean([x for bucket in bins for x in bucket], axis=0)
    return np.asarray([np.mean(bucket, axis=0) if bucket else global_mean for bucket in bins])


def baseline_predictions(data: Inputs, climate: FloatArray) -> dict[str, FloatArray]:
    fallback = climate[data.target_hours, None, :] * data.scales
    return {
        "persistence": np.where(np.isfinite(data.persistence), data.persistence, fallback),
        "daily_same_hour": np.where(np.isfinite(data.daily), data.daily, fallback),
        "train_climatology": fallback,
    }


def score(
    data: Inputs, truth: FloatArray, predictions: dict[str, FloatArray]
) -> list[dict[str, Any]]:
    """Score every scheduled origin; stale or missing input does not remove an outcome."""
    rows: list[dict[str, Any]] = []
    for node in data.topology.nodes:
        members = [
            j
            for j, n in enumerate(data.nodes)
            if n.entity_id in data.topology.descendants(node.entity_id)
        ]
        # Never disaggregate an observed pole/hospital into unseen descendants.
        if not members:
            continue
        y = truth[:, members, :].sum(axis=1)
        capacity = sum(data.scales[j, 0] for j in members)
        tension = y[:, 0] >= 0.9 * capacity  # scenario stratum, not an empirical clinical threshold
        for method, values in predictions.items():
            p = values[:, members, :].sum(axis=1)
            if p.shape != y.shape or not np.isfinite(p).all() or (p < 0).any():
                raise ValueError("Invalid forecast")
            for regime, mask in (
                ("all", np.ones(len(y), dtype=bool)),
                ("nominal_occupancy_ge90pct", tension),
            ):
                for k, target in enumerate(TARGETS):
                    error = p[mask, k] - y[mask, k]
                    actual, mean = y[mask, k], np.maximum(p[mask, k], 1e-8)
                    deviance = 2 * (mean - actual)
                    positive = actual > 0
                    deviance[positive] += (
                        2 * actual[positive] * np.log(actual[positive] / mean[positive])
                    )
                    rows.append(
                        {
                            "entity_id": node.entity_id,
                            "level": node.level,
                            "method": method,
                            "target": target,
                            "regime": regime,
                            "n": len(error),
                            "mae": float(np.abs(error).mean()) if len(error) else None,
                            "mse": float(np.square(error).mean()) if len(error) else None,
                            "bias": float(error.mean()) if len(error) else None,
                            "poisson_mean_deviance": float(deviance.mean())
                            if len(error) and target != "care_workload_proxy"
                            else None,
                        }
                    )
    return rows
