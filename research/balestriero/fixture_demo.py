"""Generate the synthetic CI reference using only the signed research-stage records.

From the repository root, supply the restored HospitalOS Balestriero study:

    python research/balestriero/fixture_demo.py --study /path/to/study --output /tmp/h4.json
    cmp /tmp/h4.json tests/world_model/fixtures/balestriero_h4.json

This file and its generated fixture are independent of the serving model.
"""

import argparse
import json
from hashlib import file_digest
from pathlib import Path

import numpy as np

ANCHORS = {
    "public": "b4b287c16940c22899fa2cf0daba3e838b9a70418955451861634dcd5a5fa2bc",
    "factuel": "a5e5a7a28b0077193017e22aef261807c8ba68971e2d9c23eae380833e85b200",
    "verite": "100f06fc7416b7df70605a6bb24d737c00a126b7d21539298c17c464699f3f4f",
}
CASES = {
    "rives": (116004, "full"),
    "parc": (116043, "partial"),
    "belvedere": (116013, "delayed"),
}


def sha256(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def load_stages(study, name):
    root = study / "cf/resultats"
    data, hashes = {}, {}
    previous = None
    for stage, anchor in ANCHORS.items():
        receipt_path = root / f"recu_{stage}.json"
        if sha256(receipt_path) != anchor:
            raise ValueError(f"Unrecognised {stage} receipt")
        receipt = json.loads(receipt_path.read_text())
        record = root / stage / name
        digest = sha256(record)
        if receipt["parent"] != previous or receipt["files"][name] != digest:
            raise ValueError(f"Research record differs from the committed {stage} stage")
        hashes[stage] = digest
        with np.load(record, allow_pickle=False) as archive:
            data[stage] = dict(archive)
        previous = anchor
    if (
        str(data["factuel"]["public_sha"]) != hashes["public"]
        or str(data["verite"]["public_sha"]) != hashes["public"]
        or str(data["verite"]["factual_sha"]) != hashes["factuel"]
        or str(data["verite"]["world_sha"]) != str(data["factuel"]["world_sha"])
    ):
        raise ValueError("Public, measured and alternative records do not describe the same case")
    return data, hashes


def unique_plans(grid):
    # At noon different labels can describe the same commissioned calendar.
    representatives = {}
    for i, schedule in enumerate(grid):
        representatives.setdefault(schedule.tobytes(), i)
    return list(representatives.values())


def option_id(triple):
    kind, ward, _donor = triple
    if kind == 0:
        return "reference"
    family = {4: "transport", 5: "cleaning"}[int(kind)]
    return f"{family}-u{ward + 1}"


def stock(census):
    return census[..., 2] + census[..., 4]


def rounded(values):
    return np.round(values, decimals=10).tolist()


def project_beds(values, beds):
    """Independent bisection, using the capacity and the monotone occupancy equation."""
    positive = np.maximum(values, 0.0)
    if not len(positive) or positive.sum() <= beds:
        return positive
    lo, hi = 0.0, positive.max()
    for _ in range(70):
        midpoint = (lo + hi) / 2
        if np.maximum(values - midpoint, 0.0).sum() > beds:
            lo = midpoint
        else:
            hi = midpoint
    return np.maximum(values - hi, 0.0)


def reconstruct_stocks(forecasts, selected, report, mask, capacities):
    shifts = np.where(mask, report - forecasts[selected], 0.0)
    counts = np.empty(forecasts.shape[:2])
    for action, priors in enumerate(forecasts):
        for ward, prior in enumerate(priors):
            adjusted = prior[1:] + shifts[ward, 1:]
            known = mask[ward, 1:] if action == selected else np.zeros(4, dtype=bool)
            reconciled = np.empty(4)
            reconciled[known] = report[ward, 1:][known]
            available = max(0.0, capacities[ward] - reconciled[known].sum())
            reconciled[~known] = project_beds(adjusted[~known], available)
            counts[action, ward] = reconciled[1] + reconciled[3]
    return counts


def make_case(study, site, feed):
    name = f"{site}_0_{feed}_4.npz"
    records, hashes = load_stages(study, name)
    public, measured, truth = (records[k] for k in ("public", "factuel", "verite"))
    (h,) = np.flatnonzero(public["horizons"] == 4)
    if int(public["source_hour"]) != 172:
        raise ValueError("Expected a forecast made at noon on day seven")
    grid = public["grid"]
    keep = unique_plans(grid)
    ids = [option_id(public["actions"][i]) for i in keep]
    native = public["pred"][0, keep, h]
    jepa = public["pred"][1, keep, h]
    forecasts = {
        key: {"by_ward": rounded(stock(native[i])), "jepa_total": rounded(stock(jepa[i]).sum())}
        for i, key in enumerate(ids)
    }
    factual = int(public["factual"])
    fact_match = next(
        i for i, source in enumerate(keep) if np.array_equal(grid[source], grid[factual])
    )
    mask = measured["mask"][h]
    reference_or_first = 0 if fact_match != 0 else 1
    reviews = []
    for selected in (fact_match, reference_or_first):
        report = np.where(mask, truth["states"][keep[selected], h], np.nan)
        if selected == fact_match and not np.array_equal(
            report, measured["reported"][h], equal_nan=True
        ):
            raise ValueError(
                "Committed factual measurement differs from the replayed single branch"
            )
        post = reconstruct_stocks(native, selected, report, mask, public["beds"])
        reviews.append(
            {
                "selected_id": ids[selected],
                "source_is_study_factual": selected == fact_match,
                "observed_by_ward": [rounded(v) if np.isfinite(v) else None for v in stock(report)],
                "reconstructed_by_option": {
                    key: rounded(row) for key, row in zip(ids, post, strict=True)
                },
            }
        )
    return {
        "record": name,
        "hashes": hashes,
        "feed": feed,
        "published_hour": int(measured["available_hour"][h]) + 8 - 7 * 24,
        "options": forecasts,
        "reviews": reviews,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "quantity": "synthetic transfer waiting stock at 16:00 after a noon decision",
        "receipts": ANCHORS,
        "cases": {key: make_case(args.study, *setting) for key, setting in CASES.items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
