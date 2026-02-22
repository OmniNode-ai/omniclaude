"""Unit tests for PREnvelope models and frame-to-PR association logic.

Tests:
- ModelPRBodyVersion validation (body hash integrity)
- ModelPRText ordering invariant
- PREnvelope invariants (pr_number, SHAs, body_versions)
- PRDescriptionDelta structure
- AssociationResult model
- associate_by_commit_ancestry
- associate_by_branch_name
- associate_by_diff_overlap (Jaccard similarity)
- associate_by_patch_hash
- find_best_association (priority order)
- compute_body_hash helper
- _normalize_patch helper
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from omniclaude.trace.pr_envelope import (
    ModelCIArtifact,
    ModelPRBodyVersion,
    ModelPRText,
    ModelPRTimeline,
    PRDescriptionDelta,
    PREnvelope,
    _normalize_patch,
    associate_by_branch_name,
    associate_by_commit_ancestry,
    associate_by_diff_overlap,
    associate_by_patch_hash,
    compute_body_hash,
    find_best_association,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TIMESTAMP = "2026-02-21T00:00:00Z"
SHA_EMPTY = "a" * 40


def make_body_version(
    version: int = 1,
    body: str = "# My PR\n\nSome description.",
    timestamp: str = TIMESTAMP,
) -> ModelPRBodyVersion:
    return ModelPRBodyVersion(
        version=version,
        body=body,
        body_hash=compute_body_hash(body),
        timestamp=timestamp,
    )


def make_pr_text(
    title: str = "Fix the bug",
    body: str = "# My PR\n\nSome description.",
) -> ModelPRText:
    return ModelPRText(
        title=title,
        body_versions=[make_body_version(version=1, body=body)],
    )


def make_pr_envelope(
    pr_number: int = 42,
    head_sha: str = "abc123" + "0" * 34,
    base_sha: str = "def456" + "0" * 34,
    branch_name: str = "feature/my-branch",
) -> PREnvelope:
    return PREnvelope(
        pr_id=uuid4(),
        provider="github",
        repo="OmniNode-ai/omniclaude",
        pr_number=pr_number,
        head_sha=head_sha,
        base_sha=base_sha,
        branch_name=branch_name,
        pr_text=make_pr_text(),
        timeline=ModelPRTimeline(created_at=TIMESTAMP),
    )


# ---------------------------------------------------------------------------
# ModelPRBodyVersion tests
# ---------------------------------------------------------------------------


class TestModelPRBodyVersion:
    def test_valid_body_version(self) -> None:
        body = "# My PR"
        bv = ModelPRBodyVersion(
            version=1,
            body=body,
            body_hash=compute_body_hash(body),
            timestamp=TIMESTAMP,
        )
        assert bv.version == 1
        assert bv.body == body

    def test_body_hash_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="body_hash mismatch"):
            ModelPRBodyVersion(
                version=1,
                body="# My PR",
                body_hash="wrong" * 10,
                timestamp=TIMESTAMP,
            )

    def test_is_frozen(self) -> None:
        bv = make_body_version()
        with pytest.raises(Exception):  # ValidationError or AttributeError
            bv.version = 99  # type: ignore[misc]

    def test_empty_body_accepted(self) -> None:
        body = ""
        bv = ModelPRBodyVersion(
            version=1,
            body=body,
            body_hash=compute_body_hash(body),
            timestamp=TIMESTAMP,
        )
        assert bv.body == ""


# ---------------------------------------------------------------------------
# ModelPRText tests
# ---------------------------------------------------------------------------


class TestModelPRText:
    def test_valid_pr_text(self) -> None:
        pt = make_pr_text()
        assert pt.title == "Fix the bug"
        assert len(pt.body_versions) == 1

    def test_multiple_ordered_versions(self) -> None:
        v1 = make_body_version(version=1)
        v2 = make_body_version(version=2, body="Updated body")
        pt = ModelPRText(title="My PR", body_versions=[v1, v2])
        assert len(pt.body_versions) == 2

    def test_unordered_versions_raises(self) -> None:
        v1 = make_body_version(version=1)
        v2 = make_body_version(version=2, body="Updated body")
        with pytest.raises(ValueError, match="ordered by version"):
            ModelPRText(title="My PR", body_versions=[v2, v1])

    def test_empty_body_versions_allowed(self) -> None:
        # ModelPRText itself allows empty — PREnvelope enforces non-empty
        pt = ModelPRText(title="My PR", body_versions=[])
        assert pt.body_versions == []


# ---------------------------------------------------------------------------
# PREnvelope tests
# ---------------------------------------------------------------------------


class TestPREnvelope:
    def test_valid_pr_envelope(self) -> None:
        pr = make_pr_envelope()
        assert pr.pr_number == 42
        assert pr.provider == "github"

    def test_negative_pr_number_raises(self) -> None:
        with pytest.raises(ValueError, match="pr_number must be positive"):
            make_pr_envelope(pr_number=-1)

    def test_zero_pr_number_raises(self) -> None:
        with pytest.raises(ValueError, match="pr_number must be positive"):
            make_pr_envelope(pr_number=0)

    def test_empty_head_sha_raises(self) -> None:
        with pytest.raises(ValueError, match="head_sha must be non-empty"):
            make_pr_envelope(head_sha="  ")

    def test_empty_base_sha_raises(self) -> None:
        with pytest.raises(ValueError, match="base_sha must be non-empty"):
            make_pr_envelope(base_sha="")

    def test_empty_body_versions_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one body version"):
            PREnvelope(
                pr_id=uuid4(),
                provider="github",
                repo="OmniNode-ai/omniclaude",
                pr_number=42,
                head_sha="abc123",
                base_sha="def456",
                branch_name="main",
                pr_text=ModelPRText(title="My PR", body_versions=[]),
                timeline=ModelPRTimeline(created_at=TIMESTAMP),
            )

    def test_is_frozen(self) -> None:
        pr = make_pr_envelope()
        with pytest.raises(Exception):
            pr.pr_number = 99  # type: ignore[misc]

    def test_optional_fields_default(self) -> None:
        pr = make_pr_envelope()
        assert pr.labels == []
        assert pr.linked_issues == []
        assert pr.reviewers == []
        assert pr.ci_artifacts == []

    def test_with_labels_and_reviewers(self) -> None:
        pr = PREnvelope(
            pr_id=uuid4(),
            provider="github",
            repo="OmniNode-ai/omniclaude",
            pr_number=10,
            head_sha="abc123",
            base_sha="def456",
            branch_name="feature/xyz",
            pr_text=make_pr_text(),
            labels=["bug", "trace"],
            reviewers=["alice", "bob"],
            timeline=ModelPRTimeline(created_at=TIMESTAMP),
        )
        assert "bug" in pr.labels
        assert "alice" in pr.reviewers

    def test_merged_at_in_timeline(self) -> None:
        pr = PREnvelope(
            pr_id=uuid4(),
            provider="github",
            repo="OmniNode-ai/omniclaude",
            pr_number=5,
            head_sha="abc",
            base_sha="def",
            branch_name="main",
            pr_text=make_pr_text(),
            timeline=ModelPRTimeline(
                created_at=TIMESTAMP,
                merged_at="2026-02-22T00:00:00Z",
            ),
        )
        assert pr.timeline.merged_at is not None

    def test_ci_artifacts(self) -> None:
        artifact = ModelCIArtifact(
            check_name="Quality Gate",
            status="success",
            logs_pointer="https://example.com/logs/123",
        )
        pr = PREnvelope(
            pr_id=uuid4(),
            provider="github",
            repo="OmniNode-ai/omniclaude",
            pr_number=7,
            head_sha="abc",
            base_sha="def",
            branch_name="main",
            pr_text=make_pr_text(),
            timeline=ModelPRTimeline(created_at=TIMESTAMP),
            ci_artifacts=[artifact],
        )
        assert pr.ci_artifacts[0].status == "success"


# ---------------------------------------------------------------------------
# PRDescriptionDelta tests
# ---------------------------------------------------------------------------


class TestPRDescriptionDelta:
    def test_valid_delta(self) -> None:
        delta = PRDescriptionDelta(
            pr_id=uuid4(),
            old_hash="a" * 64,
            new_hash="b" * 64,
            timestamp=TIMESTAMP,
        )
        assert delta.old_hash != delta.new_hash

    def test_is_frozen(self) -> None:
        delta = PRDescriptionDelta(
            pr_id=uuid4(),
            old_hash="a" * 64,
            new_hash="b" * 64,
            timestamp=TIMESTAMP,
        )
        with pytest.raises(Exception):
            delta.old_hash = "c" * 64  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Association function tests
# ---------------------------------------------------------------------------


class TestAssociateByCommitAncestry:
    def test_returns_true_when_commit_in_list(self) -> None:
        sha = "abc123def456" + "0" * 28
        assert associate_by_commit_ancestry(sha, [sha, "other"]) is True

    def test_returns_false_when_not_in_list(self) -> None:
        assert associate_by_commit_ancestry("abc123", ["def456", "ghi789"]) is False

    def test_returns_false_for_empty_list(self) -> None:
        assert associate_by_commit_ancestry("abc123", []) is False

    def test_exact_match_required(self) -> None:
        assert associate_by_commit_ancestry("abc123", ["abc12"]) is False


class TestAssociateByBranchName:
    def test_matching_branch(self) -> None:
        assert associate_by_branch_name("feature/trace", "feature/trace") is True

    def test_mismatched_branch(self) -> None:
        assert associate_by_branch_name("feature/trace", "feature/other") is False

    def test_case_sensitive(self) -> None:
        assert associate_by_branch_name("Feature/Trace", "feature/trace") is False

    def test_empty_both(self) -> None:
        assert associate_by_branch_name("", "") is True


class TestAssociateByDiffOverlap:
    def test_perfect_overlap(self) -> None:
        files = ["src/foo.py", "src/bar.py"]
        assert associate_by_diff_overlap(files, files) == 1.0

    def test_no_overlap(self) -> None:
        assert associate_by_diff_overlap(["a.py"], ["b.py"]) == 0.0

    def test_partial_overlap(self) -> None:
        result = associate_by_diff_overlap(["a.py", "b.py"], ["b.py", "c.py"])
        # intersection = {b.py}, union = {a.py, b.py, c.py} → 1/3
        assert abs(result - 1 / 3) < 1e-9

    def test_empty_both(self) -> None:
        assert associate_by_diff_overlap([], []) == 0.0

    def test_one_empty(self) -> None:
        assert associate_by_diff_overlap(["a.py"], []) == 0.0


class TestAssociateByPatchHash:
    def test_identical_patches_match(self) -> None:
        patch = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n+added line"
        assert associate_by_patch_hash(patch, patch) is True

    def test_different_patches_no_match(self) -> None:
        p1 = "--- a/foo.py\n+++ b/foo.py\n+added line"
        p2 = "--- a/bar.py\n+++ b/bar.py\n+other line"
        assert associate_by_patch_hash(p1, p2) is False

    def test_empty_patches_no_match(self) -> None:
        assert associate_by_patch_hash("", "") is False

    def test_index_line_stripped(self) -> None:
        """Two patches that differ only in git index line should match."""
        base = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n+added"
        p1 = f"index abc123..def456 100644\n{base}"
        p2 = f"index 999aaa..111bbb 100644\n{base}"
        assert associate_by_patch_hash(p1, p2) is True


# ---------------------------------------------------------------------------
# find_best_association priority tests
# ---------------------------------------------------------------------------


class TestFindBestAssociation:
    def _make_default_pr(self) -> PREnvelope:
        return make_pr_envelope(branch_name="feature/trace")

    def _patch(self) -> str:
        return "--- a/src/foo.py\n+++ b/src/foo.py\n+added"

    def test_commit_ancestry_wins_first(self) -> None:
        pr = self._make_default_pr()
        commit_sha = "abc" + "0" * 37
        result = find_best_association(
            frame_base_commit=commit_sha,
            frame_branch="other-branch",
            frame_files=["unrelated.py"],
            frame_diff_patch="",
            pr_envelope=pr,
            pr_commit_shas=[commit_sha],
            pr_files=["unrelated.py"],
            pr_diff_patch="",
        )
        assert result is not None
        assert result.association_method == "commit_ancestry"
        assert result.confidence == 1.0

    def test_branch_name_fallback(self) -> None:
        pr = self._make_default_pr()
        result = find_best_association(
            frame_base_commit="missing",
            frame_branch="feature/trace",
            frame_files=[],
            frame_diff_patch="",
            pr_envelope=pr,
            pr_commit_shas=[],
            pr_files=[],
            pr_diff_patch="",
        )
        assert result is not None
        assert result.association_method == "branch_name"
        assert result.confidence == 0.8

    def test_diff_overlap_method(self) -> None:
        pr = self._make_default_pr()
        result = find_best_association(
            frame_base_commit="missing",
            frame_branch="wrong-branch",
            frame_files=["src/foo.py", "src/bar.py"],
            frame_diff_patch="",
            pr_envelope=pr,
            pr_commit_shas=[],
            pr_files=["src/foo.py", "src/baz.py"],
            pr_diff_patch="",
            diff_overlap_threshold=0.2,
        )
        assert result is not None
        assert result.association_method == "diff_overlap"
        assert result.confidence > 0

    def test_patch_hash_method(self) -> None:
        pr = self._make_default_pr()
        patch = self._patch()
        result = find_best_association(
            frame_base_commit="missing",
            frame_branch="wrong-branch",
            frame_files=[],
            frame_diff_patch=patch,
            pr_envelope=pr,
            pr_commit_shas=[],
            pr_files=[],
            pr_diff_patch=patch,
            diff_overlap_threshold=0.99,  # Too high for empty lists
        )
        assert result is not None
        assert result.association_method == "patch_hash"
        assert result.confidence == 0.9

    def test_returns_none_when_no_match(self) -> None:
        pr = self._make_default_pr()
        result = find_best_association(
            frame_base_commit="missing",
            frame_branch="wrong-branch",
            frame_files=[],
            frame_diff_patch="",
            pr_envelope=pr,
            pr_commit_shas=[],
            pr_files=[],
            pr_diff_patch="",
        )
        assert result is None


# ---------------------------------------------------------------------------
# compute_body_hash tests
# ---------------------------------------------------------------------------


class TestComputeBodyHash:
    def test_sha256_of_body(self) -> None:
        body = "# Hello"
        expected = hashlib.sha256(body.encode("utf-8")).hexdigest()
        assert compute_body_hash(body) == expected

    def test_empty_body(self) -> None:
        result = compute_body_hash("")
        assert len(result) == 64  # SHA-256 hex

    def test_deterministic(self) -> None:
        assert compute_body_hash("same text") == compute_body_hash("same text")


# ---------------------------------------------------------------------------
# _normalize_patch tests
# ---------------------------------------------------------------------------


class TestNormalizePatch:
    def test_strips_index_line(self) -> None:
        patch = "index abc..def 100644\n--- a/foo.py\n+++ b/foo.py"
        result = _normalize_patch(patch)
        assert "index" not in result
        assert "--- a/foo.py" in result

    def test_strips_trailing_whitespace(self) -> None:
        patch = "+added line   \n+another   "
        result = _normalize_patch(patch)
        assert not any(line.endswith("   ") for line in result.splitlines())

    def test_empty_patch_returns_empty(self) -> None:
        assert _normalize_patch("") == ""

    def test_preserves_diff_content(self) -> None:
        patch = "--- a/foo.py\n+++ b/foo.py\n+added line"
        result = _normalize_patch(patch)
        assert "+added line" in result
