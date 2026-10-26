"""Duplicate a pull request of carepredict-mvp onto the computer-use MVP branch.

The MVP branch (`mvp/computer-use`) has its own history, unrelated to `main`: a pull request
of the monorepo cannot be merged into it, but its commits can be replayed. This tool replays
them one by one (cherry-pick, original author kept, `-x` reference to the source commit) on a
new branch `dup/pr-<n>`, keeps only what belongs to the MVP, records the duplication in
DUPLICATIONS.md, and can push the branch and open a pull request into the MVP.

    python tools/duplicate_pr.py 31                       # PR #31 of the upstream repository
    python tools/duplicate_pr.py 31 --include-outside     # also bring files outside the scope
    python tools/duplicate_pr.py 31 --push --open-pr      # then open the PR into the MVP

What is kept
- Paths listed in tools/mvp-scope.txt (shared with the monorepo): always.
- Other paths: dropped by default and listed in the report; brought with --include-outside,
  except the MVP's own files (PROTECTED below), which a duplication never touches.

What stops the duplication (the branch is left as it was, nothing is pushed)
- A conflict on an MVP path: the two lines of development diverged, a human decides.
- A stacked pull request (its base is another feature branch): duplicate the base first,
  the tool names it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCOPE_FILE = ROOT / "tools" / "mvp-scope.txt"
LEDGER = "DUPLICATIONS.md"
MVP_BRANCH = "mvp/computer-use"
UPSTREAM_REPO = "HospitalOsLaunch/carepredict-mvp"

# Files owned by the MVP: never replaced by an upstream version, even with --include-outside.
PROTECTED = (
    "README.md",
    "pyproject.toml",
    ".gitignore",
    "services/__init__.py",
    "tools/",
    LEDGER,
    "docker-compose.demo.yml",
    ".github/",  # monorepo workflows would run here without their dependencies
)


class DuplicationError(RuntimeError):
    pass


@dataclass
class Report:
    pr: int | None
    branch: str
    applied: list[str] = field(default_factory=list)  # source commit shas
    empty: list[str] = field(default_factory=list)  # commits with nothing for the MVP
    dropped: set[str] = field(default_factory=set)  # paths left out
    brought_outside: set[str] = field(default_factory=set)


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise DuplicationError(f"git {' '.join(args)} : {result.stderr.strip()}")
    return result.stdout.strip()


def load_scope(path: Path = SCOPE_FILE) -> tuple[str, ...]:
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return tuple(line for line in lines if line and not line.startswith("#"))


def matches(path: str, prefixes: Sequence[str]) -> bool:
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in prefixes)


def _changed(repo: Path) -> list[tuple[str, str]]:
    """(status, path) of everything staged or unmerged after a --no-commit cherry-pick."""
    out = git(repo, "status", "--porcelain=v1", "--no-renames", "-uno")
    rows = []
    for line in out.splitlines():
        if line:
            rows.append((line[:2], line[3:].strip('"')))
    return rows


def _drop(repo: Path, path: str) -> None:
    """Put the path back to its state on the MVP branch (absent if it was absent)."""
    exists = git(repo, "ls-tree", "--name-only", "HEAD", "--", path, check=False)
    if exists:
        git(repo, "checkout", "HEAD", "--", path)
    else:
        git(repo, "rm", "-q", "--cached", "--force", "--ignore-unmatch", "--", path)
        target = repo / path
        if target.exists():
            target.unlink()


def duplicate(
    repo: Path,
    commits: Sequence[str],
    onto: str,
    branch: str,
    scope: Sequence[str],
    include_outside: bool = False,
    pr: int | None = None,
    source: str = "",
) -> Report:
    """Replay `commits` (oldest first) on a new `branch` created from `onto`."""
    if git(repo, "status", "--porcelain", "-uno"):
        raise DuplicationError("l'arbre de travail a des modifications : enregistrez-les d'abord")
    start = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo, "checkout", "-q", "-B", branch, onto)
    report = Report(pr, branch)
    try:
        for sha in commits:
            parents = git(repo, "rev-list", "--parents", "-n", "1", sha).split()[1:]
            if len(parents) > 1:
                continue  # merge commits: their content arrives with the commits they merge
            subject = git(repo, "log", "-1", "--format=%s", sha)
            picked = subprocess.run(
                ["git", "cherry-pick", "--no-commit", "-x", sha],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
            conflicts = []
            unmerged_seen = False
            for status, path in _changed(repo):
                unmerged = "U" in status or status in ("AA", "DD")
                unmerged_seen = unmerged_seen or unmerged
                if matches(path, scope):
                    if unmerged:
                        conflicts.append(path)
                    continue
                if include_outside and not matches(path, PROTECTED):
                    # Outside the MVP but asked for: take the file as the commit left it.
                    if _exists_in(repo, sha, path):
                        git(repo, "checkout", sha, "--", path)
                        git(repo, "add", "--", path)
                    else:
                        git(repo, "rm", "-q", "--force", "--ignore-unmatch", "--", path)
                    report.brought_outside.add(path)
                    continue
                _drop(repo, path)
                report.dropped.add(path)
            if conflicts:
                raise DuplicationError(
                    f"conflit sur des chemins du MVP en rejouant {sha[:8]} « {subject} » : "
                    + ", ".join(sorted(conflicts))
                )
            if picked.returncode != 0 and not unmerged_seen:
                raise DuplicationError(
                    f"cherry-pick de {sha[:8]} impossible : {picked.stderr.strip()[:300]}"
                )
            if not git(repo, "diff", "--cached", "--name-only"):
                report.empty.append(sha)
                git(repo, "reset", "-q", "--hard", "HEAD")
                continue
            message = git(repo, "log", "-1", "--format=%B", sha)
            origin = f"(cherry picked from commit {sha})"
            if origin not in message:
                message = f"{message}\n\n{origin}"
            if pr is not None:
                message += f"\nDupliqué de {source or UPSTREAM_REPO}#{pr}"
            author = git(repo, "log", "-1", "--format=%an <%ae>", sha)
            date = git(repo, "log", "-1", "--format=%aI", sha)
            git(
                repo,
                "commit",
                "-q",
                "--no-verify",
                f"--author={author}",
                f"--date={date}",
                "-m",
                message,
            )
            report.applied.append(sha)
    except Exception:
        git(repo, "cherry-pick", "--abort", check=False)
        git(repo, "reset", "-q", "--hard", "HEAD", check=False)
        git(repo, "checkout", "-q", start, check=False)
        git(repo, "branch", "-q", "-D", branch, check=False)
        raise
    return report


def _exists_in(repo: Path, sha: str, path: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{sha}:{path}"], cwd=repo, capture_output=True, check=False
        ).returncode
        == 0
    )


def record(repo: Path, report: Report, title: str, head: str, url: str) -> None:
    """Append the duplication to the ledger, in its own commit on the duplication branch."""
    ledger = repo / LEDGER
    if not ledger.exists():
        ledger.write_text(
            "# PR dupliquées depuis carepredict-mvp\n\n"
            "Tenu par `tools/duplicate_pr.py`. Une ligne par duplication.\n\n"
            "| Date | PR | Tête source | Commits repris | Chemins laissés de côté |\n"
            "| --- | --- | --- | --- | --- |\n",
            encoding="utf-8",
        )
    dropped = ", ".join(f"`{p}`" for p in sorted(report.dropped)) or "aucun"
    if len(dropped) > 400:
        dropped = f"{len(report.dropped)} fichiers hors du MVP"
    line = (
        f"| {datetime.now(UTC):%Y-%m-%d} | [#{report.pr} {title}]({url}) | `{head[:8]}` "
        f"| {len(report.applied)} | {dropped} |\n"
    )
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(line)
    git(repo, "add", LEDGER)
    git(repo, "commit", "-q", "-m", f"chore: duplication de la PR #{report.pr} consignée")


def gh_json(path: str) -> dict[str, object]:
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise DuplicationError(f"gh api {path} : {out.stderr.strip()}")
    data: dict[str, object] = json.loads(out.stdout)
    return data


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pr", type=int, help="numéro de la PR dans le dépôt source")
    parser.add_argument("--repo", default=UPSTREAM_REPO, help="dépôt source owner/nom")
    parser.add_argument("--remote", default="origin", help="remote git pointant vers ce dépôt")
    parser.add_argument("--onto", default=MVP_BRANCH)
    parser.add_argument("--include-outside", action="store_true")
    parser.add_argument(
        "--allow-stacked",
        action="store_true",
        help="dupliquer même si la PR est empilée sur une autre branche",
    )
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--open-pr", action="store_true")
    parser.add_argument(
        "--target-repo", default=None, help="dépôt du MVP pour --open-pr (défaut : le dépôt source)"
    )
    args = parser.parse_args(argv)

    info = gh_json(f"repos/{args.repo}/pulls/{args.pr}")
    base = info["base"]
    head = info["head"]
    assert isinstance(base, dict) and isinstance(head, dict)
    default = gh_json(f"repos/{args.repo}")["default_branch"]
    if base["ref"] != default and not args.allow_stacked:
        below = [
            p
            for p in json.loads(
                subprocess.run(
                    ["gh", "api", f"repos/{args.repo}/pulls?state=all&per_page=100"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
            )
            if p["head"]["ref"] == base["ref"]
        ]
        hint = f" (PR #{below[0]['number']})" if below else ""
        raise DuplicationError(
            f"la PR #{args.pr} est empilée sur {base['ref']}{hint} : dupliquez d'abord cette "
            "base, puis relancez avec --allow-stacked"
        )
    git(ROOT, "fetch", "-q", args.remote, f"pull/{args.pr}/head:refs/dup/pr-{args.pr}")
    git(ROOT, "fetch", "-q", args.remote, f"{base['sha']}")
    commits = git(
        ROOT, "rev-list", "--reverse", "--topo-order", f"{base['sha']}..refs/dup/pr-{args.pr}"
    ).split()
    branch = f"dup/pr-{args.pr}"
    report = duplicate(
        ROOT, commits, args.onto, branch, load_scope(), args.include_outside, args.pr, args.repo
    )
    if not report.applied:
        git(ROOT, "checkout", "-q", args.onto)
        git(ROOT, "branch", "-q", "-D", branch)
        outside = len(report.dropped)
        print(f"PR #{args.pr} : rien qui concerne le MVP ({outside} fichiers hors champ).")
        return 0
    record(ROOT, report, str(info["title"]), str(head["sha"]), str(info["html_url"]))
    print(f"Branche {branch} : {len(report.applied)} commit(s) repris de la PR #{args.pr}.")
    if report.dropped:
        print(f"Laissés de côté (hors MVP) : {len(report.dropped)} fichier(s).")
    if report.brought_outside:
        print(f"Apportés hors périmètre : {len(report.brought_outside)} fichier(s).")
    if args.push or args.open_pr:
        git(ROOT, "push", "-q", "-u", args.remote, branch)
    if args.open_pr:
        target = args.target_repo or args.repo
        body = (
            f"Duplication de {info['html_url']} sur `{args.onto}`.\n\n"
            f"- Commits repris : {len(report.applied)} (référence `cherry picked from` dans "
            "chaque message)\n"
            f"- Commits sans effet sur le MVP : {len(report.empty)}\n"
            f"- Fichiers laissés de côté : {len(report.dropped)}\n"
            f"- Fichiers hors périmètre apportés : {len(report.brought_outside)}\n"
        )
        out = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{target}/pulls",
                "-f",
                f"title=[MVP] {info['title']}",
                "-f",
                f"head={branch}",
                "-f",
                f"base={args.onto}",
                "-f",
                f"body={body}",
                "--jq",
                ".html_url",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode != 0:
            raise DuplicationError(f"ouverture de la PR : {out.stderr.strip()}")
        print(out.stdout.strip())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DuplicationError as exc:
        print(f"Duplication interrompue : {exc}", file=sys.stderr)
        raise SystemExit(1) from None
