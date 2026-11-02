"""The agent loop: heartbeat (with the playbook catalogue), claim and route tasks.

HospitalOS decides what to read and when: each claimed task of a connection carries the
software's address, allowed hosts, credentials and playbook name. The worker only picks
that playbook in its own bundled catalogue. Legacy mode (no connection for this worker,
``AGENT_PORTAL_URL`` set): the worker asks for its syncs itself, as before.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from services.admissions_agent import __version__
from services.admissions_agent.api_client import ApiError, HospitalOSClient
from services.admissions_agent.browser import BrowserSession
from services.admissions_agent.config import AgentSettings
from services.admissions_agent.engines.anthropic_cu import AnthropicComputerUse
from services.admissions_agent.engines.base import VisionEngine
from services.admissions_agent.engines.openai_vlm import OpenWeightsVision
from services.admissions_agent.playbook import Playbook, Transforms, load_catalogue
from services.admissions_agent.router import Router, TaskOutcome

log = logging.getLogger("admissions_agent")
SYNC_KINDS = ("sync_inbox", "sync_movements")
AGENT_KINDS = (*SYNC_KINDS, "reply_portal")


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
        self.engine_factory = engine_factory or default_engine_factory(settings)
        self.catalogue = load_catalogue(settings.playbooks_dir)
        self.transforms = Transforms(api.vocabulary())
        # Legacy mode: one implicit connection described by environment variables.
        self.playbook: Playbook | None = None
        if settings.portal_url:
            self.playbook = Playbook.load(
                settings.playbook_path or os.path.join(settings.playbooks_dir, "demo_portal.yaml")
            )
        self.router = Router(
            settings,
            api,
            self.playbook or Playbook({}),
            self.transforms,
            self.engine_factory,
            self.new_session,
        )
        self.last_sync = 0.0
        # Legacy: only the task kinds this machine's playbook knows.
        self.kinds = [k for k in AGENT_KINDS if self.playbook and self.playbook.supports(k)]
        self.legacy = False

    def new_session(self) -> BrowserSession:
        return BrowserSession(
            self.settings.portal_url,
            self.settings.allowed_hosts,
            self.settings.viewport,
            self.settings.headless,
        )

    def playbooks_report(self) -> list[dict[str, Any]]:
        return [p.info() for p in self.catalogue.values()]

    def router_for(self, task: dict[str, Any]) -> Router | str:
        """The router for this task, or why it cannot run on this machine."""
        conn = task.get("connection")
        if conn is None:
            if self.playbook is None:
                return "Tâche sans connexion : ce poste n'a pas de configuration historique"
            return self.router
        playbook = self.catalogue.get(str(conn["playbook"]))
        if playbook is None or not playbook.supports(task["kind"]):
            return "Script de la connexion absent du catalogue de ce poste"
        url, hosts = str(conn["url"]), tuple(conn["allowed_hosts"])

        def session() -> BrowserSession:
            return BrowserSession(url, hosts, self.settings.viewport, self.settings.headless)

        return Router(
            self.settings,
            self.api,
            playbook,
            self.transforms,
            self.engine_factory,
            session,
            credentials={
                "username": conn.get("username") or "",
                "password": conn.get("secret") or "",
            },
            source_system=conn.get("source_system"),
        )

    def beat(self) -> dict[str, Any]:
        return self.api.heartbeat(
            self.settings.agent_id, __version__, self.engine_reports(), self.playbooks_report()
        )

    def engine_reports(self) -> list[dict[str, Any]]:
        detail = (
            self.playbook.name
            if self.playbook
            else f"{len(self.catalogue)} script(s) embarqué(s) : {', '.join(self.catalogue)}"
        )
        reports = [{"name": "playbook", "configured": True, "detail": detail}]
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
        """One heartbeat (HospitalOS creates the syncs that are due), then every claimable
        task. Legacy mode asks for its own syncs. Returns the number of tasks handled."""
        beat = self.beat()
        if beat["paused"]:
            log.info("agent en pause")
            return 0
        self.legacy = not beat.get("connections") and self.playbook is not None
        if self.legacy:
            interval = int(beat["policy"]["sync_interval_minutes"]) * 60
            if time.monotonic() - self.last_sync >= interval or self.last_sync == 0.0:
                for kind in SYNC_KINDS:
                    if kind in self.kinds:
                        self.api.request_sync(kind)
                self.last_sync = time.monotonic()
        kinds = self.kinds if self.legacy else list(AGENT_KINDS)
        handled = 0
        while True:
            tasks = self.api.claim(
                self.settings.agent_id, limit=1, kinds=kinds, legacy=self.playbook is not None
            )
            if not tasks:
                break
            for task in tasks:
                try:
                    router = self.router_for(task)
                    if isinstance(router, str):
                        outcome = TaskOutcome("failed", None, error=router)
                    else:
                        outcome = router.handle(task, beat)
                except Exception as exc:  # noqa: BLE001 - isolate a broken task from the queue
                    log.exception("exécution interrompue de la tâche %s", task["id"])
                    outcome = TaskOutcome(
                        "needs_human" if task["kind"] == "reply_portal" else "failed",
                        None,
                        error=f"Exécution interrompue : {type(exc).__name__}",
                    )
                try:
                    self.api.complete(
                        task["id"], outcome.status, outcome.engine, outcome.result, outcome.error
                    )
                except ApiError:
                    # A revoked/expired lease cannot be completed by its former worker.
                    log.warning("fin de tâche %s non confirmée par HospitalOS", task["id"])
                finally:
                    self.api.leases.pop(task["id"], None)
                    task.pop("connection", None)  # the password lives for one task only
                log.info(
                    "tâche %s %s : %s (%s)",
                    task["id"],
                    task["kind"],
                    outcome.status,
                    outcome.engine,
                )
                handled += 1
            beat = self.beat()
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
