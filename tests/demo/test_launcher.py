"""Lifecycle failures must not attach to or terminate unrelated local services."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

import demo


def sleeper() -> subprocess.Popen[bytes]:
    return demo.start(
        [sys.executable, "-c", "import time; time.sleep(60)"], Path.cwd(), dict(os.environ)
    )


def test_occupied_port_rejected_before_install_and_existing_listener_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        monkeypatch.setattr(demo, "tools", lambda: (sys.executable, sys.executable))

        def unexpected(*args: object) -> Path:
            raise AssertionError("must not install or launch when a port is occupied")

        monkeypatch.setattr(demo, "prepare", unexpected)
        assert demo.main(["--port", str(port), "--api-port", "8001"]) == 1
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass


def test_same_port_rejected() -> None:
    with pytest.raises(demo.DemoError, match="distincts"):
        demo.check_ports([8000, 8000])


def test_other_api_never_counts_as_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo, "request", lambda url: {"status": "ok", "mode": "shadow"})
    with pytest.raises(demo.DemoError, match="n'est pas celle du simulateur"):
        demo.wait_ready("http://unused.test", [])


def test_early_exit_detected_without_waiting_for_http() -> None:
    child = demo.start([sys.executable, "-c", "raise SystemExit(7)"], Path.cwd(), dict(os.environ))
    child.wait(timeout=5)
    with pytest.raises(demo.DemoError, match="code 7"):
        demo.wait_ready("http://unused.test", [child])


def test_stop_only_terminates_owned_services() -> None:
    owned = [sleeper(), sleeper()]
    unrelated = sleeper()
    try:
        demo.stop(owned)
        assert all(child.poll() is not None for child in owned)
        assert unrelated.poll() is None
    finally:
        demo.stop([*owned, unrelated])


def test_failure_starting_cockpit_stops_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    child = sleeper()
    calls = 0

    def launch(*args: object) -> subprocess.Popen[bytes]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("cockpit launch failed")
        return child

    monkeypatch.setattr(demo, "tools", lambda: (sys.executable, sys.executable))
    monkeypatch.setattr(demo, "prepare", lambda *args: Path(sys.executable))
    monkeypatch.setattr(demo, "check_ports", lambda ports: None)
    monkeypatch.setattr(demo, "wait_ready", lambda *args: None)
    monkeypatch.setattr(demo, "start", launch)
    try:
        assert demo.main(["--no-browser"]) == 1
        assert child.poll() is not None
    finally:
        demo.stop([child])
