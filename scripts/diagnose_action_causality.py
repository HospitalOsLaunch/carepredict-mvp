#!/usr/bin/env python3
"""Diagnostic causal des actions exogènes du simulateur RS-JEPA."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_jepa.config import RSJEPAConfig, load_config  # noqa: E402
from rs_jepa.synthetic import SyntheticHospitalSimulator  # noqa: E402


class RegressionResult(NamedTuple):
    coefficient: float
    t_stat: float


class CausalReport(NamedTuple):
    staffing_effect: RegressionResult
    discharge_occupancy_effect: RegressionResult
    discharge_criticality_effect: RegressionResult
    corr_staffing_surge: float
    corr_staffing_occupancy: float
    corr_discharge_surge: float
    corr_discharge_occupancy: float
    verdict_green: bool


def config_with_interventions(cfg: RSJEPAConfig) -> RSJEPAConfig:
    """Return a copy with exogenous interventions enabled."""
    return replace(
        cfg,
        synthetic=replace(
            cfg.synthetic,
            interventions_enabled=True,
        ),
    )


def run_causal_diagnostic(cfg: RSJEPAConfig) -> CausalReport:
    """Measure action exogeneity and causal response on generated Phase A data."""
    data = SyntheticHospitalSimulator(cfg.synthetic).generate().temporal
    y_staff = data["criticality"].to_numpy(dtype=float)
    x_staff = np.column_stack(
        [
            data["occupancy_ratio"].to_numpy(dtype=float),
            data["inflow_surge"].to_numpy(dtype=float),
            data["staffing_delta"].to_numpy(dtype=float),
        ]
    )
    staffing_effect = _ols_last_feature(x_staff, y_staff)

    occ_next_parts = []
    crit_next_parts = []
    discharge_x_parts = []
    for _site_id, group in data.groupby("site_id", sort=True):
        group = group.sort_values("timestamp")
        if len(group) < 2:
            continue
        discharge_x_parts.append(
            np.column_stack(
                [
                    group["occupancy_ratio"].to_numpy(dtype=float)[:-1],
                    group["inflow_surge"].to_numpy(dtype=float)[:-1],
                    group["discharge_delta"].to_numpy(dtype=float)[:-1],
                ]
            )
        )
        occ_next_parts.append(group["occupancy_ratio"].to_numpy(dtype=float)[1:])
        crit_next_parts.append(group["criticality"].to_numpy(dtype=float)[1:])
    discharge_x = np.concatenate(discharge_x_parts, axis=0)
    occ_next = np.concatenate(occ_next_parts, axis=0)
    crit_next = np.concatenate(crit_next_parts, axis=0)
    discharge_occupancy_effect = _ols_last_feature(discharge_x, occ_next)
    discharge_criticality_effect = _ols_last_feature(discharge_x, crit_next)

    staffing_delta = data["staffing_delta"].to_numpy(dtype=float)
    discharge_delta = data["discharge_delta"].to_numpy(dtype=float)
    surge = data["inflow_surge"].to_numpy(dtype=float)
    occupancy = data["occupancy_ratio"].to_numpy(dtype=float)
    corr_staffing_surge = _corr(staffing_delta, surge)
    corr_staffing_occupancy = _corr(staffing_delta, occupancy)
    corr_discharge_surge = _corr(discharge_delta, surge)
    corr_discharge_occupancy = _corr(discharge_delta, occupancy)

    max_abs_corr = max(
        abs(corr_staffing_surge),
        abs(corr_staffing_occupancy),
        abs(corr_discharge_surge),
        abs(corr_discharge_occupancy),
    )
    verdict_green = (
        staffing_effect.coefficient < 0.0
        and staffing_effect.t_stat < -2.0
        and discharge_occupancy_effect.coefficient < 0.0
        and discharge_occupancy_effect.t_stat < -2.0
        and discharge_criticality_effect.coefficient < 0.0
        and discharge_criticality_effect.t_stat < -2.0
        and max_abs_corr < 0.05
    )
    return CausalReport(
        staffing_effect=staffing_effect,
        discharge_occupancy_effect=discharge_occupancy_effect,
        discharge_criticality_effect=discharge_criticality_effect,
        corr_staffing_surge=corr_staffing_surge,
        corr_staffing_occupancy=corr_staffing_occupancy,
        corr_discharge_surge=corr_discharge_surge,
        corr_discharge_occupancy=corr_discharge_occupancy,
        verdict_green=verdict_green,
    )


def _ols_last_feature(x: np.ndarray, y: np.ndarray) -> RegressionResult:
    design = np.column_stack([np.ones(x.shape[0]), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    residual = y - design @ beta
    dof = max(design.shape[0] - design.shape[1], 1)
    sigma2 = float((residual @ residual) / dof)
    xtx_inv = np.linalg.pinv(design.T @ design)
    se = float(np.sqrt(max(sigma2 * xtx_inv[-1, -1], 1e-18)))
    coefficient = float(beta[-1])
    return RegressionResult(coefficient=coefficient, t_stat=coefficient / se)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if float(np.std(a)) == 0.0 or float(np.std(b)) == 0.0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prouve la causalité des actions exogènes.")
    parser.add_argument("--config", default="configs/phaseA.yaml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = config_with_interventions(load_config(args.config))
    report = run_causal_diagnostic(cfg)
    print("=== ACTION CAUSALITY DIAGNOSTIC ===")
    print(
        "staffing_delta -> criticality | "
        f"coef={report.staffing_effect.coefficient:.4f} "
        f"t={report.staffing_effect.t_stat:.2f}"
    )
    print(
        "discharge_delta -> occupancy[t+1] | "
        f"coef={report.discharge_occupancy_effect.coefficient:.4f} "
        f"t={report.discharge_occupancy_effect.t_stat:.2f}"
    )
    print(
        "discharge_delta -> criticality[t+1] | "
        f"coef={report.discharge_criticality_effect.coefficient:.4f} "
        f"t={report.discharge_criticality_effect.t_stat:.2f}"
    )
    print(
        "corr(action,state) | "
        f"staff~surge={report.corr_staffing_surge:.4f} "
        f"staff~occ={report.corr_staffing_occupancy:.4f} "
        f"discharge~surge={report.corr_discharge_surge:.4f} "
        f"discharge~occ={report.corr_discharge_occupancy:.4f}"
    )
    if report.verdict_green:
        print(
            "[VERT] effet causal du bon signe par canal ET actions décorrélées -> "
            "données prêtes pour ré-entraîner un RS-JEPA actionné (marche 2)"
        )
    else:
        print("[ROUGE] effet absent ou injection non exogène -> ajuster avant marche 2")
    return 0 if report.verdict_green else 1


if __name__ == "__main__":
    raise SystemExit(main())
