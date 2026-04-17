# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Agent claim extractor (OMN-9055 Task 4 scaffold).

Scans Agent turn output for structured claims about side effects that a
PostToolUse hook can subsequently verify against ground truth. Scaffold
taxonomy (3 kinds): pr_merged, thread_resolved, linear_state.

Maturity (≥6 kinds: pr_opened, commit_sha, ci_passing, file_committed,
blocker_on_X) and real resolver integration ship under a follow-up ticket;
`node_evidence_bundle` is NOT the right surface — its request shape targets
ticket-execution evidence bundles, not agent-turn claims. A dedicated
claim-resolver node in omnimarket is required for the maturity upgrade.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

EnumClaimKind = Literal["pr_merged", "thread_resolved", "linear_state"]


class ModelAgentClaim(BaseModel):
    """A single verifiable claim extracted from an agent turn.

    Attributes:
        kind: Category of claim; determines which resolver is used.
        ref: Canonical reference (e.g. "omniclaude#1336", "OMN-9032").
        expected: Expected value when `kind` names a state transition
            (e.g. "Done" for a linear_state claim). None for pure assertions.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: EnumClaimKind
    ref: str
    expected: str | None = None


_PR_MERGED_RE = re.compile(r"PR\s+#(\d+)\s+merged", re.IGNORECASE)
_THREAD_RESOLVED_RE = re.compile(
    r"thread\s+(PRRT_[A-Za-z0-9_-]+)\s+(?:resolved|with\s+reply\s*\+\s*resolve)",
    re.IGNORECASE,
)
_LINEAR_STATE_RE = re.compile(
    r"(OMN-\d+)\s+moved\s+to\s+(Done|Cancelled|In\s+Progress|Todo|Backlog)",
    re.IGNORECASE,
)


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

    for match in _THREAD_RESOLVED_RE.finditer(body):
        claims.append(ModelAgentClaim(kind="thread_resolved", ref=match.group(1)))

    for match in _LINEAR_STATE_RE.finditer(body):
        expected_raw = match.group(2)
        expected = " ".join(part.capitalize() for part in expected_raw.split())
        claims.append(
            ModelAgentClaim(
                kind="linear_state",
                ref=match.group(1),
                expected=expected,
            )
        )

    return claims


__all__ = ["EnumClaimKind", "ModelAgentClaim", "extract_claims"]
