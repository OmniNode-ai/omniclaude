# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the /onex:changelog_audit skill.

Verifies:
- SKILL.md exists and has correct frontmatter
- dispatch module is importable
- Unknown target returns structured error
- Changelog parsing classifies entries correctly
- BREAKING_CHANGE entries trigger workspace grep
- ADOPT_NOW and BREAKING_CHANGE entries create Linear tickets
- Dry-run skips ticket creation and state writes
- Dashboard is regenerated after a successful audit run
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

SKILL_DIR = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "changelog_audit"
)

MOCK_CHANGELOG = """
## 1.2.0 (2026-04-10)

- Added new flag --bare for headless operation
- New hook permissionDenied fires when tool is blocked
- New env var CLAUDE_CODE_DISABLE_CRON disables session crons
- Improved startup performance by 30%

## 1.1.0 (2026-03-01)

- Fixed bug in session routing
- TaskOutput removed from tool result schema
- Deprecated --legacy-mode flag, use --mode=legacy instead
- Added new command /onex:session for session orchestration
"""


def _load_dispatch_module() -> Any:
    dispatch_path = SKILL_DIR / "_lib" / "dispatch.py"
    spec = importlib.util.spec_from_file_location(
        "changelog_audit_dispatch", dispatch_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
class TestChangelogAuditSkillScaffolding:
    """Verify skill directory and SKILL.md structure."""

    def test_skill_dir_exists(self) -> None:
        assert SKILL_DIR.is_dir(), f"{SKILL_DIR} should exist"

    def test_skill_md_exists(self) -> None:
        assert (SKILL_DIR / "SKILL.md").is_file()

    def test_dispatch_py_exists(self) -> None:
        assert (SKILL_DIR / "_lib" / "dispatch.py").is_file()

    def test_skill_md_has_required_frontmatter(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        assert content.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
        _, _, rest = content.partition("---\n")
        frontmatter_text, sep, _ = rest.partition("\n---\n")
        assert sep, "SKILL.md frontmatter must be terminated by '---'"
        meta = yaml.safe_load(frontmatter_text)
        assert isinstance(meta, dict)
        for key in (
            "description",
            "mode",
            "version",
            "level",
            "category",
            "tags",
            "author",
            "args",
        ):
            assert key in meta, f"SKILL.md frontmatter missing '{key}'"
        arg_names = {arg.get("name") for arg in meta["args"] if isinstance(arg, dict)}
        assert "--target" in arg_names

    def test_dispatch_module_importable(self) -> None:
        module = _load_dispatch_module()
        assert hasattr(module, "dispatch")
        assert hasattr(module, "SUPPORTED_TARGETS")
        assert hasattr(module, "CHANGELOG_URLS")


@pytest.mark.unit
class TestChangelogAuditDispatch:
    """Verify dispatch logic: classification, ticket creation, dry-run."""

    def test_unknown_target_returns_error(self) -> None:
        module = _load_dispatch_module()
        result = module.dispatch("totally-unknown-target")
        assert result["success"] is False
        assert "Unknown target" in result["error"]

    def test_custom_url_without_url_arg_returns_error(self) -> None:
        module = _load_dispatch_module()
        result = module.dispatch("custom-url")
        assert result["success"] is False
        assert "requires --url" in result["error"]

    def test_invalid_since_date_returns_error(self) -> None:
        module = _load_dispatch_module()
        with patch.object(module, "_fetch_changelog", return_value=MOCK_CHANGELOG):
            result = module.dispatch("claude-code", since_date="not-a-date")
        assert result["success"] is False
        assert "Invalid since-date" in result["error"]

    def test_dry_run_does_not_create_tickets_or_write_state(
        self, tmp_path: Path
    ) -> None:
        module = _load_dispatch_module()
        with (
            patch.object(module, "_fetch_changelog", return_value=MOCK_CHANGELOG),
            patch.object(module, "_create_linear_ticket") as mock_ticket,
            patch.object(module, "_save_last_audit_date") as mock_save,
            patch.object(module, "_write_report") as mock_report,
            patch.object(module, "_regenerate_dashboard") as mock_dash,
        ):
            result = module.dispatch(
                "claude-code", since_date="2026-01-01", dry_run=True
            )

        assert result["success"] is True
        assert result["dry_run"] is True
        mock_ticket.assert_not_called()
        mock_save.assert_not_called()
        mock_report.assert_not_called()
        mock_dash.assert_not_called()

    def test_breaking_change_entries_are_classified(self) -> None:
        module = _load_dispatch_module()
        entries = module._parse_changelog_entries(
            MOCK_CHANGELOG, since=date(2026, 1, 1)
        )
        classifications = {e["text"]: e["classification"] for e in entries}

        # "TaskOutput removed" should be BREAKING_CHANGE
        breaking = [t for t, c in classifications.items() if c == "BREAKING_CHANGE"]
        assert any(
            "removed" in t.lower() or "deprecated" in t.lower() for t in breaking
        ), f"Expected BREAKING_CHANGE entries, got: {breaking}"

    def test_adopt_now_entries_are_classified(self) -> None:
        module = _load_dispatch_module()
        entries = module._parse_changelog_entries(
            MOCK_CHANGELOG, since=date(2026, 1, 1)
        )
        adopt_now = [e["text"] for e in entries if e["classification"] == "ADOPT_NOW"]
        assert any(
            "flag" in t.lower() or "hook" in t.lower() or "env var" in t.lower()
            for t in adopt_now
        ), f"Expected ADOPT_NOW entries for flags/hooks/env vars, got: {adopt_now}"

    def test_since_date_filters_old_entries(self) -> None:
        module = _load_dispatch_module()
        # Since 2026-04-01 — should exclude the 2026-03-01 section
        entries = module._parse_changelog_entries(
            MOCK_CHANGELOG, since=date(2026, 4, 1)
        )
        dates = {e["date"] for e in entries}
        assert all(d > "2026-04-01" for d in dates), (
            f"Entries older than since_date present: {dates}"
        )

    def test_full_run_creates_tickets_for_adopt_now_and_breaking(self) -> None:
        module = _load_dispatch_module()
        created_tickets: list[dict] = []

        def mock_create_ticket(target: str, entry: dict) -> str:
            created_tickets.append({"target": target, "entry": entry})
            return f"OMN-TEST-{len(created_tickets)}"

        with (
            patch.object(module, "_fetch_changelog", return_value=MOCK_CHANGELOG),
            patch.object(
                module, "_create_linear_ticket", side_effect=mock_create_ticket
            ),
            patch.object(module, "_save_last_audit_date"),
            patch.object(module, "_write_report", return_value=Path("/tmp/report.md")),
            patch.object(
                module, "_regenerate_dashboard", return_value=Path("/tmp/DASHBOARD.md")
            ),
            patch.object(module, "_grep_workspace", return_value=[]),
        ):
            result = module.dispatch(
                "claude-code", since_date="2026-01-01", dry_run=False
            )

        assert result["success"] is True
        assert len(result["tickets_created"]) > 0, "Expected Linear tickets created"
        # All created tickets must be for ADOPT_NOW or BREAKING_CHANGE
        for t in created_tickets:
            assert t["entry"]["classification"] in ("ADOPT_NOW", "BREAKING_CHANGE")

    def test_breaking_change_triggers_workspace_grep(self) -> None:
        module = _load_dispatch_module()
        grep_calls: list[str] = []

        def mock_grep(pattern: str) -> list[str]:
            grep_calls.append(pattern)
            return ["src/foo.py:42"]

        with (
            patch.object(module, "_fetch_changelog", return_value=MOCK_CHANGELOG),
            patch.object(module, "_create_linear_ticket", return_value=None),
            patch.object(module, "_save_last_audit_date"),
            patch.object(module, "_write_report", return_value=Path("/tmp/report.md")),
            patch.object(
                module, "_regenerate_dashboard", return_value=Path("/tmp/DASHBOARD.md")
            ),
            patch.object(module, "_grep_workspace", side_effect=mock_grep),
        ):
            result = module.dispatch(
                "claude-code", since_date="2026-01-01", dry_run=False
            )

        assert result["success"] is True
        # There should have been at least one grep call for breaking changes
        assert len(grep_calls) > 0, (
            "Expected workspace grep calls for BREAKING_CHANGE entries"
        )
        # Usages should appear in result
        assert any(
            len(usages) > 0 for usages in result["breaking_change_usages"].values()
        )


@pytest.mark.unit
class TestChangelogAuditDashboard:
    """Verify dashboard generation."""

    def test_regenerate_dashboard_creates_file(self, tmp_path: Path) -> None:
        module = _load_dispatch_module()

        with patch.object(module, "_audit_dir", return_value=tmp_path):
            # Write a dummy last_audit.json so dashboard shows a real date
            (tmp_path / "claude-code.last_audit.json").write_text(
                json.dumps({"last_audit_date": "2026-04-14", "target": "claude-code"})
            )
            dashboard_path = module._regenerate_dashboard()

        assert dashboard_path.exists()
        content = dashboard_path.read_text()
        assert "claude-code" in content
        assert "Changelog Audit Dashboard" in content
        assert "GREEN" in content or "YELLOW" in content or "RED" in content

    def test_stale_target_shows_red(self, tmp_path: Path) -> None:
        module = _load_dispatch_module()

        with patch.object(module, "_audit_dir", return_value=tmp_path):
            # Write a last_audit date 30 days ago — should be RED
            old_date = date(2026, 3, 1).isoformat()
            (tmp_path / "claude-code.last_audit.json").write_text(
                json.dumps({"last_audit_date": old_date, "target": "claude-code"})
            )
            dashboard_path = module._regenerate_dashboard()

        content = dashboard_path.read_text()
        # Find the claude-code row and check it shows RED
        for line in content.splitlines():
            if "claude-code" in line:
                assert "RED" in line, f"Expected RED for stale target, got: {line}"
                break
