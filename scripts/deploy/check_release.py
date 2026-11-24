#!/usr/bin/env python3
"""Release gate for the deployments (enclave: deploy/nantes, cloud: deploy/cloud).

    python scripts/deploy/check_release.py                  # compose + Dockerfiles
    python scripts/deploy/check_release.py --env FILE       # also the operator secrets file
    python scripts/deploy/check_release.py --compose FILE   # audit another file (the dev one fails)
    python scripts/deploy/check_release.py --profile cloud  # deploy/cloud/docker-compose.yml

Profiles: ``enclave`` (offline CHU, default) and ``cloud`` (Internet-facing VM, staging and
production). In the cloud profile only the ``edge`` service (Caddy, HTTPS) publishes ports, and
only 80/443; product images come from the registry as ``${REGISTRY}/hospitalos-*:${IMAGE_TAG}``
and are pulled at deployment (no pull_policy rule); read-only configuration files may sit next to
the compose file.

Rules (exit 1 and one line per violation):
  R1 third-party images pinned by digest, and the digest equals deploy/nantes/images.lock.json;
     built images named <repo>:${RELEASE_TAG...}; every FROM of their Dockerfiles pinned by digest
  R2 published ports bound to 127.0.0.1 only; datastores publish no port
  R3 no host bind-mount except read-only configuration under infrastructure/ or deploy/
  R4 secrets (*PASSWORD*, *SECRET*, *TOKEN*) are required variables `${VAR:?...}`, never
     defaulted or literal; env_file is never .env.example
  R5 every service has no-new-privileges, a restart policy and pull_policy never
  R6 datastores only on internal networks
  R7 (--env) no secret left to REPLACE_ME, empty, shorter than 16 characters or equal to a
     known development default
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/nantes/docker-compose.release.yml"
CLOUD_COMPOSE = ROOT / "deploy/cloud/docker-compose.yml"
CLOUD_IMAGE = re.compile(
    r"^\$\{REGISTRY(:\?[^}]*)?\}/hospitalos-[a-z]+:\$\{IMAGE_TAG(:\?[^}]*)?\}$"
)
LOCK = ROOT / "deploy/nantes/images.lock.json"
DATASTORES = {"timescaledb", "redis", "redpanda", "dagster-postgres"}
SECRET_KEY = re.compile(r"(PASSWORD|SECRET|TOKEN)", re.I)
REQUIRED_VAR = re.compile(r"^\$\{[A-Z0-9_]+:\?[^}]*\}$")
DEV_DEFAULTS = {
    "carepredict_dev_password",
    "dagster_dev_password",
    "password",
    "changeme",
    "replace_me",
}


def _strings(x: Any) -> list[str]:
    if isinstance(x, str):
        return [x]
    if isinstance(x, list):
        return [s for v in x for s in _strings(v)]
    if isinstance(x, dict):
        return [s for v in x.values() for s in _strings(v)]
    return []


def check_compose(path: Path, profile: str = "enclave") -> list[str]:
    cloud = profile == "cloud"
    doc = yaml.safe_load(path.read_text())
    pins = json.loads(LOCK.read_text())["images"]
    nets = doc.get("networks") or {}
    out: list[str] = []
    for name, svc in (doc.get("services") or {}).items():
        img = str(svc.get("image", ""))
        build = svc.get("build")
        # R1
        if build is not None:
            if not re.search(r":\$\{RELEASE_TAG(:\?[^}]*)?\}$", img):
                out.append(f"R1 {name}: built image must be tagged ${{RELEASE_TAG}} (got {img!r})")
            ctx = (
                path.parent / (build.get("context", ".") if isinstance(build, dict) else build)
            ).resolve()
            dockerfile = ctx / (
                build.get("dockerfile", "Dockerfile") if isinstance(build, dict) else "Dockerfile"
            )
            for line in dockerfile.read_text().splitlines():
                if line.strip().upper().startswith("FROM ") and "@sha256:" not in line:
                    out.append(
                        f"R1 {name}: base image not pinned by digest in "
                        f"{dockerfile.relative_to(ROOT)}: {line.strip()}"
                    )
        elif cloud and img.startswith("${REGISTRY"):
            if not CLOUD_IMAGE.match(img):
                out.append(
                    f"R1 {name}: registry image must be ${{REGISTRY}}/hospitalos-*:${{IMAGE_TAG}}"
                )
        elif img.startswith("hospitalos/"):
            if not re.search(r":\$\{RELEASE_TAG(:\?[^}]*)?\}$", img):
                out.append(
                    f"R1 {name}: product image must be tagged ${{RELEASE_TAG}} (got {img!r})"
                )
        else:
            ref, _, dig = img.partition("@")
            if not dig.startswith("sha256:"):
                out.append(f"R1 {name}: image not pinned by digest: {img}")
            elif pins.get(ref) != dig:
                out.append(f"R1 {name}: digest of {ref} differs from images.lock.json")
        # R2
        for p in svc.get("ports") or []:
            spec = (
                p
                if isinstance(p, str)
                else f"{p.get('host_ip', '')}:{p.get('published', '')}:{p.get('target', '')}"
            )
            if name in DATASTORES:
                out.append(f"R2 {name}: datastore publishes a host port ({spec})")
            elif cloud:
                if name != "edge" or str(spec).split("/")[0] not in ("80:80", "443:443"):
                    out.append(f"R2 {name}: only edge may publish, and only 80/443 ({spec})")
            elif not str(spec).startswith("127.0.0.1:"):
                out.append(f"R2 {name}: port not bound to 127.0.0.1 ({spec})")
        # R3
        for v in svc.get("volumes") or []:
            src = v.split(":")[0] if isinstance(v, str) else str(v.get("source", ""))
            ro = v.endswith(":ro") if isinstance(v, str) else bool(v.get("read_only"))
            if src.startswith((".", "/", "~")):
                rel = (path.parent / src).resolve()
                allowed = any(
                    str(rel).startswith(str(ROOT / d)) for d in ("infrastructure", "deploy")
                ) or (cloud and rel.parent == path.parent.resolve())  # config next to the compose
                if not (ro and allowed):
                    out.append(
                        f"R3 {name}: host bind-mount {v!r} "
                        "(only read-only config under infrastructure/ or deploy/)"
                    )
        # R4
        env = svc.get("environment") or {}
        items = env.items() if isinstance(env, dict) else (e.split("=", 1) for e in env if "=" in e)
        for k, val in items:
            if SECRET_KEY.search(str(k)) and not REQUIRED_VAR.match(str(val)):
                out.append(f"R4 {name}: secret {k} is not a required variable ${{{k}:?...}}")
        for s in _strings(svc.get("command") or []):
            for m in re.finditer(r"\$\{([A-Z0-9_]+)(:-|-)", s):
                if SECRET_KEY.search(m.group(1)):
                    out.append(f"R4 {name}: secret {m.group(1)} has a default value in command")
        env_files = svc.get("env_file") or []
        for ef in [env_files] if isinstance(env_files, str) else env_files:
            if ".env.example" in str(ef):
                out.append(f"R4 {name}: env_file is .env.example")
        # R5
        if "no-new-privileges:true" not in (svc.get("security_opt") or []):
            out.append(f"R5 {name}: missing security_opt no-new-privileges:true")
        if not svc.get("restart"):
            out.append(f"R5 {name}: missing restart policy")
        if not cloud and svc.get("pull_policy") != "never":
            out.append(f"R5 {name}: pull_policy must be never (images preloaded offline)")
        # R6
        if name in DATASTORES:
            for n in svc.get("networks") or ["default"]:
                if not (nets.get(n) or {}).get("internal"):
                    out.append(f"R6 {name}: datastore attached to non-internal network {n!r}")
    return out


def check_env(path: Path) -> list[str]:
    out = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, v = (s.strip() for s in line.split("=", 1))
        if k == "RELEASE_TAG" and (not v or v.upper() == "REPLACE_ME"):
            out.append("R7 RELEASE_TAG is not set")
        elif "replace_me" in v.lower() and not SECRET_KEY.search(k):
            out.append(f"R7 {k} still holds a template value")
        if SECRET_KEY.search(k):
            if (
                not v
                or v.lower() in DEV_DEFAULTS
                or "replace_me" in v.lower()
                or "dev_password" in v.lower()
            ):
                out.append(f"R7 {k} is empty, a template value or a development default")
            elif len(v) < 16:
                out.append(f"R7 {k} is shorter than 16 characters")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compose", type=Path)
    ap.add_argument("--profile", choices=("enclave", "cloud"), default="enclave")
    ap.add_argument("--env", type=Path)
    a = ap.parse_args()
    a.compose = a.compose or (CLOUD_COMPOSE if a.profile == "cloud" else COMPOSE)
    problems = check_compose(a.compose, a.profile) + (check_env(a.env) if a.env else [])
    for p in problems:
        print(p)
    print(json.dumps({"compose": str(a.compose), "violations": len(problems)}))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
