"""Thin client for the HospitalOS Admissions API, with the ``ingestion`` service account."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx

from services.admissions_agent.replay import StepRefused


class ApiError(RuntimeError):
    pass


def _reason(response: httpx.Response) -> str:
    """What may be said of an error: the API's own message, or the fields and rules a
    validation error names. Never the body as such, which may quote a value read on a
    screen (REVIEW S-M2)."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return ""
    if isinstance(detail, str):
        return f" {detail[:200]}"
    if isinstance(detail, list):
        parts = [
            f"{'.'.join(str(p) for p in d.get('loc', []))} : {d.get('msg', '')}"
            for d in detail[:5]
            if isinstance(d, dict)
        ]
        return f" ({'; '.join(parts)})"[:300]
    return ""


class TaskInterrupted(RuntimeError):
    """The worker can no longer prove it owns the current decision."""


class HospitalOSClient:
    def __init__(self, http: httpx.Client, email: str, password: str) -> None:
        self.http = http
        self.email = email
        self.password = password
        self.token: str | None = None
        self.leases: dict[int, dict[str, str]] = {}

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
        # Claims are deliberately NOT retried after a lost response: ownership is uncertain.
        safe = path.endswith(
            (
                "/renew",
                "/attempts",
                "/complete",
                "/heartbeat",
                "/begin-write",
                "/authorize",
                "/ingest/requests",
                "/ingest/movements",
            )
        )
        for attempt in range(3 if safe else 1):
            try:
                r = self.http.request(method, path, json=json, headers=self._headers())
                if r.status_code == 401:
                    self.token = None
                    r = self.http.request(method, path, json=json, headers=self._headers())
                if safe and r.status_code in (429, 502, 503, 504) and attempt < 2:
                    time.sleep(0.2 * 2**attempt)
                    continue
                if r.status_code >= 400:
                    raise ApiError(f"{method} {path} : {r.status_code}{_reason(r)}")
                return r.json() if r.content else None
            except httpx.TransportError as exc:
                if not safe or attempt == 2:
                    raise ApiError(f"HospitalOS injoignable : {type(exc).__name__}") from exc
                time.sleep(0.2 * 2**attempt)
        raise ApiError("HospitalOS injoignable")

    def _lease(self, task_id: int) -> dict[str, str]:
        if task_id not in self.leases:
            raise ApiError("Aucune réservation de cette tâche")
        return self.leases[task_id]

    def checkpoint(self, task_id: int) -> None:
        try:
            self._call("POST", f"/api/agent/tasks/{task_id}/renew", self._lease(task_id))
        except ApiError as exc:
            raise TaskInterrupted(str(exc)) from exc

    def begin_write(self, task_id: int) -> None:
        self._call("POST", f"/api/agent/tasks/{task_id}/begin-write", self._lease(task_id))

    def authorize(self, task_id: int, engine: str) -> float:
        result = self._call(
            "POST",
            f"/api/agent/tasks/{task_id}/authorize",
            {**self._lease(task_id), "engine": engine},
        )
        return float(result["budget_usd"])

    def post_step(
        self, task_id: int, meta: dict[str, Any], frame: bytes | None, timeout: float
    ) -> None:
        """One player step (called from the upload thread). Never retried by the caller:
        ``StepRefused`` when the task no longer accepts steps (lease lost, finished)."""
        lease = self.leases.get(task_id)
        if lease is None:
            raise StepRefused("plus de réservation")
        files = {"frame": ("frame.jpg", frame, "image/jpeg")} if frame is not None else None
        for _ in range(2):
            r = self.http.post(
                f"/api/agent/tasks/{task_id}/steps",
                data={"meta": json.dumps({**lease, **meta})},
                files=files,
                headers=self._headers(),
                timeout=timeout,
            )
            if r.status_code != 401:
                break
            self.token = None
        if r.status_code in (401, 403, 404, 409):
            raise StepRefused(f"étape refusée ({r.status_code})")
        if r.status_code >= 400:
            raise ApiError(f"étape non enregistrée : {r.status_code}{_reason(r)}")

    def vocabulary(self) -> dict[str, dict[str, str]]:
        r = self.http.get("/api/vocabulary")
        r.raise_for_status()
        data: dict[str, dict[str, str]] = r.json()
        return data

    def heartbeat(
        self,
        agent_id: str,
        version: str,
        engines: list[dict[str, Any]],
        playbooks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = self._call(
            "POST",
            "/api/agent/heartbeat",
            {
                "agent_id": agent_id,
                "version": version,
                "engines": engines,
                "playbooks": playbooks or [],
            },
        )
        return result

    def claim(
        self,
        agent_id: str,
        limit: int = 1,
        kinds: list[str] | None = None,
        legacy: bool = True,
    ) -> list[dict[str, Any]]:
        """Claimed tasks of a connection carry its ``connection`` block, password included:
        the caller keeps it in memory for the task only."""
        body: dict[str, Any] = {
            "protocol_version": 2,
            "agent_id": agent_id,
            "limit": limit,
            "legacy": legacy,
        }
        if kinds is not None:
            body["kinds"] = kinds
        result: list[dict[str, Any]] = self._call("POST", "/api/agent/tasks/claim", body)
        for task in result:
            self.leases[int(task["id"])] = {
                "agent_id": agent_id,
                "lease_token": task["lease_token"],
            }
        return result

    def attempt(self, task_id: int, **fields: Any) -> None:
        self._call(
            "POST",
            f"/api/agent/tasks/{task_id}/attempts",
            {**self._lease(task_id), "report_key": uuid.uuid4().hex, **fields},
        )

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
            {
                **self._lease(task_id),
                "status": status,
                "engine": engine,
                "result": result,
                "error": error,
            },
        )

        self.leases.pop(task_id, None)

    def ingest(self, request: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._call("POST", "/api/ingest/requests", request)
        return result

    def request_sync(self, kind: str = "sync_inbox") -> dict[str, Any]:
        result: dict[str, Any] = self._call("POST", f"/api/agent/sync?kind={kind}")
        return result

    def ingest_movements(self, movements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._call("POST", "/api/ingest/movements", movements)
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
