"""Check causal invariants and score the fixed nominal transition model at the same origins."""
import csv
import json
import sys
from pathlib import Path

import numpy as np
from cohort import EYE, filter_reports, rounds, simulate, transitions


def check(root):
    for result in sorted(root.glob("*/metrics.json")):
        seed = int(result.parent.name)
        days, extra, beds, messages = simulate(seed)
        post, _ = filter_reports(days, extra, messages)
        np.testing.assert_allclose(post.sum(-1), 1, atol=1e-10)
        scores = []
        for r, (lo, cut, end) in enumerate(rounds(days), 1):
            assert (days[cut-1]-days[lo]).days >= 148 and 28 <= end-cut <= 31
            # An arbitrary suffix of feedback can be discarded without changing the origin.
            prefix, _ = filter_reports(days[:cut], extra[:cut], messages[:cut])
            np.testing.assert_array_equal(prefix[-1], post[cut-1])
            p = prefix[-1].copy()
            error = []
            for i in range(cut, end):
                for u in range(len(p)):
                    p[u] = p[u] @ transitions(days[i], u, extra[i], nominal=True)
                error.extend(abs(p[..., 1].sum(1) - (beds[i] == 1).sum(1)))
            scores.append({"round":r,"ready_mae":float(np.mean(error))})
        (result.parent/"nominal.json").write_text(json.dumps(scores, indent=2)+"\n")
        with (result.parent/"forecasts.csv").open() as f:
            pred = list(csv.DictReader(f))
        for row in json.loads(result.read_text()):
            vals = [abs(float(p["forecast_ready_beds"]) - int(p["true_ready_beds"])) for p in pred
                    if p["variant"] == row["variant"] and int(p["round"]) == row["round"]]
            assert len(vals) == 2 * row["days"]
            np.testing.assert_allclose(np.mean(vals), row["ready_mae"], atol=1e-5)
    # Out-of-order delivery of an obsolete observation cannot overwrite a newer exact one.
    days, extra, _, _ = simulate(0)
    messages = [[], [(1, 0, 0, 1)], [(0, 0, 0, 2)]]
    a, _ = filter_reports(days[:3], extra[:3], messages)
    np.testing.assert_allclose(a[2,0,0], EYE[1] @ transitions(days[2], 0, extra[2], nominal=True))


if __name__ == "__main__":
    check(Path(sys.argv[1]))
