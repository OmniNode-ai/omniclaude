# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for scripts/lint_closes_ref.py — OMN-14641.

The Closes-reference gate requires a STRONG close signal (Closes-word OR
branch-primary head branch) on product PRs, so a real merge closes its own
ticket. A bare ``OMN-####`` mention is a WEAK signal that must NOT pass.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_SCRIPT_DIR = pathlib.Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import lint_closes_ref as gate  # noqa: E402

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Strong signals PASS
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "body",
    [
        "Closes OMN-14641",
        "closes omn-14641",
        "This Fixes OMN-1.",
        "Resolves OMN-9999 and adds tests.",
        "Closed: OMN-42",
        "body\n\nFixes: OMN-100\nmore",
    ],
)
def test_closes_word_passes(body: str) -> None:
    ok, _ = gate.evaluate("feat(OMN-1): x", body, "no-omn-branch")
    assert ok is True


@pytest.mark.parametrize(
    "head_ref",
    [
        "jonah/omn-14641-done-signal-integrity",
        "omn-14641-desc",
        "OMN-14641/sub",
        "jonahgabriel/OMN-1-foo",
    ],
)
def test_branch_primary_passes(head_ref: str) -> None:
    ok, reason = gate.evaluate("feat(OMN-1): x", "no closing word here", head_ref)
    assert ok is True
    assert "branch-primary" in reason


# --------------------------------------------------------------------------- #
# WEAK signal — bare mention — FAILS
# --------------------------------------------------------------------------- #


def test_bare_mention_fails() -> None:
    ok, reason = gate.evaluate(
        "feat(OMN-14641): thing",
        "Part of OMN-14641. Related to OMN-14640. (bare mentions only)",
        "feature/no-ticket-token",
    )
    assert ok is False
    assert "WEAK" in reason


def test_empty_body_and_plain_branch_fails() -> None:
    ok, _ = gate.evaluate("feat(OMN-1): x", "", "feature/plain")
    assert ok is False


# --------------------------------------------------------------------------- #
# Carve-outs PASS
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "title",
    [
        "chore(deps): bump ruff",
        "build(deps-dev): bump pytest",
        "Bump actions/checkout from 6 to 7",
        "chore: release 0.26.0",
        "release: cut 0.26.0",
    ],
)
def test_release_titles_pass(title: str) -> None:
    ok, _ = gate.evaluate(title, "", "dependabot/pip/ruff")
    assert ok is True


def test_skip_escape_passes() -> None:
    ok, reason = gate.evaluate(
        "docs: fix typo",
        "Pure docs change. [closes-ref-exempt: no ticket, typo fix]",
        "feature/typo",
    )
    assert ok is True
    assert "closes-ref-exempt" in reason


def test_empty_skip_escape_does_not_pass() -> None:
    """A bare `[closes-ref-exempt:]` with no reason must not satisfy the escape."""
    ok, _ = gate.evaluate("docs: x", "[closes-ref-exempt: ]", "feature/typo")
    assert ok is False


@pytest.mark.parametrize(
    "head_ref",
    ["evidence/omn-14582-bind-pr", "occ/OMN-14582", "occ-companion/omn-1"],
)
def test_evidence_companion_branch_is_weak_and_passes_gate(head_ref: str) -> None:
    """Evidence/OCC companion branches are weak signals — not gated, and their
    branch-primary token must NOT count as a strong close signal."""
    ok, reason = gate.evaluate("evidence(OMN-14582): bind PR", "", head_ref)
    assert ok is True
    assert "companion" in reason
    # And the branch-primary helper must reject them explicitly.
    assert gate.is_branch_primary(head_ref) is False


# --------------------------------------------------------------------------- #
# main() exit codes via env
# --------------------------------------------------------------------------- #


def test_main_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_TITLE", "feat(OMN-14641): fix")
    monkeypatch.setenv("PR_BODY", "Closes OMN-14641")
    monkeypatch.setenv("PR_HEAD_REF", "jonah/omn-14641-x")
    assert gate.main() == 0


def test_main_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_TITLE", "feat(OMN-14641): fix")
    monkeypatch.setenv("PR_BODY", "Part of OMN-14641 (bare)")
    monkeypatch.setenv("PR_HEAD_REF", "feature/no-token")
    assert gate.main() == 1
