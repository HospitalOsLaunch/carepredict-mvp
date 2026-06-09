"""Typed client for the Hospital World Model FastAPI endpoint."""

from __future__ import annotations

import math
from typing import Annotated, Any, Self

import requests
from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorldModelClientError(RuntimeError):
    """Base exception for dashboard API client errors."""


class WorldModelClientUnreachable(WorldModelClientError):
    """Raised when the FastAPI service cannot be reached."""


class WorldModelClientValidationError(WorldModelClientError):
    """Raised when FastAPI returns a request validation error."""


class WorldModelClientServerError(WorldModelClientError):
    """Raised when FastAPI returns a server-side error."""


class ActionStep(BaseModel):
    """Known intervention vector for one future hourly step."""

    model_config = ConfigDict(extra="forbid", strict=True)

    scheduled_admissions: Annotated[int, Field(ge=0, le=200)]
    scheduled_discharges: Annotated[int, Field(ge=0, le=200)]
    staff_redeployments: Annotated[int, Field(ge=0, le=200)]
    scheduled_surgeries: Annotated[int, Field(ge=0, le=200)]
    expected_transfers: Annotated[int, Field(ge=0, le=200)]


class SimulationRequest(BaseModel):
    """Request sent to the Hospital World Model simulation endpoint."""

    model_config = ConfigDict(extra="forbid")

    hospital_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
    service_id: Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]
    history_siips: Annotated[list[float], Field(min_length=24, max_length=720)]
    actions: Annotated[list[ActionStep], Field(min_length=1, max_length=168)]

    @model_validator(mode="after")
    def validate_history_values(self) -> Self:
        """Ensure SIIPS history values are finite and non-negative."""
        for value in self.history_siips:
            if not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError("history_siips values must be finite and non-negative")
        return self


class SimulationStepResult(BaseModel):
    """One simulated future hourly point."""

    model_config = ConfigDict(extra="forbid")

    step_index: int
    predicted_siips: float
    lower_bound: float
    upper_bound: float
    reward: float
    is_critical: bool


class SimulationResponse(BaseModel):
    """Parsed simulation response with point forecasts and intervals."""

    model_config = ConfigDict(extra="forbid")

    status: str
    hospital_id: str
    service_id: str
    model_version: str
    results: list[SimulationStepResult]


class WorldModelClient:
    """Small typed boundary around the CarePredict FastAPI service."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout_seconds: float = 30.0,
    ) -> None:
        """Create a client for a running CarePredict FastAPI service."""
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._session = requests.Session()

    def simulate(self, request: SimulationRequest) -> SimulationResponse:
        """Call ``POST /simulate/hospital-world`` and parse the response."""
        response = self._request(
            "POST",
            "/simulate/hospital-world",
            json=request.model_dump(mode="json"),
        )
        return SimulationResponse.model_validate(response.json())

    def health_check(self) -> bool:
        """Return whether ``GET /health`` responds with HTTP 200."""
        try:
            response = self._session.get(
                f"{self.base_url}/health",
                timeout=self.timeout_seconds,
            )
        except requests.RequestException:
            return False
        return response.status_code == 200

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """Execute one HTTP request and map common failures to typed exceptions."""
        try:
            response = self._session.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise WorldModelClientUnreachable(str(exc)) from exc
        if response.status_code == 422:
            raise WorldModelClientValidationError(response.text)
        if response.status_code >= 500:
            raise WorldModelClientServerError(response.text)
        if response.status_code >= 400:
            raise WorldModelClientError(response.text)
        return response
