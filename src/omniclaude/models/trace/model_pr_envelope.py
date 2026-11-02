# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""PREnvelope model and frame-to-PR association logic.

A PR is not an event — it is a container of frames. The PR is the
human-readable summary; ChangeFrames are the source of truth.

Models:
- PREnvelope: top-level PR record with full lifecycle metadata
- ModelPRText: title + versioned body history
- ModelPRBodyVersion: immutable snapshot of a PR body edit
- ModelPRTimeline: created/merged timestamps
- ModelCIArtifact: CI check result captured at PR review time
- PRDescriptionDelta: immutable record of a PR body edit
- AssociationResult: result of frame-to-PR matching with method used

Stage 5 of DESIGN_AGENT_TRACE_PR_DEBUGGING_SYSTEM.md
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class ModelPRBodyVersion(BaseModel):
    """Immutable snapshot of a PR body at a point in time."""

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    version: int
    body: str
    body_hash: str  # SHA-256 of body
    timestamp: str  # ISO-8601 UTC — explicitly injected, no datetime.now()

    @model_validator(mode="after")
    def validate_body_hash(self) -> ModelPRBodyVersion:
        """Verify body_hash matches body content."""
        expected = hashlib.sha256(self.body.encode("utf-8")).hexdigest()
        if self.body_hash != expected:
            raise ValueError(
                f"ModelPRBodyVersion invariant: body_hash mismatch. "
                f"Expected {expected[:16]}…, got {self.body_hash[:16]}…"
            )
        return self


class ModelPRText(BaseModel):
    """PR title and versioned body history."""

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    title: str
    body_versions: list[ModelPRBodyVersion]

    @model_validator(mode="after")
    def validate_body_versions(self) -> ModelPRText:
        """Ensure body_versions are ordered by version number."""
        if not self.body_versions:
            return self
        versions = [v.version for v in self.body_versions]
        if versions != sorted(versions):
            raise ValueError(
                "ModelPRText invariant: body_versions must be ordered by version"
            )
        return self


class ModelPRTimeline(BaseModel):
    """PR lifecycle timestamps."""

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    created_at: str  # ISO-8601 UTC
    merged_at: str | None = None  # ISO-8601 UTC, set on merge


class ModelCIArtifact(BaseModel):
    """CI check result captured at PR review time."""

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    check_name: str
    status: Literal["success", "failure"]
    logs_pointer: str  # URL or storage key to full logs


# ---------------------------------------------------------------------------
# Primary PREnvelope model
# ---------------------------------------------------------------------------


class PREnvelope(BaseModel):
    """Container model representing a pull request and its full lifecycle.

    Invariants:
    1. pr_number must be positive
    2. head_sha and base_sha must be non-empty (valid commit references)
    3. pr_text must have at least one body version (the initial PR body)
    """

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    pr_id: UUID
    provider: Literal["github"]
    repo: str
    pr_number: int
    head_sha: str
    base_sha: str
    branch_name: str
    pr_text: ModelPRText
    labels: list[str] = []
    linked_issues: list[str] = []
    reviewers: list[str] = []
    timeline: ModelPRTimeline
    ci_artifacts: list[ModelCIArtifact] = []

    @model_validator(mode="after")
    def validate_pr_envelope_invariants(self) -> PREnvelope:
        """Enforce PREnvelope invariants."""
        # Invariant 1: pr_number must be positive
        if self.pr_number <= 0:
            raise ValueError(
                f"PREnvelope invariant: pr_number must be positive, got {self.pr_number}"
            )
        # Invariant 2: SHAs must be non-empty
        if not self.head_sha.strip():
            raise ValueError("PREnvelope invariant: head_sha must be non-empty")
        if not self.base_sha.strip():
            raise ValueError("PREnvelope invariant: base_sha must be non-empty")
        # Invariant 3: at least one body version
        if not self.pr_text.body_versions:
            raise ValueError(
                "PREnvelope invariant: pr_text must have at least one body version"
            )
        return self


# ---------------------------------------------------------------------------
# PR description delta (immutable edit history record)
# ---------------------------------------------------------------------------


class PRDescriptionDelta(BaseModel):
    """Immutable record of a PR body edit.

    Every PR body edit creates a new PRDescriptionDelta. These records
    form the complete audit trail of PR description changes.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    pr_id: UUID
    old_hash: str  # SHA-256 of previous body
    new_hash: str  # SHA-256 of new body
    timestamp: str  # ISO-8601 UTC — explicitly injected


# ---------------------------------------------------------------------------
# Frame-to-PR association
# ---------------------------------------------------------------------------


class AssociationResult(BaseModel):
    """Result of matching a ChangeFrame to a PREnvelope.

    Records which association method succeeded and the confidence
    of the match for audit purposes.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    frame_id: UUID
    pr_id: UUID
    association_method: Literal[
        "commit_ancestry",
        "branch_name",
        "diff_overlap",
        "patch_hash",
    ]
    confidence: float  # 0.0–1.0; higher = more confident


# ---------------------------------------------------------------------------
# Frame-to-PR association functions
# ---------------------------------------------------------------------------


def associate_by_commit_ancestry(
    frame_base_commit: str,
    pr_commit_shas: list[str],
) -> bool:
    """Method 1 (primary): Check if frame's base commit appears in PR history.

    Args:
        frame_base_commit: SHA from frame's workspace_ref.base_commit
        pr_commit_shas: List of commit SHAs in the PR (from GitHub API)

    Returns:
        True if frame_base_commit appears in the PR commit list
    """
    return frame_base_commit in pr_commit_shas


def associate_by_branch_name(
    frame_branch: str,
    pr_branch_name: str,
) -> bool:
    """Method 2 (fallback): Check if frame's branch matches the PR branch.

    Args:
        frame_branch: Branch name from frame's workspace_ref.branch
        pr_branch_name: Branch name from the PR

    Returns:
        True if branches match (case-sensitive)
    """
    return frame_branch == pr_branch_name


def associate_by_diff_overlap(
    frame_files: list[str],
    pr_files: list[str],
) -> float:
    """Method 3 (safety): Measure file overlap between frame and PR diffs.

    Uses Jaccard similarity: |intersection| / |union|

    Args:
        frame_files: Files changed in the ChangeFrame
        pr_files: Files changed in the PR

    Returns:
        Overlap ratio in [0.0, 1.0]; 0.0 if both are empty
    """
    if not frame_files and not pr_files:
        return 0.0
    frame_set = set(frame_files)
    pr_set = set(pr_files)
    intersection = frame_set & pr_set
    union = frame_set | pr_set
    if not union:
        return 0.0
    return len(intersection) / len(union)


def associate_by_patch_hash(
    frame_diff_patch: str,
    pr_diff_patch: str,
) -> bool:
    """Method 4 (safety): Check if frame and PR diffs share a content hash.

    Normalizes whitespace before hashing to handle trivial formatting diffs.

    Args:
        frame_diff_patch: Unified diff from the ChangeFrame
        pr_diff_patch: Unified diff from the PR

    Returns:
        True if normalized patch content hashes match
    """
    normalized_frame = _normalize_patch(frame_diff_patch)
    normalized_pr = _normalize_patch(pr_diff_patch)
    if not normalized_frame or not normalized_pr:
        return False
    hash_frame = hashlib.sha256(normalized_frame.encode("utf-8")).hexdigest()
    hash_pr = hashlib.sha256(normalized_pr.encode("utf-8")).hexdigest()
    return hash_frame == hash_pr


def _normalize_patch(patch: str) -> str:
    """Normalize a unified diff for stable hashing.

    Strips index lines, removes trailing whitespace, collapses blank lines.
    """
    lines = []
    for line in patch.splitlines():
        # Skip git index lines (unstable hashes)
        if re.match(r"^index [0-9a-f]+\.\.[0-9a-f]+", line):
            continue
        lines.append(line.rstrip())
    return "\n".join(line for line in lines if line)


def find_best_association(
    frame_base_commit: str,
    frame_branch: str,
    frame_files: list[str],
    frame_diff_patch: str,
    pr_envelope: PREnvelope,
    pr_commit_shas: list[str],
    pr_files: list[str],
    pr_diff_patch: str,
    diff_overlap_threshold: float = 0.2,
) -> AssociationResult | None:
    """Try all four association methods in priority order.

    Priority:
    1. Commit ancestry (highest confidence = 1.0)
    2. Branch name (confidence = 0.8)
    3. Diff overlap >= threshold (confidence = overlap ratio)
    4. Patch hash (confidence = 0.9)

    Returns:
        AssociationResult for the first successful method, or None if no match
    """
    # Method 1: commit ancestry
    if associate_by_commit_ancestry(frame_base_commit, pr_commit_shas):
        return AssociationResult(
            frame_id=UUID(int=0),  # Caller must set the real frame_id
            pr_id=pr_envelope.pr_id,
            association_method="commit_ancestry",
            confidence=1.0,
        )

    # Method 2: branch name
    if associate_by_branch_name(frame_branch, pr_envelope.branch_name):
        return AssociationResult(
            frame_id=UUID(int=0),
            pr_id=pr_envelope.pr_id,
            association_method="branch_name",
            confidence=0.8,
        )

    # Method 3: diff overlap
    overlap = associate_by_diff_overlap(frame_files, pr_files)
    if overlap >= diff_overlap_threshold:
        return AssociationResult(
            frame_id=UUID(int=0),
            pr_id=pr_envelope.pr_id,
            association_method="diff_overlap",
            confidence=overlap,
        )

    # Method 4: patch hash
    if associate_by_patch_hash(frame_diff_patch, pr_diff_patch):
        return AssociationResult(
            frame_id=UUID(int=0),
            pr_id=pr_envelope.pr_id,
            association_method="patch_hash",
            confidence=0.9,
        )

    return None


# ---------------------------------------------------------------------------
# Helper: compute body hash (for creating ModelPRBodyVersion)
# ---------------------------------------------------------------------------


def compute_body_hash(body: str) -> str:
    """Compute SHA-256 hash of a PR body string."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
