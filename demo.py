#!/usr/bin/env python3
"""Launch HospitalOS with autonomous virtual hospitals; laboratory mode is explicit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from types import FrameType
from typing import Any

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".venv-demo"
WEB = ROOT / "web"
REQUIREMENTS = ROOT / "requirements-demo.txt"


class DemoError(Exception):
    """An actionable setup or launch failure."""


def say(message: str) -> None:
    print(f"[HospitalOS] {message}", flush=True)


def checked(command: Sequence[str], cwd: Path = ROOT) -> None:
    try:
        subprocess.run(command, cwd=cwd, check=True)
    except subprocess.CalledProcessError as error:
        raise DemoError(
            f"Échec de {command[0]} (code {error.returncode}). Voir le détail ci-dessus."
        ) from error


def tools() -> tuple[str, str]:
    node, npm = shutil.which("node"), shutil.which("npm")
    if node is None or npm is None:
        raise DemoError(
            "Node.js 22 ou supérieur et npm sont nécessaires. Installez-les puis relancez."
        )
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if int(version.removeprefix("v").split(".")[0]) < 22:
        raise DemoError(f"Node.js {version} détecté ; la démo requiert Node.js 22 ou supérieur.")
    return node, npm


def fingerprint(paths: Sequence[Path]) -> str:
    return hashlib.sha256(b"\0".join(p.read_bytes() for p in paths)).hexdigest()


def matches(path: Path, value: str) -> bool:
    return path.is_file() and path.read_text().strip() == value


def prepare(npm: str, install: bool) -> Path:
    python = ENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python_stamp = ENV / ".hospitalos-requirements"
    python_key = fingerprint([REQUIREMENTS])
    node_stamp = WEB / "node_modules/.hospitalos-package-lock"
    node_key = fingerprint([WEB / "package.json", WEB / "package-lock.json"])
    if not install:
        if not python.is_file() or not matches(python_stamp, python_key):
            raise DemoError("Dépendances Python absentes ou modifiées. Relancez sans --no-install.")
        if not (WEB / "node_modules/vite/bin/vite.js").is_file() or not matches(
            node_stamp, node_key
        ):
            raise DemoError(
                "Dépendances du cockpit absentes ou modifiées. Relancez sans --no-install."
            )
        return python
    if not python.is_file():
        if ENV.exists() and any(ENV.iterdir()):
            raise DemoError(".venv-demo est incomplet. Retirez ce dossier dédié puis relancez.")
        say("Création de l'environnement Python dédié .venv-demo…")
        venv.EnvBuilder(with_pip=True).create(ENV)
    if not matches(python_stamp, python_key):
        say("Installation des dépendances Python de la démo…")
        checked(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(REQUIREMENTS),
            ]
        )
        python_stamp.write_text(python_key + "\n")
    if not (WEB / "node_modules/vite/bin/vite.js").is_file() or not matches(node_stamp, node_key):
        say("Installation du cockpit depuis package-lock.json…")
        checked([npm, "ci", "--no-audit", "--no-fund"], WEB)
        node_stamp.write_text(node_key + "\n")
    return python


def port_number(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 65535:
        raise argparse.ArgumentTypeError("le port doit être compris entre 1 et 65535")
    return number


def check_ports(ports: Sequence[int]) -> None:
    if len(set(ports)) != len(ports):
        raise DemoError("Le cockpit et le backend doivent utiliser deux ports distincts.")
    for port in ports:
        with socket.socket() as probe:
            if os.name != "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as error:
                raise DemoError(
                    f"Le port {port} est occupé ou indisponible. Arrêtez votre ancien serveur "
                    "ou choisissez --port et --api-port. Aucun processus existant n'a été arrêté."
                ) from error


def choose_port(requested: int | None, default: int, excluded: int = 0) -> int:
    if requested is not None:
        return requested
    for candidate in range(default, default + 20):
        if candidate == excluded:
            continue
        try:
            check_ports([candidate])
        except DemoError:
            continue
        if candidate != default:
            say(f"Port {default} occupé : utilisation du port libre {candidate}.")
        return candidate
    raise DemoError("Aucun port libre à proximité. Choisissez --port et --api-port.")


def start(command: Sequence[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(command, cwd=cwd, env=env, start_new_session=os.name != "nt")


def alive(children: Sequence[subprocess.Popen[bytes]]) -> None:
    for child in children:
        result = child.poll()
        if result is not None:
            raise DemoError(f"Un service s'est arrêté (code {result}). Voir son message ci-dessus.")


def request(url: str, body: bytes | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as response:
        result: Any = json.load(response)
    if not isinstance(result, dict):
        raise DemoError("Le serveur n'a pas renvoyé une session valide.")
    return result


def wait_ready(
    url: str,
    children: Sequence[subprocess.Popen[bytes]],
    timeout: float = 180,
    virtual: bool = False,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive(children)
        try:
            view = request(url)
            if virtual:
                if (
                    view.get("schema_version") == "HOSPITAL_WORKSPACE_1"
                    and view.get("synthetic") is True
                    and view.get("hospitals")
                ):
                    return
                raise DemoError("Le backend joint ne fournit pas les hôpitaux virtuels attendus.")
            if (
                view.get("schema_version") == "DYNAMIC_DEMO_1"
                and view.get("mode") == "simulation_sandbox"
            ):
                return
            raise DemoError("L'API jointe n'est pas celle du simulateur HospitalOS.")
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.2)
    raise DemoError(
        f"Le backend n’est pas prêt après {timeout:g} secondes. Voir les messages des services."
    )


def stop(children: Sequence[subprocess.Popen[bytes]]) -> None:
    for child in reversed(children):
        if child.poll() is None:
            with suppress(ProcessLookupError):
                # Let Vite close its compiler before resorting to group termination.
                child.terminate()
    for child in reversed(children):
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "nt":
                    child.kill()
                else:
                    os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()


def interrupted(signum: int, frame: FrameType | None) -> None:
    raise KeyboardInterrupt


def check_cockpit(origin: str) -> None:
    # Request the entry and its bundled dependencies, as a browser would. This
    # also lets Vite finish its initial dependency scan before --check shuts down.
    with urllib.request.urlopen(origin, timeout=20) as response:
        response.read()
    with urllib.request.urlopen(f"{origin}/src/main.tsx", timeout=20) as response:
        entry = response.read().decode()
    for dependency in set(re.findall(r"""from ["'](/node_modules/[^"']+)["']""", entry)):
        with urllib.request.urlopen(origin + dependency, timeout=20) as response:
            response.read()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=port_number, default=None, help="port du cockpit (5173)")
    parser.add_argument("--api-port", type=port_number, default=None, help="port du backend (8000)")
    parser.add_argument("--seed", type=int, default=7, help="graine du scénario (7)")
    parser.add_argument("--no-browser", action="store_true", help="afficher le lien sans l'ouvrir")
    parser.add_argument(
        "--setup-only", action="store_true", help="préparer les dépendances puis quitter"
    )
    parser.add_argument(
        "--no-install", action="store_true", help="exiger les dépendances déjà préparées"
    )
    parser.add_argument(
        "--check", action="store_true", help="vérifier la boucle HTTP puis tout arrêter"
    )
    parser.add_argument("--lab", action="store_true", help="ouvrir le laboratoire de simulation")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=ROOT / ".hospitalos-campus",
        help="état persistant des établissements virtuels",
    )
    parser.add_argument(
        "--clock-rate", type=float, default=1, help="horloge produit temps réel (1)"
    )
    args = parser.parse_args(argv)
    if not args.lab and args.clock_rate != 1:
        parser.error("le produit utilise le temps réel : clock-rate doit être 1")
    if not 0 < args.clock_rate <= 60:
        parser.error("clock-rate doit être entre 0 (exclu) et 60")
    if not 0 <= args.seed <= 1_000_000_000:
        parser.error("seed doit être compris entre 0 et 1000000000")
    if args.setup_only and args.check:
        parser.error("--setup-only et --check sont incompatibles")
    children: list[subprocess.Popen[bytes]] = []
    previous_term = signal.signal(signal.SIGTERM, interrupted)
    try:
        if sys.version_info < (3, 11):  # noqa: UP036 -- entry point before package installation
            raise DemoError("Python 3.11 ou supérieur est nécessaire.")
        node, npm = tools()
        if not args.setup_only:
            args.api_port = choose_port(args.api_port, 8000, args.port or 0)
            args.port = choose_port(args.port, 5173, args.api_port)
            check_ports([args.port, args.api_port])
        python = prepare(npm, not args.no_install)
        if args.setup_only:
            say("Dépendances prêtes. Lancez python3 demo.py.")
            return 0
        env = dict(os.environ)
        env.update(
            PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT)]),
            PYTHONUNBUFFERED="1",
            HOSPITALOS_DEMO_API_PORT=str(args.api_port),
            VITE_HOSPITALOS_API="/api",
        )
        say("Démarrage du backend et du cockpit…")
        children.append(
            start(
                [
                    str(python),
                    str(
                        WEB
                        / ("dev/serve_simulator_api.py" if args.lab else "dev/serve_virtual_api.py")
                    ),
                    "--port",
                    str(args.api_port),
                    "--seed",
                    str(args.seed),
                    *(
                        []
                        if args.lab
                        else [
                            "--state-dir",
                            str(args.state_dir.resolve()),
                            "--clock-rate",
                            str(args.clock_rate),
                        ]
                    ),
                ],
                ROOT,
                env,
            )
        )
        endpoint = "/demo/session" if args.lab else "/product/hospitals"
        wait_ready(
            f"http://127.0.0.1:{args.api_port}{endpoint}",
            children,
            45 if args.lab else 180,
            not args.lab,
        )
        children.append(
            start(
                [
                    node,
                    str(WEB / "node_modules/vite/bin/vite.js"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.port),
                    "--strictPort",
                ],
                WEB,
                env,
            )
        )
        origin = f"http://127.0.0.1:{args.port}"
        wait_ready(f"{origin}/api{endpoint}", children, 45 if args.lab else 180, not args.lab)
        url = f"{origin}/?source={'simulator' if args.lab else 'virtual'}"
        if args.check:
            check_cockpit(origin)
            if not args.lab:
                catalog = request(f"{origin}/api/product/hospitals")
                for hospital in catalog["hospitals"]:
                    for entry in hospital["units"]:
                        path = (
                            f"{origin}/api/product/hospitals/{hospital['id']}/units/{entry['id']}"
                        )
                        unit = request(path)
                        history = request(path + "/history")
                        if (
                            unit.get("hospital_id") != hospital["id"]
                            or unit.get("unit_id") != entry["id"]
                            or unit["snapshot"]["issues"]
                            or unit["clock_rate"] != 1
                            or history["samples"] < 672
                        ):
                            raise DemoError("Flux, horloge ou historique hospitalier incomplet.")
                say(
                    "Vérification réussie : hôpital, quatre unités, "
                    "temps réel et historique. Arrêt."
                )
                return 0
            view = request(f"{origin}/api/demo/evaluate", b"{}")
            if not view.get("can_apply") or not view.get("episode"):
                raise DemoError("Le scénario initial n'a pas produit de proposition applicable.")
            pair = request(
                f"{origin}/api/demo/compare",
                b'{"horizon_minutes":1,"policy":"disabled"}',
            )
            if (
                pair.get("schema_version") != "PAIRED_DEMO_1"
                or pair.get("waiting_patient_minutes_saved") != 0
                or pair.get("physical_trajectories_identical") is not True
            ):
                raise DemoError("Le contrôle de neutralité A0/A1 a échoué.")
            say(
                "Vérification réussie : cockpit → proxy → simulateur → planificateur, "
                "comparaison A0/A1 neutre. "
                "Arrêt des services."
            )
            return 0
        say(f"Démo prête : {url}")
        say(
            "L’hôpital évolue en temps réel Paris. Choisissez votre unité. "
            "Ctrl+C arrête les services et conserve les décisions."
            if not args.lab
            else "Laboratoire : évaluer, décider, avancer. Ctrl+C arrête les services."
        )
        if not args.no_browser:
            try:
                webbrowser.open(url)
            except webbrowser.Error:
                say("Ouvrez le lien ci-dessus dans votre navigateur.")
        while True:
            alive(children)
            time.sleep(0.5)
    except KeyboardInterrupt:
        say("Arrêt de la démo.")
        return 130
    except (DemoError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"[HospitalOS] {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        stop(children)
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    raise SystemExit(main())
