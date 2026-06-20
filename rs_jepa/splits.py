"""Cross-site and temporal split utilities for RS-JEPA validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from rs_jepa.config import SplitConfig

TRAIN = "train"
TEMPORAL_VAL = "temporal_val"
CROSS_SITE_VAL = "cross_site_val"


@dataclass(frozen=True)
class SplitSummary:
    train_sites: tuple[str, ...]
    cross_site_val_sites: tuple[str, ...]
    temporal_holdout_start: pd.Timestamp
    temporal_holdout_weeks: int


def require_monotonic_by_site(frame: pd.DataFrame) -> None:
    """Reject shuffled rows; temporal validation assumes ordered site histories."""

    required = {"site_id", "timestamp"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Colonnes de split manquantes: {sorted(missing)}")
    for site_id, group in frame.groupby("site_id", sort=False):
        if not group["timestamp"].is_monotonic_increasing:
            raise ValueError(
                "Split aléatoire refusé: les timestamps doivent rester croissants "
                f"dans chaque site (site={site_id})."
            )


def choose_cross_site_validation_sites(site_ids: Iterable[str], cfg: SplitConfig) -> tuple[str, ...]:
    sites = np.array(sorted(set(site_ids)))
    if len(sites) < 2:
        raise ValueError("Le split cross-site exige au moins deux sites.")
    rng = np.random.default_rng(cfg.seed)
    order = rng.permutation(len(sites))
    n_val = max(1, int(round(len(sites) * cfg.cross_site_val_fraction)))
    return tuple(sorted(sites[order[:n_val]].tolist()))


def add_validation_splits(frame: pd.DataFrame, cfg: SplitConfig) -> tuple[pd.DataFrame, SplitSummary]:
    """Attach train / temporal hold-out / unseen-site labels without row shuffling."""

    require_monotonic_by_site(frame)
    out = frame.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=False)
    val_sites = choose_cross_site_validation_sites(out["site_id"].unique(), cfg)
    train_sites = tuple(sorted(set(out["site_id"].unique()) - set(val_sites)))
    max_ts = out["timestamp"].max()
    holdout_start = max_ts - pd.Timedelta(weeks=cfg.temporal_holdout_weeks) + pd.Timedelta(hours=1)
    out["split"] = TRAIN
    out.loc[out["site_id"].isin(val_sites), "split"] = CROSS_SITE_VAL
    temporal_mask = out["site_id"].isin(train_sites) & (out["timestamp"] >= holdout_start)
    out.loc[temporal_mask, "split"] = TEMPORAL_VAL
    summary = SplitSummary(
        train_sites=train_sites,
        cross_site_val_sites=val_sites,
        temporal_holdout_start=holdout_start,
        temporal_holdout_weeks=cfg.temporal_holdout_weeks,
    )
    validate_split_frame(out, summary)
    return out, summary


def validate_split_frame(frame: pd.DataFrame, summary: SplitSummary) -> None:
    """Validate the two first-class validation axes: unseen sites and held-out period."""

    train_site_set = set(summary.train_sites)
    cross_site_set = set(summary.cross_site_val_sites)
    if train_site_set & cross_site_set:
        raise ValueError("Fuite cross-site: un site est à la fois train et validation.")
    train_rows = frame[frame["split"] == TRAIN]
    if not train_rows.empty and (train_rows["timestamp"] >= summary.temporal_holdout_start).any():
        raise ValueError("Fuite temporelle: des lignes train tombent dans le hold-out.")
    temporal_rows = frame[frame["split"] == TEMPORAL_VAL]
    if not temporal_rows.empty and (temporal_rows["timestamp"] < summary.temporal_holdout_start).any():
        raise ValueError("Hold-out temporel invalide: lignes trop anciennes en validation.")
    cross_rows = frame[frame["split"] == CROSS_SITE_VAL]
    if set(cross_rows["site_id"].unique()) - cross_site_set:
        raise ValueError("Fuite cross-site: lignes de validation hors sites réservés.")
