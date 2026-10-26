"""Agent settings, from the environment of the machine that runs the agent.

Secrets (portal password, API keys) live here and only here: the HospitalOS API never
stores them, and model engines never see the portal credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True)
class EngineEndpoint:
    """Where an engine runs. Absent endpoint = engine not configured on this agent."""

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    coordinates: str = "normalized_1000"  # open models: "normalized_1000" or "pixels"


@dataclass(frozen=True)
class AgentSettings:
    api_url: str
    api_email: str
    api_password: str
    agent_id: str
    portal_url: str
    portal_username: str
    portal_password: str
    playbook_path: str
    allowed_hosts: tuple[str, ...]
    headless: bool = True
    viewport: tuple[int, int] = (1280, 800)
    max_steps: int = 40
    heartbeat_seconds: int = 60
    engines: dict[str, EngineEndpoint] = field(default_factory=dict)

    @property
    def portal_host(self) -> str:
        return urlparse(self.portal_url).hostname or ""


def _endpoint(prefix: str) -> EngineEndpoint:
    return EngineEndpoint(
        base_url=os.getenv(f"{prefix}_URL") or None,
        api_key=os.getenv(f"{prefix}_API_KEY") or None,
        model=os.getenv(f"{prefix}_MODEL") or None,
        coordinates=os.getenv(f"{prefix}_COORDINATES", "normalized_1000"),
    )


def load_settings() -> AgentSettings:
    portal_url = os.getenv("AGENT_PORTAL_URL", "http://127.0.0.1:8020")
    hosts = os.getenv("AGENT_ALLOWED_HOSTS", "")
    allowed = tuple(h.strip() for h in hosts.split(",") if h.strip()) or (
        urlparse(portal_url).hostname or "",
    )
    anthropic = EngineEndpoint(
        base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        api_key=os.getenv("ANTHROPIC_API_KEY") or None,
    )
    return AgentSettings(
        api_url=os.getenv("AGENT_API_URL", "http://127.0.0.1:8010"),
        api_email=os.getenv("AGENT_API_EMAIL", ""),
        api_password=os.getenv("AGENT_API_PASSWORD", ""),
        agent_id=os.getenv("AGENT_ID", os.uname().nodename),
        portal_url=portal_url,
        portal_username=os.getenv("AGENT_PORTAL_USERNAME", ""),
        portal_password=os.getenv("AGENT_PORTAL_PASSWORD", ""),
        playbook_path=os.getenv(
            "AGENT_PLAYBOOK",
            os.path.join(os.path.dirname(__file__), "playbooks", "demo_portal.yaml"),
        ),
        allowed_hosts=allowed,
        headless=os.getenv("AGENT_HEADLESS", "1") != "0",
        max_steps=int(os.getenv("AGENT_MAX_STEPS", "40")),
        heartbeat_seconds=max(5, int(os.getenv("AGENT_HEARTBEAT_SECONDS", "60"))),
        engines={
            "open_light": _endpoint("OPEN_LIGHT"),
            "open_heavy": _endpoint("OPEN_HEAVY"),
            "closed_fast": anthropic,
            "closed_best": anthropic,
        },
    )
