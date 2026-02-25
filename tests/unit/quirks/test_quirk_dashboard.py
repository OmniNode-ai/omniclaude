# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for NodeQuirkDashboardQueryEffect.

Tests cover:
- No-DB mode: all methods return empty/None without error
- QuirkSignalRow / QuirkFindingRow serialisation
- summary() empty structure shape
- list_signals() / list_findings() return list (no DB)
- get_signal() / get_finding() return None (no DB)
- _empty_summary() structure
- _build_summary() correctly aggregates raw rows

Related: OMN-2586
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from omniclaude.quirks.dashboard import (
    NodeQuirkDashboardQueryEffect,
    QuirkFindingRow,
    QuirkSignalRow,
    _build_summary,
    _empty_summary,
)

# ---------------------------------------------------------------------------
# Helpers: fake DB rows
# ---------------------------------------------------------------------------


def _make_signal_row_tuple(
    quirk_type: str = "STUB_CODE",
    session_id: str = "test-session",
    confidence: float = 0.9,
    stage: str = "OBSERVE",
) -> tuple[Any, ...]:
    """Build a fake row tuple matching the SELECT column order for quirk_signals."""
    now = datetime.now(tz=UTC)
    return (
        str(uuid4()),  # id
        quirk_type,  # quirk_type
        session_id,  # session_id
        confidence,  # confidence
        ["evidence1"],  # evidence (list)
        stage,  # stage
        now,  # detected_at (datetime)
        "regex",  # extraction_method
        "src/foo.py",  # file_path
        None,  # diff_hunk
        None,  # ast_span
        now,  # created_at (datetime)
    )


def _make_finding_row_tuple(
    quirk_type: str = "STUB_CODE",
    policy_recommendation: str = "observe",
    confidence: float = 0.8,
) -> tuple[Any, ...]:
    """Build a fake row tuple matching the SELECT column order for quirk_findings."""
    now = datetime.now(tz=UTC)
    return (
        str(uuid4()),  # id
        str(uuid4()),  # signal_id
        quirk_type,  # quirk_type
        policy_recommendation,  # policy_recommendation
        None,  # validator_blueprint_id
        [],  # suggested_exemptions
        "Fix the stub code.",  # fix_guidance
        confidence,  # confidence
        now,  # created_at
    )


# ---------------------------------------------------------------------------
# QuirkSignalRow serialisation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_quirk_signal_row_to_dict_keys() -> None:
    """QuirkSignalRow.to_dict() must contain all expected keys."""
    row = QuirkSignalRow(_make_signal_row_tuple())
    d = row.to_dict()
    expected_keys = {
        "id",
        "quirk_type",
        "session_id",
        "confidence",
        "evidence",
        "stage",
        "detected_at",
        "extraction_method",
        "file_path",
        "diff_hunk",
        "ast_span",
        "created_at",
    }
    assert expected_keys == set(d.keys())


@pytest.mark.unit
def test_quirk_signal_row_values() -> None:
    """QuirkSignalRow must expose correct field values."""
    row_tuple = _make_signal_row_tuple(
        quirk_type="NO_TESTS", session_id="session-42", confidence=0.77, stage="WARN"
    )
    row = QuirkSignalRow(row_tuple)
    assert row.quirk_type == "NO_TESTS"
    assert row.session_id == "session-42"
    assert row.confidence == pytest.approx(0.77)
    assert row.stage == "WARN"
    assert row.file_path == "src/foo.py"
    assert row.diff_hunk is None
    assert row.ast_span is None


@pytest.mark.unit
def test_quirk_signal_row_datetime_to_isoformat() -> None:
    """detected_at and created_at must be ISO-8601 strings after to_dict()."""
    row = QuirkSignalRow(_make_signal_row_tuple())
    d = row.to_dict()
    # should be a string containing 'T' (ISO format)
    assert "T" in d["detected_at"]
    assert "T" in d["created_at"]


# ---------------------------------------------------------------------------
# QuirkFindingRow serialisation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_quirk_finding_row_to_dict_keys() -> None:
    """QuirkFindingRow.to_dict() must contain all expected keys."""
    row = QuirkFindingRow(_make_finding_row_tuple())
    d = row.to_dict()
    expected_keys = {
        "id",
        "signal_id",
        "quirk_type",
        "policy_recommendation",
        "validator_blueprint_id",
        "suggested_exemptions",
        "fix_guidance",
        "confidence",
        "created_at",
    }
    assert expected_keys == set(d.keys())


@pytest.mark.unit
def test_quirk_finding_row_values() -> None:
    """QuirkFindingRow must expose correct field values."""
    row_tuple = _make_finding_row_tuple(
        quirk_type="SYCOPHANCY", policy_recommendation="warn", confidence=0.92
    )
    row = QuirkFindingRow(row_tuple)
    assert row.quirk_type == "SYCOPHANCY"
    assert row.policy_recommendation == "warn"
    assert row.confidence == pytest.approx(0.92)
    assert row.validator_blueprint_id is None
    assert row.suggested_exemptions == []


# ---------------------------------------------------------------------------
# _empty_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_summary_structure() -> None:
    """_empty_summary must return a dict with the correct zero-state shape."""
    result = _empty_summary(7)
    assert result["window_days"] == 7
    assert result["total_signals"] == 0
    assert result["total_findings"] == 0
    assert result["by_quirk_type"] == {}
    assert result["by_stage"] == {}
    assert result["by_recommendation"] == {}


@pytest.mark.unit
def test_empty_summary_custom_days() -> None:
    """_empty_summary must reflect the supplied days value."""
    assert _empty_summary(30)["window_days"] == 30


# ---------------------------------------------------------------------------
# _build_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_summary_basic() -> None:
    """_build_summary must aggregate signal and finding rows correctly."""
    signal_rows: list[tuple[str, int]] = [
        ("STUB_CODE", 45),
        ("NO_TESTS", 20),
    ]
    finding_rows: list[tuple[str, int, str]] = [
        ("STUB_CODE", 4, "warn"),
        ("NO_TESTS", 1, "observe"),
    ]
    stage_rows: list[tuple[str, int]] = [
        ("OBSERVE", 50),
        ("WARN", 15),
    ]
    rec_rows: list[tuple[str, int]] = [
        ("observe", 3),
        ("warn", 2),
    ]

    result = _build_summary(7, signal_rows, finding_rows, stage_rows, rec_rows)

    assert result["window_days"] == 7
    assert result["total_signals"] == 65
    assert result["total_findings"] == 5
    assert result["by_quirk_type"]["STUB_CODE"]["signals"] == 45
    assert result["by_quirk_type"]["STUB_CODE"]["findings"] == 4
    assert result["by_quirk_type"]["STUB_CODE"]["latest_recommendation"] == "warn"
    assert result["by_stage"] == {"OBSERVE": 50, "WARN": 15}
    assert result["by_recommendation"] == {"observe": 3, "warn": 2}


@pytest.mark.unit
def test_build_summary_empty_rows() -> None:
    """_build_summary with empty rows returns zero totals."""
    result = _build_summary(7, [], [], [], [])
    assert result["total_signals"] == 0
    assert result["total_findings"] == 0
    assert result["by_quirk_type"] == {}
    assert result["by_stage"] == {}
    assert result["by_recommendation"] == {}


# ---------------------------------------------------------------------------
# NodeQuirkDashboardQueryEffect: no-DB mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summary_no_db_returns_empty() -> None:
    """summary() with no DB factory returns empty summary."""
    query = NodeQuirkDashboardQueryEffect(db_session_factory=None)
    result = await query.summary()
    assert result["total_signals"] == 0
    assert result["total_findings"] == 0
    assert result["by_quirk_type"] == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_signals_no_db_returns_empty_list() -> None:
    """list_signals() with no DB factory returns empty list."""
    query = NodeQuirkDashboardQueryEffect()
    result = await query.list_signals()
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_findings_no_db_returns_empty_list() -> None:
    """list_findings() with no DB factory returns empty list."""
    query = NodeQuirkDashboardQueryEffect()
    result = await query.list_findings()
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_signal_no_db_returns_none() -> None:
    """get_signal() with no DB factory returns None."""
    query = NodeQuirkDashboardQueryEffect()
    result = await query.get_signal(str(uuid4()))
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_finding_no_db_returns_none() -> None:
    """get_finding() with no DB factory returns None."""
    query = NodeQuirkDashboardQueryEffect()
    result = await query.get_finding(str(uuid4()))
    assert result is None


# ---------------------------------------------------------------------------
# NodeQuirkDashboardQueryEffect: limit capping
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_signals_limit_capped_at_1000() -> None:
    """list_signals() with limit > 1000 should be silently capped (no crash)."""
    query = NodeQuirkDashboardQueryEffect(db_session_factory=None)
    # With no DB this always returns [], but must not raise.
    result = await query.list_signals(limit=9999)
    assert result == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_findings_limit_capped_at_1000() -> None:
    """list_findings() with limit > 1000 should be silently capped (no crash)."""
    query = NodeQuirkDashboardQueryEffect(db_session_factory=None)
    result = await query.list_findings(limit=9999)
    assert result == []


# ---------------------------------------------------------------------------
# NodeQuirkDashboardQueryEffect: default instantiation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_default_instantiation_no_factory() -> None:
    """NodeQuirkDashboardQueryEffect can be created with no arguments."""
    query = NodeQuirkDashboardQueryEffect()
    assert query._db_session_factory is None
