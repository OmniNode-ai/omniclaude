# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for feature-dashboard skill SKILL.md frontmatter (OMN-3503).

Validates that the SKILL.md has correct frontmatter fields, both audit and
ticketize mode instructions are present, the discovery rule is documented,
the applicability matrix is embedded, and the coverage check hierarchy is
documented.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_SKILL_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "skills"
    / "feature_dashboard"
)
_SKILL_MD = _SKILL_DIR / "SKILL.md"

_REQUIRED_ARGS = {
    "mode",
    "format",
    "output-dir",
    "filter-skill",
    "filter-status",
    "fail-on",
    "team",
    "online",
}


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Parse YAML frontmatter and body from a SKILL.md file.

    Returns (frontmatter_dict, body_text).
    Raises ValueError if frontmatter delimiters are missing or YAML fails.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError("SKILL.md does not start with frontmatter delimiter '---'")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("SKILL.md missing closing frontmatter delimiter '---'")
    fm = yaml.safe_load(parts[1])
    body = parts[2]
    return fm, body


@pytest.mark.unit
class TestFeatureDashboardFrontmatter:
    """Validate SKILL.md frontmatter fields."""

    def test_skill_md_exists(self) -> None:
        assert _SKILL_MD.exists(), f"SKILL.md not found at {_SKILL_MD}"

    def test_frontmatter_parses(self) -> None:
        fm, _ = _parse_frontmatter(_SKILL_MD)
        assert isinstance(fm, dict), "Frontmatter must parse as a YAML mapping"

    def test_name_field_absent(self) -> None:
        """Name is derived from directory, not frontmatter (OMN-5389)."""
        fm, _ = _parse_frontmatter(_SKILL_MD)
        assert "name" not in fm, (
            "name field must NOT be in frontmatter — it is derived from the directory name"
        )

    def test_description_field_present_and_nonempty(self) -> None:
        fm, _ = _parse_frontmatter(_SKILL_MD)
        desc = fm.get("description", "")
        assert desc, "description field must be present and non-empty"

    def test_version_field(self) -> None:
        fm, _ = _parse_frontmatter(_SKILL_MD)
        assert "version" in fm, "version field must be present"
        assert fm["version"], "version field must be non-empty"

    def test_ticket_field_matches_omn_pattern(self) -> None:
        fm, _ = _parse_frontmatter(_SKILL_MD)
        ticket = fm.get("ticket", "")
        assert re.match(r"OMN-[1-9]\d+", str(ticket)), (
            f"ticket field must match OMN-[1-9]\\d+, got {ticket!r}"
        )

    def test_args_field_is_list(self) -> None:
        fm, _ = _parse_frontmatter(_SKILL_MD)
        assert isinstance(fm.get("args"), list), "args must be a list"

    def test_all_required_args_present(self) -> None:
        fm, _ = _parse_frontmatter(_SKILL_MD)
        arg_names = {a["name"] for a in fm.get("args", []) if isinstance(a, dict)}
        missing = _REQUIRED_ARGS - arg_names
        assert not missing, f"Missing required args in frontmatter: {sorted(missing)}"

    def test_mode_arg_default_is_audit(self) -> None:
        fm, _ = _parse_frontmatter(_SKILL_MD)
        args = {a["name"]: a for a in fm.get("args", []) if isinstance(a, dict)}
        assert args.get("mode", {}).get("default") == "audit", (
            "mode arg default must be 'audit'"
        )

    def test_format_arg_default_is_cli(self) -> None:
        fm, _ = _parse_frontmatter(_SKILL_MD)
        args = {a["name"]: a for a in fm.get("args", []) if isinstance(a, dict)}
        assert args.get("format", {}).get("default") == "cli", (
            "format arg default must be 'cli'"
        )

    def test_output_dir_arg_default(self) -> None:
        fm, _ = _parse_frontmatter(_SKILL_MD)
        args = {a["name"]: a for a in fm.get("args", []) if isinstance(a, dict)}
        assert args.get("output-dir", {}).get("default") == "docs/feature-dashboard", (
            "output-dir arg default must be 'docs/feature-dashboard'"
        )

    def test_filter_status_default_is_all(self) -> None:
        fm, _ = _parse_frontmatter(_SKILL_MD)
        args = {a["name"]: a for a in fm.get("args", []) if isinstance(a, dict)}
        assert args.get("filter-status", {}).get("default") == "all", (
            "filter-status default must be 'all'"
        )

    def test_team_arg_default_is_omninode(self) -> None:
        fm, _ = _parse_frontmatter(_SKILL_MD)
        args = {a["name"]: a for a in fm.get("args", []) if isinstance(a, dict)}
        assert args.get("team", {}).get("default") == "OmniNode", (
            "team arg default must be 'OmniNode'"
        )

    def test_online_arg_default_is_false(self) -> None:
        fm, _ = _parse_frontmatter(_SKILL_MD)
        args = {a["name"]: a for a in fm.get("args", []) if isinstance(a, dict)}
        online_default = str(args.get("online", {}).get("default", "")).lower()
        assert online_default == "false", (
            f"online arg default must be 'false', got {online_default!r}"
        )


@pytest.mark.unit
class TestFeatureDashboardBody:
    """Validate SKILL.md body contains required sections and content."""

    def test_audit_mode_instructions_present(self) -> None:
        _, body = _parse_frontmatter(_SKILL_MD)
        assert "audit" in body.lower(), "Body must contain audit mode instructions"
        assert "Running feature-dashboard audit" in body, (
            "Body must contain the audit announce string"
        )

    def test_ticketize_mode_instructions_present(self) -> None:
        _, body = _parse_frontmatter(_SKILL_MD)
        assert "ticketize" in body.lower(), (
            "Body must contain ticketize mode instructions"
        )
        assert "Running feature-dashboard ticketize" in body, (
            "Body must contain the ticketize announce string"
        )

    def test_discovery_rule_documented(self) -> None:
        _, body = _parse_frontmatter(_SKILL_MD)
        assert "plugins/onex/skills/" in body, (
            "Body must document the discovery rule with plugins/onex/skills/"
        )
        # Discovery rule excludes underscore-prefixed dirs
        assert "_" in body or "not start with" in body or "does NOT start" in body, (
            "Body must mention that underscore-prefixed dirs are excluded"
        )

    def test_applicability_matrix_embedded(self) -> None:
        _, body = _parse_frontmatter(_SKILL_MD)
        # All 8 check names must appear
        required_checks = [
            "skill_md",
            "orchestrator_node",
            "contract_yaml",
            "event_bus_present",
            "topics_nonempty",
            "topics_namespaced",
            "test_coverage",
            "linear_ticket",
        ]
        for check in required_checks:
            assert check in body, f"Applicability matrix must include check '{check}'"

    def test_coverage_check_hierarchy_documented(self) -> None:
        _, body = _parse_frontmatter(_SKILL_MD)
        # Must mention canonical (primary) source
        assert "test_skill_node_coverage.py" in body, (
            "Coverage check must reference test_skill_node_coverage.py as canonical source"
        )
        # Must mention fallback heuristics
        assert "heuristic" in body.lower() or "fallback" in body.lower(), (
            "Coverage check must document fallback heuristics"
        )

    def test_stable_json_behavior_documented(self) -> None:
        _, body = _parse_frontmatter(_SKILL_MD)
        assert "stable.json" in body, "Body must document stable.json write behavior"
        assert "generated_at" in body, (
            "Body must document that generated_at is excluded from stable.json"
        )
        assert "sort" in body.lower(), (
            "Body must document sorted keys requirement for stable.json"
        )

    def test_status_rollup_documented(self) -> None:
        _, body = _parse_frontmatter(_SKILL_MD)
        for status in ["broken", "partial", "wired", "unknown"]:
            assert status in body, (
                f"Body must document status rollup including '{status}'"
            )

    def test_fail_on_behavior_documented(self) -> None:
        _, body = _parse_frontmatter(_SKILL_MD)
        assert "fail-on" in body or "fail_on" in body, (
            "Body must document --fail-on behavior"
        )

    def test_ticketize_linear_tool_documented(self) -> None:
        _, body = _parse_frontmatter(_SKILL_MD)
        assert "mcp__linear-server__save_issue" in body, (
            "ticketize mode must document the Linear MCP tool to call"
        )

    def test_ticket_title_format_documented(self) -> None:
        _, body = _parse_frontmatter(_SKILL_MD)
        assert "Feature Dashboard" in body, (
            "ticketize mode must document the '[Feature Dashboard]' ticket title format"
        )
        assert "worst_severity" in body or "worst severity" in body.lower(), (
            "ticketize mode must document worst_severity in ticket title"
        )
