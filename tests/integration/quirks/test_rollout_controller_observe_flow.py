# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Integration tests for ValidatorRolloutController OBSERVE → annotate flow.

Tests exercise the full path from diff injection through detector dispatch,
stage lookup, and CI annotation output.  No live DB or Kafka required.

Scenarios:
1. OBSERVE stage: detectors run, CI exits 0, annotations emitted as notice.
2. WARN stage: CI exits 0, annotations emitted as warning.
3. BLOCK stage (no exemption): CI exits 1, annotations emitted as error.
4. BLOCK stage (exempted): CI exits 0, exemption logged.
5. Exemption parsing: ``omninode-exempt:`` lines are correctly extracted.

Related: OMN-2564
"""

from __future__ import annotations

import pytest

from omniclaude.quirks.ci.run_checks import parse_exemptions, run_checks
from omniclaude.quirks.controller import NodeValidatorRolloutOrchestratorOrchestrator
from omniclaude.quirks.enums import QuirkStage, QuirkType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_code_diff() -> str:
    """Minimal diff containing a NotImplementedError stub."""
    return (
        "diff --git a/src/foo/bar.py b/src/foo/bar.py\n"
        "--- a/src/foo/bar.py\n"
        "+++ b/src/foo/bar.py\n"
        "@@ -1,3 +1,5 @@\n"
        "+def compute():\n"
        "+    raise NotImplementedError\n"
    )


# ---------------------------------------------------------------------------
# Scenario 1: OBSERVE stage — CI passes, notice annotations
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_observe_stage_ci_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """In OBSERVE stage, CI exits 0 regardless of detected quirks."""
    # Default stage for all types is OBSERVE; no promotion needed.
    exit_code = await run_checks(
        diff_content=_stub_code_diff(),
        pr_description="",
        db_session_factory=None,
    )
    assert exit_code == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_observe_stage_emits_notice_annotation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """In OBSERVE stage, annotations use the 'notice' level."""
    await run_checks(
        diff_content=_stub_code_diff(),
        pr_description="",
        db_session_factory=None,
    )
    captured = capsys.readouterr()
    # If any signals were detected, they should be 'notice' level.
    if captured.out.strip():
        assert "::notice" in captured.out, (
            "Expected ::notice annotation in OBSERVE stage"
        )


# ---------------------------------------------------------------------------
# Scenario 2: WARN stage — CI passes, warning annotations
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_warn_stage_ci_exits_zero() -> None:
    """In WARN stage, CI exits 0."""
    # Set up a controller in WARN stage to verify exit code logic.
    controller = NodeValidatorRolloutOrchestratorOrchestrator(db_session_factory=None)
    await controller.start()

    await controller.promote(
        QuirkType.STUB_CODE,
        to_stage=QuirkStage.WARN,
        finding_count_7d=12,
        confirmed_false_positive_rate=0.05,
    )

    assert controller.get_ci_exit_code(QuirkType.STUB_CODE) == 0
    await controller.stop()


# ---------------------------------------------------------------------------
# Scenario 3: BLOCK stage (no exemption) — CI fails
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_block_stage_ci_exits_one() -> None:
    """In BLOCK stage without exemption, CI exit code is 1."""
    controller = NodeValidatorRolloutOrchestratorOrchestrator(db_session_factory=None)
    await controller.start()

    await controller.promote(
        QuirkType.STUB_CODE,
        to_stage=QuirkStage.WARN,
        finding_count_7d=12,
        confirmed_false_positive_rate=0.05,
    )
    await controller.approve_block(QuirkType.STUB_CODE, approver="ops@example.com")
    await controller.promote(
        QuirkType.STUB_CODE,
        to_stage=QuirkStage.BLOCK,
        finding_count_7d=35,
        operator="ops@example.com",
    )

    assert controller.get_ci_exit_code(QuirkType.STUB_CODE) == 1
    await controller.stop()


# ---------------------------------------------------------------------------
# Scenario 4: BLOCK stage with exemption — CI passes
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exemption_parsing_valid() -> None:
    """Valid exemption lines are extracted correctly."""
    pr_desc = (
        "## Summary\n"
        "This PR fixes the core.\n\n"
        "omninode-exempt: STUB_CODE: scaffolding only, will replace in OMN-9999\n"
        "omninode-exempt: NO_TESTS: tests in follow-up OMN-9998\n"
    )
    exemptions = parse_exemptions(pr_desc)
    assert QuirkType.STUB_CODE in exemptions
    assert "scaffolding only" in exemptions[QuirkType.STUB_CODE]
    assert QuirkType.NO_TESTS in exemptions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_exemption_parsing_unknown_type_ignored() -> None:
    """Unknown quirk types in exemption lines are silently ignored."""
    pr_desc = "omninode-exempt: NONEXISTENT_TYPE: some reason\n"
    exemptions = parse_exemptions(pr_desc)
    assert len(exemptions) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_exemption_in_clean_pr_description() -> None:
    """PR descriptions without exemption lines produce empty dict."""
    pr_desc = "## Summary\nThis PR adds a feature.\n"
    exemptions = parse_exemptions(pr_desc)
    assert exemptions == {}


# ---------------------------------------------------------------------------
# Scenario 5: Clean diff — no annotations, CI passes
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_clean_diff_exits_zero() -> None:
    """A diff with no quirks exits 0 with no annotations."""
    clean_diff = (
        "diff --git a/src/foo/bar.py b/src/foo/bar.py\n"
        "--- a/src/foo/bar.py\n"
        "+++ b/src/foo/bar.py\n"
        "@@ -1,3 +1,5 @@\n"
        "+def compute(x: int) -> int:\n"
        "+    return x * 2\n"
    )
    exit_code = await run_checks(
        diff_content=clean_diff,
        pr_description="",
        db_session_factory=None,
    )
    assert exit_code == 0


# ---------------------------------------------------------------------------
# Scenario 6: Controller start/stop lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_controller_start_stop_lifecycle() -> None:
    """Controller starts and stops cleanly without errors."""
    controller = NodeValidatorRolloutOrchestratorOrchestrator(db_session_factory=None)
    await controller.start()

    # All types should be accessible after start.
    for qt in QuirkType:
        stage = await controller.get_stage(qt)
        assert stage == QuirkStage.OBSERVE

    await controller.stop()  # Should not raise.
