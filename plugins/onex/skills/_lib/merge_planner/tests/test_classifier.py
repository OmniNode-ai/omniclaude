"""Tests for QPM PR Type Classifier."""

import pytest
from merge_planner.classifier import PRContext, classify_pr
from merge_planner.models import EnumPRQueueClass


@pytest.fixture
def ci_fix_pr():
    return PRContext(
        number=42,
        repo="OmniNode-ai/omnibase_core",
        title="fix(ci): add ruff rule",
        is_draft=False,
        ci_status="success",
        review_state="approved",
        changed_files=[".github/workflows/ci.yml"],
        labels=[],
    )


@pytest.fixture
def test_only_pr():
    return PRContext(
        number=43,
        repo="OmniNode-ai/omniclaude",
        title="test: add unit tests for scorer",
        is_draft=False,
        ci_status="success",
        review_state="none",
        changed_files=["tests/unit/test_scorer.py", "tests/conftest.py"],
        labels=[],
    )


@pytest.fixture
def feature_pr():
    return PRContext(
        number=44,
        repo="OmniNode-ai/omniclaude",
        title="feat: add new dashboard page",
        is_draft=False,
        ci_status="success",
        review_state="approved",
        changed_files=[
            "src/omniclaude/handlers/dashboard.py",
            "src/omniclaude/routes.py",
        ],
        labels=[],
    )


@pytest.fixture
def draft_pr():
    return PRContext(
        number=45,
        repo="OmniNode-ai/omniclaude",
        title="wip: experiment",
        is_draft=True,
        ci_status="pending",
        review_state="none",
        changed_files=["src/omniclaude/experiment.py"],
        labels=[],
    )


@pytest.fixture
def failing_ci_pr():
    return PRContext(
        number=46,
        repo="OmniNode-ai/omniclaude",
        title="feat: broken feature",
        is_draft=False,
        ci_status="failure",
        review_state="none",
        changed_files=["src/omniclaude/broken.py"],
        labels=[],
    )


def test_ci_fix_is_accelerator(ci_fix_pr):
    assert classify_pr(ci_fix_pr) == EnumPRQueueClass.ACCELERATOR


def test_test_only_is_accelerator(test_only_pr):
    assert classify_pr(test_only_pr) == EnumPRQueueClass.ACCELERATOR


def test_feature_is_normal(feature_pr):
    assert classify_pr(feature_pr) == EnumPRQueueClass.NORMAL


def test_draft_is_blocked(draft_pr):
    assert classify_pr(draft_pr) == EnumPRQueueClass.BLOCKED


def test_failing_ci_is_blocked(failing_ci_pr):
    assert classify_pr(failing_ci_pr) == EnumPRQueueClass.BLOCKED


def test_mixed_ci_and_feature_is_normal():
    """A PR touching both CI and feature code is NORMAL, not ACCELERATOR."""
    ctx = PRContext(
        number=50,
        repo="OmniNode-ai/omniclaude",
        title="feat: add feature with CI fix",
        is_draft=False,
        ci_status="success",
        review_state="none",
        changed_files=[".github/workflows/ci.yml", "src/omniclaude/new_feature.py"],
        labels=[],
    )
    assert classify_pr(ctx) == EnumPRQueueClass.NORMAL


def test_changes_requested_is_blocked():
    ctx = PRContext(
        number=51,
        repo="OmniNode-ai/omniclaude",
        title="feat: needs review fixes",
        is_draft=False,
        ci_status="success",
        review_state="changes_requested",
        changed_files=["src/omniclaude/feature.py"],
        labels=[],
    )
    assert classify_pr(ctx) == EnumPRQueueClass.BLOCKED


def test_empty_files_is_normal():
    """PR with no changed files is NORMAL (not accelerator, not blocked)."""
    ctx = PRContext(
        number=52,
        repo="OmniNode-ai/omniclaude",
        title="chore: empty commit",
        is_draft=False,
        ci_status="success",
        review_state="none",
        changed_files=[],
        labels=[],
    )
    assert classify_pr(ctx) == EnumPRQueueClass.NORMAL


def test_docs_only_is_accelerator():
    ctx = PRContext(
        number=53,
        repo="OmniNode-ai/omniclaude",
        title="docs: update architecture guide",
        is_draft=False,
        ci_status="success",
        review_state="none",
        changed_files=["docs/architecture/overview.md", "docs/README.md"],
        labels=[],
    )
    assert classify_pr(ctx) == EnumPRQueueClass.ACCELERATOR
