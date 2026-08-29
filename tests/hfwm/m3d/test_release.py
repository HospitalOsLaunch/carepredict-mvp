"""Release-surface and two-commit attestation tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from hfwm.m3d.release import (
    enumerate_release_scope,
    git_tree_sha,
    load_scope,
    validate_manifest_file_hashes,
    validate_release_scope,
    validate_two_commit_release,
)

ROOT = Path(__file__).resolve().parents[3]
SCOPE = ROOT / "docs/research/hfwm/HFWM_R0_M3D1_RELEASE_SCOPE.yaml"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_filesystem_scope_classifies_relevant_and_ignored_files() -> None:
    scope = load_scope(SCOPE)
    errors = validate_release_scope(ROOT, scope)
    assert errors == []
    discovered = enumerate_release_scope(ROOT)
    # The final manifest is deliberately Commit-B-only and is absent from the
    # clean Commit-A checkout used for validation.
    if (ROOT / "artifacts/hfwm-r0/m3d/manifest.json").is_file():
        assert "artifacts/hfwm-r0/m3d/manifest.json" in discovered["filesystem_files"]
    assert any(path.startswith(".mypy_cache/") for path in discovered["ignored_files"])
    assert any(path.startswith("artifacts/hfwm-r0/") for path in discovered["ignored_files"])


def test_scope_fails_closed_for_an_unclassified_file(tmp_path: Path) -> None:
    scope = yaml.safe_load(SCOPE.read_text(encoding="utf-8"))
    assert isinstance(scope, dict)
    target = tmp_path / "repo"
    target.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    (target / "docs/research/hfwm").mkdir(parents=True)
    (target / "docs/research/hfwm/new.md").write_text("new", encoding="utf-8")
    scope["files"] = []
    # The validator uses the actual release prefixes and must reject the file.
    assert any(
        "unclassified release-relevant file" in error
        for error in validate_release_scope(target, scope)
    )


def test_two_commit_invariant_and_tree_sha_in_temp_repository(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "release.txt").write_text("content\n", encoding="utf-8")
    subprocess.run(["git", "add", "release.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "A",
        ],
        cwd=tmp_path,
        check=True,
    )
    commit_a = _git(tmp_path, "rev-parse", "HEAD")
    tree_a = git_tree_sha(tmp_path, commit_a)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "release_content_commit_sha": commit_a,
                "release_content_tree_sha": tree_a,
                "files_sha256": {
                    "release.txt": (
                        "434728a410a78f56fc1b5899c3593436e61ab0c731e9072d95e96db290205e53"
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "manifest.json"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "B",
        ],
        cwd=tmp_path,
        check=True,
    )
    commit_b = _git(tmp_path, "rev-parse", "HEAD")
    subprocess.run(["git", "tag", "HFWM-R0-M3D.1", commit_b], cwd=tmp_path, check=True)
    assert validate_two_commit_release(
        tmp_path,
        content_commit=commit_a,
        manifest_commit=commit_b,
        tag="HFWM-R0-M3D.1",
        manifest_path="manifest.json",
    ) == []
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["release_content_tree_sha"] == tree_a
    assert validate_manifest_file_hashes(tmp_path, manifest) == []
    manifest["files_sha256"]["release.txt"] = "0" * 64
    assert validate_manifest_file_hashes(tmp_path, manifest) == [
        "hash mismatch against commit A: release.txt"
    ]
