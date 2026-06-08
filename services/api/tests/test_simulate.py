"""Behavioral tests for the Hospital World Model simulation endpoint."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest
import torch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.routers.simulate import get_world_model_service, router
from services.api.schemas.simulate import SimulationResponse
from services.ml.world_model.config import (
    RewardConfig,
    RSSMConfig,
    ServingConfig,
    TrainConfig,
)
from services.ml.world_model.inference import WorldModelService
from services.ml.world_model.rssm import HospitalRSSM
from services.ml.world_model.train import WorldModelTrainer


@pytest.fixture(scope="module")
def trained_service(tmp_path_factory: pytest.TempPathFactory) -> WorldModelService:
    """Train a small RSSM and return a service backed by temporary artifacts."""
    artifact_dir = tmp_path_factory.mktemp("world_model")
    torch.manual_seed(123)
    np.random.seed(123)
    rssm_config = RSSMConfig(obs_dim=1, action_dim=5, deter_dim=16, stoch_dim=8, hidden_dim=32)
    model = HospitalRSSM(rssm_config)
    trainer = WorldModelTrainer(
        model=model,
        reward_config=RewardConfig(p75=1.5, p90=2.5),
        train_config=TrainConfig(lr=1e-3, grad_clip=10.0, batch_size=8, seed=123),
        device=torch.device("cpu"),
    )
    dtype = torch.float32
    device = torch.device("cpu")
    for step in range(50):
        generator = torch.Generator(device=device)
        generator.manual_seed(10_000 + step)
        history_actions = torch.rand(8, 24, 5, generator=generator, device=device, dtype=dtype)
        future_actions = torch.rand(8, 12, 5, generator=generator, device=device, dtype=dtype)
        history_signal = history_actions.sum(dim=-1, keepdim=True) * 0.15
        time_axis = torch.linspace(0.0, 1.0, 24, device=device, dtype=dtype).view(1, 24, 1)
        history_obs = history_signal + time_axis
        future_base = future_actions.sum(dim=-1, keepdim=True) * 0.2 + 1.0
        trainer.train_step(
            {
                "history_obs": history_obs,
                "history_actions": history_actions,
                "future_actions": future_actions,
                "future_siips_targets": future_base,
            }
        )

    checkpoint_path = artifact_dir / "rssm_checkpoint.pt"
    scaler_path = artifact_dir / "siips_scaler.npz"
    residuals_path = artifact_dir / "conformal_residuals.npz"
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "config": model.config_dict(),
            "model_version": "rssm-test-v1",
        },
        checkpoint_path,
    )
    np.savez(scaler_path, mean=np.asarray([100.0]), std=np.asarray([20.0]))
    residuals = np.full((32, 168), 6.0, dtype=np.float64)
    np.savez(
        residuals_path,
        residuals=residuals,
        service_p95_threshold=np.asarray(90.0, dtype=np.float64),
    )
    return WorldModelService.from_artifacts(
        ServingConfig(
            checkpoint_path=str(checkpoint_path),
            scaler_path=str(scaler_path),
            calibration_residuals_path=str(residuals_path),
            max_history_length=720,
            max_horizon=168,
        )
    )


@pytest.fixture(scope="module")
def client(trained_service: WorldModelService) -> Iterator[TestClient]:
    """Create a test app with dependency-injected world model service."""
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_world_model_service] = lambda: trained_service
    with TestClient(app) as test_client:
        yield test_client


def _action(value: int) -> dict[str, int]:
    return {
        "scheduled_admissions": value,
        "scheduled_discharges": 0,
        "staff_redeployments": 0,
        "scheduled_surgeries": value,
        "expected_transfers": 0,
    }


def _payload(action_value: int = 1, horizon: int = 12) -> dict[str, object]:
    return {
        "hospital_id": "hosp-001",
        "service_id": "urg-001",
        "history_siips": [100.0 + float(index % 6) for index in range(48)],
        "actions": [_action(action_value) for _ in range(horizon)],
    }


def test_response_schema(client: TestClient) -> None:
    response = client.post("/simulate/hospital-world", json=_payload())
    assert response.status_code == 200
    parsed = SimulationResponse.model_validate(response.json())
    assert parsed.status == "ok"
    assert len(parsed.results) == 12
    for result in parsed.results:
        assert result.lower_bound <= result.predicted_siips <= result.upper_bound


def test_determinism(client: TestClient) -> None:
    torch.manual_seed(777)
    first = client.post("/simulate/hospital-world", json=_payload()).json()
    torch.manual_seed(777)
    second = client.post("/simulate/hospital-world", json=_payload()).json()
    first_predictions = [item["predicted_siips"] for item in first["results"]]
    second_predictions = [item["predicted_siips"] for item in second["results"]]
    assert first_predictions == second_predictions


def test_history_too_short(client: TestClient) -> None:
    payload = _payload()
    payload["history_siips"] = [1.0 for _ in range(10)]
    assert client.post("/simulate/hospital-world", json=payload).status_code == 422


def test_history_too_long(client: TestClient) -> None:
    payload = _payload()
    payload["history_siips"] = [1.0 for _ in range(1000)]
    assert client.post("/simulate/hospital-world", json=payload).status_code == 422


def test_horizon_too_long(client: TestClient) -> None:
    payload = _payload(horizon=200)
    assert client.post("/simulate/hospital-world", json=payload).status_code == 422


def test_invalid_hospital_id(client: TestClient) -> None:
    payload = _payload()
    payload["hospital_id"] = "Hosp_001"
    assert client.post("/simulate/hospital-world", json=payload).status_code == 422


def test_critical_flag_monotone(client: TestClient) -> None:
    response = client.post("/simulate/hospital-world", json=_payload(action_value=120, horizon=24))
    assert response.status_code == 200
    assert any(item["is_critical"] for item in response.json()["results"])


def test_conformal_coverage_shape(client: TestClient) -> None:
    response = client.post("/simulate/hospital-world", json=_payload())
    assert response.status_code == 200
    for item in response.json()["results"]:
        assert item["upper_bound"] - item["lower_bound"] > 0.0
