"""Lock all choices on development hospitals, then score paired held-out futures."""
import argparse
import gzip
import hashlib
import json
import platform
from pathlib import Path

import joblib
import numpy as np
import sklearn
import torch

from policy import decide, dev_headroom, fit_models, scenarios
from sim import CFG, OUT, PLANS

METHODS = ('fixed', 'simulation', 'direct', 'paired')
NAMES = (['boarding', 'transfer', 'care', 'saturation', 'onset_h', 'committed_hours']
         + [f'{name}_U{i}' for name in ('final_queue', 'release_h', 'final_free') for i in range(4)])
SNAPSHOT = ('beds', 'free', 'dirty', 'cleaning', 'admissions', 'transfers',
            'ready', 'authorised', 'transport_requested')
HERE = Path(__file__).resolve().parent
WEIGHTS = OUT / 'sequence_models.joblib'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, values):
    (OUT / name).write_text(json.dumps(values, indent=2, allow_nan=False) + '\n')


def read(split):
    path = OUT / f'{split}.json'
    if path.exists():
        return json.loads(path.read_text())
    with gzip.open(str(path) + '.gz', 'rt') as stream:
        return json.load(stream)


def score(data, method, models, penalty, fixed):
    rows = []
    for site, case in scenarios(data):
        first, last, morning, noon = decide(site, case, method, models, penalty, fixed)
        rows.append(dict(hospital=site['hospital'], draw=case['draw'], first=first, last=last,
                         actual=case['rows'][last]['full'],
                         initial_actual=case['rows'][first]['full'],
                         noon_actual=case['rows'][last]['future'],
                         morning=None if morning is None else morning.tolist(),
                         noon=None if noon is None else noon.tolist()))
    return rows


def field(rows, name):
    return np.asarray([r[name] for r in rows])


def fit():
    train, dev = read('TRAIN'), read('DEV')
    room = dev_headroom(dev)
    save('dev_headroom.json', room)
    fixed = room['fixed']
    models = fit_models(train)
    calibration = {}
    selected = {}
    fixed_cost = field(score(dev, 'fixed', models, 0, fixed), 'actual').mean(0)
    for method in METHODS[1:]:
        trials = []
        for penalty in (0, 1, 4):
            rows = score(dev, method, models, penalty, fixed)
            mean = field(rows, 'actual').mean(0)
            excess = np.maximum(mean[1:3] - fixed_cost[1:3], 0)
            violation = float((excess / np.maximum(fixed_cost[1:3], 1)).sum())
            trials.append((violation, mean[0], penalty))
        selected[method] = min(trials)[2]
    rows = score(dev, 'paired', models, selected['paired'], fixed)
    for name, truth in [('morning', 'initial_actual'), ('noon', 'noon_actual')]:
        error = np.abs(field(rows, truth) - field(rows, name))
        calibration[name] = np.quantile(error, .90, axis=0, method='higher').tolist()
    joblib.dump(models, WEIGHTS, compress=('xz', 3))
    inputs = [HERE / file for file in ('protocol.json', 'sim.py', 'policy.py', 'representation.py', 'evaluate.py')]
    save('selection.json', dict(fixed=fixed, penalties=selected, absolute_q90=calibration,
                                hashes={p.name: digest(p) for p in inputs + [WEIGHTS]},
                                python=platform.python_version(), sklearn=sklearn.__version__,
                                numpy=np.__version__, torch=torch.__version__))
    print('Locked', selected, digest(OUT / 'selection.json'), flush=True)


def intervals(values):
    return np.quantile(values, [.025, .975], axis=0).tolist()


def compare(actual, hospital, oracle):
    # Paired hospital means; every site has two identical-weight realizations.
    unique = np.unique(hospital)
    group = np.stack([actual[hospital == h].mean(0) for h in unique])
    sites = np.random.default_rng(CFG['seed']).integers(len(group), size=(2000, len(group)))
    sums = group.mean(0)
    best = int(sums[:3, 0].argmin())
    samples = group[sites].mean(1)
    # Re-select the strongest comparator inside every bootstrap sample.
    selected = samples[np.arange(len(samples)), samples[:, :3, 0].argmin(1)]
    candidate = samples[:, 3]
    gain_samples = 100 * (1 - candidate[:, 0] / selected[:, 0])
    guard_delta = sums[3, 1:3] - sums[best, 1:3]
    guard_ci = np.asarray(intervals(candidate[:, 1:3] - selected[:, 1:3])).T
    gain = float(100 * (1 - sums[3, 0] / sums[best, 0]))
    gain_ci = intervals(gain_samples)
    spend_ok = bool(np.all(actual[:, :, 5] == 16))
    return dict(reference=METHODS[best], gain_percent=gain, gain_ci95=gain_ci,
                transfer_delta=guard_delta[0], transfer_ci95=guard_ci[0].tolist(),
                care_delta=guard_delta[1], care_ci95=guard_ci[1].tolist(), equal_commitments=spend_ok,
                hindsight_floor=float(oracle.mean()),
                hindsight_headroom_percent=float(100 * (1 - oracle.mean() / sums[best, 0])),
                pass_gate=bool(gain >= 10 and gain_ci[0] > 0 and max(guard_ci[:, 1]) <= 0 and spend_ok))


def forecast_accuracy(rows, config):
    metrics = {}
    for stage, target in [('morning', 'initial_actual'), ('noon', 'noon_actual')]:
        truth, prediction = field(rows, target), field(rows, stage)
        error = np.abs(truth - prediction)
        metrics[stage] = dict(mae=dict(zip(NAMES, error.mean(0))),
                              coverage90=dict(zip(NAMES, (error <= config['absolute_q90'][stage]).mean(0))),
                              brier=float(((truth[:, 3] - prediction[:, 3]) ** 2).mean()),
                              saturation_rate=float(truth[:, 3].mean()))
    return metrics


def per_unit(snapshot):
    n = len(SNAPSHOT)
    return {f'U{i}': dict(zip(SNAPSHOT, snapshot[i*n:(i+1)*n])) for i in range(4)}


def replay(data, row, config, models):
    from sim import W, L, advance, apply, outcome, public_forecast
    site = next(s for s in data if s['hospital'] == row['hospital'])
    case = next(c for c in site['cases'] if c['draw'] == row['draw'])
    original, revised = row['first'], row['last']
    # Re-create the public simulation's four-hour projection from the 08h cutoff.
    spec = W.episode(W.n_unit_structure('PLAN48_A_TEST', row['hospital'], 4, regime='fragile',
                         bottlenecks=('cleaning','transport','aval','transfer')), 0)
    spec.theta['lag_min'] = 180
    pre = L.prefix(spec, 56)
    pe = L.public_view(pre, W.Recorder(spec, 0), pre['t0'])[1]
    engine, provider = public_forecast(spec, pe, 10001)
    apply(engine, PLANS[original][0], provider, pre['t0'])
    projection = outcome(advance(engine, provider, 16), engine, pre['t0'])
    def named(values):
        return dict(zip(NAMES, values))
    chosen = case['rows'][revised]
    return dict(hospital=row['hospital'], draw=row['draw'], plan_at_08=PLANS[original],
                plan_after_12=PLANS[revised], public_at_08=per_unit(site['morning']),
                public_at_12=per_unit(chosen['noon']),
                prior_4h_projection=named(projection), later_reconstructed_4h=named(chosen['observed_4h']),
                forecast_48h_at_08=named(row['morning']), forecast_remaining_44h_at_12=named(row['noon']),
                dev_absolute_q90=config['absolute_q90'],
                actual_48h_initial_plan=named(row['initial_actual']),
                actual_48h_revised_plan=named(row['actual']),
                actual_44h_revised_plan=named(row['noon_actual']))


def test():
    config = json.loads((OUT / 'selection.json').read_text())
    for name, checksum in config['hashes'].items():
        path = WEIGHTS if name == WEIGHTS.name else HERE / name
        if digest(path) != checksum:
            raise ValueError(f'Frozen input changed: {name}')
    models = joblib.load(WEIGHTS)
    data = read('TEST')
    by_method = {m: score(data, m, models, config['penalties'].get(m, 0), config['fixed'])
                 for m in METHODS}
    actual = np.stack([field(by_method[m], 'actual') for m in METHODS], axis=1)
    hospital = field(by_method['paired'], 'hospital')
    oracle = np.array([min(r['full'][0] for r in c['rows']) for _, c in scenarios(data)])
    verdict = compare(actual, hospital, oracle)
    rows = by_method['paired']
    old = field(rows, 'initial_actual')
    revised = field(rows, 'actual')
    changed = [r for r in rows if r['first'] != r['last']]
    result = dict(independent_hospitals=len(data), futures=len(rows),
                  sequence_paths=len(rows)*len(PLANS),
                  frozen_selection_sha256=digest(OUT / 'selection.json'),
                  verdict=verdict,
                  means={m: dict(zip(NAMES, actual[:, i].mean(0))) for i, m in enumerate(METHODS)},
                  noon_revisions=len(changed), open_loop_means=dict(zip(NAMES, old.mean(0))),
                  noon_revised_minus_open_loop=dict(zip(NAMES, (revised - old).mean(0))),
                  forecast=forecast_accuracy(rows, config))
    save('result.json', result)
    save('decisions.json', by_method)
    save('replay.json', replay(data, (changed or rows)[0], config, models))
    print(json.dumps(verdict, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['fit','test'])
    if parser.parse_args().stage == 'fit':
        fit()
    else:
        test()
