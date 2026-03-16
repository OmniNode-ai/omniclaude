# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for DoD parser — extraction and classification of DoD items."""

from __future__ import annotations

import sys
from pathlib import Path

# Add the skill lib to path so we can import dod_parser
sys.path.insert(
    0,
    str(
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "onex"
        / "skills"
        / "_lib"
        / "dod-parser"
    ),
)

from dod_parser import classify_dod_item, extract_dod_items


class TestExtractDodFromMarkdownChecklist:
    """Tests for extracting DoD items from markdown."""

    def test_extracts_dod_from_markdown_checklist(self) -> None:
        desc = (
            "## Description\nSome work.\n\n"
            "## Definition of Done\n"
            "- [ ] Tests added and passing\n"
            "- [ ] Config file created\n"
        )
        items = extract_dod_items(desc)
        assert len(items) == 2
        assert items[0].description == "Tests added and passing"
        assert items[1].description == "Config file created"

    def test_extracts_dod_from_dod_heading(self) -> None:
        for heading in ["## DoD", "## Acceptance Criteria", "### Definition of Done"]:
            desc = f"## Overview\nStuff.\n\n{heading}\n- [ ] Item one\n"
            items = extract_dod_items(desc)
            assert len(items) == 1, f"Failed for heading: {heading}"

    def test_returns_empty_when_no_dod_section(self) -> None:
        desc = "## Overview\nJust a description with no DoD section.\n"
        items = extract_dod_items(desc)
        assert items == []

    def test_returns_empty_for_empty_description(self) -> None:
        items = extract_dod_items("")
        assert items == []

    def test_stops_at_next_heading(self) -> None:
        desc = (
            "## Definition of Done\n"
            "- [ ] First item\n"
            "## Next Section\n"
            "- [ ] Not a DoD item\n"
        )
        items = extract_dod_items(desc)
        assert len(items) == 1
        assert items[0].description == "First item"


class TestClassifyDodItem:
    """Tests for heuristic classification of DoD bullets."""

    def test_classifies_test_mention_as_test_exists(self) -> None:
        check = classify_dod_item("Tests added and passing")
        assert check.check_type == "test_exists"

    def test_classifies_unit_test_mention(self) -> None:
        check = classify_dod_item("Unit tests cover edge cases")
        assert check.check_type == "test_exists"

    def test_classifies_endpoint_mention_as_endpoint(self) -> None:
        check = classify_dod_item("API returns 200 on health check")
        assert check.check_type == "endpoint"

    def test_classifies_file_mention_as_file_exists(self) -> None:
        check = classify_dod_item("Config file created")
        assert check.check_type == "file_exists"

    def test_classifies_lint_mention_as_command(self) -> None:
        check = classify_dod_item("mypy --strict passes")
        assert check.check_type == "command"

    def test_classifies_ruff_as_command(self) -> None:
        check = classify_dod_item("ruff check passes with no errors")
        assert check.check_type == "command"

    def test_fallback_to_manual_command(self) -> None:
        check = classify_dod_item("Product owner signs off on design")
        assert check.check_type == "command"
        assert "MANUAL:" in str(check.check_value)
        assert "exit 1" in str(check.check_value)


class TestAssignsSequentialIds:
    """Tests for sequential ID assignment."""

    def test_assigns_sequential_ids(self) -> None:
        desc = "## Definition of Done\n- [ ] First\n- [ ] Second\n- [ ] Third\n"
        items = extract_dod_items(desc)
        assert [i.id for i in items] == ["dod-001", "dod-002", "dod-003"]

    def test_all_items_have_linear_source(self) -> None:
        desc = "## DoD\n- [ ] Item one\n- [ ] Item two\n"
        items = extract_dod_items(desc)
        for item in items:
            assert item.source == "linear"
            assert item.linear_dod_text == item.description

    def test_each_item_has_at_least_one_check(self) -> None:
        desc = "## DoD\n- [ ] Something\n"
        items = extract_dod_items(desc)
        assert len(items[0].checks) >= 1
