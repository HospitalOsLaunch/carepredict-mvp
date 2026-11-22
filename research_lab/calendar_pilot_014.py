"""Exploratory paired decision check on the existing train/development 014 archive."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import re
import zipfile
from pathlib import Path

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from research_lab.future_calendar import CLOCK, MINUTE_NS, calendar_grid

SPEC_HASH = "963b4a8c5db43267b19ac65b2ab68375e34b7221baaa7554cff9629d94b50049"
PLAN_HASH = "a3cb04f996c6e6db7461b8e58099bee6a71816df886b55c166422e965cd6f916"


def future_features(origin_ns: int, step_minutes: int) -> list[float]:
    rows = calendar_grid(origin_ns, 24, step_minutes)
    # The original boosting vector already has the hour of day. Count time, not slots.
    return [*rows[0][2:4], sum(r[4] * r[6] for r in rows), sum(r[5] * r[6] for r in rows)]


def load_pilot(archive: Path):
    with zipfile.ZipFile(archive) as z:
        hashes = json.loads(z.read("SHA256.json"))

        def verified(name: str, sha: str):
            data = z.read(name)
            if hashlib.sha256(data).hexdigest() != sha:
                raise ValueError(f"014 source differs: {name}")
            return data

        spec = json.loads(verified("pilot/SPEC.json", SPEC_HASH))
        plans = json.loads(verified("pilot/PLANS.json", PLAN_HASH))
        base = int(dt.datetime(2025, 1, 1, tzinfo=CLOCK).timestamp()) * 1_000_000_000
        x, k, y, groups, train, candidate = [], [], [], [], [], []
        seeds, episodes = set(), set()
        for plan in sorted(plans, key=lambda p: p["episode_id"]):
            eid = plan["episode_id"]
            split = plan["split"]
            if (
                not re.fullmatch("[a-f0-9]{24}", eid)
                or split not in ("train", "development")
                or eid in episodes
                or plan["physics_seed"] in seeds
            ):
                raise ValueError("014 episode or partition identity invalid")
            episodes.add(eid)
            seeds.add(plan["physics_seed"])
            name = f"pilot/{eid}.json.gz"
            doc = json.loads(gzip.decompress(verified(name, hashes[name])))
            if doc["plan"] != plan or [r["decision_h"] for r in doc["rows"]] != list(
                range(0, 72, 6)
            ):
                raise ValueError("014 episode does not match its decision manifest")
            for row in doc["rows"]:
                if row["episode_id"] != eid or row["split"] != split:
                    raise ValueError("014 row belongs to a different episode")
                origin = base + (24 * plan["calendar_day"] + row["decision_h"]) * 60 * MINUTE_NS
                features = future_features(origin, 30)
                if features != future_features(origin, 60):
                    raise ValueError("Calendar exposure changes with display resolution")
                # Only the original, pre-decision input vector and deterministic K may enter X.
                x.append(row["features"])
                k.append(features)
                labels = row["targets"]["24"]
                delta = labels["treatment"][2] - labels["control"][2]  # urgent queue, patients
                if delta != labels["contrast"][2]:
                    raise ValueError("Mismatched paired target")
                y.append(delta)
                groups.append(eid)
                train.append(split == "train")
                candidate.append(row["action"] != "no_action")
    if len(episodes) != 144 or sum(train) != 864 or len(y) != 1728:
        raise ValueError("Incomplete pilot")
    return spec, *map(np.asarray, (x, k, y, groups, train, candidate))


def run(archive: Path):
    spec, x, k, y, groups, train, candidate = load_pilot(archive)
    evaluate = ~train & candidate
    truth = y[evaluate]
    params = dict(spec["boosting"])
    del params["algorithm"]
    summaries, regrets = {}, []
    with threadpool_limits(limits=1):
        for name, features in (("baseline", x), ("with_calendar", np.column_stack((x, k)))):
            pred = (
                HistGradientBoostingRegressor(**params)
                .fit(features[train], y[train])
                .predict(features[evaluate])
            )
            chosen = pred < 0
            regret = np.where(chosen, truth, 0) - np.minimum(truth, 0)
            informative = truth != 0
            regrets.append(regret)
            summaries[name] = {
                "mean_regret_patients": float(regret.mean()),
                "contrast_mae_patients": float(np.abs(pred - truth).mean()),
                "correct_when_outcomes_differ": int(
                    np.count_nonzero(chosen[informative] == (truth[informative] < 0))
                ),
            }
    # Paired bootstrap of the difference in mean regret, preserving whole episodes.
    clusters, idx = np.unique(groups[evaluate], return_inverse=True)
    sums = np.bincount(idx, weights=regrets[1] - regrets[0])
    counts = np.bincount(idx)
    sample = np.random.default_rng(22112026).integers(len(clusters), size=(2000, len(clusters)))
    diff = sums[sample].sum(axis=1) / counts[sample].sum(axis=1)
    return {
        "scope": "exploratory_development_same_structures",
        "sklearn": sklearn.__version__,
        "train_decisions": int(train.sum()),
        "development_episodes_scored": len(clusters),
        "development_candidate_pairs": len(truth),
        "non_tied_pairs": int(np.count_nonzero(truth)),
        "models": summaries,
        "calendar_minus_baseline_regret_95pct": np.quantile(diff, [0.025, 0.975]).tolist(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    print(json.dumps(run(parser.parse_args().archive), indent=2))
