# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Agent claim extractor for resolver-backed hook verification.

Scans Agent turn output for structured claims about side effects that a
PostToolUse hook can verify against the omnimarket claim-resolver node.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

EnumClaimKind = Literal[
    "pr_merged",
    "pr_opened",
    "commit_sha",
    "ci_passing",
    "file_committed",
    "blocker_on_X",
    "thread_resolved",
    "linear_state",
]


class ModelAgentClaim(BaseModel):
    """A single verifiable claim extracted from an agent turn.

    Attributes:
        kind: Category of claim; determines which resolver is used.
        ref: Canonical reference (e.g. "omniclaude#1336", "OMN-9032").
        expected: Expected value when `kind` names a state transition
            (e.g. "Done" for a linear_state claim). None for pure assertions.
        evidence: Quoted command/evidence snippets attached to the claim.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EnumClaimKind
    ref: str
    expected: str | None = None
    evidence: tuple[str, ...] = ()


_PR_MERGED_RE = re.compile(r"PR\s+#(\d+)\s+merged", re.IGNORECASE)
_PR_OPENED_RE = re.compile(
    r"(?:PR\s+#(\d+)\s+(?:opened|created)|(?:opened|created)\s+PR\s+#(\d+))",
    re.IGNORECASE,
)
_CI_PASSING_RE = re.compile(
    r"(?:"
    r"(?:CI|checks?)\s+(?:is\s+)?passing\s+(?:for|on)\s+PR\s+#(\d+)"
    r"|PR\s+#(\d+)\s+(?:CI|checks?)\s+(?:is\s+)?passing"
    r")",
    re.IGNORECASE,
)
_COMMIT_SHA_RE = re.compile(
    r"\b(?:commit(?:ted)?|commit\s+sha)\s+([0-9a-f]{7,40})\b",
    re.IGNORECASE,
)
_FILE_COMMITTED_RE = re.compile(
    r"\b(?:committed|added|updated)\s+file\s+([A-Za-z0-9_./-]+)",
    re.IGNORECASE,
)
_BLOCKER_ON_RE = re.compile(
    r"\bblocker\s+on\s+([A-Z]+-\d+|[#A-Za-z0-9_./-]+)",
    re.IGNORECASE,
)
_THREAD_RESOLVED_RE = re.compile(
    r"thread\s+(PRRT_[A-Za-z0-9_-]+)\s+(?:resolved|with\s+reply\s*\+\s*resolve)",
    re.IGNORECASE,
)
_LINEAR_STATE_RE = re.compile(
    r"(OMN-\d+)\s+moved\s+to\s+(Done|Cancelled|In\s+Progress|Todo|Backlog)",
    re.IGNORECASE,
)
_QUOTED_SNIPPET_RE = re.compile(
    r"`([^`]+)`|\"([^\"]*gh\s+pr\s+view[^\"]*)\"|'([^']*gh\s+pr\s+view[^']*)'",
    re.IGNORECASE,
)
_JSON_EVIDENCE_RE = re.compile(r"(\{[^{}]*(?:isResolved|resolved|state|name)[^{}]*\})")


def extract_claims(body: str, repo_hint: str | None) -> list[ModelAgentClaim]:
    """Extract structured claims from a free-form agent turn body.

    Args:
        body: Raw agent turn output (stdout/chat text).
        repo_hint: Repository slug to qualify PR references; if None, refs
            are emitted without a repo prefix ("#1336" rather than
            "omniclaude#1336") and must be resolved by caller context.

    Returns:
        List of `ModelAgentClaim`. Empty when no recognized claim patterns
        match (plain prose, empty body).
    """
    claims: list[ModelAgentClaim] = []

    for match in _PR_MERGED_RE.finditer(body):
        number = match.group(1)
        ref = f"{repo_hint}#{number}" if repo_hint else f"#{number}"
        claims.append(ModelAgentClaim(kind="pr_merged", ref=ref))

    for match in _PR_OPENED_RE.finditer(body):
        number = match.group(1) or match.group(2)
        ref = f"{repo_hint}#{number}" if repo_hint else f"#{number}"
        claims.append(ModelAgentClaim(kind="pr_opened", ref=ref))

    for match in _CI_PASSING_RE.finditer(body):
        number = match.group(1) or match.group(2)
        ref = f"{repo_hint}#{number}" if repo_hint else f"#{number}"
        claims.append(ModelAgentClaim(kind="ci_passing", ref=ref, expected="passing"))

    for match in _COMMIT_SHA_RE.finditer(body):
        claims.append(ModelAgentClaim(kind="commit_sha", ref=match.group(1)))

    for match in _FILE_COMMITTED_RE.finditer(body):
        claims.append(
            ModelAgentClaim(kind="file_committed", ref=match.group(1).rstrip(".,;:"))
        )

    quoted_evidence = _extract_quoted_evidence(body)
    for match in _BLOCKER_ON_RE.finditer(body):
        claims.append(
            ModelAgentClaim(
                kind="blocker_on_X",
                ref=match.group(1),
                evidence=quoted_evidence,
            )
        )

    json_evidence = _extract_json_evidence(body)
    for match in _THREAD_RESOLVED_RE.finditer(body):
        claims.append(
            ModelAgentClaim(
                kind="thread_resolved",
                ref=match.group(1),
                evidence=json_evidence,
            )
        )

    for match in _LINEAR_STATE_RE.finditer(body):
        expected_raw = match.group(2)
        expected = " ".join(part.capitalize() for part in expected_raw.split())
        claims.append(
            ModelAgentClaim(
                kind="linear_state",
                ref=match.group(1),
                expected=expected,
                evidence=json_evidence,
            )
        )

    return claims


def _extract_quoted_evidence(body: str) -> tuple[str, ...]:
    evidence: list[str] = []
    for match in _QUOTED_SNIPPET_RE.finditer(body):
        snippet = next(group for group in match.groups() if group)
        evidence.append(snippet.strip())
    return tuple(evidence)


def _extract_json_evidence(body: str) -> tuple[str, ...]:
    return tuple(match.group(1).strip() for match in _JSON_EVIDENCE_RE.finditer(body))


__all__ = ["EnumClaimKind", "ModelAgentClaim", "extract_claims"]
