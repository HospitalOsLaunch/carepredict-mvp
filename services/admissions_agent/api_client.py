"""Thin client for the HospitalOS Admissions API, with the ``ingestion`` service account."""

from __future__ import annotations

from typing import Any

import httpx


class ApiError(RuntimeError):
    pass


class HospitalOSClient:
    def __init__(self, http: httpx.Client, email: str, password: str) -> None:
        self.http = http
        self.email = email
        self.password = password
        self.token: str | None = None

    def _headers(self) -> dict[str, str]:
        if self.token is None:
            self.login()
        return {"Authorization": f"Bearer {self.token}"}

    def login(self) -> None:
        r = self.http.post("/api/auth/login", json={"email": self.email, "password": self.password})
        if r.status_code != 200:
            raise ApiError(f"connexion à HospitalOS refusée ({r.status_code})")
        self.token = r.json()["token"]

    def _call(self, method: str, path: str, json: Any = None) -> Any:
        r = self.http.request(method, path, json=json, headers=self._headers())
        if r.status_code == 401:
            self.token = None
            r = self.http.request(method, path, json=json, headers=self._headers())
        if r.status_code >= 400:
            raise ApiError(f"{method} {path} : {r.status_code} {r.text[:300]}")
        return r.json() if r.content else None

    def vocabulary(self) -> dict[str, dict[str, str]]:
        r = self.http.get("/api/vocabulary")
        r.raise_for_status()
        data: dict[str, dict[str, str]] = r.json()
        return data

    def heartbeat(
        self, agent_id: str, version: str, engines: list[dict[str, Any]]
    ) -> dict[str, Any]:
        result: dict[str, Any] = self._call(
            "POST",
            "/api/agent/heartbeat",
            {"agent_id": agent_id, "version": version, "engines": engines},
        )
        return result

    def claim(self, agent_id: str, limit: int = 1) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._call(
            "POST", "/api/agent/tasks/claim", {"agent_id": agent_id, "limit": limit}
        )
        return result

    def attempt(self, task_id: int, **fields: Any) -> None:
        self._call("POST", f"/api/agent/tasks/{task_id}/attempts", fields)

    def complete(
        self,
        task_id: int,
        status: str,
        engine: str | None,
        result: dict[str, Any] | None,
        error: str | None,
    ) -> None:
        self._call(
            "POST",
            f"/api/agent/tasks/{task_id}/complete",
            {"status": status, "engine": engine, "result": result, "error": error},
        )

    def ingest(self, request: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._call("POST", "/api/ingest/requests", request)
        return result

    def request_sync(self) -> dict[str, Any]:
        result: dict[str, Any] = self._call("POST", "/api/agent/sync")
        return result

    def calibration(
        self, engine: str, model: str, convention: str | None, hit_rate: float, trials: int
    ) -> None:
        self._call(
            "POST",
            "/api/agent/calibrations",
            {
                "engine": engine,
                "model": model,
                "convention": convention,
                "hit_rate": hit_rate,
                "trials": trials,
            },
        )
