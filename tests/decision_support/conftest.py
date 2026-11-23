"""Shared synthetic fixtures for the decision-support tests (T01-T32)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from hospitalos.decision_support.contracts import Observation, PublicSnapshot, ScenarioLocks
from hospitalos.decision_support.planner import Settings, recommend, simulate
from hospitalos.decision_support.snapshot import (
    build_snapshot,
    load_fixture_public,
    load_profile,
    snapshot_from_fixture,
)

FX = Path(__file__).resolve().parent / "fixtures"


def fixture_path(name: str) -> Path:
    return FX / name


def snapshot_with(name: str, extra: list[dict], as_of: datetime | None = None) -> PublicSnapshot:
    _, observations, fixture_as_of = load_fixture_public(FX / name)
    observations += [Observation.model_validate(o) for o in extra]
    return build_snapshot(observations, as_of or fixture_as_of, load_profile())


def locks_of(name: str) -> ScenarioLocks:
    return ScenarioLocks.model_validate(json.loads((FX / name).read_text())["locks"])


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.default()


@pytest.fixture(scope="session")
def nominal() -> PublicSnapshot:
    return snapshot_from_fixture(FX / "nominal_auto.json")


@pytest.fixture(scope="session")
def auto(nominal, settings):
    return recommend(nominal, settings)


@pytest.fixture(scope="session")
def manual(nominal, settings):
    return simulate(nominal, locks_of("scenario_x1x2.json"), settings)


# The independent v5 audit tests import their helper as a top-level module
# (``from test_v4_resource_boundaries import ...``); expose this directory without editing them.
import sys as _sys  # noqa: E402

_sys.path.insert(0, str(Path(__file__).resolve().parent))
