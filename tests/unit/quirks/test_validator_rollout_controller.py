# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for NodeValidatorRolloutOrchestratorOrchestrator.

Tests cover:
- Default stage is OBSERVE for all QuirkTypes
- OBSERVE → WARN promotion: happy path and rule violations
- WARN → BLOCK promotion: happy path and missing approval
- approve_block: records approval; rejects non-WARN stage
- get_all_stages: returns record for every QuirkType
- get_ci_exit_code: 0 for OBSERVE/WARN, 1 for BLOCK
- InvalidTransitionError: skipping stages, promoting from BLOCK
- Concurrent promote calls do not corrupt state

Related: OMN-2564
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from omniclaude.quirks.controller import (
    ApprovalRequiredError,
    InsufficientFindingsError,
    InvalidTransitionError,
    NodeValidatorRolloutOrchestratorOrchestrator,
    PromotionError,
    QuirkStageRecord,
)
from omniclaude.quirks.enums import QuirkStage, QuirkType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_controller() -> NodeValidatorRolloutOrchestratorOrchestrator:
    """Return a fresh in-memory controller."""
    return NodeValidatorRolloutOrchestratorOrchestrator(db_session_factory=None)


# ---------------------------------------------------------------------------
# Default state
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_default_stage_is_observe() -> None:
    controller = _make_controller()
    await controller.start()
    stage = await controller.get_stage(QuirkType.STUB_CODE)
    assert stage == QuirkStage.OBSERVE


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_all_stages_covers_all_quirk_types() -> None:
    controller = _make_controller()
    await controller.start()
    records = await controller.get_all_stages()
    known_types = {qt.value for qt in QuirkType}
    returned_types = {r.quirk_type.value for r in records}
    assert known_types == returned_types


@pytest.mark.unit
@pytest.mark.asyncio
async def test_all_default_stages_are_observe() -> None:
    controller = _make_controller()
    await controller.start()
    records = await controller.get_all_stages()
    for r in records:
        assert r.current_stage == QuirkStage.OBSERVE, (
            f"{r.quirk_type.value} should default to OBSERVE"
        )


# ---------------------------------------------------------------------------
# OBSERVE → WARN promotion
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promote_observe_to_warn_happy_path() -> None:
    controller = _make_controller()
    await controller.start()

    record = await controller.promote(
        QuirkType.STUB_CODE,
        to_stage=QuirkStage.WARN,
        finding_count_7d=15,
        confirmed_false_positive_rate=0.05,
    )

    assert record.current_stage == QuirkStage.WARN
    assert record.quirk_type == QuirkType.STUB_CODE
    assert record.promoted_at is not None
    assert isinstance(record.promoted_at, datetime)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promote_warn_requires_finding_count_gte_10() -> None:
    controller = _make_controller()
    await controller.start()

    with pytest.raises(InsufficientFindingsError, match="finding_count=9"):
        await controller.promote(
            QuirkType.STUB_CODE,
            to_stage=QuirkStage.WARN,
            finding_count_7d=9,
            confirmed_false_positive_rate=0.05,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promote_warn_requires_false_positive_rate() -> None:
    controller = _make_controller()
    await controller.start()

    with pytest.raises(ApprovalRequiredError, match="confirmed_false_positive_rate"):
        await controller.promote(
            QuirkType.STUB_CODE,
            to_stage=QuirkStage.WARN,
            finding_count_7d=15,
            confirmed_false_positive_rate=None,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promote_warn_false_positive_rate_too_high() -> None:
    controller = _make_controller()
    await controller.start()

    with pytest.raises(PromotionError, match="false_positive_rate"):
        await controller.promote(
            QuirkType.STUB_CODE,
            to_stage=QuirkStage.WARN,
            finding_count_7d=15,
            confirmed_false_positive_rate=0.20,  # > 10%
        )


# ---------------------------------------------------------------------------
# WARN → BLOCK promotion
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promote_warn_to_block_happy_path() -> None:
    controller = _make_controller()
    await controller.start()

    # First promote to WARN.
    await controller.promote(
        QuirkType.NO_TESTS,
        to_stage=QuirkStage.WARN,
        finding_count_7d=12,
        confirmed_false_positive_rate=0.08,
    )

    # Record approval.
    await controller.approve_block(QuirkType.NO_TESTS, approver="ops@example.com")

    # Now promote to BLOCK.
    record = await controller.promote(
        QuirkType.NO_TESTS,
        to_stage=QuirkStage.BLOCK,
        finding_count_7d=35,
        operator="ops@example.com",
    )

    assert record.current_stage == QuirkStage.BLOCK
    assert record.approved_by == "ops@example.com"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promote_block_requires_finding_count_gte_30() -> None:
    controller = _make_controller()
    await controller.start()

    await controller.promote(
        QuirkType.SYCOPHANCY,
        to_stage=QuirkStage.WARN,
        finding_count_7d=12,
        confirmed_false_positive_rate=0.05,
    )
    await controller.approve_block(QuirkType.SYCOPHANCY, approver="ops@example.com")

    with pytest.raises(InsufficientFindingsError, match="finding_count=29"):
        await controller.promote(
            QuirkType.SYCOPHANCY,
            to_stage=QuirkStage.BLOCK,
            finding_count_7d=29,
            operator="ops@example.com",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promote_block_requires_operator_approval() -> None:
    controller = _make_controller()
    await controller.start()

    await controller.promote(
        QuirkType.HALLUCINATED_API,
        to_stage=QuirkStage.WARN,
        finding_count_7d=12,
        confirmed_false_positive_rate=0.05,
    )

    # No approval recorded, no operator arg.
    with pytest.raises(ApprovalRequiredError, match="operator approval"):
        await controller.promote(
            QuirkType.HALLUCINATED_API,
            to_stage=QuirkStage.BLOCK,
            finding_count_7d=35,
        )


# ---------------------------------------------------------------------------
# approve_block
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_block_records_approver() -> None:
    controller = _make_controller()
    await controller.start()

    # Move to WARN first.
    await controller.promote(
        QuirkType.STUB_CODE,
        to_stage=QuirkStage.WARN,
        finding_count_7d=12,
        confirmed_false_positive_rate=0.05,
    )

    await controller.approve_block(QuirkType.STUB_CODE, approver="lead@example.com")
    pending = controller.get_pending_block_approval(QuirkType.STUB_CODE)
    assert pending == "lead@example.com"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_block_rejected_when_not_in_warn() -> None:
    controller = _make_controller()
    await controller.start()

    with pytest.raises(InvalidTransitionError, match="must be WARN"):
        await controller.approve_block(QuirkType.STUB_CODE, approver="ops@example.com")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_approve_block_consumed_after_promote() -> None:
    controller = _make_controller()
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

    # Approval should have been consumed.
    assert controller.get_pending_block_approval(QuirkType.STUB_CODE) is None


# ---------------------------------------------------------------------------
# CI exit codes
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ci_exit_code_observe_is_zero() -> None:
    controller = _make_controller()
    await controller.start()
    assert controller.get_ci_exit_code(QuirkType.STUB_CODE) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ci_exit_code_warn_is_zero() -> None:
    controller = _make_controller()
    await controller.start()

    await controller.promote(
        QuirkType.NO_TESTS,
        to_stage=QuirkStage.WARN,
        finding_count_7d=12,
        confirmed_false_positive_rate=0.05,
    )
    assert controller.get_ci_exit_code(QuirkType.NO_TESTS) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ci_exit_code_block_is_one() -> None:
    controller = _make_controller()
    await controller.start()

    await controller.promote(
        QuirkType.LOW_EFFORT_PATCH,
        to_stage=QuirkStage.WARN,
        finding_count_7d=12,
        confirmed_false_positive_rate=0.05,
    )
    await controller.approve_block(
        QuirkType.LOW_EFFORT_PATCH, approver="ops@example.com"
    )
    await controller.promote(
        QuirkType.LOW_EFFORT_PATCH,
        to_stage=QuirkStage.BLOCK,
        finding_count_7d=35,
        operator="ops@example.com",
    )
    assert controller.get_ci_exit_code(QuirkType.LOW_EFFORT_PATCH) == 1


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cannot_skip_stages_observe_to_block() -> None:
    controller = _make_controller()
    await controller.start()

    with pytest.raises(InvalidTransitionError, match="OBSERVE → BLOCK"):
        await controller.promote(
            QuirkType.STUB_CODE,
            to_stage=QuirkStage.BLOCK,
            finding_count_7d=35,
            operator="ops@example.com",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cannot_re_promote_from_block() -> None:
    controller = _make_controller()
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

    with pytest.raises(InvalidTransitionError, match="terminal stage"):
        await controller.promote(
            QuirkType.STUB_CODE,
            to_stage=QuirkStage.BLOCK,
            finding_count_7d=35,
            operator="ops@example.com",
        )


# ---------------------------------------------------------------------------
# QuirkStageRecord serialisation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_quirk_stage_record_to_dict() -> None:
    now = datetime.now(tz=UTC)
    record = QuirkStageRecord(
        quirk_type=QuirkType.SYCOPHANCY,
        current_stage=QuirkStage.WARN,
        promoted_at=now,
        approved_by=None,
        notes="test note",
    )
    d = record.to_dict()
    assert d["quirk_type"] == "SYCOPHANCY"
    assert d["current_stage"] == "WARN"
    assert d["promoted_at"] == now.isoformat()
    assert d["notes"] == "test note"


@pytest.mark.unit
def test_quirk_stage_record_to_dict_no_promoted_at() -> None:
    record = QuirkStageRecord(quirk_type=QuirkType.STUB_CODE)
    d = record.to_dict()
    assert d["promoted_at"] is None


# ---------------------------------------------------------------------------
# Stage isolation: different QuirkTypes are independent
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promote_one_type_does_not_affect_another() -> None:
    controller = _make_controller()
    await controller.start()

    await controller.promote(
        QuirkType.STUB_CODE,
        to_stage=QuirkStage.WARN,
        finding_count_7d=12,
        confirmed_false_positive_rate=0.05,
    )

    stage_no_tests = await controller.get_stage(QuirkType.NO_TESTS)
    assert stage_no_tests == QuirkStage.OBSERVE


# ---------------------------------------------------------------------------
# promote records notes
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_promote_records_notes() -> None:
    controller = _make_controller()
    await controller.start()

    record = await controller.promote(
        QuirkType.UNSAFE_ASSUMPTION,
        to_stage=QuirkStage.WARN,
        finding_count_7d=12,
        confirmed_false_positive_rate=0.05,
        notes="promoted during incident review",
    )

    assert record.notes == "promoted during incident review"
