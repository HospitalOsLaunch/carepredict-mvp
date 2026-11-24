"""Release gate for the enclave deployment (scripts/deploy/check_release.py)."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
from pathlib import Path
from types import ModuleType

import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "deploy/nantes/docker-compose.release.yml"


def _gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_release", ROOT / "scripts/deploy/check_release.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_release_compose_satisfies_every_rule() -> None:
    assert _gate().check_compose(RELEASE) == []


def test_dev_compose_is_rejected_on_the_documented_gaps() -> None:
    rules = {v.split()[0] for v in _gate().check_compose(ROOT / "docker-compose.yml")}
    assert {"R1", "R2", "R3", "R4", "R5", "R6"} <= rules


def test_mutations_of_the_release_compose_are_caught(tmp_path: Path) -> None:
    gate = _gate()
    doc = yaml.safe_load(RELEASE.read_text())
    doc["services"]["cockpit"]["ports"] = ["8080:8080"]
    doc["services"]["redis"]["image"] = "redis:7.2.5-alpine"
    doc["services"]["timescaledb"]["ports"] = ["127.0.0.1:5432:5432"]
    doc["services"]["timescaledb"]["environment"]["POSTGRES_PASSWORD"] = "${POSTGRES_PASSWORD:-x}"
    doc["services"]["api"]["volumes"] = ["../..:/app"]
    del doc["services"]["mlflow"]["security_opt"]
    bad = tmp_path / "docker-compose.release.yml"
    bad.write_text(yaml.safe_dump(doc))
    # build contexts are resolved relative to the compose file: keep them pointing at the repository
    for svc in doc["services"].values():
        if isinstance(svc.get("build"), dict):
            svc["build"]["context"] = str(ROOT)
    bad.write_text(yaml.safe_dump(doc))
    found = "\n".join(gate.check_compose(bad))
    for needle in (
        "R2 cockpit",
        "R1 redis",
        "R2 timescaledb",
        "R4 timescaledb",
        "R3 api",
        "R5 mlflow",
    ):
        assert needle in found, needle


def test_env_file_rule(tmp_path: Path) -> None:
    gate = _gate()
    template = ROOT / "deploy/nantes/env.release.template"
    assert any(v.startswith("R7 POSTGRES_PASSWORD") for v in gate.check_env(template))
    good = tmp_path / ".env.release"
    good.write_text(template.read_text().replace("REPLACE_ME", "q7Hc2-vB9xL4pR8nT3mW6zK1"))
    assert gate.check_env(good) == []
    dev = tmp_path / "dev.env"
    dev.write_text(
        "RELEASE_TAG=1.0.0\nPOSTGRES_PASSWORD=carepredict_dev_password\nREDIS_PASSWORD=short\n"
    )
    assert len(gate.check_env(dev)) == 2


def test_every_pinned_base_matches_the_image_lock() -> None:
    pins = json.loads((ROOT / "deploy/nantes/images.lock.json").read_text())["images"]
    dockerfiles = list((ROOT / "infrastructure").glob("*/Dockerfile")) + [
        ROOT / "services/dashboard/Dockerfile"
    ]
    seen = 0
    for df in dockerfiles:
        for m in re.finditer(r"^FROM\s+(\S+)@(sha256:[0-9a-f]{64})", df.read_text(), re.M):
            assert pins.get(m.group(1)) == m.group(2), (df, m.group(1))
            seen += 1
    assert seen >= 7


# ---------------------------------------------------- cloud profile (staging, production)
CLOUD = ROOT / "deploy/cloud/docker-compose.yml"
CLOUD_ENVS = ROOT / "deploy/cloud/env"


def test_cloud_compose_satisfies_every_rule() -> None:
    assert _gate().check_compose(CLOUD, "cloud") == []


def test_cloud_mutations_are_caught(tmp_path: Path) -> None:
    gate = _gate()
    doc = yaml.safe_load(CLOUD.read_text())
    doc["services"]["cockpit"]["ports"] = ["8080:8080"]
    doc["services"]["edge"]["ports"].append("2019:2019")
    doc["services"]["platform"]["image"] = "ghcr.io/hospitaloslaunch/hospitalos-product:latest"
    doc["services"]["platform"]["environment"]["SMTP_PASSWORD"] = "${SMTP_PASSWORD:-}"
    doc["services"]["hybrid-api"]["volumes"] = ["../../src:/app/src"]
    del doc["services"]["decision-api"]["security_opt"]
    bad = tmp_path / "docker-compose.yml"
    bad.write_text(yaml.safe_dump(doc))
    found = "\n".join(gate.check_compose(bad, "cloud"))
    for needle in (
        "R2 cockpit",
        "R2 edge",
        "R1 platform",
        "R4 platform",
        "R3 hybrid-api",
        "R5 decision-api",
    ):
        assert needle in found, needle


def test_cloud_environment_templates(tmp_path: Path) -> None:
    gate = _gate()
    staging = (CLOUD_ENVS / "staging.env.example").read_text()
    production = (CLOUD_ENVS / "production.env.example").read_text()
    assert "APP_ENV=staging" in staging and "APP_ENV=production" in production
    # analytics only in production; staging is never indexed
    assert "GA_MEASUREMENT_ID" not in staging
    assert "GA_MEASUREMENT_ID=G-" in production
    assert "ROBOTS_TAG=noindex" in staging
    for text in (staging, production):
        path = tmp_path / "t.env"
        path.write_text(text)
        problems = gate.check_env(path)
        assert any("IMAGE_TAG" in p for p in problems)
        assert any("SMTP_PASSWORD" in p for p in problems)
        path.write_text(
            text.replace("IMAGE_TAG=REPLACE_ME", "IMAGE_TAG=sha-0123456789ab").replace(
                "REPLACE_ME", "q7hc2vb9xl4pr8nt3mw6zk1"
            )
        )
        assert gate.check_env(path) == []


def test_deploy_scripts_refuse_unsafe_tags() -> None:
    script = ROOT / "deploy/cloud/deploy.sh"
    for args, message in (
        (["production", "sha-0123456"], "versions étiquetées"),
        (["staging", "v1;rm -rf /"], "tag d'image invalide"),
        (["recette", "v1.0.0"], "environnement inconnu"),
    ):
        r = subprocess.run(["bash", str(script), *args], capture_output=True, text=True)
        assert r.returncode == 2 and message in r.stderr, (args, r.stderr)
    for name in ("deploy.sh", "smoke.sh"):
        assert subprocess.run(["bash", "-n", str(ROOT / "deploy/cloud" / name)]).returncode == 0
