"""Export public inputs and a separate synthetic event tape from the sealed study.

Usage: python research/balestriero/export_demo.py /absolute/path/to/restored/HospitalOS_Balestriero
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "src/hospitalos/world_model/data"
CASES = (
    ("rives", "Hôpital des Rives", 116004, "full"),
    ("parc", "Centre hospitalier du Parc", 116043, "partial"),
    ("belvedere", "Hôpital du Belvédère", 116013, "delayed"),
)


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(study):
    sys.path[:0] = [str(study), str(study / "base"), str(study / "base/parent")]
    from cf import experience as experiment
    from cible import engine
    from j7.episodes import first_week
    from lot28 import features, simulator

    receipts = json.loads((Path(__file__).with_name("empreintes.json")).read_text())[
        "contrefactuel"
    ]
    experiment.verify_all(*(receipts[k] for k in ("gel", "public", "factuel", "verite")))
    TARGET.mkdir(parents=True, exist_ok=True)
    records = []
    for code, label, site_id, feed in CASES:
        ep = simulator.episode(site_id, 0)
        site = ep.site
        cp = first_week(ep, feed, 7)
        view, grid, actions, physical = experiment.prepare(ep, cp, feed, 4)
        public = experiment.payload(
            experiment.OUT / "public" / experiment.record_name(site_id, 0, feed, 4)
        )
        if str(public["public_view_sha"]) != experiment.view_digest(view) or not np.array_equal(
            grid, public["grid"]
        ):
            raise ValueError("Public case differs from sealed experiment")
        # Remove duplicate calendar effects, starting with the established reference.
        indices = np.r_[0, experiment.alternatives(grid, 0)]
        grid, actions = grid[indices], actions[indices]
        blank = np.zeros((len(grid), 1, site.wards, 9), dtype=np.float32)
        fixed_controls = features.action_features(site, view, grid, blank, 4, (4,))[:, 0]
        morning, *_ = engine._open_noon(ep, 7, feed, 7, cp.state, cp.records[0][-6:], cp.seed)
        public_path = TARGET / f"{code}_public.npz"
        np.savez_compressed(
            public_path,
            initial=view.state,
            drivers=view.forecast[4:8],
            beds=site.beds,
            route=site.route,
            actions=actions,
            schedules=grid[:, :1],
            morning=morning[0],
            state_features=features.state_features(site, view.state),
            controls=fixed_controls,
            base_column=features.public_features(view, site).shape[-1],
        )
        observation = experiment.payload(
            experiment.OUT / "factuel" / experiment.record_name(site_id, 0, feed, 4)
        )
        if str(observation["source_physical_sha"]) != experiment.digest_array(physical) or str(
            observation["world_sha"]
        ) != experiment.digest_array(ep.truth[172:196]):
            raise ValueError("Synthetic event tape or factual source mismatched")
        scenario_path = TARGET / f"{code}_events.npz"
        np.savez_compressed(
            scenario_path, initial=physical, drivers=ep.truth[172:176], mask=observation["mask"][1]
        )
        kinds = {"medecine": "Médecine", "observation_courte": "Observation courte"}
        ward_labels = [f"{kinds[t]} {i + 1}" for i, t in enumerate(site.specialties)]
        records.append(
            {
                "id": code,
                "label": label,
                "feed": feed,
                "site": site_id,
                "episode": 0,
                "wards": ward_labels,
                "published_hour": int(observation["available_hour"][1]) + 8 - 7 * 24,
                "public_sha": file_sha(public_path),
                "events_sha": file_sha(scenario_path),
                "public_view_sha": str(public["public_view_sha"]),
            }
        )
    kernel = Path(__file__).resolve().parents[2] / "src/hospitalos/world_model/flow_kernel.cpp"
    weights = TARGET / "jepa_19.npz"
    if file_sha(kernel) != file_sha(study / "base/parent/lot28/flow_kernel.cpp") or file_sha(
        weights
    ) != file_sha(study / "base/parent/run/weights/jepa_19.npz"):
        raise ValueError("Serving kernel or weights differ from release")
    manifest = {
        "version": "J7-CF-2026.11.21",
        "kernel_sha256": file_sha(kernel),
        "weights_sha256": file_sha(weights),
        "source_sha256": experiment.PARENT,
        "public_receipt": receipts["public"],
        "cases": records,
    }
    (TARGET / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    export(parser.parse_args().study.resolve())
