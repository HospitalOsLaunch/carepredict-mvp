"""Prepare and serve the built React cockpit and both real APIs behind one local port."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.util
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import venv
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parent
DEPS = WEB / "dev/requirements-demo.txt"


def setup() -> str:
    if sys.version_info < (3, 11):  # noqa: UP036 — invoked by users before project installation
        raise SystemExit("Le cockpit requiert Python 3.11 ou plus récent.")
    if not all(shutil.which(name) for name in ("node", "npm", "c++")):
        raise SystemExit("Installez Node.js 22 ou plus récent, npm et un compilateur C++17.")
    major = int(
        subprocess.check_output(["node", "-p", "process.versions.node.split('.')[0]"], text=True)
    )
    if major < 22:
        raise SystemExit("Le cockpit requiert Node.js 22 ou plus récent.")
    python = sys.executable
    if not all(
        importlib.util.find_spec(m) for m in ("fastapi", "pydantic", "numpy", "sklearn", "uvicorn")
    ):
        sandbox = WEB / ".demo-venv"
        python = str(sandbox / "bin/python")
        stamp = sandbox / "requirements.sha256"
        wanted = hashlib.sha256(DEPS.read_bytes()).hexdigest()
        if not Path(python).exists():
            venv.create(sandbox, with_pip=True)
        if not stamp.exists() or stamp.read_text() != wanted:
            subprocess.run([python, "-m", "pip", "install", "-r", str(DEPS)], check=True)
            stamp.write_text(wanted)
    lock = hashlib.sha256((WEB / "package-lock.json").read_bytes()).hexdigest()
    installed = WEB / "node_modules/.hospitalos-demo-lock"
    if (
        not installed.exists()
        or installed.read_text() != lock
        or not (WEB / "node_modules/vite/bin/vite.js").is_file()
    ):
        subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=WEB, check=True)
        installed.write_text(lock)
    # Always rebuild tracked sources so a new checkout or branch is presented immediately.
    subprocess.run(
        ["npm", "run", "build"],
        cwd=WEB,
        check=True,
    )
    return python


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(proc: subprocess.Popen, port: int, path: str) -> None:
    start = time.monotonic()
    while time.monotonic() - start < 40:
        if proc.poll() is not None:
            raise RuntimeError(f"Le service sur le port {port} s’est arrêté ({proc.returncode}).")
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
        try:
            connection.request("GET", path)
            if connection.getresponse().status == 200:
                return
        except OSError:
            pass
        finally:
            connection.close()
        time.sleep(0.2)
    raise RuntimeError(f"Le service sur le port {port} n’a pas répondu.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    python = setup()
    if args.prepare_only:
        return
    with socket.socket() as available:
        try:
            available.bind(("127.0.0.1", args.port))
        except OSError:
            raise SystemExit(
                f"Le port {args.port} est déjà occupé. Choisissez un autre port avec --port."
            ) from None
    children: list[subprocess.Popen] = []

    def stop(_signal: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        api_port = free_port()
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT / "src"), str(ROOT))))
        api = subprocess.Popen(
            [python, "web/dev/serve_demo_api.py", "--port", str(api_port)], cwd=ROOT, env=env
        )
        children.append(api)
        wait_ready(api, api_port, "/world-model/contexts")
        decision_port = free_port()
        decision = subprocess.Popen(
            [python, "web/decision/serve.py", "--port", str(decision_port)], cwd=ROOT, env=env
        )
        children.append(decision)
        wait_ready(decision, decision_port, "/api/units")
        env.update(HOSPITALOS_API_PORT=str(api_port), HOSPITALOS_DECISION_PORT=str(decision_port))
        space = os.getenv("CODESPACE_NAME")
        domain = os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
        if space and domain:
            env["__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS"] = f"{space}-{args.port}.{domain}"
        web = subprocess.Popen(
            [
                "node",
                "node_modules/vite/bin/vite.js",
                "preview",
                "--host",
                "127.0.0.1",
                "--strictPort",
                "--port",
                str(args.port),
            ],
            cwd=WEB,
            env=env,
        )
        children.append(web)
        wait_ready(web, args.port, "/api/world-model/contexts")
        url = (
            f"https://{space}-{args.port}.{domain}"
            if space and domain
            else f"http://127.0.0.1:{args.port}"
        )
        print(f"\nHospitalOS · Démo de simulation prête\n{url}/#/\n", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        raise RuntimeError("Un service du cockpit s’est arrêté. Relancez le démonstrateur.")
    except KeyboardInterrupt:
        pass
    finally:
        # The foreground process group and its parent Make can both forward the same stop.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=4)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
