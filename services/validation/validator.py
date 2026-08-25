"""Validator v2 — deterministic barrier on the eight NO-GO defects (HOS-006).

Turns an extraction into a GO / RESTRICT / NO-GO decision, failing cleanly (never
crashing) on a non-exploitable extraction. Builds on the Canonical Schema v1
validator (HOS-002) for per-record schema/type/value/timestamp/unknown-category
checks, and adds the file- and batch-level defects.

Eight NO-GO defect classes (source: HOS-006):
    1. corrupt files        -> corrupt_file
    2. schema               -> missing_required / unknown_field (HOS-002)
    3. types                -> type_mismatch (HOS-002)
    4. values               -> out_of_range (HOS-002)
    5. timestamps           -> tz (HOS-002) + order + future
    6. duplicates           -> duplicate_record / conflicting_restatement
    7. missingness          -> missingness (optional; > threshold)
    8. unknown categories   -> enum_violation (HOS-002)

Delegated value-level checks (routed here by HOS-002/HOS-003):
    * lag degeneracy   -> lag_degeneracy   (available_at == event_time mass)
    * history span     -> history_span     (span < min_history_days), opt-in

Bitemporality: a record carries event_time (business time) and available_at
(availability time). Two rows with the same (unit, event_time) but different
available_at are a legitimate *restatement* — NOT a duplicate. An exact duplicate
is the same bitemporal coordinate AND identical payload; the same coordinate with
different values is a conflict.

Guarantees: deterministic, fail-closed (any ERROR -> NO-GO; unparseable/empty ->
NO-GO; naive/omitted reference handled explicitly; never a silent repair), no
sensitive echo (only field names, coordinates and rates — never raw values).
Exit codes: GO=0, RESTRICT=10, NO-GO=20, usage error=1.

Usage:
    python -m services.validation.validator --input records.json --domain care_load \\
        [--now 2026-08-11T09:00:00+02:00] [--min-history-days 90] [--json report.json]
    # records.json: a JSON list of records, or {"domain": "...", "records": [...]}.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from services.connectors.schemas.canonical_schema import (
    SCHEMA_VERSION,
    Severity,
    load_canonical_schema,
    validate_record,
)

_PARIS = ZoneInfo("Europe/Paris")

# Soft thresholds (WARNING -> RESTRICT above them).
_MISSINGNESS_WARN_RATE = 0.5
_ZERO_LAG_WARN_RATE = 0.5


class Decision(StrEnum):
    GO = "GO"
    RESTRICT = "RESTRICT"
    NO_GO = "NO-GO"


class DefectCode(StrEnum):
    CORRUPT_FILE = "corrupt_file"
    EMPTY_EXTRACTION = "empty_extraction"
    DUPLICATE = "duplicate_record"
    CONFLICT = "conflicting_restatement"
    TEMPORAL_ORDER = "temporal_order"  # available_at < event_time
    TIMESTAMP_FUTURE = "timestamp_future"
    MISSINGNESS = "missingness"
    LAG_DEGENERACY = "lag_degeneracy"  # available_at == event_time (defaulted?)
    HISTORY_SPAN = "history_span"


_EXIT_CODES = {Decision.GO: 0, Decision.RESTRICT: 10, Decision.NO_GO: 20}
_USAGE_ERROR = 1


class CorruptFileError(ValueError):
    """The input is not parseable as the declared format (defect #1)."""


class UsageError(ValueError):
    """Operator misuse (e.g. missing domain) — distinct from data corruption."""


@dataclass(frozen=True, order=True)
class Finding:
    """A single validator finding. Ordering is stable for deterministic reports."""

    severity: Severity
    code: str
    location: str
    message: str
    remediation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "location": self.location,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass
class ValidationReport:
    decision: Decision
    run_id: str
    schema_version: str
    domain: str
    record_count: int
    reference_time: str | None = None
    findings: list[Finding] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return _EXIT_CODES[self.decision]

    def to_dict(self) -> dict[str, Any]:
        errors = sum(1 for f in self.findings if f.severity is Severity.ERROR)
        warnings = sum(1 for f in self.findings if f.severity is Severity.WARNING)
        return {
            "decision": self.decision.value,
            "exit_code": self.exit_code,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "domain": self.domain,
            "record_count": self.record_count,
            "reference_time": self.reference_time,
            "summary": {"errors": errors, "warnings": warnings, "findings": len(self.findings)},
            "findings": [f.to_dict() for f in self.findings],
        }


def _parse_paris(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _bitemporal_key(domain: str, record: dict[str, Any]) -> tuple[str, ...]:
    return (
        domain,
        str(record.get("hospital_id")),
        str(record.get("service_id")),
        str(record.get("event_time")),
        str(record.get("available_at")),
    )


def _err(code: DefectCode, location: str, message: str, remediation: str) -> Finding:
    return Finding(Severity.ERROR, code.value, location, message, remediation)


def _warn(code: DefectCode, location: str, message: str, remediation: str) -> Finding:
    return Finding(Severity.WARNING, code.value, location, message, remediation)


def validate_batch(
    records: list[dict[str, Any]],
    domain: str,
    *,
    run_id: str,
    reference_time: datetime | None = None,
    min_history_days: int | None = None,
) -> ValidationReport:
    """Validate a batch of records for ``domain``. Deterministic, fail-closed."""
    if reference_time is not None and reference_time.tzinfo is None:
        raise ValueError("reference_time must be tz-aware")

    spec = load_canonical_schema()

    ref_iso = reference_time.isoformat() if reference_time is not None else None

    # Defect: empty extraction (likely a failed pull) -> NO-GO, fail-closed.
    if not records:
        return _finalize(
            [_err(DefectCode.EMPTY_EXTRACTION, "file", "extraction is empty", "Provide records.")],
            run_id,
            domain,
            0,
            ref_iso,
        )

    findings: list[Finding] = []

    # Defects 2/3/4/5(tz)/8: per-record schema validation (HOS-002).
    for index, record in enumerate(records):
        for v in validate_record(spec, domain, record, index=index):
            findings.append(Finding(v.severity, v.code.value, v.location, v.message, v.remediation))

    # Defect 5 (order + future): cross-field temporal invariants (delegated by HOS-002).
    for index, record in enumerate(records):
        event = _parse_paris(record.get("event_time"))
        available = _parse_paris(record.get("available_at"))
        if event is not None and available is not None and available < event:
            findings.append(
                _err(
                    DefectCode.TEMPORAL_ORDER,
                    f"record[{index}].available_at",
                    "available_at is before event_time (leakage)",
                    "Ensure available_at >= event_time.",
                )
            )
        if reference_time is not None:
            for name, ts in (("event_time", event), ("available_at", available)):
                if ts is not None and ts > reference_time:
                    findings.append(
                        _err(
                            DefectCode.TIMESTAMP_FUTURE,
                            f"record[{index}].{name}",
                            f"{name} is in the future",
                            "Timestamps must not exceed the reference time.",
                        )
                    )

    # Defect 6: exact duplicate vs conflicting restatement (bitemporal-aware).
    seen: dict[tuple[str, ...], tuple[int, dict[str, Any]]] = {}
    for index, record in enumerate(records):
        key = _bitemporal_key(domain, record)
        if key in seen:
            first_index, first_record = seen[key]
            if record == first_record:
                findings.append(
                    _err(
                        DefectCode.DUPLICATE,
                        f"record[{index}]",
                        f"exact duplicate of record[{first_index}]",
                        "Remove duplicate rows (no silent dedup).",
                    )
                )
            else:
                findings.append(
                    _err(
                        DefectCode.CONFLICT,
                        f"record[{index}]",
                        f"conflicting values at same bitemporal key as record[{first_index}]",
                        "Resolve which version is correct (no silent merge).",
                    )
                )
        else:
            seen[key] = (index, record)

    # Defect 7: optional-field missingness above the soft threshold.
    domain_spec = spec.domain(domain)
    if domain_spec is not None:
        for fname, fspec in domain_spec.fields.items():
            if not fspec.nullable:
                continue  # required missingness is already a per-record ERROR.
            rate = sum(1 for r in records if r.get(fname) is None) / len(records)
            if rate > _MISSINGNESS_WARN_RATE:
                findings.append(
                    _warn(
                        DefectCode.MISSINGNESS,
                        f"field.{fname}",
                        f"optional field '{fname}' missing in {int(rate * 100)}% of rows",
                        "Provide the field or confirm it is unavailable for the pilot.",
                    )
                )

    # Delegated: lag degeneracy (available_at == event_time mass), per service_id.
    findings.extend(_lag_degeneracy_findings(records))

    # Delegated (opt-in): history span < min_history_days.
    if min_history_days is not None:
        findings.extend(_history_span_findings(records, min_history_days))

    return _finalize(findings, run_id, domain, len(records), ref_iso)


def _lag_degeneracy_findings(records: list[dict[str, Any]]) -> list[Finding]:
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # service_id -> [total, zero_lag]
    for record in records:
        event = _parse_paris(record.get("event_time"))
        available = _parse_paris(record.get("available_at"))
        if event is None or available is None:
            continue
        svc = str(record.get("service_id"))
        stats[svc][0] += 1
        if available == event:
            stats[svc][1] += 1
    out: list[Finding] = []
    for svc in sorted(stats):
        total, zero = stats[svc]
        if total and (zero / total) > _ZERO_LAG_WARN_RATE:
            out.append(
                _warn(
                    DefectCode.LAG_DEGENERACY,
                    f"service.{svc}",
                    f"available_at == event_time in {int(zero / total * 100)}% of rows "
                    "(available_at likely defaulted to event_time)",
                    "Source available_at from a real availability lag (contract defect).",
                )
            )
    return out


def _history_span_findings(records: list[dict[str, Any]], min_days: int) -> list[Finding]:
    events = [e for e in (_parse_paris(r.get("event_time")) for r in records) if e is not None]
    if len(events) < 2:
        return [
            _warn(
                DefectCode.HISTORY_SPAN,
                "file",
                "insufficient records to establish a history span",
                f"Provide >= {min_days} days of history.",
            )
        ]
    span = max(events) - min(events)
    if span < timedelta(days=min_days):
        return [
            _warn(
                DefectCode.HISTORY_SPAN,
                "file",
                f"history span {span.days}d below required {min_days}d",
                f"Provide >= {min_days} days of history.",
            )
        ]
    return []


def _decide(findings: list[Finding]) -> Decision:
    if any(f.severity is Severity.ERROR for f in findings):
        return Decision.NO_GO
    if any(f.severity is Severity.WARNING for f in findings):
        return Decision.RESTRICT
    return Decision.GO


def _finalize(
    findings: list[Finding], run_id: str, domain: str, count: int, reference_time: str | None = None
) -> ValidationReport:
    findings.sort()
    return ValidationReport(
        decision=_decide(findings),
        run_id=run_id,
        schema_version=SCHEMA_VERSION,
        domain=domain,
        record_count=count,
        reference_time=reference_time,
        findings=findings,
    )


def corrupt_file_report(domain: str, run_id: str, detail: str) -> ValidationReport:
    """Defect #1: build a NO-GO report for an unparseable input (never crash)."""
    return _finalize(
        [
            _err(
                DefectCode.CORRUPT_FILE,
                "file",
                f"input is not parseable: {detail}",
                "Provide a well-formed extraction file.",
            )
        ],
        run_id,
        domain,
        0,
    )


def load_records(path: Path, domain_hint: str | None) -> tuple[list[dict[str, Any]], str]:
    """Load records + resolve domain. Raises CorruptFileError / UsageError."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise CorruptFileError(str(exc)) from exc
    domain = domain_hint
    if isinstance(raw, dict):
        domain = raw.get("domain", domain)
        raw = raw.get("records", [])
    if not isinstance(raw, list) or not all(isinstance(r, dict) for r in raw):
        raise CorruptFileError("records must be a list of objects")
    if not domain:
        raise UsageError("domain is required (via --domain or the file's 'domain' key)")
    return raw, domain


def render_human(report: ValidationReport) -> str:
    d = report.to_dict()
    lines = [
        f"Validator v2 — DECISION: {report.decision.value} (exit {report.exit_code})",
        f"run_id={report.run_id}  schema={report.schema_version}  domain={report.domain}  "
        f"records={report.record_count}",
        f"errors={d['summary']['errors']}  warnings={d['summary']['warnings']}"
        + (f"  reference_time={report.reference_time}" if report.reference_time else ""),
        "",
    ]
    lines.extend(
        f"  [{f.severity.value}] {f.code} @ {f.location}: {f.message} → correctif: {f.remediation}"
        for f in report.findings
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validator v2 GO/RESTRICT/NO-GO on 8 NO-GO defects"
    )
    parser.add_argument("--input", required=True, help="JSON records file")
    parser.add_argument("--domain", help="canonical domain (or provide it in the file)")
    parser.add_argument("--now", help="reference time (ISO tz-aware); default = now (Europe/Paris)")
    parser.add_argument("--min-history-days", type=int, help="enable history-span check")
    parser.add_argument("--run-id", default="validator-local")
    parser.add_argument("--json", help="write the machine-readable report to this path")
    args = parser.parse_args(argv)

    # Reference time: default to now(Paris); a provided --now must be valid & tz-aware
    # (a malformed --now is an operator error, not a silently-skipped check).
    if args.now:
        reference = _parse_paris(args.now)
        if reference is None:
            print("validator: --now must be an ISO tz-aware timestamp", file=sys.stderr)
            return _USAGE_ERROR
    else:
        reference = datetime.now(_PARIS)

    domain_for_error = args.domain or "unknown"
    try:
        records, domain = load_records(Path(args.input), args.domain)
    except UsageError as exc:
        print(f"validator: {exc}", file=sys.stderr)
        return _USAGE_ERROR
    except CorruptFileError as exc:
        report = corrupt_file_report(domain_for_error, args.run_id, str(exc))
    else:
        report = validate_batch(
            records,
            domain,
            run_id=args.run_id,
            reference_time=reference,
            min_history_days=args.min_history_days,
        )

    if args.json:
        with Path(args.json).open("w", encoding="utf-8") as handle:
            json.dump(report.to_dict(), handle, ensure_ascii=False, indent=2, sort_keys=True)
    print(render_human(report))
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
