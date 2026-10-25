from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from services.admissions_agent.api_client import HospitalOSClient
from services.admissions_agent.browser import BrowserSession
from services.admissions_agent.config import AgentSettings, EngineEndpoint
from services.admissions_agent.demo_portal import app as portal_module
from services.admissions_agent.runner import Agent
from services.admissions_smr.clock import Clock
from services.admissions_smr.config import Settings
from services.admissions_smr.main import create_app
from services.admissions_smr.models import BedPool, Group, Site, User
from services.admissions_smr.security import hash_password

PASSWORD = "mot-de-passe-solide"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def portal_url() -> Iterator[str]:
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(portal_module.app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


@pytest.fixture
def portal(portal_url: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=portal_url) as client:
        client.post("/_test/reset")
        yield client


@pytest.fixture
def api(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        secret_key="t" * 40,
        token_ttl_minutes=60,
        password_iterations=1000,
        timezone="Europe/Paris",
        cors_origins=(),
    )
    app = create_app(settings, Clock("Europe/Paris"))
    with TestClient(app) as client:
        session = app.state.session_factory()
        now = datetime.now(UTC)
        group = Group(name="Groupe agent", created_at=now)
        session.add(group)
        session.flush()
        site = Site(
            group_id=group.id, name="SMR Test", capabilities="oxygene,tracheotomie", created_at=now
        )
        session.add(site)
        session.flush()
        for mention in ("geriatrie", "locomoteur", "neuro"):
            site.pools.append(
                BedPool(
                    site_id=site.id,
                    mention=mention,
                    beds_installed=20,
                    beds_open=20,
                    isolation_rooms=2,
                    updated_at=now,
                )
            )
        for email, role in (
            ("agent@test.fr", "ingestion"),
            ("coord@test.fr", "coordination"),
            ("admin@test.fr", "admin_groupe"),
        ):
            session.add(
                User(
                    group_id=group.id,
                    email=email,
                    full_name=email,
                    role=role,
                    password_hash=hash_password(PASSWORD, 1000),
                    created_at=now,
                )
            )
        session.commit()
        session.close()
        yield client


def login(api: TestClient, email: str) -> dict[str, str]:
    token = api.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def make_agent(api: TestClient, portal_url: str) -> Callable[..., Agent]:
    def factory(
        engine_factory: Any = None,
        engines: dict[str, EngineEndpoint] | None = None,
        playbook_path: str | None = None,
    ) -> Agent:
        settings = AgentSettings(
            api_url="http://testserver",
            api_email="agent@test.fr",
            api_password=PASSWORD,
            agent_id="agent-test",
            portal_url=portal_url,
            portal_username="demo",
            portal_password="demo-portail",
            playbook_path=playbook_path
            or str(Path(portal_module.__file__).parent.parent / "playbooks" / "demo_portal.yaml"),
            allowed_hosts=("127.0.0.1",),
            max_steps=12,
            engines=engines or {},
        )
        agent = Agent(settings, HospitalOSClient(api, "agent@test.fr", PASSWORD), engine_factory)
        sessions: list[BrowserSession] = []
        original = agent.router.session_factory

        def tracked() -> BrowserSession:
            session = original()
            sessions.append(session)
            return session

        agent.router.session_factory = tracked
        agent.sessions = sessions  # type: ignore[attr-defined]
        return agent

    return factory
