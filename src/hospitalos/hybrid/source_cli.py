"""Local read-only source qualification. No network or hospital execution.

Input exports must already be minimized/pseudonymized upstream. This program
never prints source values or Pydantic validation details, including on failure.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .live_models import LivePolicy
from .live_store import LiveStore
from .source_adapter import MAX_BYTES, SourceAdapter, check_columns, strict_json
from .source_contract import ColumnManifest, SourceProfile
from .source_demo import fixture


def read_limited(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Input exceeds local budget")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true")
    mode.add_argument("--example-profile", action="store_true")
    mode.add_argument("--preflight", type=Path, help="ColumnManifest JSON; no patient values")
    mode.add_argument("--import-export", type=Path, help="Read a local SourceExport JSON")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--db", type=Path)
    args = parser.parse_args(argv)
    store: LiveStore | None = None
    try:
        if args.demo or args.example_profile:
            if args.profile or args.policy or args.db:
                parser.error("Fictional examples cannot use external inputs")
            policy, profile, export = fixture()
            if args.example_profile:
                print(profile.model_dump_json(indent=2))
                return 0
            store = LiveStore(policy)
            adapter = SourceAdapter(
                store, profile, clock=lambda: datetime.fromisoformat(export["exported_at"])
            )
            result = adapter.receive(json.dumps(export).encode())
        else:
            if not args.profile:
                parser.error("--profile is required")
            profile = SourceProfile.model_validate(strict_json(read_limited(args.profile)))
            if args.preflight:
                if args.policy or args.db:
                    parser.error("Preflight reads metadata only and does not open a database")
                manifest = ColumnManifest.model_validate(strict_json(read_limited(args.preflight)))
                issues = check_columns(profile, manifest)
                print(
                    json.dumps(
                        {
                            "schema_version": "UNIT_SOURCE_PREFLIGHT_1",
                            "column_contract_compatible": not issues,
                            "value_quality_assessed": False,
                            "clinical_validation": False,
                            "issues": [i.model_dump(mode="json") for i in issues],
                        },
                        indent=2,
                    )
                )
                return 20 if issues else 0
            if not args.policy or not args.db:
                parser.error("Import requires --policy and --db")
            # Read/validate configuration and input before creating the destination.
            policy = LivePolicy.model_validate(strict_json(read_limited(args.policy)))
            data = read_limited(args.import_export)
            store = LiveStore(policy, str(args.db))
            result = SourceAdapter(store, profile).receive(data)
        print(result.model_dump_json(indent=2))
        if result.report.status == "REJECTED":
            return 20
        return 0 if result.report.state_ready and result.current_state_assessed else 10
    except (OSError, ValueError, ValidationError, RecursionError, sqlite3.Error):
        print(json.dumps({"status": "INPUT_OR_CONFIGURATION_ERROR", "source_values_omitted": True}))
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
