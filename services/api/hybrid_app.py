"""Separate local prototype API, without loading TFT/RSSM or writing to a hospital.

Run on loopback only. Authentication, tenant isolation and real connectors must
be supplied before any non-local deployment. Approval lives in the sandbox
workflow module; this API intentionally exposes no execution endpoint.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from hospitalos.hybrid.planning import Plan, PlanRequest, plan

app = FastAPI(title="HospitalOS Hybrid MVP - local prototype", version="0.1.0")


@app.post("/hybrid/plan", response_model=Plan)
def recommend(request: PlanRequest) -> Plan:
    try:
        return plan(request)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "local_prototype_no_external_execution"}
