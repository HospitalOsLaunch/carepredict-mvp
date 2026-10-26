"""End to end: real Chromium on the demo portal, real API, scripted model servers."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi.testclient import TestClient

from services.admissions_agent.browser import BrowserSession
from services.admissions_agent.calibrate import calibrate
from services.admissions_agent.config import EngineEndpoint
from services.admissions_agent.engines.anthropic_cu import AnthropicComputerUse
from services.admissions_agent.engines.openai_vlm import OpenWeightsVision
from services.admissions_agent.tests.conftest import login

ANTHROPIC = {
    "closed_best": EngineEndpoint(base_url="https://api.anthropic.test", api_key="sk-test")
}
OPEN = {
    "open_light": EngineEndpoint(
        base_url="http://vllm.test", model="holo", coordinates="normalized_1000"
    )
}


def requests_by_ref(api: TestClient) -> dict[str, dict[str, Any]]:
    rows = api.get("/api/requests?scope=toutes", headers=login(api, "coord@test.fr")).json()
    return {r["external_ref"]: r for r in rows}


def set_policy(api: TestClient, change: Callable[[dict[str, Any]], None]) -> None:
    admin = login(api, "admin@test.fr")
    policy = api.get("/api/agent/status", headers=admin).json()["policy"]
    change(policy)
    r = api.put("/api/agent/policy", json=policy, headers=admin)
    assert r.status_code == 200, r.text


def accord(api: TestClient, ref: str, days: int = 3) -> str:
    coord = login(api, "coord@test.fr")
    req = requests_by_ref(api)[ref]
    site_id = api.get("/api/sites", headers=coord).json()[0]["id"]
    proposed = (date.today() + timedelta(days=days)).isoformat()
    r = api.post(
        f"/api/requests/{req['id']}/accord",
        json={"site_id": site_id, "proposed_date": proposed},
        headers=coord,
    )
    assert r.status_code == 200, r.text
    return proposed


def broken_playbook(tmp_path: Path, original: str) -> str:
    spec = yaml.safe_load(Path(original).read_text())
    spec["timeout_ms"] = 1500
    spec["reply_portal"] = [
        s if s != {"click": "#envoyer"} else {"click": "#bouton-renomme"}
        for s in spec["reply_portal"]
    ]
    path = tmp_path / "broken.yaml"
    path.write_text(yaml.safe_dump(spec, allow_unicode=True))
    return str(path)


def test_playbook_sync_then_reply_with_independent_verification(
    api: TestClient, portal: httpx.Client, make_agent: Callable[..., Any]
) -> None:
    agent = make_agent()
    assert agent.cycle() == 1  # the agent asks for a sync, then handles it

    rows = requests_by_ref(api)
    assert set(rows) == {"DOS-2026-0412", "DOS-2026-0413", "DOS-2026-0414"}
    neuro = rows["DOS-2026-0414"]
    assert neuro["source"] == "portail" and neuro["patient_ref"] == "DOS-2026-0414"
    assert neuro["mention_requested"] == "neuro" and neuro["care_level"] == 4
    assert neuro["isolation_required"] is True and neuro["special_needs"] == ["tracheotomie"]
    # The portal shows the patient's name: it must never reach HospitalOS.
    dump = json.dumps(rows, ensure_ascii=False)
    assert "Imaginaire" not in dump and "Exemple" not in dump and "Fictif" not in dump

    proposed = accord(api, "DOS-2026-0412")
    coord = login(api, "coord@test.fr")
    refused_id = rows["DOS-2026-0413"]["id"]
    api.post(f"/api/requests/{refused_id}/refuse", json={"reason": "pas_de_lit"}, headers=coord)
    assert agent.cycle() == 2

    state = portal.get("/_test/state").json()
    assert (
        state["DOS-2026-0412"]["status"] == "Accord donné"
        and state["DOS-2026-0412"]["proposed"] == proposed
    )
    assert state["DOS-2026-0413"]["status"] == "Refusé"
    assert state["DOS-2026-0413"]["refusal_reason"] == "Pas de lit disponible à la date souhaitée"
    assert "Bonjour" in (state["DOS-2026-0412"]["message"] or "")
    detail = api.get(f"/api/requests/{rows['DOS-2026-0412']['id']}", headers=coord).json()
    assert (
        detail["portal_reply"]["status"] == "done"
        and detail["portal_reply"]["engine_used"] == "playbook"
    )

    # Idempotent: a second sync creates nothing new.
    agent.last_sync = 0.0
    agent.cycle()
    assert len(requests_by_ref(api)) == 3


class ScriptedClaude:
    """Speaks the Anthropic Messages wire format; decides clicks by looking at the live page."""

    def __init__(self, sessions: list[BrowserSession], date_to_type: str) -> None:
        self.sessions = sessions
        self.date_to_type = date_to_type
        self.calls: list[dict[str, Any]] = []

    def center(self, selector: str) -> list[int]:
        box = self.sessions[-1].page.locator(selector).bounding_box()
        assert box is not None
        return [int(box["x"] + box["width"] / 2), int(box["y"] + box["height"] / 2)]

    def scroll_to(self, selector: str, step_id: str) -> list[dict[str, Any]]:
        """Scroll so that the element sits in the upper part of the viewport.

        Computed from the live layout, like a model reading the screenshot would: font
        metrics differ between machines (the CI runner renders taller text), so a fixed
        amount is not portable.
        """
        box = self.sessions[-1].page.locator(selector).bounding_box()
        assert box is not None
        notches = max(0, int((box["y"] - 120) // 100))
        return [
            self.use(
                step_id,
                "scroll",
                {"coordinate": [640, 400], "scroll_direction": "down", "scroll_amount": notches},
            )
        ]

    @staticmethod
    def use(step_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "tool_use",
            "id": step_id,
            "name": name,
            "toolset_name": "computer",
            "input": args,
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append({"headers": dict(request.headers), "body": body})
        turn = len(self.calls)
        usage = {"input_tokens": 3000, "output_tokens": 200}
        click = "left_click"
        steps: list[Callable[[], list[dict[str, Any]]]] = [
            lambda: self.scroll_to("#decision-accord", "s0"),
            lambda: [
                self.use("t1", click, {"coordinate": self.center("#decision-accord")}),
                self.use("t2", click, {"coordinate": self.center("#date-entree")}),
                self.use("t3", "type", {"text": self.date_to_type}),
            ],
            lambda: self.scroll_to("#message", "s1"),
            lambda: [
                self.use("t4", click, {"coordinate": self.center("#message")}),
                self.use(
                    "t5",
                    "type",
                    {"text": body["messages"][0]["content"][0]["text"].split("\n---\n")[1]},
                ),
                self.use("t6", click, {"coordinate": self.center("#envoyer")}),
            ],
            lambda: [self.use("t7", "screenshot", {})],
        ]
        if turn <= len(steps):
            content = steps[turn - 1]()
            stop = "tool_use"
        else:
            content = [
                {"type": "text", "text": "La réponse est enregistrée. <resultat>TERMINE</resultat>"}
            ]
            stop = "end_turn"
        return httpx.Response(200, json={"content": content, "usage": usage, "stop_reason": stop})


def track(agent: Any, sessions: list[BrowserSession]) -> None:
    """Let the scripted model see the live page of the session the router opens."""
    base = agent.router.session_factory

    def tracked() -> BrowserSession:
        session: BrowserSession = base()
        sessions.append(session)
        return session

    agent.router.session_factory = tracked


def claude_factory(fake: ScriptedClaude) -> Callable[[str, dict[str, Any]], Any]:
    def build(name: str, engine: dict[str, Any]) -> Any:
        client = httpx.Client(
            base_url="https://api.anthropic.test", transport=httpx.MockTransport(fake)
        )
        return AnthropicComputerUse(
            name,
            engine["model"],
            "sk-test",
            client,
            engine["input_usd_per_mtok"],
            engine["output_usd_per_mtok"],
        )

    return build


def enable_claude(policy: dict[str, Any]) -> None:
    policy["engines"]["closed_best"].update(enabled=True, identifiable_data_allowed=True)


def typed(day: str) -> str:
    y, m, d = day.split("-")
    return f"{d}/{m}/{y}"


def test_failed_playbook_escalates_to_claude_and_is_verified(
    api: TestClient, portal: httpx.Client, make_agent: Callable[..., Any], tmp_path: Path
) -> None:
    make_agent().cycle()  # sync with the normal playbook
    set_policy(api, enable_claude)
    proposed = accord(api, "DOS-2026-0412")
    original = make_agent().settings.playbook_path
    sessions: list[BrowserSession] = []
    fake = ScriptedClaude(sessions, typed(proposed))
    agent = make_agent(claude_factory(fake), ANTHROPIC, broken_playbook(tmp_path, original))
    track(agent, sessions)
    agent.last_sync = time.monotonic()  # no inbox sync in this test
    assert agent.cycle() == 1

    task = api.get("/api/agent/tasks", headers=login(api, "admin@test.fr")).json()[0]
    state = portal.get("/_test/state").json()["DOS-2026-0412"]
    assert state["proposed"] == proposed, (state, task["error"], task["result"])
    assert task["status"] == "done" and task["engine_used"] == "closed_best"
    route = task["result"]["route"]
    assert [(step["engine"], step["decision"]) for step in route] == [
        ("playbook", "failure"),
        ("open_heavy", "ignoré"),
        ("closed_best", "success"),
    ]
    assert route[1]["reason"] == "désactivé dans la politique"
    assert task["result"]["verification"]["observed"]["status"] == "Accord donné"
    # 6 calls x (3000 in at $4 + 200 out at $20) per million tokens
    assert abs(task["cost_usd"] - 6 * (3000 * 4 + 200 * 20) / 1e6) < 1e-9

    first = fake.calls[0]
    assert first["body"]["tools"] == [
        {"type": "computer_toolset_20260801", "configs": {"zoom": {"enabled": False}}}
    ]
    assert first["body"]["model"] == "claude-opus-5-5"
    assert (
        "anthropic-beta" not in first["headers"]
        and first["headers"]["anthropic-version"] == "2023-06-01"
    )
    assert first["body"]["messages"][0]["content"][1]["type"] == "image"
    results = fake.calls[2]["body"]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2", "t3"]
    assert all(r["toolset_name"] == "computer" and r["content"] == "OK" for r in results)
    shot = fake.calls[5]["body"]["messages"][-1]["content"][0]["content"][0]
    assert isinstance(shot, dict), f"capture attendue, reçu : {shot!r}"
    assert shot["type"] == "image" and shot["source"]["media_type"] == "image/png"
    status = api.get("/api/agent/status", headers=login(api, "admin@test.fr")).json()
    spend = {s["engine"]: s for s in status["spend_30d"]}
    assert spend["playbook"]["cost_usd"] == 0 and spend["closed_best"]["successes"] == 1


def test_wrong_write_stops_for_a_human_without_escalating(
    api: TestClient, portal: httpx.Client, make_agent: Callable[..., Any], tmp_path: Path
) -> None:
    make_agent().cycle()
    set_policy(api, enable_claude)
    proposed = accord(api, "DOS-2026-0412")
    wrong = (date.fromisoformat(proposed) + timedelta(days=2)).isoformat()
    sessions: list[BrowserSession] = []
    fake = ScriptedClaude(sessions, typed(wrong))
    original = make_agent().settings.playbook_path
    agent = make_agent(claude_factory(fake), ANTHROPIC, broken_playbook(tmp_path, original))
    track(agent, sessions)
    agent.last_sync = time.monotonic()
    agent.cycle()
    task = api.get("/api/agent/tasks", headers=login(api, "admin@test.fr")).json()[0]
    state = portal.get("/_test/state").json()["DOS-2026-0412"]
    assert task["status"] == "needs_human", (state, task["error"], task["result"])
    assert "relecture" in task["error"]
    assert state["proposed"] == wrong, (state, task["error"], task["result"])


def test_model_engines_are_refused_without_data_permission_or_budget(
    api: TestClient, portal: httpx.Client, make_agent: Callable[..., Any], tmp_path: Path
) -> None:
    make_agent().cycle()
    set_policy(api, lambda p: p["engines"]["closed_best"].update(enabled=True))
    accord(api, "DOS-2026-0412")
    original = make_agent().settings.playbook_path
    agent = make_agent(
        claude_factory(ScriptedClaude([], "")), ANTHROPIC, broken_playbook(tmp_path, original)
    )
    agent.last_sync = time.monotonic()
    agent.cycle()
    task = api.get("/api/agent/tasks", headers=login(api, "admin@test.fr")).json()[0]
    assert task["status"] == "needs_human"
    skipped = task["result"]["route"][-1]
    assert skipped["engine"] == "closed_best" and "identifiantes" in skipped["reason"]

    def no_budget(p: dict[str, Any]) -> None:
        enable_claude(p)
        p["daily_budget_usd"] = 0

    set_policy(api, no_budget)
    coord = login(api, "coord@test.fr")
    retry = api.post(f"/api/agent/tasks/{task['id']}/retry", headers=coord)
    assert retry.status_code == 200
    agent.cycle()
    task = api.get("/api/agent/tasks", headers=login(api, "admin@test.fr")).json()[0]
    assert task["reconcile_only"] is True
    assert "Réponse précédente incertaine" in task["error"]
    assert task["status"] == "needs_human"


def test_open_weights_engine_reads_the_inbox(
    api: TestClient, portal: httpx.Client, make_agent: Callable[..., Any]
) -> None:
    """vLLM wire format, harness-defined tools, labels turned into codes, names never kept."""
    items = [
        {
            "external_ref": "DOS-2026-0413",
            "received_at": "2026-10-24T09:30",
            "referrer_facility": "Hôpital Saint-Rambert",
            "referrer_unit": "Orthopédie",
            "patient_age": 71,
            "patient_sex": "M",
            "mention_requested": "Locomoteur",
            "clinical_category": "Prothèse totale de genou",
            "care_level": 2,
            "isolation_required": False,
            "special_needs": ["Oxygénothérapie"],
            "desired_date": "2026-10-30",
            "patient_name": "M. Paul Fictif",
        }
    ]
    seen: list[dict[str, Any]] = []

    def vllm(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        call = {
            "id": "c1",
            "type": "function",
            "function": {
                "name": "finish",
                "arguments": json.dumps(
                    {"result": "<resultat>" + json.dumps(items, ensure_ascii=False) + "</resultat>"}
                ),
            },
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "", "tool_calls": [call]}}],
                "usage": {"prompt_tokens": 5000, "completion_tokens": 300},
            },
        )

    def build(name: str, engine: dict[str, Any]) -> Any:
        client = httpx.Client(base_url="http://vllm.test", transport=httpx.MockTransport(vllm))
        return OpenWeightsVision(name, "holo", client, None, "normalized_1000", usd_per_hour=2.0)

    def only_open(p: dict[str, Any]) -> None:
        p["engines"]["playbook"]["enabled"] = False
        p["engines"]["open_light"].update(enabled=True, identifiable_data_allowed=True)

    agent = make_agent(build, OPEN)
    agent.api.heartbeat("agent-test", "test", [])  # creates the agent state
    set_policy(api, only_open)
    agent.cycle()
    task = api.get("/api/agent/tasks", headers=login(api, "admin@test.fr")).json()[0]
    assert task["status"] == "needs_human"
    assert "calibration" in task["result"]["route"][1]["reason"]  # not calibrated yet

    agent.api.calibration("open_light", "holo", "normalized_1000", 0.95, 20)
    api.post(f"/api/agent/tasks/{task['id']}/retry", headers=login(api, "coord@test.fr"))
    agent.cycle()
    task = api.get("/api/agent/tasks", headers=login(api, "admin@test.fr")).json()[0]
    assert task["status"] == "done" and task["engine_used"] == "open_light"
    row = requests_by_ref(api)["DOS-2026-0413"]
    assert row["mention_requested"] == "locomoteur" and row["special_needs"] == ["oxygene"]
    assert "Fictif" not in json.dumps(row, ensure_ascii=False)
    assert seen[0]["tools"][-1]["function"]["name"] == "finish" and seen[0]["temperature"] == 0
    assert seen[0]["messages"][1]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )


def test_calibration_scores_both_coordinate_conventions(portal_url: str) -> None:
    state: dict[str, Any] = {}

    def vllm(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        text = body["messages"][1]["content"][0]["text"] if len(body["messages"]) == 2 else ""
        if text:
            label = text.split("« ")[1].split(" »")[0]
            box = state["session"].page.get_by_role("button", name=label, exact=True).bounding_box()
            x = (box["x"] + box["width"] / 2) / 1280 * 1000
            y = (box["y"] + box["height"] / 2) / 800 * 1000
            call = {
                "id": "c",
                "type": "function",
                "function": {"name": "click", "arguments": json.dumps({"x": x, "y": y})},
            }
        else:
            call = {
                "id": "f",
                "type": "function",
                "function": {
                    "name": "finish",
                    "arguments": json.dumps({"result": "<resultat>TERMINE</resultat>"}),
                },
            }
        return httpx.Response(
            200, json={"choices": [{"message": {"tool_calls": [call]}}], "usage": {}}
        )

    engine = OpenWeightsVision(
        "open_light",
        "holo",
        httpx.Client(base_url="http://vllm.test", transport=httpx.MockTransport(vllm)),
        None,
        "normalized_1000",
    )
    with BrowserSession(portal_url, ("127.0.0.1",)) as session:
        state["session"] = session
        result = calibrate(engine, session, trials=5)
    assert result.hit_rate_configured == 1.0 and result.best_convention == "normalized_1000"
    assert result.hit_rate_by_convention["pixels"] < 1.0


def test_browser_blocks_other_hosts(portal_url: str) -> None:
    with BrowserSession(portal_url, ("127.0.0.1",)) as session:
        session.goto("/login")
        session.page.evaluate("fetch('https://exfiltration.example/x').catch(() => null)")
        session.page.wait_for_timeout(300)
        assert any("exfiltration.example" in u for u in session.blocked)
        try:
            session.goto("https://exfiltration.example/")
        except Exception as exc:  # noqa: BLE001
            assert "non autorisé" in str(exc)
        else:
            raise AssertionError("navigation should be blocked")
        try:
            session.key("ctrl+l")
        except ValueError:
            pass
        else:
            raise AssertionError("browser shortcuts should be refused")
