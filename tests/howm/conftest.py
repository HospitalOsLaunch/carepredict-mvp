from __future__ import annotations

import pytest

from hospitalos.howm.b0 import fit_pool
from hospitalos.howm.dataset import build
from hospitalos.howm.generator import establishment, generate


@pytest.fixture(scope="session")
def train_eps():
    return [generate(establishment("TRAIN", i)) for i in range(3)]


@pytest.fixture(scope="session")
def b0p(train_eps):
    return fit_pool(train_eps)


@pytest.fixture(scope="session")
def val_ep():
    return generate(establishment("VAL", 1), keep_instants=True)


@pytest.fixture(scope="session")
def val_est(val_ep):
    return build(val_ep, [40, 60, 100, 120])
