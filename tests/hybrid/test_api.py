"""API contract checks; local computation only, no hospital integration."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from hospitalos.hybrid.demo import demo_request, future_request, pathway_request
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

    def test_pathway_exposes_logistics_and_sampled_service_status(self) -> None:
        response = self.client.post("/hybrid/plan", json=pathway_request().model_dump(mode="json"))
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["schema_version"], "HYBRID_PLAN_4")
        self.assertEqual(result["selected"]["kind"], "request_transport")
        self.assertEqual(result["discharge_readiness"][0]["stage"], "transport_to_request")
        self.assertEqual(result["service_status"], "served_in_all_sampled_scenarios")

    def test_old_fact_schema_is_not_silently_upgraded(self) -> None:
        payload = pathway_request().model_dump(mode="json")
        payload["events"][0]["schema_version"] = "HYBRID_MVP_1"
        self.assertEqual(self.client.post("/hybrid/plan", json=payload).status_code, 422)

    def test_future_scenario_remains_an_explicit_hypothesis(self) -> None:
        response = self.client.post("/hybrid/plan", json=future_request().model_dump(mode="json"))
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["future"]["provenance"], "synthetic_hypothesis")
        self.assertGreater(result["candidates"][0]["max_arrived"], 0)
        self.assertEqual(result["service_status"], "unserved_in_some_sampled_scenarios")

    def test_future_foreknowledge_and_unknown_pool_are_rejected(self) -> None:
        payload = future_request().model_dump(mode="json")
        payload["future"]["declared_at"] = "2026-10-24T09:00:00Z"
        self.assertEqual(self.client.post("/hybrid/plan", json=payload).status_code, 422)
        payload = future_request().model_dump(mode="json")
        payload["future"]["changes"][0]["target_id"] = "invented-pool"
        self.assertEqual(self.client.post("/hybrid/plan", json=payload).status_code, 422)


if __name__ == "__main__":
    unittest.main()
