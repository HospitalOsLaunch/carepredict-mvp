"""Learn paired intervention effects and test a care-constrained decision rule."""
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import torch
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "filter_pipeline"))
from common import ROOT, W, L, structure, laws, provider, extended, PROTO
from consequences import project
from correction import choices
from longitudinal import graph_inputs
from jepa_stage import Model, tensor
from review_metrics import monthly_resource_plan
from hospitalos.howmint.features import schedule

CONFIG = json.loads(Path(__file__).with_name("protocol.json").read_text())
OUT = Path("evidence/action_effects")


def load_models():
    ensemble = []
    for seed in PROTO["model_seeds"]:
        checkpoint = torch.load(ROOT / "jepa" / f"physical_{seed}.pt", weights_only=True)
        model = Model()
        model.load_state_dict(checkpoint["model"])
        ensemble.append(model.eval())
    with (ROOT / "filter_models.pkl").open("rb") as stream:
        filters = pickle.load(stream)
    enabled = json.loads((ROOT / "filter_selection.json").read_text())["enabled"]
    return ensemble, filters, enabled


@torch.no_grad()
def public_features(spec, pe, ps, actions, ensemble, filters, enabled):
    particles = []
    for draw in range(20001, 20005):
        engine = extended(pe, ps, laws(180), draw, provider(spec, pe.tick, draw),
                          filters, enabled)
        particles.append(graph_inputs(engine, spec, 0))
    averaged = [np.mean(arrays, axis=0) for arrays in zip(*particles)]
    inputs = {key: tensor(np.stack([value] * len(actions)))
              for key, value in zip(("unit", "res", "glob", "uu"), averaged)}
    plans = [schedule([a], spec.units, pe.tick, 4, 6, spec.drop, step_h=6)["R"]
             for a in actions]
    inputs["R"] = tensor(monthly_resource_plan(np.stack(plans)))
    hours = np.arange(4) * 6
    clock = np.stack([np.sin(hours * np.pi/12), np.cos(hours * np.pi/12),
                      np.zeros(4)], axis=-1)
    inputs["clock"] = tensor(np.stack([clock] * len(actions)))
    beds = tensor([spec.beds[unit] for unit in spec.units])
    inputs["beds"] = beds.expand(len(actions), -1)
    predictions = []
    for model in ensemble:
        _, wait, care, _ = model(inputs)
        cumulative = torch.stack([(x * beds * 360).sum(-1).cumsum(1)
                                  for x in (wait, care)], dim=-1)
        predictions.append(cumulative[:, [0, 1, 3]].numpy())
    absolute = np.mean(predictions, axis=0)
    effects = absolute[1:] - absolute[:1]
    unit, resource, _, _ = averaged
    features = np.concatenate([unit[:, :15].mean(0), unit[:, :15].max(0),
                               resource.flatten(), effects.flatten()])
    return features, absolute


def generate(split, idx, assets):
    base = structure(CONFIG["partition_prefix"] + "_" + split, idx, 180)
    result = []
    for episode in range(CONFIG["episodes_per_structure"]):
        spec = W.episode(base, episode)
        prefix = L.prefix(spec, CONFIG["prefix_hours"])
        engine, _, recorder = L.start_future(prefix, spec, 1)
        ps, pe = L.public_view(prefix, recorder, engine.tick)
        actions = choices(pe, spec.units, pe.tick, pe.tick + 96)
        assert [a["kind"] for a in actions] == ["none", "cl", "tr"]
        assert [a["staff_hours"] for a in actions] == [0, 16, 16]
        x, baseline = public_features(spec, pe, ps, actions, *assets)
        outcomes = []
        for draw in CONFIG["truth_draws"]:
            branches = []
            for action in actions:
                state, future, _ = L.start_future(prefix, spec, draw)
                scores = project(state, future, action, refresh=False)
                assert all(s["rejected"] == 0 for s in scores.values())
                branches.append([[scores[h][k] for k in ("wait_patient_min", "uncovered_care_min")]
                                 for h in CONFIG["horizons"]])
            outcomes.append(branches)
        truth = np.mean(outcomes, axis=0)
        np.testing.assert_equal(truth[:, 0], np.repeat(truth[:1, 0], 3, axis=0))
        result.append(dict(split=split, hospital=idx, episode=episode,
                           features=x.tolist(), baseline=baseline.tolist(), truth=truth.tolist()))
    return result


def arrays(rows):
    x = np.asarray([r["features"] for r in rows])
    truth = np.asarray([r["truth"] for r in rows])
    return x, (truth[:, 1:] - truth[:, :1]).reshape(len(x), -1)


def predict(x, scale, model):
    result = model.predict(scale.transform(x)).reshape(len(x), 2, 3, 2)
    result[:, :, 0] = 0  # Both interventions begin six hours after the decision.
    return result


def fit(train, dev):
    x, y = arrays(train)
    dx, dy = arrays(dev)
    scale = StandardScaler().fit(x)
    unit = np.maximum(1., np.abs(y).mean(axis=0))
    trials = []
    for alpha in (1, 10, 100):
        model = Ridge(alpha=alpha).fit(scale.transform(x), y)
        error = predict(dx, scale, model).reshape(dy.shape) - dy
        trials.append((float(np.mean(np.abs(error) / unit)), alpha, model))
    score, alpha, model = min(trials, key=lambda t: t[0])
    return scale, model, dict(alpha=alpha, development_loss=score, mean=scale.mean_.tolist(),
                              scale=scale.scale_.tolist(), coef=model.coef_.tolist(),
                              intercept=model.intercept_.tolist())


def action_choice(values, guard=False, fixed=False):
    allowed = [1, 2] if fixed else [0, 1, 2]
    if guard:
        allowed = [a for a in allowed if values[a, 1] <= 0]
    return min(allowed, key=lambda a: (round(float(values[a, 0]), 6), a))


def evaluate(rows, effects):
    decisions = []
    errors = []
    for row, predicted in zip(rows, effects):
        base = np.asarray(row["baseline"])
        baseline = base - base[:1]
        paired = np.concatenate([np.zeros((1, 3, 2)), predicted])
        truth = np.asarray(row["truth"])
        for h, hours in enumerate(CONFIG["horizons"]):
            target = truth[1:, h] - truth[0, h]
            errors.append(dict(hospital=row["hospital"], horizon=hours, **{
                name: np.abs(pred - target).mean(0).tolist() for name, pred in
                [('paired', predicted[:, h]), ('baseline', baseline[1:, h]), ('zero', 0.)]}))
            policies = dict(baseline=action_choice(baseline[:, h]),
                            baseline_guard=action_choice(baseline[:, h], guard=True),
                            wait_only=action_choice(paired[:, h]),
                            care_guard=action_choice(paired[:, h], guard=True),
                            fixed_baseline=action_choice(baseline[:, h], fixed=True),
                            fixed_paired=action_choice(paired[:, h], fixed=True), none=0)
            for name, action in policies.items():
                decisions.append(dict(hospital=row["hospital"], episode=row["episode"],
                                      horizon=hours, policy=name, action=action,
                                      wait=truth[action, h, 0], care=truth[action, h, 1],
                                      staff=float(action != 0)*16))
    return decisions, errors


def analyse(decisions, errors):
    import pandas as pd
    df = pd.DataFrame(decisions)
    summary = df.groupby(["horizon", "policy"])[["wait", "care", "staff"]].mean()
    comparisons = []
    for h in CONFIG["horizons"]:
        frame = df[df.horizon == h]
        for candidate, reference in [('care_guard','baseline'), ('care_guard','baseline_guard'),
                                     ('care_guard','wait_only'), ('fixed_paired','fixed_baseline')]:
            for metric in ('wait','care','staff'):
                pivot = frame.pivot(index=['hospital','episode'],columns='policy',values=metric)
                delta = (pivot[candidate]-pivot[reference]).groupby('hospital').mean().to_numpy()
                rng = np.random.default_rng(20261120)
                ci = np.quantile(rng.choice(delta,(2000,len(delta))).mean(1),[.025,.975])
                comparisons.append(dict(horizon=h, candidate=candidate, reference=reference,
                                        metric=metric, delta=delta.mean(), ci95=ci.tolist()))
    mae = {str(h):{m:np.mean([r[m] for r in errors if r["horizon"]==h],0).tolist()
                   for m in ('paired','baseline','zero')} for h in CONFIG["horizons"]}
    return dict(means=summary.reset_index().to_dict('records'), comparisons=comparisons, effect_mae=mae)


def main():
    torch.set_num_threads(1)
    OUT.mkdir(exist_ok=True,parents=True)
    assets = load_models()
    def dataset(split):
        return [row for idx in range(CONFIG[split.lower() + '_structures'])
                for row in generate(split, idx, assets)]
    train, dev = dataset('TRAIN'), dataset('DEV')
    scale, model, frozen = fit(train, dev)
    (OUT/'effect_model.json').write_text(json.dumps(frozen))
    test = dataset('TEST')
    effects = predict(arrays(test)[0], scale, model)
    decisions, errors = evaluate(test, effects)
    for name, data in [('examples',train+dev+test), ('decisions',decisions),
                       ('test_effects',effects.tolist()), ('summary',analyse(decisions,errors))]:
        (OUT/(name+'.json')).write_text(json.dumps(data)+'\n')


if __name__ == '__main__':
    main()
