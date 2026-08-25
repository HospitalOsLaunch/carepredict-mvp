"""Nantes preflight — GO / RESTRICT / NO-GO on an extraction column manifest (HOS-003).

Given the *column manifest* of a Nantes extraction (column names only — never
patient values) and the Nantes mapping template, this decides whether the
extraction is exploitable, and emits a coverage report + a decision.

Privacy by design: the preflight inspects metadata (column names) only. It never
reads, logs or echoes patient values. A column whose name matches a forbidden
token (nominative / free text) is itself a NO-GO cause.

Forbidden matching is **token-based** (names are normalized then split on
non-alphanumeric boundaries). A single-token pattern matches an exact token
(so ``nom`` blocks ``Nom_Patient`` but not ``nombre_presents``); a multi-token
pattern (e.g. ``date_naissance``) matches when *all* its tokens are present
(so ``date_de_naissance`` is caught despite the filler).

Decision (deterministic, fail-closed):
    * NO-GO    if any forbidden column is present, OR any *required* canonical
               field is missing.  (exit code 20)
    * RESTRICT if all required fields are present but at least one is only
               derived, unknown columns are present, or the twin is reduced to
               forecast-only (staffing AND capacity domains absent).  (exit 10)
    * GO       otherwise.  (exit 0)

Usage:
    python -m services.validation.preflight --columns manifest.json [--json report.json]
    # manifest.json: {"columns": ["etablissement_id", ...]} or a plain JSON list.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from services.connectors.schemas.canonical_schema import (
    SCHEMA_VERSION,
    CanonicalSchemaSpec,
    load_canonical_schema,
)

_TEMPLATE_PATH = Path(__file__).with_name("nantes") / "nantes_mapping_template.yaml"
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


class PreflightConfigError(ValueError):
    """The template or schema is malformed / inconsistent (fail-closed)."""


class Decision(StrEnum):
    GO = "GO"
    RESTRICT = "RESTRICT"
    NO_GO = "NO-GO"


class Coverage(StrEnum):
    MAPPED = "mapped"
    DERIVED = "derived"
    MISSING = "missing"
    UNKNOWN = "unknown"
    FORBIDDEN = "forbidden"


# Exit codes. GO=0; NO-GO non-zero (contract). RESTRICT non-zero to force a human
# acknowledgement in gating contexts, but distinct from NO-GO.
_EXIT_CODES: dict[Decision, int] = {Decision.GO: 0, Decision.RESTRICT: 10, Decision.NO_GO: 20}
_USAGE_ERROR = 1

# Optional domains whose joint absence reduces the twin to forecast-only.
_TWIN_DOMAINS = ("staffing", "capacity")


@dataclass(frozen=True)
class MappingEntry:
    canonical: str
    source: str
    requirement: str  # "required" | "optional"
    derivable_from: tuple[str, ...] = ()

    @property
    def domain(self) -> str:
        return self.canonical.split(".", 1)[0]


@dataclass(frozen=True)
class MappingTemplate:
    schema_ref: str
    version: str
    entries: tuple[MappingEntry, ...]
    forbidden_patterns: tuple[tuple[str, ...], ...]  # each pattern is a token tuple


@dataclass(frozen=True)
class FieldResult:
    canonical: str
    requirement: str
    coverage: Coverage
    source: str | None
    detail: str


@dataclass
class PreflightReport:
    decision: Decision
    run_id: str
    schema_version: str
    template_version: str
    fields: list[FieldResult] = field(default_factory=list)
    unknown_columns: list[str] = field(default_factory=list)
    forbidden_columns: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return _EXIT_CODES[self.decision]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "exit_code": self.exit_code,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "template_version": self.template_version,
            "coverage": {
                "mapped": [f.canonical for f in self.fields if f.coverage is Coverage.MAPPED],
                "derived": [f.canonical for f in self.fields if f.coverage is Coverage.DERIVED],
                "missing": [f.canonical for f in self.fields if f.coverage is Coverage.MISSING],
                "unknown": sorted(self.unknown_columns),
                "forbidden": sorted(self.forbidden_columns),
            },
            "fields": [
                {
                    "canonical": f.canonical,
                    "requirement": f.requirement,
                    "coverage": f.coverage.value,
                    "source": f.source,
                    "detail": f.detail,
                }
                for f in self.fields
            ],
            "reasons": self.reasons,
            "notes": self.notes,
        }


def _normalize(name: str) -> str:
    """Lowercase + strip accents."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.lower().strip()


def _tokens(name: str) -> frozenset[str]:
    return frozenset(t for t in _TOKEN_SPLIT.split(_normalize(name)) if t)


def _match_forbidden(column: str, patterns: tuple[tuple[str, ...], ...]) -> bool:
    """True if the column name contains all tokens of any forbidden pattern."""
    toks = _tokens(column)
    return any(all(pt in toks for pt in pattern) for pattern in patterns)


def load_template(path: str | Path | None = None) -> MappingTemplate:
    template_path = Path(path) if path else _TEMPLATE_PATH
    with template_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict) or "mappings" not in raw or "schema_ref" not in raw:
        raise PreflightConfigError("template must define 'schema_ref' and 'mappings'")
    entries = tuple(
        MappingEntry(
            canonical=canonical,
            source=str(spec["source"]),
            requirement=str(spec.get("requirement", "optional")),
            derivable_from=tuple(spec.get("derivable_from", ())),
        )
        for canonical, spec in raw["mappings"].items()
    )
    patterns = tuple(
        tuple(t for t in _TOKEN_SPLIT.split(_normalize(str(p))) if t)
        for p in raw.get("forbidden_patterns", ())
    )
    return MappingTemplate(
        schema_ref=str(raw["schema_ref"]),
        version=str(raw["version"]),
        entries=entries,
        forbidden_patterns=patterns,
    )


def _canonical_keys(spec: CanonicalSchemaSpec) -> set[str]:
    keys = {f"identity.{n}" for n in spec.identity}
    keys |= {f"temporal.{n}" for n in spec.temporal}
    for dname, dspec in spec.domains.items():
        keys |= {f"{dname}.{fn}" for fn in dspec.fields}
    return keys


def validate_template_against_schema(template: MappingTemplate, spec: CanonicalSchemaSpec) -> None:
    """Fail-closed: every template canonical target must exist in the frozen schema."""
    valid = _canonical_keys(spec)
    unknown = sorted(e.canonical for e in template.entries if e.canonical not in valid)
    if unknown:
        raise PreflightConfigError(
            f"template targets absent from schema {template.schema_ref}: {unknown}"
        )


def run_preflight(columns: list[str], *, run_id: str, template: MappingTemplate) -> PreflightReport:
    """Classify the manifest against the template and decide. Deterministic, fail-closed."""
    spec = load_canonical_schema()
    validate_template_against_schema(template, spec)

    present = {_normalize(c): c for c in columns}
    present_norm = set(present)

    report = PreflightReport(
        decision=Decision.GO,
        run_id=run_id,
        schema_version=SCHEMA_VERSION,
        template_version=template.version,
    )

    # 1) Forbidden columns (fail-closed, token-based).
    for column in columns:
        if _match_forbidden(column, template.forbidden_patterns):
            report.forbidden_columns.append(column)

    # 2) Field-by-field coverage.
    mapped_sources: set[str] = set()
    domains_seen: set[str] = set()
    for entry in template.entries:
        src_norm = _normalize(entry.source)
        if src_norm in present_norm:
            report.fields.append(
                FieldResult(
                    entry.canonical,
                    entry.requirement,
                    Coverage.MAPPED,
                    present[src_norm],
                    "direct mapping",
                )
            )
            mapped_sources.add(src_norm)
            domains_seen.add(entry.domain)
        elif entry.derivable_from and all(
            _normalize(c) in present_norm for c in entry.derivable_from
        ):
            report.fields.append(
                FieldResult(
                    entry.canonical,
                    entry.requirement,
                    Coverage.DERIVED,
                    None,
                    f"derivable from {list(entry.derivable_from)}",
                )
            )
            mapped_sources.update(_normalize(c) for c in entry.derivable_from)
            domains_seen.add(entry.domain)
        else:
            report.fields.append(
                FieldResult(
                    entry.canonical, entry.requirement, Coverage.MISSING, None, "no source column"
                )
            )

    # 3) Unknown columns = present but neither a mapped source nor forbidden.
    forbidden_norm = {_normalize(c) for c in report.forbidden_columns}
    for norm, original in present.items():
        if norm not in mapped_sources and norm not in forbidden_norm:
            report.unknown_columns.append(original)

    # 4) Notes: whole optional domains absent (non-blocking observation).
    for dname in sorted({e.domain for e in template.entries}):
        if dname not in domains_seen:
            report.notes.append(f"optional domain '{dname}' absent")

    # 5) Decision.
    required_missing = sorted(
        f.canonical
        for f in report.fields
        if f.requirement == "required" and f.coverage is Coverage.MISSING
    )
    required_derived = sorted(
        f.canonical
        for f in report.fields
        if f.requirement == "required" and f.coverage is Coverage.DERIVED
    )
    forecast_only = all(d not in domains_seen for d in _TWIN_DOMAINS)

    if report.forbidden_columns:
        report.decision = Decision.NO_GO
        _n = len(report.forbidden_columns)
        report.reasons.append(
            f"{_n} forbidden column(s) present: {sorted(report.forbidden_columns)}"
        )
    if required_missing:
        report.decision = Decision.NO_GO
        report.reasons.append(f"required field(s) missing: {required_missing}")

    if report.decision is not Decision.NO_GO:
        if required_derived or report.unknown_columns or forecast_only:
            report.decision = Decision.RESTRICT
            if required_derived:
                report.reasons.append(
                    f"required field(s) only derived (dégradation): {required_derived}"
                )
            if report.unknown_columns:
                report.reasons.append(
                    f"{len(report.unknown_columns)} unknown column(s) ignored (informatif)"
                )
            if forecast_only:
                report.reasons.append(
                    "twin reduced to forecast-only: staffing and capacity domains absent"
                )
        else:
            report.reasons.append(
                "all required fields directly mapped; no forbidden or unknown columns"
            )

    return report


def render_human(report: PreflightReport) -> str:
    lines = [
        f"Nantes preflight — DECISION: {report.decision.value} (exit {report.exit_code})",
        f"run_id={report.run_id}  schema={report.schema_version}  "
        f"template={report.template_version}",
        "",
    ]
    data = report.to_dict()["coverage"]
    for cat in ("mapped", "derived", "missing", "unknown", "forbidden"):
        items = data[cat]
        lines.append(f"  {cat:<9}: {len(items)}" + (f"  {items}" if items else ""))
    lines.append("")
    lines.append("Reasons:")
    lines.extend(f"  - {r}" for r in report.reasons)
    if report.notes:
        lines.append("Notes:")
        lines.extend(f"  - {n}" for n in report.notes)
    return "\n".join(lines)


def _load_columns(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if isinstance(raw, dict):
        raw = raw.get("columns", [])
    if not isinstance(raw, list):
        raise ValueError("manifest must be a JSON list or an object with a 'columns' list")
    columns: list[str] = []
    for item in raw:
        if isinstance(item, str):
            columns.append(item)
        elif isinstance(item, dict) and "name" in item:
            columns.append(str(item["name"]))
        else:
            raise ValueError("each column must be a string or an object with a 'name'")
    return columns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nantes preflight GO/RESTRICT/NO-GO")
    parser.add_argument("--columns", required=True, help="JSON manifest of extraction columns")
    parser.add_argument("--json", help="write the machine-readable report to this path")
    parser.add_argument("--run-id", default="preflight-local", help="provenance run id")
    parser.add_argument("--template", help="override mapping template path")
    args = parser.parse_args(argv)

    try:
        columns = _load_columns(Path(args.columns))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"preflight: cannot read manifest: {exc}", file=sys.stderr)
        return _USAGE_ERROR

    try:
        template = load_template(args.template)
        report = run_preflight(columns, run_id=args.run_id, template=template)
    except (OSError, PreflightConfigError, yaml.YAMLError) as exc:
        print(f"preflight: configuration error: {exc}", file=sys.stderr)
        return _USAGE_ERROR

    if args.json:
        with Path(args.json).open("w", encoding="utf-8") as handle:
            json.dump(report.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
    print(render_human(report))
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
