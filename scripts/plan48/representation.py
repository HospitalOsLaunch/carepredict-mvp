"""Reuse the frozen probabilistic filter and online JEPA encoder from the 5-year run."""
import json
import pickle
from functools import lru_cache

import numpy as np
import torch

from common import ROOT, extended, laws
from jepa_stage import Model, tensor
from longitudinal import graph_inputs


@lru_cache(maxsize=1)
def assets():
    torch.set_num_threads(1)
    model = Model()
    checkpoint = torch.load(ROOT / 'jepa/physical_jepa_11.pt', weights_only=True)
    model.load_state_dict(checkpoint['model'])
    with (ROOT / 'filter_models.pkl').open('rb') as stream:
        filters = pickle.load(stream)
    enabled = json.loads((ROOT / 'filter_selection.json').read_text())['enabled']
    return model.eval(), filters, enabled, laws(180)


@torch.no_grad()
def representation(spec, public_stream, public_state, prior):
    model, filters, enabled, service_laws = assets()
    month = int(spec.start_utc[5:7]) - 1
    inputs = []
    for draw in range(20001, 20005):
        particle = extended(public_state, public_stream, service_laws, draw, prior, filters, enabled)
        unit, _, global_state, _ = graph_inputs(particle, spec, month)
        inputs.append(model.encode(tensor(unit), tensor(global_state)).flatten().numpy())
    return np.mean(inputs, axis=0).tolist()
