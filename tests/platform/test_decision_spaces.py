"""The 24-hour planner engine keeps one isolated space per pilot account (X-HospitalOS-User)."""

from __future__ import annotations

import importlib.util
import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def server() -> Iterator[tuple[ModuleType, str]]:
    spec = importlib.util.spec_from_file_location("decision_serve", ROOT / "web/decision/serve.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield mod, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(base: str, path: str, user: str | None, body: dict[str, object] | None = None) -> Any:
    headers = {"Content-Type": "application/json"} | ({"X-HospitalOS-User": user} if user else {})
    data = None if body is None else json.dumps(body).encode()
    with urlopen(Request(base + path, data=data, headers=headers)) as response:  # noqa: S310 (loopback)
        return json.loads(response.read())


def test_injected_events_stay_in_their_space(server: tuple[ModuleType, str]) -> None:
    mod, base = server
    events = call(base, "/api/units", "alice")["events"]
    event = next(e for e in events if e["unit"] == "nominal_auto")
    before = call(base, "/api/auto?unit=nominal_auto", "bob")["snapshot"]["fingerprint"]
    call(base, "/api/inject", "alice", {"unit": "nominal_auto", "event": event["id"]})
    assert mod.state_for("alice").injected["nominal_auto"]
    assert mod.state_for("bob").injected["nominal_auto"] == []
    assert mod.state_for(None).injected["nominal_auto"] == []
    after = call(base, "/api/auto?unit=nominal_auto", "bob")["snapshot"]["fingerprint"]
    assert before == after


def test_spaces_are_bounded(server: tuple[ModuleType, str]) -> None:
    mod, _ = server
    for i in range(mod.MAX_SPACES + 5):
        mod.state_for(f"user-{i}")
    assert len(mod._SPACES) == mod.MAX_SPACES
