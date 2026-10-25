"""The agent loop: heartbeat, periodic inbox sync, claim and route tasks."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from services.admissions_agent import __version__
from services.admissions_agent.api_client import HospitalOSClient
from services.admissions_agent.browser import BrowserSession
from services.admissions_agent.config import AgentSettings
from services.admissions_agent.engines.anthropic_cu import AnthropicComputerUse
from services.admissions_agent.engines.base import VisionEngine
from services.admissions_agent.engines.openai_vlm import OpenWeightsVision
from services.admissions_agent.playbook import Playbook, Transforms
from services.admissions_agent.router import Router

log = logging.getLogger("admissions_agent")


def default_engine_factory(settings: AgentSettings) -> Any:
    def build(name: str, engine: dict[str, Any]) -> VisionEngine | None:
        endpoint = settings.engines.get(name)
        if endpoint is None:
            return None
        if engine["kind"] == "anthropic":
            if not endpoint.api_key:
                return None
            return AnthropicComputerUse(
                name,
                engine.get("model") or "claude-sonnet-5-5",
                endpoint.api_key,
                httpx.Client(base_url=endpoint.base_url or "https://api.anthropic.com"),
                engine.get("input_usd_per_mtok", 0.0),
                engine.get("output_usd_per_mtok", 0.0),
            )
        if engine["kind"] == "openai_compatible":
            if not endpoint.base_url:
                return None
            return OpenWeightsVision(
                name,
                endpoint.model or engine.get("model") or "",
                httpx.Client(base_url=endpoint.base_url),
                endpoint.api_key,
                endpoint.coordinates,
                engine.get("input_usd_per_mtok", 0.0),
                engine.get("output_usd_per_mtok", 0.0),
                engine.get("usd_per_hour", 0.0),
            )
        return None

    return build


class Agent:
    def __init__(
        self, settings: AgentSettings, api: HospitalOSClient, engine_factory: Any | None = None
    ) -> None:
        self.settings = settings
        self.api = api
        self.playbook = Playbook.load(settings.playbook_path)
        self.transforms = Transforms(api.vocabulary())
        self.router = Router(
            settings,
            api,
            self.playbook,
            self.transforms,
            engine_factory or default_engine_factory(settings),
            self.new_session,
        )
        self.last_sync = 0.0

    def new_session(self) -> BrowserSession:
        return BrowserSession(
            self.settings.portal_url,
            self.settings.allowed_hosts,
            self.settings.viewport,
            self.settings.headless,
        )

    def engine_reports(self) -> list[dict[str, Any]]:
        reports = [{"name": "playbook", "configured": True, "detail": self.playbook.name}]
        for name, endpoint in self.settings.engines.items():
            if name.startswith("closed"):
                configured = bool(endpoint.api_key)
                detail = "clé API Anthropic présente" if configured else "ANTHROPIC_API_KEY absente"
            else:
                configured = bool(endpoint.base_url)
                detail = (
                    f"{endpoint.base_url} ({endpoint.coordinates})"
                    if configured
                    else "point d'accès non renseigné"
                )
            reports.append({"name": name, "configured": configured, "detail": detail})
        return reports

    def cycle(self) -> int:
        """One heartbeat, an inbox sync if due, then every claimable task. Returns tasks handled."""
        beat = self.api.heartbeat(self.settings.agent_id, __version__, self.engine_reports())
        if beat["paused"]:
            log.info("agent en pause")
            return 0
        interval = int(beat["policy"]["sync_interval_minutes"]) * 60
        if time.monotonic() - self.last_sync >= interval or self.last_sync == 0.0:
            self.api.request_sync()
            self.last_sync = time.monotonic()
        handled = 0
        while True:
            tasks = self.api.claim(self.settings.agent_id, limit=1)
            if not tasks:
                break
            for task in tasks:
                outcome = self.router.handle(task, beat)
                self.api.complete(
                    task["id"], outcome.status, outcome.engine, outcome.result, outcome.error
                )
                log.info(
                    "tâche %s %s : %s (%s)",
                    task["id"],
                    task["kind"],
                    outcome.status,
                    outcome.engine,
                )
                handled += 1
            beat = self.api.heartbeat(self.settings.agent_id, __version__, self.engine_reports())
            if beat["paused"]:
                break
        return handled

    def run_forever(self) -> None:
        while True:
            try:
                self.cycle()
            except Exception:  # noqa: BLE001 - keep the agent alive, the API shows it offline
                log.exception("cycle en erreur")
            time.sleep(self.settings.heartbeat_seconds)
