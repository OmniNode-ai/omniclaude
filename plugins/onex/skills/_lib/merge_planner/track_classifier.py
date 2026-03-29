# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Merge-sweep Track A/B/C PR classifier for OMN-6506.

Classifies PRs into merge-sweep tracks:
    Track A — ready to merge (all checks pass, no unresolved comments, mergeable)
    Track B — needs polish (checks pass but has unresolved review comments)
    Track C — blocked (checks failing, merge conflicts, or draft)

Deterministic, no I/O. Designed for use in merge-sweep's classify step.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumMergeSweepTrack(StrEnum):
    """Merge-sweep track classification."""

    TRACK_A = "track_a"  # Ready to merge
    TRACK_B = "track_b"  # Needs polish
    TRACK_C = "track_c"  # Blocked


class ModelPRClassificationInput(BaseModel):
    """Input data for PR track classification.

    Populated from ``gh pr view`` JSON output.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    number: int = Field(..., ge=1, description="PR number.")
    repo: str = Field(..., description="Repository slug (owner/name).")
    title: str = Field(default="", description="PR title.")
    is_draft: bool = Field(default=False, description="Whether PR is a draft.")
    mergeable_state: str = Field(
        default="UNKNOWN",
        description="GitHub mergeable state: MERGEABLE, CONFLICTING, UNKNOWN.",
    )
    ci_status: str = Field(
        default="pending",
        description="CI status: success, failure, pending.",
    )
    has_unresolved_comments: bool = Field(
        default=False,
        description="Whether PR has unresolved review thread comments.",
    )
    review_decision: str = Field(
        default="none",
        description="Review decision: approved, changes_requested, none.",
    )
    auto_merge_enabled: bool = Field(
        default=False,
        description="Whether auto-merge is enabled on the PR.",
    )
    in_merge_queue: bool = Field(
        default=False,
        description="Whether PR is currently in the merge queue.",
    )


class ModelPRClassificationResult(BaseModel):
    """Result of PR track classification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int = Field(..., ge=1)
    repo: str
    track: EnumMergeSweepTrack
    reason: str = Field(..., description="Human-readable classification reason.")


def classify_pr_track(pr: ModelPRClassificationInput) -> ModelPRClassificationResult:
    """Classify a PR into a merge-sweep track.

    Classification rules (evaluated in order):
        1. In merge queue -> skip (not classified)
        2. Draft -> Track C
        3. CI failing -> Track C
        4. Merge conflicts -> Track C
        5. Changes requested -> Track C
        6. Unresolved review comments -> Track B
        7. Otherwise -> Track A
    """
    number = pr.number
    repo = pr.repo

    # Skip PRs in merge queue — they're already being processed
    if pr.in_merge_queue:
        return ModelPRClassificationResult(
            number=number,
            repo=repo,
            track=EnumMergeSweepTrack.TRACK_C,
            reason="In merge queue — skip",
        )

    # Track C: blocked conditions
    if pr.is_draft:
        return ModelPRClassificationResult(
            number=number,
            repo=repo,
            track=EnumMergeSweepTrack.TRACK_C,
            reason="Draft PR",
        )

    if pr.ci_status == "failure":
        return ModelPRClassificationResult(
            number=number,
            repo=repo,
            track=EnumMergeSweepTrack.TRACK_C,
            reason="CI checks failing",
        )

    if pr.mergeable_state == "CONFLICTING":
        return ModelPRClassificationResult(
            number=number,
            repo=repo,
            track=EnumMergeSweepTrack.TRACK_C,
            reason="Merge conflicts",
        )

    if pr.review_decision == "changes_requested":
        return ModelPRClassificationResult(
            number=number,
            repo=repo,
            track=EnumMergeSweepTrack.TRACK_C,
            reason="Changes requested by reviewer",
        )

    # Track B: needs polish
    if pr.has_unresolved_comments:
        return ModelPRClassificationResult(
            number=number,
            repo=repo,
            track=EnumMergeSweepTrack.TRACK_B,
            reason="Unresolved review comments",
        )

    # Track A: ready to merge
    return ModelPRClassificationResult(
        number=number,
        repo=repo,
        track=EnumMergeSweepTrack.TRACK_A,
        reason="All checks pass, no blockers",
    )


def classify_prs(
    prs: list[ModelPRClassificationInput],
) -> dict[EnumMergeSweepTrack, list[ModelPRClassificationResult]]:
    """Classify a batch of PRs and group by track.

    Returns a dict mapping each track to its classified PRs.
    """
    results: dict[EnumMergeSweepTrack, list[ModelPRClassificationResult]] = {
        EnumMergeSweepTrack.TRACK_A: [],
        EnumMergeSweepTrack.TRACK_B: [],
        EnumMergeSweepTrack.TRACK_C: [],
    }
    for pr in prs:
        result = classify_pr_track(pr)
        results[result.track].append(result)
    return results


__all__ = [
    "EnumMergeSweepTrack",
    "ModelPRClassificationInput",
    "ModelPRClassificationResult",
    "classify_pr_track",
    "classify_prs",
]
