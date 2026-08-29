"""Fail-closed filesystem and two-commit release invariants for M3D.1."""

from __future__ import annotations

import fnmatch
import hashlib
import subprocess
from pathlib import Path
from typing import Any

import yaml

ALLOWED_CLASSIFICATIONS = {
    "EXTERNAL_CLAIM_SURFACE",
    "EXECUTABLE_EXTERNAL_CONTRACT",
    "INTERNAL_EVIDENCE_ONLY",
    "TEST_ONLY",
    "SELF_LEDGER",
    "OUT_OF_RELEASE_WITH_REASON",
}
RELEASE_PREFIXES = (
    "docs/research/hfwm/",
    "scripts/hfwm/",
    "configs/hfwm/",
    "src/hfwm/m3d/",
    "src/hfwm/bakeoff/",
    "src/hfwm/baselines/",
    "src/hfwm/candidate/",
    "src/hfwm/data_slice/",
    "tests/hfwm/m3d/",
    "tests/hfwm/bakeoff/",
    "tests/hfwm/baselines/",
    "tests/hfwm/candidate/",
    "tests/hfwm/data_slice/",
    "tests/fixtures/hfwm/m3d_synthetic_contract.yaml",
    "src/hfwm/evaluation/preregistration.py",
    "src/hfwm/models/local/model.py",
    "tests/hfwm/evaluation/test_preregistration.py",
    "artifacts/hfwm-r0/",
)


def _relative_files(root: Path) -> set[str]:
    result: set[str] = set()
    for prefix in RELEASE_PREFIXES:
        path = root / prefix
        if path.is_file():
            result.add(prefix)
        elif path.is_dir():
            result.update(
                candidate.relative_to(root).as_posix()
                for candidate in path.rglob("*")
                if candidate.is_file()
                and "__pycache__" not in candidate.parts
                and candidate.suffix != ".pyc"
            )
    return result


def _ignored_files(root: Path) -> set[str]:
    output = subprocess.run(
        ["git", "ls-files", "--others", "-i", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {path for path in output if path}


def enumerate_release_scope(root: Path) -> dict[str, Any]:
    """Return discovered relevant paths and ignored paths without trusting a manifest."""
    discovered = sorted(_relative_files(root))
    ignored = sorted(
        path
        for path in _ignored_files(root)
        if path in discovered
        or path.startswith((".mypy_cache/", ".pytest_cache/", ".ruff_cache/"))
        or "__pycache__/" in path
        or path.endswith(".pyc")
    )
    return {"filesystem_files": discovered, "ignored_files": ignored}


def load_scope(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("release scope must be a mapping")
    return value


def validate_release_scope(root: Path, scope: dict[str, Any]) -> list[str]:
    """Validate one classification per relevant file and explicit ignored-file handling."""
    errors: list[str] = []
    entries = scope.get("files")
    if not isinstance(entries, list):
        return ["release scope files must be a list"]
    classified: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append("every release scope entry needs a path")
            continue
        path = str(entry["path"])
        if path in classified:
            errors.append(f"duplicate release scope path: {path}")
        classified[path] = entry
        classification = entry.get("classification")
        if classification not in ALLOWED_CLASSIFICATIONS:
            errors.append(f"invalid classification for {path}: {classification}")
        if entry.get("release_phase") not in {
            "COMMIT_B_ONLY",
            "POST_TAG_REVIEW_SIDECAR",
        } and not (root / path).is_file():
            errors.append(f"classified file does not exist: {path}")
    discovered = set(enumerate_release_scope(root)["filesystem_files"])
    for path in sorted(discovered - set(classified)):
        errors.append(f"unclassified release-relevant file: {path}")
    ignored_patterns = scope.get("ignored_patterns")
    if not isinstance(ignored_patterns, list):
        errors.append("ignored_patterns must be a list")
        ignored_patterns = []
    patterns = [
        entry.get("pattern")
        for entry in ignored_patterns
        if isinstance(entry, dict) and isinstance(entry.get("pattern"), str)
    ]
    for path in enumerate_release_scope(root)["ignored_files"]:
        if path in classified:
            continue
        if not any(fnmatch.fnmatch(path, pattern) for pattern in patterns):
            errors.append(f"ignored file has no explicit classification: {path}")
    return sorted(set(errors))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_tree_sha(root: Path, commit: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", f"{commit}^{{tree}}"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def validate_two_commit_release(
    root: Path,
    *,
    content_commit: str,
    manifest_commit: str,
    tag: str,
    manifest_path: str,
) -> list[str]:
    """Check A/B/tag relationships and that A..B is manifest-only."""
    errors: list[str] = []
    def git(*args: str, check: bool = True) -> str:
        result = subprocess.run(
            ["git", *args], cwd=root, check=check, capture_output=True, text=True
        )
        return result.stdout.strip()

    content_exists = subprocess.run(
        ["git", "cat-file", "-e", f"{content_commit}^{{commit}}"],
        cwd=root,
        capture_output=True,
    ).returncode == 0
    manifest_exists = subprocess.run(
        ["git", "cat-file", "-e", f"{manifest_commit}^{{commit}}"],
        cwd=root,
        capture_output=True,
    ).returncode == 0
    if not content_exists:
        errors.append("release content commit A does not exist")
    if not manifest_exists:
        errors.append("manifest commit B does not exist")
    else:
        if git("rev-parse", f"{manifest_commit}^") != content_commit:
            errors.append("parent(B) is not A")
        changed = git("diff", "--name-only", content_commit, manifest_commit).splitlines()
        if changed != [manifest_path]:
            errors.append("A..B contains files outside the manifest allowlist")
    if git("rev-parse", tag) != manifest_commit:
        errors.append("release tag does not point to B")
    return sorted(set(errors))


def validate_manifest_file_hashes(root: Path, manifest: dict[str, Any]) -> list[str]:
    """Recompute every manifest file hash from the bytes committed in A."""
    commit = manifest.get("release_content_commit_sha")
    hashes = manifest.get("files_sha256")
    if not isinstance(commit, str) or not commit:
        return ["manifest release_content_commit_sha is missing"]
    if not isinstance(hashes, dict):
        return ["manifest files_sha256 is missing"]
    errors: list[str] = []
    for path, expected in hashes.items():
        if not isinstance(path, str) or not isinstance(expected, str):
            errors.append("manifest contains malformed file hash entry")
            continue
        result = subprocess.run(
            ["git", "show", f"{commit}:{path}"],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            errors.append(f"file missing from release content commit A: {path}")
            continue
        actual = hashlib.sha256(result.stdout).hexdigest()
        if actual != expected:
            errors.append(f"hash mismatch against commit A: {path}")
    return sorted(set(errors))
