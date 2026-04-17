#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Preflight reality-check gate for the ticket_pipeline skill.

Parses a Linear ticket description for claimed file paths, function names,
class names, database table names, and Kafka topic names, then verifies each
claim against current main. If any claim does not match reality, the pipeline
halts and a diagnosis document is written under ``docs/diagnosis-{slug}.md``.

Used by the ``pre_flight`` phase of the ticket_pipeline skill to kill the #1
wrong-approach friction category: workers executing tickets whose stated
reality does not match the current codebase (see OMN-8411).
"""

from __future__ import annotations

import os
import re
import subprocess
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EnumClaimKind(StrEnum):
    FILE_PATH = "file_path"
    FUNCTION = "function"
    CLASS = "class"
    TABLE = "table"
    TOPIC = "topic"


class ModelClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EnumClaimKind
    value: str
    raw: str = Field(description="Original matched substring from the description.")


class ModelClaimResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: ModelClaim
    verified: bool
    evidence: str = Field(
        description="File path where claim was verified, or failure reason.",
    )


class ModelRealityCheckReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: str
    results: tuple[ModelClaimResult, ...]

    @property
    def halted(self) -> bool:
        return any(not r.verified for r in self.results)

    @property
    def failures(self) -> tuple[ModelClaimResult, ...]:
        return tuple(r for r in self.results if not r.verified)


# Match `path/to/file.py`, `src/foo.ts`, etc. Requires a slash and an extension.
# Trailing sentence punctuation (period, comma) is allowed because descriptions
# commonly write "update src/foo.py." — we strip the punctuation via the group.
_FILE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_/])"
    r"([A-Za-z0-9_][A-Za-z0-9_./-]*?/[A-Za-z0-9_./-]+"
    r"\.(?:py|ts|tsx|js|jsx|yaml|yml|md|sql|toml|json|sh|go|rs))"
    r"(?![A-Za-z0-9_/])",
)

# Match backtick-quoted function-like identifiers (with parens) e.g. `foo_bar()`
_FUNCTION_RE = re.compile(r"`([a-z_][a-zA-Z0-9_]*)\(\)`")

# Match PascalCase class names in backticks e.g. `MyClass`
_CLASS_RE = re.compile(r"`([A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*)`")

# Match table name claims. We require the name to either contain an underscore
# or be backtick-quoted — otherwise "the X table" matches common English words
# like "for" and produces false positives.
_TABLE_RE = re.compile(
    r"`([a-z][a-z0-9_]{2,})`\s+table"
    r"|(?:the\s+|on\s+the\s+|from\s+|query\s+the\s+|query\s+)"
    r"([a-z][a-z0-9]*_[a-z0-9_]*)\s+table"
    r"|(?:table|tbl)\s+`([a-z][a-z0-9_]{2,})`",
)

# Match Kafka topic names following onex.{cmd|evt}.{svc}.{name}.v{N}
_TOPIC_RE = re.compile(r"(onex\.(?:cmd|evt)\.[a-z0-9._-]+\.v\d+)")


def extract_claims(description: str) -> list[ModelClaim]:
    """Extract structured claims from a ticket description.

    The regexes are deliberately conservative: we only flag claims that are
    clearly identifiers (backtick-quoted) or structurally specific (file paths
    with extensions, topics with the onex.* prefix). This keeps false positives
    low so the halt-on-mismatch gate stays trustworthy.
    """
    claims: list[ModelClaim] = []
    seen: set[tuple[EnumClaimKind, str]] = set()

    def _add(kind: EnumClaimKind, value: str, raw: str) -> None:
        key = (kind, value)
        if key in seen:
            return
        seen.add(key)
        claims.append(ModelClaim(kind=kind, value=value, raw=raw))

    for match in _FILE_PATH_RE.finditer(description):
        path = match.group(1)
        _add(EnumClaimKind.FILE_PATH, path, path)

    for match in _FUNCTION_RE.finditer(description):
        name = match.group(1)
        _add(EnumClaimKind.FUNCTION, name, match.group(0))

    for match in _CLASS_RE.finditer(description):
        name = match.group(1)
        _add(EnumClaimKind.CLASS, name, match.group(0))

    for match in _TABLE_RE.finditer(description):
        name = match.group(1) or match.group(2) or match.group(3)
        if name:
            _add(EnumClaimKind.TABLE, name, match.group(0))

    for match in _TOPIC_RE.finditer(description):
        topic = match.group(1)
        _add(EnumClaimKind.TOPIC, topic, topic)

    return claims


def _grep_repos(pattern: str, repo_roots: list[Path]) -> str | None:
    """Return the first repo path containing a regex match, or None."""
    for repo in repo_roots:
        if not repo.exists():
            continue
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "grep", "-l", "-E", pattern],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        if result.returncode == 0 and result.stdout.strip():
            first = result.stdout.splitlines()[0]
            return f"{repo.name}:{first}"
    return None


def verify_file_claim(claim: ModelClaim, repo_roots: list[Path]) -> ModelClaimResult:
    for repo in repo_roots:
        candidate = repo / claim.value
        if candidate.exists():
            return ModelClaimResult(
                claim=claim,
                verified=True,
                evidence=f"{repo.name}:{claim.value}",
            )
    return ModelClaimResult(
        claim=claim,
        verified=False,
        evidence=f"file not found in any target repo: {claim.value}",
    )


def verify_function_claim(
    claim: ModelClaim,
    repo_roots: list[Path],
) -> ModelClaimResult:
    # Match Python, TS/JS function or method definitions.
    pattern = rf"(def |function )?{re.escape(claim.value)}\("
    hit = _grep_repos(pattern, repo_roots)
    if hit:
        return ModelClaimResult(claim=claim, verified=True, evidence=hit)
    return ModelClaimResult(
        claim=claim,
        verified=False,
        evidence=f"function definition not found: {claim.value}",
    )


def verify_class_claim(
    claim: ModelClaim,
    repo_roots: list[Path],
) -> ModelClaimResult:
    pattern = rf"(class |interface ){re.escape(claim.value)}[^A-Za-z0-9_]"
    hit = _grep_repos(pattern, repo_roots)
    if hit:
        return ModelClaimResult(claim=claim, verified=True, evidence=hit)
    return ModelClaimResult(
        claim=claim,
        verified=False,
        evidence=f"class/interface definition not found: {claim.value}",
    )


TableVerifier = "callable[[str], bool] | None"


def verify_table_claim(
    claim: ModelClaim,
    *,
    verifier: object | None = None,
) -> ModelClaimResult:
    """Verify a table exists in the live database.

    ``verifier`` is a callable ``(table_name) -> bool`` so the caller can inject
    test doubles. If not provided, the check is skipped (treated as verified)
    because the offline unit tests don't have DB access — the skill's prompt.md
    wires a real psql verifier when the gate runs in-pipeline.
    """
    if verifier is None:
        return ModelClaimResult(
            claim=claim,
            verified=True,
            evidence=f"skipped (no verifier): {claim.value}",
        )
    if verifier(claim.value):  # type: ignore[operator]
        return ModelClaimResult(
            claim=claim,
            verified=True,
            evidence=f"live db has table: {claim.value}",
        )
    return ModelClaimResult(
        claim=claim,
        verified=False,
        evidence=f"table not found in live db: {claim.value}",
    )


def verify_topic_claim(
    claim: ModelClaim,
    *,
    verifier: object | None = None,
) -> ModelClaimResult:
    if verifier is None:
        return ModelClaimResult(
            claim=claim,
            verified=True,
            evidence=f"skipped (no verifier): {claim.value}",
        )
    if verifier(claim.value):  # type: ignore[operator]
        return ModelClaimResult(
            claim=claim,
            verified=True,
            evidence=f"topic exists on bus: {claim.value}",
        )
    return ModelClaimResult(
        claim=claim,
        verified=False,
        evidence=f"topic not found on bus: {claim.value}",
    )


def run_reality_check(
    ticket_id: str,
    description: str,
    repo_roots: list[Path],
    *,
    table_verifier: object | None = None,
    topic_verifier: object | None = None,
) -> ModelRealityCheckReport:
    """Extract and verify all claims in a ticket description.

    ``table_verifier`` and ``topic_verifier`` are optional callables that
    accept a name and return ``bool``. When omitted the check is skipped for
    that claim kind (treated as verified) so that offline runs and unit tests
    don't require DB/Kafka access. Production callers wire real verifiers.
    """
    claims = extract_claims(description)
    results: list[ModelClaimResult] = []
    for claim in claims:
        if claim.kind == EnumClaimKind.FILE_PATH:
            results.append(verify_file_claim(claim, repo_roots))
        elif claim.kind == EnumClaimKind.FUNCTION:
            results.append(verify_function_claim(claim, repo_roots))
        elif claim.kind == EnumClaimKind.CLASS:
            results.append(verify_class_claim(claim, repo_roots))
        elif claim.kind == EnumClaimKind.TABLE:
            results.append(verify_table_claim(claim, verifier=table_verifier))
        elif claim.kind == EnumClaimKind.TOPIC:
            results.append(verify_topic_claim(claim, verifier=topic_verifier))
    return ModelRealityCheckReport(ticket_id=ticket_id, results=tuple(results))


def _slugify(ticket_id: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", ticket_id.lower()).strip("-")


def diagnosis_path(ticket_id: str, docs_dir: Path) -> Path:
    return docs_dir / f"diagnosis-{_slugify(ticket_id)}-reality-check.md"


def write_diagnosis(
    report: ModelRealityCheckReport,
    docs_dir: Path,
) -> Path:
    """Write a Two-Strike diagnosis document for a halted preflight.

    The document has the four canonical sections enforced by the Two-Strike
    Diagnosis Protocol (see ~/.claude/CLAUDE.md OMN-6232):

      - What is known
      - What was tried and why it failed
      - Root cause hypothesis
      - Proposed fix with rationale
    """
    path = diagnosis_path(report.ticket_id, docs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    failures = report.failures
    verified = [r for r in report.results if r.verified]

    lines: list[str] = [
        f"# Diagnosis — {report.ticket_id} reality-check halt",
        "",
        "## What is known",
        "",
        (
            f"The ticket_pipeline preflight reality-check gate halted "
            f"{report.ticket_id} because {len(failures)} of "
            f"{len(report.results)} claim(s) in the ticket description do not "
            "match the current state of main."
        ),
        "",
        "Failed claims:",
        "",
    ]
    for failure in failures:
        lines.append(
            f"- **{failure.claim.kind.value}** `{failure.claim.value}` — "
            f"{failure.evidence}",
        )

    lines += [
        "",
        "Verified claims:",
        "",
    ]
    if verified:
        for ok in verified:
            lines.append(
                f"- **{ok.claim.kind.value}** `{ok.claim.value}` — {ok.evidence}",
            )
    else:
        lines.append("- (none)")

    lines += [
        "",
        "## What was tried and why it failed",
        "",
        (
            "Automated preflight reality-check parsed the Linear ticket "
            "description for concrete symbols (file paths, function names, "
            "class names, table names, Kafka topics) and verified each against "
            "the current main branch. Each failure above represents a ticket "
            "claim that the symbol exists where the ticket says it does — but "
            "the symbol is absent from the target repos."
        ),
        "",
        "## Root cause hypothesis",
        "",
        (
            "The ticket description was written against a stale mental model, "
            "a prior branch, or speculation. Executing it as-written would "
            "produce wrong-approach friction: workers editing the wrong repo, "
            "renaming symbols that don't exist, or claiming fixes for missing "
            "code paths."
        ),
        "",
        "## Proposed fix with rationale",
        "",
        ("Reframe or decompose the ticket before re-running the pipeline:"),
        "",
        (
            "1. Confirm whether each failed claim refers to a symbol that "
            "**should exist** (scope is to create it) or **was expected to "
            "exist** (stale description that needs correction)."
        ),
        (
            "2. If the symbol should be created, update the ticket description "
            "to frame it as a new-feature task and re-run the pipeline."
        ),
        (
            "3. If the symbol was expected, find the current equivalent via "
            "grep/git log and update the ticket to reference the real path."
        ),
        (
            "4. If neither, the ticket is speculative — close it or decompose "
            "into concrete sub-tickets grounded in current code."
        ),
        "",
        (
            f"Re-run the pipeline with `/onex:ticket_pipeline {report.ticket_id}` "
            "after updating the ticket description. The preflight will re-verify "
            "every claim before any code is edited."
        ),
        "",
    ]

    path.write_text("\n".join(lines))
    return path


def resolve_repo_roots(repos: list[str] | None = None) -> list[Path]:
    """Resolve a list of repo names under ``$ONEX_REGISTRY_ROOT`` to absolute paths.

    If ``repos`` is None, returns an empty list — callers must pass the repos
    explicitly (no implicit workspace scan).
    """
    omni_home = Path(os.environ.get("ONEX_REGISTRY_ROOT", ""))
    if not omni_home or not repos:
        return []
    return [omni_home / name for name in repos]


__all__: list[str] = [
    "EnumClaimKind",
    "ModelClaim",
    "ModelClaimResult",
    "ModelRealityCheckReport",
    "diagnosis_path",
    "extract_claims",
    "resolve_repo_roots",
    "run_reality_check",
    "verify_class_claim",
    "verify_file_claim",
    "verify_function_claim",
    "verify_table_claim",
    "verify_topic_claim",
    "write_diagnosis",
]

# Quiet unused-import warning for Literal; reserved for future use in verifiers.
_ = Literal
