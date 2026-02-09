# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Fingerprint computation and repeat-issue detection for pipeline review iterations."""

from __future__ import annotations

import re

from omniclaude.lib.pipeline.models import IssueFingerprint

_SEVERITY_MAP: dict[str, str] = {
    "error": "critical",
    "critical": "critical",
    "major": "major",
    "warning": "major",
    "minor": "minor",
    "info": "minor",
    "nit": "nit",
    "style": "nit",
}

_SEVERITY_PATTERN = re.compile(
    r"\b(" + "|".join(_SEVERITY_MAP.keys()) + r")(?=[\s]*[:\]\)\-,]|\s*$)",
    re.IGNORECASE,
)


def normalize_finding(file: str, rule_id: str, severity: str) -> IssueFingerprint:
    """Normalize a raw finding into a canonical fingerprint.

    - File path: strip leading ``./``, lowercase.
    - Rule ID: strip whitespace, lowercase.
    - Severity: lowercase, must be a valid level.
    """
    norm_file = file.strip()
    if norm_file.startswith("./"):
        norm_file = norm_file[2:]
    norm_file = norm_file.lower()
    norm_rule = rule_id.strip().lower()
    norm_severity = severity.strip().lower()
    return IssueFingerprint(file=norm_file, rule_id=norm_rule, severity=norm_severity)


def compute_fingerprint_set(
    findings: list[IssueFingerprint],
) -> frozenset[IssueFingerprint]:
    """Deduplicate findings into a frozenset."""
    return frozenset(findings)


def detect_repeat_issues(
    prev_fingerprints: frozenset[IssueFingerprint],
    current_fingerprints: frozenset[IssueFingerprint],
) -> bool:
    """Return True if current issues are a non-empty subset of previous (no progress)."""
    if not current_fingerprints:
        return False
    return current_fingerprints <= prev_fingerprints


def detect_new_major(
    prev_findings: list[IssueFingerprint],
    current_findings: list[IssueFingerprint],
) -> bool:
    """Return True if current iteration introduces major/critical findings absent previously."""
    major_severities = {"major", "critical"}
    prev_major = {f for f in prev_findings if f.severity in major_severities}
    current_major = {f for f in current_findings if f.severity in major_severities}
    new_major = current_major - prev_major
    return len(new_major) > 0


def classify_severity(finding_text: str) -> str:
    """Extract a severity level from free-form review text.

    Scans for known keywords and maps them to canonical severities.
    Returns ``"minor"`` when no pattern matches.
    """
    match = _SEVERITY_PATTERN.search(finding_text)
    if match:
        return _SEVERITY_MAP[match.group(1).lower()]
    return "minor"
