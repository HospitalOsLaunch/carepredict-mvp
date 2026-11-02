"""Agent settings, from the environment of the machine that runs the agent.

Minimal install: ``AGENT_API_URL``, ``AGENT_API_EMAIL``, ``AGENT_API_PASSWORD`` and
``AGENT_ID`` (plus technical knobs). The software to read, its credentials, the playbook
and the schedule come from the connections set up in HospitalOS; the password arrives
with each claimed task, stays in memory for that task only and is never written or
logged. Model engines never see the credentials.

Legacy mode: when HospitalOS returns no connection for this worker and
``AGENT_PORTAL_URL`` is set, the ``AGENT_PORTAL_*`` / ``AGENT_PLAYBOOK`` /
``AGENT_ALLOWED_HOSTS`` variables describe one implicit connection, as before.
"""

from __future__ import annotations

import ipaddress
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
    # Legacy mode only (empty portal_url: connections from HospitalOS only).
    portal_url: str = ""
    portal_username: str = ""
    portal_password: str = ""
    playbook_path: str = ""
    allowed_hosts: tuple[str, ...] = ()
    playbooks_dir: str = os.path.join(os.path.dirname(__file__), "playbooks")
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


def checked_api_url(url: str) -> str:
    """HTTPS, except to this machine or to an internal name without a dot (a compose
    service such as ``api``): the service account's password travels on it (REVIEW S-L2)."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    internal = bool(host) and "." not in host and ":" not in host
    if parsed.scheme == "https" or (parsed.scheme == "http" and (loopback or internal)):
        return url
    raise ValueError(
        "AGENT_API_URL doit être en https (http accepté seulement vers la machine locale "
        "ou un nom de service interne)"
    )


def load_settings() -> AgentSettings:
    portal_url = os.getenv("AGENT_PORTAL_URL", "")
    hosts = os.getenv("AGENT_ALLOWED_HOSTS", "")
    allowed = tuple(h.strip() for h in hosts.split(",") if h.strip()) or tuple(
        filter(None, [urlparse(portal_url).hostname])
    )
    anthropic = EngineEndpoint(
        base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        api_key=os.getenv("ANTHROPIC_API_KEY") or None,
    )
    return AgentSettings(
        api_url=checked_api_url(os.getenv("AGENT_API_URL", "http://127.0.0.1:8010")),
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
        playbooks_dir=os.getenv("AGENT_PLAYBOOKS_DIR", AgentSettings.playbooks_dir),
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
