#!/usr/bin/env python3
"""Resolve the multi-platform digest of every third-party and base image of the release.

    python scripts/deploy/pin_images.py            # writes deploy/nantes/images.lock.json
    python scripts/deploy/pin_images.py --check    # fails if a pinned digest no longer matches

The digest is the one of the image index (manifest list) served for the tag, so that
`image@digest` pulls exactly the same content on any platform. Only Docker Hub is queried."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "deploy/nantes/images.lock.json"
IMAGES = [  # (reference used in compose files / Dockerfiles, registry, repository, tag)
    # docker.redpanda.com serves the Docker Hub repository redpandadata/redpanda;
    # the release pulls from Docker Hub
    ("redpandadata/redpanda:v24.1.9", "registry-1.docker.io", "redpandadata/redpanda", "v24.1.9"),
    (
        "timescale/timescaledb:2.14.2-pg15",
        "registry-1.docker.io",
        "timescale/timescaledb",
        "2.14.2-pg15",
    ),
    ("redis:7.2.5-alpine", "registry-1.docker.io", "library/redis", "7.2.5-alpine"),
    ("postgres:15.7-alpine", "registry-1.docker.io", "library/postgres", "15.7-alpine"),
    (
        "python:3.11.9-slim-bookworm",
        "registry-1.docker.io",
        "library/python",
        "3.11.9-slim-bookworm",
    ),
    ("node:22.12.0-bookworm-slim", "registry-1.docker.io", "library/node", "22.12.0-bookworm-slim"),
    ("nginx:1.27.3-alpine", "registry-1.docker.io", "library/nginx", "1.27.3-alpine"),
    ("caddy:2.8.4-alpine", "registry-1.docker.io", "library/caddy", "2.8.4-alpine"),
]
ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


def _get(url: str, headers: dict[str, str]) -> tuple[dict[str, str], bytes]:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed https registries)
        return dict(resp.headers), resp.read()


def _token(registry: str, repo: str) -> str | None:
    if registry != "registry-1.docker.io":
        return None
    _h, body = _get(
        f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull", {}
    )
    return str(json.loads(body)["token"])


def digest(registry: str, repo: str, tag: str, attempts: int = 5) -> str:
    last: Exception | None = None
    for i in range(attempts):
        try:
            headers = {"Accept": ACCEPT}
            tok = _token(registry, repo)
            if tok:
                headers["Authorization"] = f"Bearer {tok}"
            h, _body = _get(f"https://{registry}/v2/{repo}/manifests/{tag}", headers)
            d = {k.lower(): v for k, v in h.items()}.get("docker-content-digest", "")
            if d.startswith("sha256:"):
                return d
            last = RuntimeError(f"no digest header for {repo}:{tag}")
        except Exception as e:  # noqa: BLE001 (network retries)
            last = e
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"cannot resolve {registry}/{repo}:{tag}: {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    resolved = {ref: digest(reg, repo, tag) for ref, reg, repo, tag in IMAGES}
    if a.check:
        pinned = json.loads(LOCK.read_text())["images"]
        bad = {k: (pinned.get(k), v) for k, v in resolved.items() if pinned.get(k) != v}
        print(json.dumps({"mismatch": bad}, indent=1))
        return 1 if bad else 0
    LOCK.write_text(
        json.dumps(
            {
                "resolved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "images": resolved,
            },
            indent=1,
        )
        + "\n"
    )
    print(json.dumps(resolved, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
