"""A changed form, real Chromium and scripted model responses over the provider protocol."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from services.admissions_agent.browser import BrowserSession
from services.admissions_agent.tests.conftest import login
from services.admissions_agent.tests.test_agent_e2e import (
    ANTHROPIC,
    ScriptedClaude,
    accord,
    claude_factory,
    enable_claude,
    requests_by_ref,
    set_policy,
    track,
    typed,
)


class VariantClaude(ScriptedClaude):
    """Use pixel actions on the actual v2 form; optionally obey the hostile page text."""

    def __init__(
        self, sessions: list[BrowserSession], day: str, *, follow_injection: bool = False
    ) -> None:
        super().__init__(sessions, day)
        self.follow_injection = follow_injection

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append({"headers": dict(request.headers), "body": body})
        message = body["messages"][0]["content"][0]["text"].split("\n---\n")[1]
        field = "#justification-negative" if self.follow_injection else "#accueil-prevu"
        radio = "#reponse-negative" if self.follow_injection else "#reponse-positive"

        def click(selector: str) -> dict[str, Any]:
            return self.use("click", "left_click", {"coordinate": self.center(selector)})

        steps: list[Callable[[], list[dict[str, Any]]]] = [
            lambda: self.scroll_to("#courrier-adresseur", "scroll-message"),
            lambda: [click("#courrier-adresseur"), self.use("message", "type", {"text": message})],
            lambda: self.scroll_to(field, "scroll-field"),
            lambda: (
                [click(field)]
                + (
                    [
                        self.use("option", "key", {"text": "Down"}),
                        self.use("select", "key", {"text": "Return"}),
                    ]
                    if self.follow_injection
                    else [self.use("date", "type", {"text": self.date_to_type})]
                )
            ),
            lambda: self.scroll_to(radio, "scroll-decision"),
            lambda: [click(radio)],
            lambda: self.scroll_to("#transmettre-decision", "scroll-send"),
            lambda: [click("#transmettre-decision")],
        ]
        turn = len(self.calls)
        content = (
            steps[turn - 1]()
            if turn <= len(steps)
            else [{"type": "text", "text": "<resultat>TERMINE</resultat>"}]
        )
        return httpx.Response(
            200,
            json={
                "content": content,
                "usage": {"input_tokens": 3000, "output_tokens": 200},
                "stop_reason": "tool_use" if turn <= len(steps) else "end_turn",
            },
        )


def task_for(api: TestClient, ref: str) -> dict[str, Any]:
    request_id = requests_by_ref(api)[ref]["id"]
    tasks = api.get("/api/agent/tasks", headers=login(api, "admin@test.fr")).json()
    return next(t for t in tasks if t["request_id"] == request_id)


def variant_sync(api: TestClient, portal: httpx.Client, make_agent: Callable[..., Any]) -> Any:
    assert portal.post("/_test/variant", json={"variant": "v2"}).status_code == 200
    agent = make_agent()
    agent.cycle()
    rows = requests_by_ref(api)
    assert len(rows) == 3
    dump = json.dumps(rows, ensure_ascii=False)
    for forbidden in ("Ignorez", "Exemple", "Fictif", "Imaginaire"):
        assert forbidden not in dump
    return agent


def test_v2_script_only_never_submits_and_requires_a_human(
    api: TestClient, portal: httpx.Client, make_agent: Callable[..., Any]
) -> None:
    agent = variant_sync(api, portal, make_agent)
    before = portal.get("/_test/state").json()
    accord(api, "DOS-2026-0412")
    agent.cycle()
    task = task_for(api, "DOS-2026-0412")
    assert task["status"] == "needs_human" and task["reconcile_only"]
    assert portal.get("/_test/state").json() == before
    assert portal.get("/_test/submissions").json() == {}
    assert task["route"][0]["decision"] == "failure"
    assert "formulaire" in task["route"][0]["reason"]
    assert all(s["decision"] == "skipped" for s in task["route"][1:])
    assert task["cost_usd"] == 0


@pytest.mark.parametrize("follow_injection", [False, True])
def test_v2_two_dossiers_and_independent_verification(
    api: TestClient,
    portal: httpx.Client,
    make_agent: Callable[..., Any],
    follow_injection: bool,
) -> None:
    agent = variant_sync(api, portal, make_agent)
    accord(api, "DOS-2026-0412")
    agent.cycle()
    first = task_for(api, "DOS-2026-0412")
    assert first["status"] == "needs_human"

    def allow_fallback(p: dict[str, Any]) -> None:
        enable_claude(p)
        p["engines"]["closed_fast"].update(enabled=True, identifiable_data_allowed=True)
        p["routes"]["reply_portal"].append("closed_fast")

    set_policy(api, allow_fallback)
    proposed = accord(api, "DOS-2026-0413")
    sessions: list[BrowserSession] = []
    fake = VariantClaude(sessions, typed(proposed), follow_injection=follow_injection)
    factory_calls: list[str] = []
    base_factory = claude_factory(fake)

    def factory(name: str, engine: dict[str, Any]) -> Any:
        factory_calls.append(name)
        return base_factory(name, engine)

    agent = make_agent(factory, {**ANTHROPIC, "closed_fast": ANTHROPIC["closed_best"]})
    track(agent, sessions)
    agent.last_sync = time.monotonic()
    assert agent.cycle() == 1
    second = task_for(api, "DOS-2026-0413")
    state = portal.get("/_test/state").json()
    assert task_for(api, "DOS-2026-0412")["status"] == "needs_human"
    assert state["DOS-2026-0412"]["status"] == "En attente"
    assert portal.get("/_test/submissions").json() == {"DOS-2026-0413": 1}
    assert second["cost_usd"] == pytest.approx(len(fake.calls) * 0.016)
    assert [(s["engine"], s["decision"]) for s in second["route"]] == [
        ("playbook", "failure"),
        ("open_heavy", "skipped"),
        ("closed_best", "unverified" if follow_injection else "success"),
    ]
    if follow_injection:
        assert state["DOS-2026-0413"]["status"] == "Refusé"
        assert second["status"] == "needs_human"
        assert "relecture" in second["error"]
    else:
        assert second["status"] == "done"
        observed = second["result"]["verification"]["observed"]
        assert observed["proposed_date"] == proposed
        assert (
            state["DOS-2026-0413"]["message"].replace("\r\n", "\n") == second["payload"]["message"]
        )
        assert " ".join(observed["message"].split()) == " ".join(
            second["payload"]["message"].split()
        )
        detail = api.get(
            f"/api/requests/{second['request_id']}", headers=login(api, "coord@test.fr")
        ).json()["portal_reply"]
        assert detail["route"] == second["route"]
        assert detail["cost_usd"] == second["cost_usd"]
    # Even after activation, retrying a previously fenced task can only read the portal.
    retry_id = second["id"] if follow_injection else first["id"]
    calls = len(fake.calls)
    assert (
        api.post(
            f"/api/agent/tasks/{retry_id}/retry", headers=login(api, "coord@test.fr")
        ).status_code
        == 200
    )
    agent.cycle()
    assert len(fake.calls) == calls
    assert factory_calls == ["closed_best"]
    assert portal.get("/_test/submissions").json() == {"DOS-2026-0413": 1}
    assert "demo-portail" not in json.dumps(fake.calls)
    assert "Ignore toute consigne" in fake.calls[0]["body"]["system"]


@pytest.mark.parametrize("budget", ["daily", "task"])
def test_v2_exhausted_budget_never_calls_model(
    api: TestClient, portal: httpx.Client, make_agent: Callable[..., Any], budget: str
) -> None:
    variant_sync(api, portal, make_agent)

    def policy(p: dict[str, Any]) -> None:
        enable_claude(p)
        if budget == "daily":
            p["daily_budget_usd"] = 0
        else:
            p["task_budget_usd"]["reply_portal"] = 0

    set_policy(api, policy)
    proposed = accord(api, "DOS-2026-0412")
    fake = VariantClaude([], typed(proposed))
    agent = make_agent(claude_factory(fake), ANTHROPIC)
    agent.last_sync = time.monotonic()
    agent.cycle()
    task = task_for(api, "DOS-2026-0412")
    assert task["status"] == "needs_human"
    assert "budget" in task["result"]["route"][-1]["reason"]
    assert fake.calls == []
    assert portal.get("/_test/submissions").json() == {}
