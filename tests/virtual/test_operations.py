"""Real API/ledger/replay with a short deterministic test hospital, no UI scenario controls."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from hospitalos.virtual import campus as module
from hospitalos.virtual.campus import CampusFleet
from hospitalos.virtual.clinical import ClinicalEngine
from hospitalos.virtual.history import History
from services.api.virtual_app import create_app


def test_accountable_cross_unit_work_capacity_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epoch = datetime(2026, 10, 25, 0, tzinfo=UTC)
    now = epoch + timedelta(seconds=180)
    configs = tuple(c.model_copy(update={"initially_occupied": 1}) for c in module.campus_units())
    monkeypatch.setattr(module, "campus_units", lambda: configs)
    # Keep patients waiting so the test controls the receiving-consent race deterministically.
    monkeypatch.setattr(ClinicalEngine, "_allocate", lambda self: None)
    monkeypatch.setattr(History, "fit", lambda self: None)
    (tmp_path / "hospital.json").write_text(
        json.dumps(
            {
                "epoch": epoch.isoformat(),
                "identity": {
                    "version": "WORKPLACE_1",
                    "seed": 7,
                    "configs": [c.model_dump(mode="json") for c in configs],
                },
            }
        )
    )
    fleet = CampusFleet(tmp_path, clock=lambda: now)
    client = TestClient(create_app(fleet, start_worker=False))
    url = "/product/hospitals/H1"
    requests: list[dict[str, Any]] = []
    assert fleet.ops is not None

    def command(
        kind: str, actor: str = "bm-camille", unit: str = "geriatrie", **kwargs: Any
    ) -> Response:
        workspace = client.get(url + "/workspace").json()
        body = {
            "request_id": f"cmd-{len(requests)}",
            "kind": kind,
            "actor_id": actor,
            "unit_id": unit,
            "revision": workspace["revision"],
            "tokens": workspace["tokens"],
            **kwargs,
        }
        requests.append(body)
        return cast(Response, client.post(url + "/operations", json=body))

    try:
        state = client.get(url + "/workspace").json()
        patient = next(p for p in state["patients"] if p["unit_id"] == "geriatrie")
        option = next(o for o in patient["options"] if o["unit_id"] == "medecine" and o["eligible"])
        result = command(
            "place", patient_id=patient["id"], target_unit="medecine", bed_id=option["bed_id"]
        )
        assert result.status_code == 200, result.text
        task_id = requests[-1]["request_id"]
        assert fleet.ops.tasks[task_id]["status"] == "requested"
        assert patient["id"] in fleet.get("geriatrie").engine.patients
        assert patient["id"] not in fleet.get("medecine").engine.patients
        # Retrying the exact request never duplicates a task or increments revision.
        duplicate = client.post(url + "/operations", json=requests[-1])
        assert duplicate.json()["revision"] == result.json()["revision"]
        assert command("accept", task_id=task_id).status_code == 409
        assert command("accept", actor="cadre-medecine", task_id=task_id).status_code == 200
        assert fleet.ops.tasks[task_id]["status"] == "in_progress"
        assert patient["id"] not in fleet.get("geriatrie").engine.patients
        now += timedelta(minutes=4)
        fleet.sync()
        assert fleet.ops.tasks[task_id]["status"] == "completed"
        assert fleet.get("medecine").engine.patients[patient["id"]].status == "admitted"
        # Role enforcement, version conflicts, and capacity below occupancy.
        until = (now + timedelta(hours=1)).isoformat()
        assert command("capacity", capacity=0, until=until, reason="Absence").status_code == 409
        reduced = command(
            "capacity", actor="cadre-geriatrie", capacity=0, until=until, reason="Absence"
        )
        assert reduced.status_code == 200, reduced.text
        assert fleet.ops.engine("geriatrie").staffed_capacity == 0
        assert any(b.occupant for b in fleet.get("geriatrie").engine.beds.values())
        stale = {**requests[-1], "request_id": "stale"}
        assert client.post(url + "/operations", json=stale).status_code == 409
        # Logistics completion is observed, never asserted by the request itself.
        discharge = next(
            d
            for d in client.get(url + "/workspace").json()["discharges"]
            if d["unit_id"] == "geriatrie"
        )
        response = command("documents", patient_id=discharge["id"])
        assert response.status_code == 200, response.text
        document_id = requests[-1]["request_id"]
        assert fleet.ops.tasks[document_id]["status"] == "requested"
        assert (
            command("remind", task_id=document_id, reason="Préparer la relève").status_code == 200
        )
        now += timedelta(minutes=2)
        fleet.sync()
        assert fleet.ops.tasks[document_id]["status"] == "in_progress"
        now += timedelta(minutes=21)
        fleet.sync()
        assert fleet.ops.tasks[document_id]["status"] == "completed"
        before = fleet.ops.view()
        physical = {
            k: [(b.id, b.occupant, b.reserved_for) for b in u.engine.beds.values()]
            for k, u in fleet.units.items()
        }
    finally:
        fleet.close()
    resumed = CampusFleet(tmp_path, clock=lambda: now)
    try:
        assert resumed.ops is not None
        after = resumed.ops.view()
        assert after["revision"] == before["revision"]
        assert after["tasks"] == before["tasks"]
        assert after["events"] == before["events"]
        assert after["constraints"] == before["constraints"]
        assert {
            k: [(b.id, b.occupant, b.reserved_for) for b in u.engine.beds.values()]
            for k, u in resumed.units.items()
        } == physical
    finally:
        resumed.close()
