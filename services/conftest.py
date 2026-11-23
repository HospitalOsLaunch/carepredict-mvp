"""Shared test isolation for services/.

An MLflow run left active by one test must not leak into the next one: with mlflow installed from
requirements.lock, test_moirai_wrapper failed on "Run ... is already active".
"""

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _no_active_mlflow_run() -> Iterator[None]:
    yield
    try:
        import mlflow
    except ImportError:
        return
    while mlflow.active_run() is not None:
        mlflow.end_run()
