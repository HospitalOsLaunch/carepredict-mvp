"""Failure paths do not require a paid model or a real patient portal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest

from services.admissions_agent.api_client import ApiError, HospitalOSClient
from services.admissions_agent.browser import BrowserSession, Screenshot
from services.admissions_agent.config import AgentSettings, EngineEndpoint
from services.admissions_agent.engines.anthropic_cu import AnthropicComputerUse
from services.admissions_agent.engines.base import BudgetExceeded, EngineResult, reply_goal
from services.admissions_agent.engines.openai_vlm import OpenWeightsVision
from services.admissions_agent.playbook import Playbook, Transforms
from services.admissions_agent.router import Router
from services.admissions_smr.agent_policy import default_policy

PLAYBOOK = Path(__file__).parents[1] / "playbooks" / "demo_portal.yaml"
PAYLOAD = {
    "external_ref": "DOS-1",
    "decision": "accord",
    "proposed_date": "2026-11-02",
    "message": "Bonjour,\n\nEntrée validée.",
}
BEFORE = {"external_ref": "DOS-1", "status": "En attente", "message": ""}
MATCH = {**PAYLOAD, "status": "Accord donné"}


def make_router(monkeypatch: pytest.MonkeyPatch) -> tuple[Router, Mock, dict[str, Any]]:
    settings = AgentSettings(
        api_url="http://api.test",
        api_email="agent@test.fr",
        api_password="test",
        agent_id="test",
        portal_url="http://portal.test",
        portal_username="test",
        portal_password="test",
        playbook_path=str(PLAYBOOK),
        allowed_hosts=("portal.test",),
        engines={"closed_best": EngineEndpoint(api_key="test")},
    )
    api = Mock(spec=HospitalOSClient)
    api.authorize.return_value = 1.0
    playbook = Playbook.load(str(PLAYBOOK))
    monkeypatch.setattr(playbook, "login", Mock())
    session = Mock(spec=BrowserSession)
    router = Router(settings, api, playbook, Transforms({}), Mock(), lambda: session)
    monkeypatch.setattr(router, "_report", Mock())
    policy = default_policy().model_dump()
    policy["engines"]["closed_best"].update(enabled=True, identifiable_data_allowed=True)
    return router, api, {"policy": policy}


@pytest.mark.parametrize("after", [None, {**BEFORE, "message": "unexpected write"}])
def test_failed_write_with_unknown_or_changed_readback_never_escalates(
    monkeypatch: pytest.MonkeyPatch, after: dict[str, Any] | None
) -> None:
    router, api, beat = make_router(monkeypatch)
    monkeypatch.setattr(router, "_read_back", Mock(side_effect=[BEFORE, after]))
    run = Mock(return_value=EngineResult("failure", error="timeout after submit"))
    monkeypatch.setattr(router, "_run", run)
    outcome = router.handle({"id": 1, "kind": "reply_portal", "payload": PAYLOAD}, beat)
    assert outcome.status == "needs_human"
    assert [c.args[0] for c in run.call_args_list] == ["playbook"]
    api.begin_write.assert_called_once_with(1)


def test_verified_unchanged_reply_can_escalate(monkeypatch: pytest.MonkeyPatch) -> None:
    router, _, beat = make_router(monkeypatch)
    monkeypatch.setattr(router, "_read_back", Mock(side_effect=[BEFORE, BEFORE]))
    monkeypatch.setattr(router.playbook, "verify", Mock(return_value=(True, {"observed": MATCH})))
    run = Mock(side_effect=[EngineResult("failure"), EngineResult("success")])
    monkeypatch.setattr(router, "_run", run)
    outcome = router.handle({"id": 1, "kind": "reply_portal", "payload": PAYLOAD}, beat)
    assert outcome.status == "done"
    assert [c.args[0] for c in run.call_args_list] == ["playbook", "closed_best"]


@pytest.mark.parametrize(
    "observed,reconcile,expected",
    [
        (None, False, "needs_human"),
        (MATCH, False, "done"),
        (MATCH, True, "done"),
        (BEFORE, True, "needs_human"),
    ],
)
def test_unreadable_already_applied_and_reconciliation_do_not_write(
    monkeypatch: pytest.MonkeyPatch,
    observed: dict[str, Any] | None,
    reconcile: bool,
    expected: str,
) -> None:
    router, api, beat = make_router(monkeypatch)
    monkeypatch.setattr(router, "_read_back", Mock(return_value=observed))
    run = Mock()
    monkeypatch.setattr(router, "_run", run)
    outcome = router.handle(
        {
            "id": 1,
            "kind": "reply_portal",
            "payload": PAYLOAD,
            "reconcile_only": reconcile,
        },
        beat,
    )
    assert outcome.status == expected
    run.assert_not_called()
    api.begin_write.assert_not_called()


def test_wrong_dossier_readback_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    router, _, _ = make_router(monkeypatch)
    monkeypatch.setattr(
        router.playbook,
        "verify",
        Mock(
            return_value=(
                True,
                {
                    "observed": {**MATCH, "external_ref": "ANOTHER-PATIENT"},
                },
            )
        ),
    )
    assert router._read_back(Mock(spec=BrowserSession), PAYLOAD) is None


@pytest.mark.parametrize(
    "model,convention,trials",
    [
        ("old-model", "pixels", 20),
        ("deployed", "normalized_1000", 20),
        ("deployed", "pixels", 19),
    ],
)
def test_calibration_must_match_deployed_model_and_coordinates(
    monkeypatch: pytest.MonkeyPatch, model: str, convention: str, trials: int
) -> None:
    router, api, beat = make_router(monkeypatch)
    router.settings.engines["open_light"] = EngineEndpoint(
        base_url="https://model.test", model="deployed", coordinates="pixels"
    )
    beat["policy"]["routes"]["sync_inbox"] = ["open_light"]
    beat["policy"]["engines"]["open_light"].update(enabled=True, identifiable_data_allowed=True)
    beat["calibrations"] = {"open_light": 1.0}
    beat["calibration_details"] = {
        "open_light": {
            "model": model,
            "convention": convention,
            "trials": trials,
        }
    }
    outcome = router.handle({"id": 1, "kind": "sync_inbox", "payload": {}}, beat)
    assert outcome.status == "needs_human"
    assert "calibration" in outcome.result["route"][0]["reason"]
    api.authorize.assert_not_called()


def response_for(kind: str) -> dict[str, Any]:
    usage = {
        "input_tokens": 1000,
        "output_tokens": 1000,
        "prompt_tokens": 1000,
        "completion_tokens": 1000,
    }
    if kind == "anthropic":
        return {
            "content": [{"type": "text", "text": "<resultat>TERMINE</resultat>"}],
            "usage": usage,
        }
    return {"choices": [{"message": {"content": "<resultat>TERMINE</resultat>"}}], "usage": usage}


def engine_for(kind: str, http: httpx.Client) -> Any:
    if kind == "anthropic":
        return AnthropicComputerUse("closed_best", "test", "key", http, 1000, 1000)
    return OpenWeightsVision("open_light", "test", http, None, "pixels", 1000, 1000)


@pytest.mark.parametrize("kind", ["anthropic", "open"])
def test_final_answer_cannot_bypass_budget(kind: str) -> None:
    with httpx.Client(
        base_url="https://model.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_for(kind))),
    ) as http:
        engine = engine_for(kind, http)
        session = Mock(spec=BrowserSession)
        session.checkpoint = Mock()
        session.screenshot.return_value = Screenshot(b"png", 1280, 800)
        with pytest.raises(BudgetExceeded) as error:
            engine.run(session, reply_goal(PAYLOAD), 3, 0.5)
        assert error.value.cost_usd == 2.0  # actual billed cost, never clamped to the budget


def test_open_engine_skips_rest_of_batch_after_failed_action() -> None:
    calls = 0

    def model(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise httpx.ReadTimeout("lost model response")
        actions = [
            {"id": str(i), "function": {"name": name, "arguments": json.dumps(args)}}
            for i, (name, args) in enumerate(
                [
                    ("click", {"x": 4, "y": 4}),
                    ("type_text", {"text": "must not type"}),
                ]
            )
        ]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"tool_calls": actions}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 1000},
            },
        )

    with httpx.Client(base_url="https://model.test", transport=httpx.MockTransport(model)) as http:
        session = Mock(spec=BrowserSession)
        session.checkpoint = Mock()
        session.screenshot.return_value = Screenshot(b"png", 1280, 800)
        session.click.side_effect = ValueError("missing target")
        result = engine_for("open", http).run(session, reply_goal(PAYLOAD), 3, 10)
        assert result.outcome == "failure" and result.cost_usd == 2.0
        session.type_text.assert_not_called()


def test_api_retries_reports_with_same_key_but_never_retries_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("services.admissions_agent.api_client.time.sleep", lambda _: None)
    seen: list[dict[str, Any]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        if len(seen) == 1 or request.url.path.endswith("claim"):
            raise httpx.ReadTimeout("response lost after commit")
        return httpx.Response(200, json={})

    with httpx.Client(
        base_url="https://api.test", transport=httpx.MockTransport(transport)
    ) as http:
        client = HospitalOSClient(http, "agent@test", "password")
        client.token = "token"
        client.leases[1] = {"agent_id": "test", "lease_token": "x" * 64}
        client.attempt(1, engine="playbook", outcome="success")
        assert len(seen) == 2 and seen[0] == seen[1]
        with pytest.raises(ApiError):
            client.claim("test")
        assert len(seen) == 3
