"""Refit the published action-effect estimator from cached public features and paired labels."""

import argparse
import gzip
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler


def refit(examples, alpha):
    """Reuse the validation-selected alpha; only training rows contribute to the fit."""
    train = [row for row in examples if row["split"] == "TRAIN"]
    features = np.asarray([row["features"] for row in train])
    outcomes = np.asarray([row["truth"] for row in train])
    effects = outcomes[:, 1:] - outcomes[:, :1]
    scale = StandardScaler().fit(features)
    model = Ridge(alpha=alpha).fit(scale.transform(features), effects.reshape(len(train), -1))
    return {
        "alpha": alpha,
        "mean": scale.mean_.tolist(),
        "scale": scale.scale_.tolist(),
        "coef": model.coef_.tolist(),
        "intercept": model.intercept_.tolist(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=Path, required=True, help="Archived examples.json.gz")
    parser.add_argument("--output", type=Path, required=True, help="New JSON checkpoint")
    args = parser.parse_args()
    with gzip.open(args.examples, "rt") as stream:
        examples = json.load(stream)
    evidence = Path(__file__).resolve().parents[2] / "evidence" / "action_effects"
    alpha = json.loads((evidence / "effect_model.json").read_text())["alpha"]
    weights = refit(examples, alpha)
    with args.output.open("x") as stream:
        json.dump(weights, stream, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
