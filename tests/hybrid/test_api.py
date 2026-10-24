"""API contract checks; local computation only, no hospital integration."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from hospitalos.hybrid.demo import demo_request
from services.api.hybrid_app import app


class HybridApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

    def test_demo_plan(self) -> None:
        response = self.client.post("/hybrid/plan", json=demo_request().model_dump(mode="json"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["selected"]["bed_id"], "bed-z")
        self.assertEqual(response.json()["evidence"], "simulation_under_declared_assumptions")

    def test_unknown_fields_and_excessive_budget_rejected(self) -> None:
        payload = demo_request().model_dump(mode="json")
        payload["scenarios"] = 1000000
        self.assertEqual(self.client.post("/hybrid/plan", json=payload).status_code, 422)
        payload = demo_request().model_dump(mode="json")
        payload["execute_now"] = True
        self.assertEqual(self.client.post("/hybrid/plan", json=payload).status_code, 422)

    def test_missing_fact_returns_abstention_not_a_fabricated_state(self) -> None:
        request = demo_request()
        payload = request.model_copy(update={"events": request.events[1:]}).model_dump(mode="json")
        response = self.client.post("/hybrid/plan", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["decision"], "abstain")

    def test_no_execution_endpoint(self) -> None:
        self.assertEqual(self.client.post("/hybrid/execute", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
