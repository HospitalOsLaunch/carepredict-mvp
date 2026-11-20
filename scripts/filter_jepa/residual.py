"""Residual GraphWM: fresh trajectory evaluation, ten chronological train/forecast rounds."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch

from cohort import BEDS, EYE, filter_reports, rounds, simulate, transitions
from run import DailyInputs, Experiment, forecast, tensor, train_block


class ResidualInputs(DailyInputs):
    def __init__(self, probabilities, days, schedule):
        super().__init__(probabilities, days, schedule)
        self.kernels = tensor(np.array([[transitions(day, u, schedule[i], nominal=True)
                                        for u in range(2)] for i, day in enumerate(days)]))

    def nominal(self, origins, horizon):
        state = self.unit[origins][..., [3, 4, 6]]
        result = []
        for offset in range(1, horizon+1):
            kernel = self.kernels[origins+offset]
            state = torch.einsum("bui,buij->buj", state, kernel)
            result.append(state)
        return torch.stack(result, 1)

    def rollout(self, model, origins, horizon):
        correction, latent, future = super().rollout(model, origins, horizon)
        prior = self.nominal(origins, horizon)
        result = torch.softmax(prior.clamp_min(1e-6).log() + correction.clamp_min(1e-6).log(), -1)
        return result, latent, future


def dataset(seed):
    days, schedule, states, reports = simulate(seed)
    probabilities, _ = filter_reports(days, schedule, reports)
    return days, ResidualInputs(probabilities, days, schedule), tensor(EYE[states].mean(2))


def run(out):
    torch.set_num_threads(1)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for train_seed, test_seed in [(101, 1001), (103, 1003), (107, 1007)]:
        days, train, truth = dataset(train_seed)
        _, test, test_truth = dataset(test_seed)
        for variant in ("residual", "residual_jepa"):
            torch.manual_seed(train_seed)
            model = Experiment()
            torch.nn.init.zeros_(model.graph.head_beds.weight)
            torch.nn.init.zeros_(model.graph.head_beds.bias)
            optimizer = torch.optim.AdamW(model.parameters(), lr=.002)
            rng = np.random.default_rng(train_seed)
            for round_id, (lo, cut, end) in enumerate(rounds(days), 1):
                train_block(model, optimizer, train, truth, lo, cut, rng, variant=="residual_jepa")
                predicted, _ = forecast(model, test, cut, end)
                baseline = test.nominal(np.array([cut-1]), end-cut)[0]
                actual = test_truth[cut:end]
                for horizon in (1, 7, 30):
                    k = min(horizon, end-cut)
                    rows.append(dict(train_seed=train_seed,test_seed=test_seed,variant=variant,
                                     round=round_id,horizon=k,
                                     mae=float((predicted[k-1,:,1]-actual[k-1,:,1]).abs().mean()*BEDS),
                                     baseline_mae=float((baseline[k-1,:,1]-actual[k-1,:,1]).abs().mean()*BEDS)))
                rows.append(dict(train_seed=train_seed,test_seed=test_seed,variant=variant,
                                 round=round_id,horizon="month",
                                 mae=float((predicted[...,1]-actual[...,1]).abs().mean()*BEDS),
                                 baseline_mae=float((baseline[...,1]-actual[...,1]).abs().mean()*BEDS)))
            torch.save(model.state_dict(),out/f"{variant}_{train_seed}.pt")
    (out/"metrics.json").write_text(json.dumps(rows,indent=2)+"\n")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    run(p.parse_args().out)
