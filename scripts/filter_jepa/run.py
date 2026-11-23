"""Run from the repository root: python scripts/filter_jepa/run.py --seed 11 --out results/11"""
import argparse
import copy
import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from hospitalos.howmint.models import GraphWM
from cohort import BEDS, EYE, UNITS, calendar, filter_reports, rounds, simulate

WIDTH = 24
UPDATES = 24
JEPA_WEIGHT = .15


def tensor(x):
    return torch.as_tensor(x, dtype=torch.float32)


class Experiment(nn.Module):
    def __init__(self):
        super().__init__()
        self.graph = GraphWM(WIDTH)
        self.predictor = nn.Linear(WIDTH, WIDTH)
        self.target_unit = copy.deepcopy(self.graph.unit_enc).requires_grad_(False)
        self.target_global = copy.deepcopy(self.graph.glob_enc).requires_grad_(False)

    @torch.no_grad()
    def update_target(self):
        for source, target in [(self.graph.unit_enc, self.target_unit),
                               (self.graph.glob_enc, self.target_global)]:
            for p, q in zip(source.parameters(), target.parameters(), strict=True):
                q.lerp_(p, .02)

    def encode_target(self, unit, glob):
        return torch.tanh(self.target_unit(unit) + self.target_global(glob).unsqueeze(-2))


class DailyInputs:
    """Daily adapter for the INT-1 graph. Only bed fractions are supervised here."""
    def __init__(self, probabilities, days, schedule):
        fractions = probabilities.mean(axis=2)
        self.unit = torch.zeros(len(days), UNITS, 54)
        self.unit[:, :, 0] = 1.  # capacity in units of 32 beds
        self.unit[:, :, [3, 4, 6]] = tensor(fractions)
        self.calendar = tensor(np.stack([calendar(d) for d in days]))
        self.glob = torch.zeros(len(days), 8)
        self.glob[:, :3] = self.calendar
        self.schedule = tensor(schedule)

    def rollout(self, model, origins, horizon):
        future = origins[:, None] + 1 + np.arange(horizon)
        batch = len(origins)
        res = torch.zeros(batch, 3, 10)
        res[:, 0, 0] = 1
        res[:, 0, 2] = self.unit[origins, :, 6].mean(1)
        edges = torch.zeros(batch, UNITS, 3)
        edges[:, :, 0] = 1
        resource_plan = torch.zeros(batch, horizon, 3, 3)
        resource_plan[:, :, 0, 0] = self.schedule[future]
        states, _, _, hidden = model.graph(
            self.unit[origins], res, self.glob[origins], edges, torch.zeros(batch, UNITS, UNITS),
            torch.zeros(batch, horizon, UNITS, 3), resource_plan, self.calendar[future],
            torch.full((batch, UNITS), BEDS), return_latents=True)
        return states[..., :3], model.predictor(hidden), future


def train_block(model, opt, inputs, truth, lo, cut, rng, use_jepa):
    model.train()
    for _ in range(UPDATES):
        horizon = int(rng.choice([7, 14, 30, 31]))
        origins = rng.integers(lo, cut-horizon, size=12)
        pred, latent, future = inputs.rollout(model, origins, horizon)
        loss = F.smooth_l1_loss(pred, truth[future], beta=.05)
        if use_jepa:
            with torch.no_grad():
                z = model.encode_target(inputs.unit[future], inputs.glob[future])
            loss = loss + JEPA_WEIGHT * F.mse_loss(latent, z)
        opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.)
        opt.step()
        model.update_target()


@torch.no_grad()
def forecast(model, inputs, cut, end):
    model.eval()
    pred, z, _ = inputs.rollout(model, np.array([cut-1]), end-cut)
    return pred[0], z[0]


def run(seed, out):
    torch.set_num_threads(1)
    out.mkdir(parents=True, exist_ok=True)
    days, schedule, beds, reports = simulate(seed)
    events = np.array([(arrival, *event) for arrival, batch in enumerate(reports)
                       for event in batch], dtype="int16")
    np.savez_compressed(out/"cohort.npz", days=np.array(days, dtype="datetime64[D]"),
                        schedule=schedule.astype("int8"), truth=beds.astype("int8"), reports=events)
    posterior, last = filter_reports(days, schedule, reports)
    labels = EYE[beds]
    truth = tensor(labels.mean(axis=2))
    rows, predictions = [], []
    for variant in ("raw", "filter", "filter_jepa"):
        torch.manual_seed(seed)
        rng = np.random.default_rng(seed+1)
        model = Experiment()
        opt = torch.optim.AdamW(model.parameters(), lr=.002)
        inputs = DailyInputs(last if variant == "raw" else posterior, days, schedule)
        for r, (lo, cut, end) in enumerate(rounds(days), 1):
            train_block(model, opt, inputs, truth, lo, cut, rng, variant == "filter_jepa")
            if r == 1:
                frozen = copy.deepcopy(model)
            pred, z = forecast(model, inputs, cut, end)
            frozen_pred, _ = forecast(frozen, inputs, cut, end)
            actual = truth[cut:end]
            # All scores use the same synthetic outcomes. Nowcast admits new reports daily;
            # the month-ahead forecast above receives none of them.
            def mae(y):
                return float((y[..., 1] - actual[..., 1]).abs().mean() * BEDS)
            with torch.no_grad():
                target = model.encode_target(inputs.unit[cut:end], inputs.glob[cut:end])
                target_var = float(target.flatten(0, 1).var(0, unbiased=False).mean())
            row = dict(seed=seed, variant=variant, round=r, month=str(days[cut])[:7],
                       train_first=str(days[lo]), train_last=str(days[cut-1]), days=end-cut,
                       ready_mae=mae(pred), frozen_round1_mae=mae(frozen_pred),
                       past_mean_mae=mae(truth[lo:cut].mean(0)), persistence_mae=mae(inputs.unit[cut-1:cut, :, [3,4,6]]),
                       state_mae=float((pred-actual).abs().mean()*BEDS),
                       filtering_brier=float(np.square(posterior[cut:end]-labels[cut:end]).sum(-1).mean()),
                       last_report_brier=float(np.square(last[cut:end]-labels[cut:end]).sum(-1).mean()),
                       nowcast_ready_mae=mae(tensor(posterior[cut:end].mean(2))),
                       last_report_ready_mae=mae(tensor(last[cut:end].mean(2))))
            if variant == "filter_jepa":
                row.update(latent_mse=float(F.mse_loss(z, target)), target_variance=target_var)
            rows.append(row)
            for j, day in enumerate(days[cut:end]):
                for u in range(UNITS):
                    predictions.append([seed,variant,r,str(day),u,float(pred[j,u,1]*BEDS),int(round(float(actual[j,u,1]*BEDS)))])
        torch.save(model.state_dict(), out/(variant+".pt"))
    (out/"metrics.json").write_text(json.dumps(rows, indent=2)+"\n")
    with (out/"forecasts.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["seed","variant","round","date","ward","forecast_ready_beds","true_ready_beds"])
        writer.writerows(predictions)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.seed, args.out)
