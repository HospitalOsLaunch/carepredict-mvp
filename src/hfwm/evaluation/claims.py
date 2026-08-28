"""Fail-closed scan of HFWM-R0 evidence claims."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

FORBIDDEN_CLAIMS: tuple[str, ...] = (
    "P0 PASS",
    "HFWM PASS",
    "VALIDATED WORLD MODEL",
    "PROVEN FOUNDATION MODEL",
    "VALIDATED AT NANTES",
    "CAUSAL EFFECT",
    "COUNTERFACTUAL EFFECT",
    "BEST ACTION",
    "PROVEN OPERATIONAL IMPACT",
    "AUTONOMOUS EXECUTION",
)

ALLOWED_CLAIMS: frozenset[str] = frozenset(
    {
        "EXPERIMENTAL_HOSPITAL_WORLD_MODEL",
        "HOSPITAL_WORLD_MODEL_CANDIDATE",
        "FOUNDATION_ARCHITECTURE_CANDIDATE",
        "BEHAVIOR_CONDITIONED_DYNAMICS_MODEL",
        "OBSERVATIONAL",
        "SHADOW_ONLY",
        "UNVALIDATED_AT_NANTES",
        "FOUNDATION_EVIDENCE_INSUFFICIENT",
        "ACTION_CONDITIONING_NOT_IDENTIFIABLE",
    }
)


@dataclass(frozen=True)
class ClaimFinding:
    """Forbidden text found in a report or evidence payload."""

    source: str
    line: int
    claim: str


def scan_claims(documents: Iterable[tuple[str, str]]) -> tuple[ClaimFinding, ...]:
    """Scan generated evidence, excluding policy documents by caller choice."""
    patterns = {
        claim: re.compile(rf"(?<![A-Z0-9_]){re.escape(claim)}(?![A-Z0-9_])", re.IGNORECASE)
        for claim in FORBIDDEN_CLAIMS
    }
    findings: list[ClaimFinding] = []
    for source, text in sorted(documents):
        for line_number, line in enumerate(text.splitlines(), start=1):
            for claim, pattern in patterns.items():
                if pattern.search(line):
                    findings.append(ClaimFinding(source=source, line=line_number, claim=claim))
    return tuple(findings)


def validate_declared_claims(claims: Iterable[str]) -> list[str]:
    """Return claims not present in the allowlist."""
    return sorted({claim for claim in claims if claim not in ALLOWED_CLAIMS})
