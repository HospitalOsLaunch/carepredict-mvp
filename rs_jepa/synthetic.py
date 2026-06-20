"""Phase A multi-site synthetic hospital dynamics simulator."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from rs_jepa.config import SyntheticConfig

TEMPORAL_FEATURE_COLUMNS = (
    "inflow_per_capacity",
    "discharges_per_capacity",
    "occupancy_ratio",
    "staffing_ratio",
    "inflow_surge",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
)
STATIC_FEATURE_COLUMNS = (
    "capacity_norm",
    "case_mix_index",
    "base_saturation",
    "seasonality_strength",
)
CRITICALITY_INPUTS = ("occupancy_ratio", "inflow_surge", "staffing_ratio")
ABSOLUTE_FORBIDDEN_LABEL_INPUTS = {"capacity", "occupancy", "inflow", "discharges", "staffing"}


@dataclass(frozen=True)
class SyntheticHospitalData:
    temporal: pd.DataFrame
    static: pd.DataFrame
    temporal_feature_columns: tuple[str, ...]
    static_feature_columns: tuple[str, ...]
    criticality_column: str = "criticality"
    criticality_inputs: tuple[str, ...] = CRITICALITY_INPUTS


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


class SyntheticHospitalSimulator:
    """Generate heterogeneous hourly hospital dynamics with known criticality."""

    def __init__(self, cfg: SyntheticConfig):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed)

    def generate(self) -> SyntheticHospitalData:
        frames: list[pd.DataFrame] = []
        static_rows: list[dict[str, float | str]] = []
        total_steps = int(self.cfg.total_days * 24 / self.cfg.step_hours)
        timestamps = pd.date_range("2024-01-01", periods=total_steps, freq=f"{self.cfg.step_hours}h")
        max_capacity = float(self.cfg.max_capacity)

        for site_idx in range(self.cfg.n_sites):
            site_id = f"site-{site_idx:03d}"
            site_rng = np.random.default_rng(self.cfg.seed + 1009 * (site_idx + 1))
            capacity = int(site_rng.integers(self.cfg.min_capacity, self.cfg.max_capacity + 1))
            case_mix = float(site_rng.uniform(self.cfg.min_case_mix, self.cfg.max_case_mix))
            base_saturation = float(site_rng.uniform(self.cfg.min_base_saturation, self.cfg.max_base_saturation))
            staffing_base = float(site_rng.uniform(self.cfg.min_staffing_ratio, self.cfg.max_staffing_ratio))
            seasonality_strength = float(site_rng.uniform(0.05, 0.22))
            weekday_strength = float(site_rng.uniform(0.04, 0.15))
            discharge_rate = float(site_rng.uniform(0.040, 0.085))
            frame = self._simulate_site(
                site_id=site_id,
                timestamps=timestamps,
                capacity=capacity,
                case_mix=case_mix,
                base_saturation=base_saturation,
                staffing_base=staffing_base,
                seasonality_strength=seasonality_strength,
                weekday_strength=weekday_strength,
                discharge_rate=discharge_rate,
                rng=site_rng,
            )
            frames.append(frame)
            static_rows.append(
                {
                    "site_id": site_id,
                    "capacity_norm": capacity / max_capacity,
                    "case_mix_index": case_mix,
                    "base_saturation": base_saturation,
                    "seasonality_strength": seasonality_strength,
                }
            )

        temporal = pd.concat(frames, ignore_index=True)
        static = pd.DataFrame(static_rows)
        data = SyntheticHospitalData(
            temporal=temporal,
            static=static,
            temporal_feature_columns=TEMPORAL_FEATURE_COLUMNS,
            static_feature_columns=STATIC_FEATURE_COLUMNS,
        )
        assert_criticality_is_unitless(data)
        return data

    def _simulate_site(
        self,
        *,
        site_id: str,
        timestamps: pd.DatetimeIndex,
        capacity: int,
        case_mix: float,
        base_saturation: float,
        staffing_base: float,
        seasonality_strength: float,
        weekday_strength: float,
        discharge_rate: float,
        rng: np.random.Generator,
    ) -> pd.DataFrame:
        n = len(timestamps)
        hours = timestamps.hour.to_numpy()
        dow = timestamps.dayofweek.to_numpy()
        day = np.arange(n) / 24.0
        yearly = np.sin(2 * np.pi * day / 365.25)
        weekly = np.where(dow < 5, 1.0, -0.55)
        hourly = 0.08 * np.sin(2 * np.pi * (hours - 10) / 24)
        base_inflow = capacity * discharge_rate * base_saturation
        surge = self._surge_process(n, rng)
        inflow_multiplier = (
            1.0
            + seasonality_strength * yearly
            + weekday_strength * weekly
            + hourly
            + surge
            + rng.normal(0.0, self.cfg.noise_std, size=n)
        )
        inflow = np.clip(base_inflow * case_mix * inflow_multiplier, 0.0, None)
        staffing_ratio = np.clip(
            staffing_base - 0.10 * surge + rng.normal(0.0, 0.025, size=n),
            0.45,
            1.35,
        )
        occupancy = np.empty(n, dtype=float)
        discharges = np.empty(n, dtype=float)
        occupancy[0] = capacity * base_saturation
        for t in range(n - 1):
            pressure_slowdown = np.clip(1.15 - occupancy[t] / capacity, 0.45, 1.15)
            discharges[t] = discharge_rate * occupancy[t] * pressure_slowdown * rng.uniform(0.88, 1.12)
            occupancy[t + 1] = np.clip(occupancy[t] + inflow[t] - discharges[t], 0.0, capacity * 1.35)
        discharges[-1] = discharge_rate * occupancy[-1]

        occupancy_ratio = occupancy / capacity
        expected_inflow = max(base_inflow * case_mix, 1e-6)
        inflow_surge = inflow / expected_inflow
        patients_per_staff_ratio = np.clip(occupancy_ratio / staffing_ratio, 0.0, 3.0)
        criticality = sigmoid(
            3.0 * (occupancy_ratio - 0.90)
            + 1.00 * (inflow_surge - 1.0)
            + 1.40 * (patients_per_staff_ratio - 1.0)
        )
        levels = np.digitize(criticality, bins=np.array([0.35, 0.60, 0.80]), right=False)

        return pd.DataFrame(
            {
                "site_id": site_id,
                "timestamp": timestamps,
                "inflow": inflow,
                "discharges": discharges,
                "occupancy": occupancy,
                "capacity": float(capacity),
                "staffing": staffing_ratio * capacity,
                "inflow_per_capacity": inflow / capacity,
                "discharges_per_capacity": discharges / capacity,
                "occupancy_ratio": occupancy_ratio,
                "staffing_ratio": staffing_ratio,
                "inflow_surge": inflow_surge,
                "hour_sin": np.sin(2 * np.pi * hours / 24),
                "hour_cos": np.cos(2 * np.pi * hours / 24),
                "dow_sin": np.sin(2 * np.pi * dow / 7),
                "dow_cos": np.cos(2 * np.pi * dow / 7),
                "criticality": criticality,
                "criticality_level": levels.astype(int),
            }
        )

    def _surge_process(self, n: int, rng: np.random.Generator) -> np.ndarray:
        surge = np.zeros(n, dtype=float)
        expected_events = self.cfg.surge_event_rate_per_30d * (n / (24 * 30))
        n_events = int(rng.poisson(expected_events))
        for _ in range(n_events):
            start = int(rng.integers(0, max(1, n - self.cfg.surge_min_duration_h)))
            duration = int(rng.integers(self.cfg.surge_min_duration_h, self.cfg.surge_max_duration_h + 1))
            amplitude = float(rng.uniform(0.25, 0.75))
            end = min(n, start + duration)
            shape = np.sin(np.linspace(0, np.pi, end - start))
            surge[start:end] += amplitude * shape
        return surge


def assert_criticality_is_unitless(data: SyntheticHospitalData) -> None:
    """Criticality must depend only on ratios or per-site normalized quantities."""

    inputs = set(data.criticality_inputs)
    forbidden = inputs & ABSOLUTE_FORBIDDEN_LABEL_INPUTS
    if forbidden:
        raise ValueError(f"Criticality dépend de seuils absolus interdits: {sorted(forbidden)}")
    for name in inputs:
        if not (name.endswith("_ratio") or name.endswith("_surge") or name.endswith("_rank")):
            raise ValueError(f"Entrée de criticality non unitless: {name}")
