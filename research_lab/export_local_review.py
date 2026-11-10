"""Export a private review brief from a verified local research journal; no API calls."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .cli import STAGES, validate_answer, verify_journal


def export_review(workspace: Path) -> Path:
    """Create, without overwriting, a local Markdown dossier of completed stages."""
    events = verify_journal(workspace)
    if not events or events[0]["event"].get("type") != "START":
        raise ValueError("Not a research journal")
    results: dict[str, dict[str, Any]] = {}
    known = {stage.name for stage in STAGES}
    for entry in events:
        event = entry["event"]
        if event["type"] not in ("RESUMED_STAGE", "STAGE_OUTPUT"):
            continue
        name = event.get("stage")
        if name not in known or name in results:
            raise ValueError("Stage sequence invalid or duplicated")
        if (event["type"] == "STAGE_OUTPUT"
                and event.get("scientific_status") != "UNVERIFIED_MODEL_PROPOSAL"):
            raise ValueError("Fixture results cannot be exported as research")
        results[name] = validate_answer(json.dumps(event["result"]))
    expected = [stage.name for stage in STAGES[:len(results)]]
    if list(results) != expected:
        raise ValueError("Missing or out-of-order stage output")
    if not results:
        raise ValueError("No completed scientific stage to export")

    final = events[-1]["event"]["type"]
    lines = [
        "# HospitalOS — Private Scientific Review",
        "",
        "**PRIVATE: Do not commit this document to a public repository.**",
        "",
        "All text below consists of unverified agent proposals, not demonstrated results.",
        f"**Journal status:** {final}",
        f"**Validated journal events:** {len(events)}",
        f"**Completed stages:** {len(results)}/{len(STAGES)}",
        "",
    ]
    for stage, result in results.items():
        lines += [f"## {stage}", "", f"**Gate proposed by agent:** {result['gate']}", ""]
        for key in ("claims", "falsifiers", "prior_art", "next_steps"):
            lines += [f"### {key}", ""]
            lines += [f"- {item}" for item in result[key]] or ["_None supplied_"]
            lines += [""]
    lines += ["---", "Requires independent prior-art checking and human review.", ""]
    destination = workspace / "private-review.md"
    # Exclusive create: never overwrite research summaries or existing evidence.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines))
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Export private review; no API calls")
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    try:
        path = export_review(args.workspace)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"Exported {path} locally. Inspect before private sharing. Never commit it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
