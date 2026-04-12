# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for plan_to_tickets detect_structure() — OMN-8491: § heading support."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_lib_dir = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "skills"
    / "_lib"
    / "plan_to_tickets"
)
if str(_lib_dir) not in sys.path:
    sys.path.insert(0, str(_lib_dir))

from detect_structure import detect_structure  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SECTION_PLAN_SIMPLE = """\
# My Epic

§1 Bootstrap

Do the bootstrap work here.

§2 Validate

Run all validation checks.
"""

SECTION_PLAN_DECIMAL = """\
# My Epic

§1 Phase One

First phase content.

§1.1 Phase One Sub

Sub-phase content.

§2 Phase Two

Second phase content.
"""

SECTION_PLAN_WITH_DEPS = """\
# My Epic

§1 Foundation

Lay the foundation.

§2 Build

Build on top of foundation.
Dependencies: P1
"""

TASK_PLAN = """\
# Task Epic

## Task 1: Do Something

Task one content here.

## Task 2: Do Another Thing

Task two content here.
"""

NON_MATCHING_PLAN = """\
# My Plan

Some random content with no structured headings.

Just paragraphs.
"""


# ---------------------------------------------------------------------------
# § heading tests (OMN-8491)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSectionHeadings:
    """Verify §N and §N.x headings are parsed by detect_structure()."""

    def test_simple_section_headings_produce_entries(self) -> None:
        doc = detect_structure(SECTION_PLAN_SIMPLE, source_path="test.md")
        assert doc.structure_type.value == "section_headings"
        assert len(doc.entries) == 2

    def test_section_entry_ids_are_normalized(self) -> None:
        doc = detect_structure(SECTION_PLAN_SIMPLE, source_path="test.md")
        ids = [e.id for e in doc.entries]
        assert ids == ["P1", "P2"]

    def test_section_entry_titles_include_number_and_text(self) -> None:
        doc = detect_structure(SECTION_PLAN_SIMPLE, source_path="test.md")
        assert doc.entries[0].title == "§1 Bootstrap"
        assert doc.entries[1].title == "§2 Validate"

    def test_section_entry_content_is_captured(self) -> None:
        doc = detect_structure(SECTION_PLAN_SIMPLE, source_path="test.md")
        assert "bootstrap work" in doc.entries[0].content.lower()
        assert "validation checks" in doc.entries[1].content.lower()

    def test_decimal_section_headings_produce_entries(self) -> None:
        doc = detect_structure(SECTION_PLAN_DECIMAL, source_path="test.md")
        assert doc.structure_type.value == "section_headings"
        assert len(doc.entries) == 3

    def test_decimal_section_ids_use_underscore(self) -> None:
        doc = detect_structure(SECTION_PLAN_DECIMAL, source_path="test.md")
        ids = [e.id for e in doc.entries]
        assert "P1_1" in ids

    def test_section_dependencies_are_parsed(self) -> None:
        doc = detect_structure(SECTION_PLAN_WITH_DEPS, source_path="test.md")
        p2 = doc.entry_by_id("P2")
        assert p2 is not None
        assert "P1" in p2.dependencies

    def test_section_plan_title_extracted(self) -> None:
        doc = detect_structure(SECTION_PLAN_SIMPLE, source_path="test.md")
        assert doc.title == "My Epic"


# ---------------------------------------------------------------------------
# Regression: existing heading types still work
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExistingHeadingRegression:
    """§ support must not break ## Task N: or ## Phase N: detection."""

    def test_task_sections_still_detected(self) -> None:
        doc = detect_structure(TASK_PLAN, source_path="test.md")
        assert doc.structure_type.value == "task_sections"
        assert len(doc.entries) == 2

    def test_task_sections_take_priority_over_section_headings(self) -> None:
        mixed = TASK_PLAN + "\n§3 Extra\n\nExtra section.\n"
        doc = detect_structure(mixed, source_path="test.md")
        # Task sections win — § heading is ignored when ## Task N: exists
        assert doc.structure_type.value == "task_sections"
        assert len(doc.entries) == 2


# ---------------------------------------------------------------------------
# Regression guard: zero-ticket result on non-empty plan must fail
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestZeroTicketGuard:
    """detect_structure() must never silently return 0 entries for a non-empty plan."""

    def test_non_matching_plan_raises_value_error(self) -> None:
        """A non-empty plan with no recognizable headings must raise ValueError."""
        with pytest.raises(ValueError, match="no valid structure"):
            detect_structure(NON_MATCHING_PLAN, source_path="test.md")

    def test_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="no valid structure"):
            detect_structure("", source_path="test.md")

    def test_whitespace_only_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="no valid structure"):
            detect_structure("   \n\n  ", source_path="test.md")
