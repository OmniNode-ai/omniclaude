# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for duplication-sweep skill check logic.

Scope: D1 (Drizzle table duplication) parsing logic only.
D2-D4 and whole-skill aggregation/exit semantics are follow-up scope.
"""

import re
from pathlib import Path

import pytest


@pytest.mark.unit
class TestDuplicationSweepD1:
    """D1: Drizzle table duplication detection."""

    def test_detects_duplicate_table_in_two_schema_files(self, tmp_path: Path) -> None:
        """Two schema files defining the same pgTable should be flagged."""
        schema_a = tmp_path / "intelligence-schema.ts"
        schema_b = tmp_path / "omniclaude-state-schema.ts"
        schema_a.write_text(
            'export const gateDecisions = pgTable("gate_decisions", {\n'
            '  id: serial("id"),\n'
            "});\n"
        )
        schema_b.write_text(
            'export const gateDecisions = pgTable("gate_decisions", {\n'
            '  id: serial("id"),\n'
            "});\n"
        )

        # Parse both files for pgTable calls
        tables: dict[str, list[str]] = {}
        for f in [schema_a, schema_b]:
            for match in re.finditer(r'pgTable\("(\w+)"', f.read_text()):
                tables.setdefault(match.group(1), []).append(f.name)

        duplicates = {k: v for k, v in tables.items() if len(v) > 1}
        assert "gate_decisions" in duplicates
        assert len(duplicates["gate_decisions"]) == 2

    def test_no_false_positive_for_unique_tables(self, tmp_path: Path) -> None:
        """Tables appearing in only one file should not be flagged."""
        schema_a = tmp_path / "intelligence-schema.ts"
        schema_a.write_text(
            'export const agentActions = pgTable("agent_actions", {\n'
            '  id: serial("id"),\n'
            "});\n"
        )

        tables: dict[str, list[str]] = {}
        for match in re.finditer(r'pgTable\("(\w+)"', schema_a.read_text()):
            tables.setdefault(match.group(1), []).append(schema_a.name)

        duplicates = {k: v for k, v in tables.items() if len(v) > 1}
        assert len(duplicates) == 0

    def test_detects_multiple_tables_across_files(self, tmp_path: Path) -> None:
        """Multiple duplicate tables across files should all be flagged."""
        schema_a = tmp_path / "schema-a.ts"
        schema_b = tmp_path / "schema-b.ts"
        schema_a.write_text(
            'export const users = pgTable("users", { id: serial("id") });\n'
            'export const events = pgTable("events", { id: serial("id") });\n'
        )
        schema_b.write_text(
            'export const users = pgTable("users", { id: serial("id") });\n'
            'export const logs = pgTable("logs", { id: serial("id") });\n'
        )

        tables: dict[str, list[str]] = {}
        for f in [schema_a, schema_b]:
            for match in re.finditer(r'pgTable\("(\w+)"', f.read_text()):
                tables.setdefault(match.group(1), []).append(f.name)

        duplicates = {k: v for k, v in tables.items() if len(v) > 1}
        assert "users" in duplicates
        assert "events" not in duplicates
        assert "logs" not in duplicates
