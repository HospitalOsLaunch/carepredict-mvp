"""The duplication tool, on a throw-away repository shaped like carepredict-mvp.

`main` holds the monorepo, `mvp` is an orphan branch holding the MVP; a feature branch of
`main` plays the pull request to duplicate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.duplicate_pr import DuplicationError, duplicate

SCOPE = ("services/admissions_agent/",)
AGENT = "services/admissions_agent/agent.py"


def run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def write(repo: Path, path: str, text: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def commit(repo: Path, message: str, author: str = "Dev <dev@example.org>") -> str:
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", message, f"--author={author}")
    return run(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    run(r, "init", "-q", "-b", "main")
    run(r, "config", "user.email", "ci@example.org")
    run(r, "config", "user.name", "CI")
    write(r, AGENT, "def act():\n    return 1\n")
    write(r, "src/world_model.py", "MODEL = 'jepa'\n")
    write(r, "README.md", "# Monorepo\n")
    commit(r, "monorepo")
    run(r, "checkout", "-q", "--orphan", "mvp")
    run(r, "rm", "-q", "-rf", ".")
    write(r, AGENT, "def act():\n    return 1\n")
    write(r, "README.md", "# MVP computer use\n")
    commit(r, "mvp")
    run(r, "checkout", "-q", "-b", "feature", "main")
    return r


def make_pr(repo: Path) -> list[str]:
    write(repo, AGENT, "def act():\n    return 2\n")
    write(repo, "src/world_model.py", "MODEL = 'jepa-2'\n")
    write(repo, "README.md", "# Monorepo, updated\n")
    first = commit(repo, "fix(agent): better act", "Alice <alice@example.org>")
    write(repo, "services/admissions_agent/helper.py", "X = 1\n")
    write(repo, "src/simulator.py", "SIM = True\n")
    second = commit(repo, "feat: helper and simulator")
    write(repo, "docs/note.md", "only docs\n")
    third = commit(repo, "docs: unrelated to the MVP")
    run(repo, "checkout", "-q", "mvp")
    return [first, second, third]


def files(repo: Path) -> set[str]:
    return set(run(repo, "ls-files").splitlines())


def test_keeps_the_mvp_paths_and_drops_the_rest(repo: Path) -> None:
    commits = make_pr(repo)
    report = duplicate(repo, commits, "mvp", "dup/pr-1", SCOPE, pr=1)
    assert report.applied == commits[:2] and report.empty == [commits[2]]
    assert (repo / AGENT).read_text() == "def act():\n    return 2\n"
    assert files(repo) == {AGENT, "services/admissions_agent/helper.py", "README.md"}
    assert (repo / "README.md").read_text() == "# MVP computer use\n"
    assert report.dropped == {
        "src/world_model.py",
        "README.md",
        "src/simulator.py",
        "docs/note.md",
    }
    log = run(repo, "log", "--format=%an|%B", "-2")
    assert "Alice|fix(agent): better act" in log
    assert f"(cherry picked from commit {commits[0]})" in log
    assert "Dupliqué de" in log and "#1" in log
    assert run(repo, "status", "--porcelain") == ""


def test_include_outside_brings_files_but_never_the_mvp_own_ones(repo: Path) -> None:
    commits = make_pr(repo)
    report = duplicate(repo, commits, "mvp", "dup/pr-2", SCOPE, include_outside=True, pr=2)
    assert {"src/world_model.py", "src/simulator.py", "docs/note.md"} <= files(repo)
    assert (repo / "src/world_model.py").read_text() == "MODEL = 'jepa-2'\n"
    assert (repo / "README.md").read_text() == "# MVP computer use\n"  # protected
    assert report.dropped == {"README.md"}
    assert len(report.applied) == 3


def test_a_conflict_on_an_mvp_path_stops_and_leaves_nothing(repo: Path) -> None:
    run(repo, "checkout", "-q", "mvp")
    write(repo, AGENT, "def act():\n    return 'mvp'\n")
    commit(repo, "mvp: own change to act")
    run(repo, "checkout", "-q", "feature")
    commits = make_pr(repo)
    with pytest.raises(DuplicationError, match="conflit sur des chemins du MVP"):
        duplicate(repo, commits, "mvp", "dup/pr-3", SCOPE, pr=3)
    assert run(repo, "rev-parse", "--abbrev-ref", "HEAD") == "mvp"
    assert "dup/pr-3" not in run(repo, "branch", "--list", "dup/pr-3")
    assert (repo / AGENT).read_text() == "def act():\n    return 'mvp'\n"
    assert run(repo, "status", "--porcelain") == ""


def test_refuses_a_dirty_work_tree(repo: Path) -> None:
    commits = make_pr(repo)
    write(repo, AGENT, "uncommitted\n")
    with pytest.raises(DuplicationError, match="modifications"):
        duplicate(repo, commits, "mvp", "dup/pr-4", SCOPE)
