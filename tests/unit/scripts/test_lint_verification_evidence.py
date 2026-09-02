# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the verification-evidence lint gate (OMN-13341, R6).

Doctrine: knowledge-base reference/omniclaude-verification-doctrine.md.
The lint flags worker prompts / receipts / handoffs / evidence docs that cite a
local-clone path, ticket text, or a statusCheckRollup verdict AS proof of state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.lint_verification_evidence import (
    _in_scope,
    _scan_text,
    main,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Violations — non-authoritative surface asserted AS proof of state
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "line",
    [
        "CI verified via statusCheckRollup PASS",
        "PR is green per statusCheckRollup, merging.",
        "the merge is FAILURE according to statusCheckRollup",
        "Confirmed the node exists, verified against the local clone.",
        "Node absence proven from the local canonical clone (NOT_FOUND).",
        "Behavior verified using the local clone state.",
        "The ticket says escalation never fires, so the layer is broken.",
        "Ticket states the topic is empty, therefore no consumer is wired.",
    ],
)
def test_flags_non_authoritative_proof(line: str) -> None:
    hits, _ = _scan_text(line)
    assert hits, f"expected a violation for: {line!r}"


# --------------------------------------------------------------------------- #
# Clean — authoritative surfaces, or mere mention without a proof chain
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "line",
    [
        "CI verified green via `gh pr checks 1781 --repo OmniNode-ai/omniclaude`.",
        "Confirmed the node exists on origin/dev via git show origin/dev:<path>.",
        "Runtime state verified against projection_delegation_model_routing.",
        # Raw field access / mechanics — not a verdict assertion.
        "gh pr view 1 --json headRefOid,state,statusCheckRollup",
        'live.pop("statusCheckRollup", None)',
        "Merge queues require ALL `statusCheckRollup` entries to complete.",
        # Mere mention of a clone / ticket without asserting state from it.
        "Read the file from the local clone, then re-verify against origin/dev.",
        "The ticket describes the intended behavior; current state TBD.",
    ],
)
def test_passes_authoritative_or_mention(line: str) -> None:
    hits, _ = _scan_text(line)
    assert not hits, f"expected no violation for: {line!r}"


def test_suppression_token_silences() -> None:
    line = "verified against the local clone  # verification-evidence-ok: doc example"
    hits, _ = _scan_text(line)
    assert not hits


# --------------------------------------------------------------------------- #
# Scope filter
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "plugins/onex/skills/foo/SKILL.md",
        "docs/handoffs/2026-06-19-something.md",
        "docs/receipts/run-123.md",
        "docs/foo/omn-1-receipt.md",
        ".onex_state/evidence/run/out.txt",
    ],
)
def test_in_scope_documents(path: str) -> None:
    assert _in_scope(Path(path)) is True


@pytest.mark.parametrize(
    "path",
    [
        "src/omniclaude/foo.py",
        "tests/unit/scripts/test_lint_verification_evidence.py",
        "scripts/lint_verification_evidence.py",  # self-excluded
        "README.md",
        "docs/reference/AGENT_YAML_SCHEMA.md",
    ],
)
def test_out_of_scope_documents(path: str) -> None:
    assert _in_scope(Path(path)) is False


# --------------------------------------------------------------------------- #
# End-to-end via main()
# --------------------------------------------------------------------------- #


def test_main_blocks_on_violation(tmp_path: Path) -> None:
    doc = tmp_path / "docs" / "handoffs" / "bad.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("The ticket says it works, so we shipped it.\n", encoding="utf-8")
    assert main([str(doc)]) == 1


def test_main_passes_clean(tmp_path: Path) -> None:
    doc = tmp_path / "docs" / "handoffs" / "good.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "Verified via `gh pr checks 1`; node present on origin/dev.\n",
        encoding="utf-8",
    )
    assert main([str(doc)]) == 0


def test_main_self_test_passes() -> None:
    assert main(["--self-test"]) == 0
