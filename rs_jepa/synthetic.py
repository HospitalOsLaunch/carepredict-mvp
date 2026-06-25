"""Phase A multi-site synthetic hospital dynamics simulator."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from rs_jepa.config import SyntheticConfig
from rs_jepa.splits import CROSS_SITE_VAL, add_validation_splits, choose_cross_site_validation_sites

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
INSTANTANEOUS_OBSERVABLE_COLUMNS = (
    "inflow_per_capacity",
    "discharges_per_capacity",
    "occupancy_ratio",
    "staffing_ratio",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
)
ACTION_COLUMNS = ("staffing_delta", "discharge_delta")


@dataclass(frozen=True)
class SyntheticHospitalData:
    temporal: pd.DataFrame
    static: pd.DataFrame
    temporal_feature_columns: tuple[str, ...]
    static_feature_columns: tuple[str, ...]
    action_columns: tuple[str, ...] = ACTION_COLUMNS
    criticality_column: str = "criticality"
    criticality_inputs: tuple[str, ...] = CRITICALITY_INPUTS


@dataclass(frozen=True)
class SyntheticSiteDiagnostics:
    site_id: str
    split: str
    occupancy_total: np.ndarray
    util: np.ndarray
    rise: np.ndarray
    kappa: np.ndarray
    observable_instantaneous: np.ndarray
    capacity: float
    nurse_ratio_target: float
    casemix: np.ndarray


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def pairwise_distances(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a[:, None, :] - b[None, :, :]
    return np.sqrt(np.sum(diff * diff, axis=2))


class SyntheticHospitalSimulator:
    """Generate heterogeneous hourly hospital dynamics with known criticality."""

    def __init__(self, cfg: SyntheticConfig, reserved_site_ids: set[str] | None = None):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed)
        self.reserved_site_ids = reserved_site_ids or set()

    def generate(self) -> SyntheticHospitalData:
        frames: list[pd.DataFrame] = []
        static_rows: list[dict[str, float | str]] = []
        total_steps = int(self.cfg.total_days * 24 / self.cfg.step_hours)
        timestamps = pd.date_range("2024-01-01", periods=total_steps, freq=f"{self.cfg.step_hours}h")
        max_capacity = float(self.cfg.max_capacity)
        bulk_signatures = []
        for support_idx in range(self.cfg.n_sites):
            support_id = f"site-{support_idx:03d}"
            if support_id in self.reserved_site_ids:
                continue
            support_rng = np.random.default_rng(self.cfg.seed + 1009 * (support_idx + 1))
            support_capacity = int(support_rng.integers(self.cfg.min_capacity, int(self.cfg.max_capacity * 0.82)))
            support_case_mix = float(support_rng.uniform(self.cfg.min_case_mix, 1.14))
            support_base_saturation = float(support_rng.uniform(self.cfg.min_base_saturation, 0.84))
            support_staffing_base = float(support_rng.uniform(0.92, self.cfg.max_staffing_ratio))
            support_seasonality_strength = float(support_rng.uniform(0.05, 0.18))
            bulk_signatures.append(
                [
                    support_capacity,
                    support_staffing_base,
                    support_case_mix,
                    support_base_saturation,
                    support_seasonality_strength,
                ]
            )
        bulk_signatures_arr = np.asarray(bulk_signatures, dtype=float)
        bulk_intra = pairwise_distances(bulk_signatures_arr, bulk_signatures_arr)
        bulk_intra_median = float(np.median(bulk_intra[bulk_intra > 0]))

        for site_idx in range(self.cfg.n_sites):
            site_id = f"site-{site_idx:03d}"
            site_rng = np.random.default_rng(self.cfg.seed + 1009 * (site_idx + 1))
            is_reserved = site_id in self.reserved_site_ids
            if is_reserved:
                best_candidate = None
                best_gap = float("inf")
                for _ in range(200):
                    candidate_capacity = int(site_rng.integers(self.cfg.min_capacity, self.cfg.max_capacity + 1))
                    candidate_case_mix = float(site_rng.uniform(self.cfg.min_case_mix, self.cfg.max_case_mix))
                    candidate_base_saturation = float(site_rng.uniform(self.cfg.min_base_saturation, self.cfg.max_base_saturation))
                    candidate_staffing_base = float(site_rng.uniform(self.cfg.min_staffing_ratio, self.cfg.max_staffing_ratio))
                    candidate_seasonality_strength = float(site_rng.uniform(0.05, 0.24))
                    signature = np.asarray(
                        [
                            candidate_capacity,
                            candidate_staffing_base,
                            candidate_case_mix,
                            candidate_base_saturation,
                            candidate_seasonality_strength,
                        ],
                        dtype=float,
                    )
                    ratio = float(np.min(np.linalg.norm(bulk_signatures_arr - signature[None, :], axis=1)) / bulk_intra_median)
                    gap = 0.0 if 0.35 <= ratio <= 0.50 else min(abs(ratio - 0.35), abs(ratio - 0.50))
                    if gap < best_gap:
                        best_candidate = (
                            candidate_capacity,
                            candidate_case_mix,
                            candidate_base_saturation,
                            candidate_staffing_base,
                            candidate_seasonality_strength,
                            ratio,
                        )
                        best_gap = gap
                    if 0.35 <= ratio <= 0.50:
                        break
                capacity, case_mix, base_saturation, staffing_base, seasonality_strength, ratio = best_candidate
                if not (0.35 <= ratio <= 0.50):
                    anchor = bulk_signatures_arr[int(site_rng.integers(0, len(bulk_signatures_arr)))]
                    target_ratio = float(site_rng.uniform(0.38, 0.47))
                    capacity = int(
                        np.clip(
                            round(anchor[0] + target_ratio * bulk_intra_median),
                            self.cfg.min_capacity,
                            self.cfg.max_capacity,
                        )
                    )
                    staffing_base = float(np.clip(anchor[1] + site_rng.normal(0.0, 0.015), self.cfg.min_staffing_ratio, self.cfg.max_staffing_ratio))
                    case_mix = float(np.clip(anchor[2] + site_rng.normal(0.0, 0.025), self.cfg.min_case_mix, self.cfg.max_case_mix))
                    base_saturation = float(np.clip(anchor[3] + site_rng.normal(0.0, 0.020), self.cfg.min_base_saturation, self.cfg.max_base_saturation))
                    seasonality_strength = float(np.clip(anchor[4] + site_rng.normal(0.0, 0.015), 0.05, 0.24))
            else:
                capacity = int(site_rng.integers(self.cfg.min_capacity, int(self.cfg.max_capacity * 0.82)))
                case_mix = float(site_rng.uniform(self.cfg.min_case_mix, 1.14))
                base_saturation = float(site_rng.uniform(self.cfg.min_base_saturation, 0.84))
                staffing_base = float(site_rng.uniform(0.92, self.cfg.max_staffing_ratio))
                seasonality_strength = float(site_rng.uniform(0.05, 0.18))
            weekday_strength = float(site_rng.uniform(0.04, 0.15))
            discharge_rate = float(site_rng.uniform(0.0025, 0.0065))
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
        staffing_delta, discharge_delta = self._exogenous_actions(n, rng)
        effective_staffing_ratio = np.clip(staffing_ratio + staffing_delta, 0.45, 1.45)
        occupancy = np.empty(n, dtype=float)
        discharges = np.empty(n, dtype=float)
        occupancy[0] = capacity * base_saturation
        for t in range(n - 1):
            pressure_slowdown = np.clip(1.15 - occupancy[t] / capacity, 0.45, 1.15)
            baseline_discharges = (
                discharge_rate * occupancy[t] * pressure_slowdown * rng.uniform(0.88, 1.12)
            )
            forced_discharges = discharge_delta[t] * capacity
            discharges[t] = baseline_discharges + forced_discharges
            occupancy[t + 1] = np.clip(
                occupancy[t] + inflow[t] - discharges[t],
                0.0,
                capacity * 1.35,
            )
        discharges[-1] = discharge_rate * occupancy[-1] + discharge_delta[-1] * capacity

        occupancy_ratio = occupancy / capacity
        expected_inflow = max(base_inflow * case_mix, 1e-6)
        inflow_surge = inflow / expected_inflow
        patients_per_staff_ratio = np.clip(occupancy_ratio / effective_staffing_ratio, 0.0, 3.0)
        criticality = sigmoid(
            1.60 * (occupancy_ratio - 0.90)
            + 4.80 * (inflow_surge - 1.0)
            + 0.80 * (patients_per_staff_ratio - 1.0)
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
                "staffing_ratio": effective_staffing_ratio,
                "inflow_surge": inflow_surge,
                "staffing_delta": staffing_delta,
                "discharge_delta": discharge_delta,
                "hour_sin": np.sin(2 * np.pi * hours / 24),
                "hour_cos": np.cos(2 * np.pi * hours / 24),
                "dow_sin": np.sin(2 * np.pi * dow / 7),
                "dow_cos": np.cos(2 * np.pi * dow / 7),
                "criticality": criticality,
                "criticality_level": levels.astype(int),
            }
        )

    def _exogenous_actions(self, n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        """Draw state-independent action deltas for causal simulator diagnostics."""
        staffing_delta = np.zeros(n, dtype=float)
        discharge_delta = np.zeros(n, dtype=float)
        if not self.cfg.interventions_enabled:
            return staffing_delta, discharge_delta

        staff_mask = rng.random(n) < self.cfg.p_intervention
        discharge_mask = rng.random(n) < self.cfg.p_intervention
        staff_sign = rng.choice(np.array([-1.0, 1.0]), size=n)
        staffing_delta = (
            staff_mask
            * staff_sign
            * rng.uniform(0.04, self.cfg.max_staffing_delta, size=n)
        )
        discharge_delta = (
            discharge_mask
            * rng.uniform(0.004, self.cfg.max_discharge_delta_per_capacity, size=n)
        )
        return staffing_delta.astype(float), discharge_delta.astype(float)

    def _surge_process(self, n: int, rng: np.random.Generator) -> np.ndarray:
        surge = np.zeros(n, dtype=float)
        expected_events = self.cfg.surge_event_rate_per_30d * 1.35 * (n / (24 * 30))
        n_events = int(rng.poisson(expected_events))
        for _ in range(n_events):
            start = int(rng.integers(0, max(1, n - self.cfg.surge_min_duration_h)))
            min_duration = int(self.cfg.surge_min_duration_h * 1.5)
            max_duration = int(self.cfg.surge_max_duration_h * 1.8)
            duration = int(rng.integers(min_duration, max_duration + 1))
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


def generate_sites(cfg) -> list[SyntheticSiteDiagnostics]:
    """Return per-site diagnostic views of the Phase A simulator output."""

    synthetic_cfg = getattr(cfg, "synthetic", cfg)
    split_cfg = getattr(cfg, "split", None)
    site_ids = [f"site-{site_idx:03d}" for site_idx in range(synthetic_cfg.n_sites)]
    reserved_site_ids = (
        set(choose_cross_site_validation_sites(site_ids, split_cfg))
        if split_cfg is not None
        else set()
    )
    data = SyntheticHospitalSimulator(synthetic_cfg, reserved_site_ids=reserved_site_ids).generate()
    split_frame = data.temporal[["site_id", "timestamp"]].copy()
    if split_cfg is not None:
        split_frame, _summary = add_validation_splits(split_frame, split_cfg)
    else:
        split_frame["split"] = "train"
    temporal = data.temporal.merge(split_frame, on=["site_id", "timestamp"], how="left")
    static = data.static.set_index("site_id")
    sites: list[SyntheticSiteDiagnostics] = []
    for site_id, group in temporal.groupby("site_id", sort=True):
        group = group.sort_values("timestamp")
        split = "unseen" if (group["split"] == CROSS_SITE_VAL).all() else "train"
        site_static = static.loc[site_id]
        sites.append(
            SyntheticSiteDiagnostics(
                site_id=site_id,
                split=split,
                occupancy_total=group["occupancy"].to_numpy(dtype=float),
                util=group["occupancy_ratio"].to_numpy(dtype=float),
                rise=group["inflow_surge"].to_numpy(dtype=float),
                kappa=group["criticality"].to_numpy(dtype=float),
                observable_instantaneous=group.loc[:, INSTANTANEOUS_OBSERVABLE_COLUMNS].to_numpy(dtype=float),
                capacity=float(group["capacity"].iloc[0]),
                nurse_ratio_target=float(group["staffing_ratio"].median()),
                casemix=np.array(
                    [
                        site_static["case_mix_index"],
                        site_static["base_saturation"],
                        site_static["seasonality_strength"],
                    ],
                    dtype=float,
                ),
            )
        )
    return sites
