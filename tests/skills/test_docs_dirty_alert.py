# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the docs_dirty_alert skill check module (OMN-13046).

Verifies that the docs-branch leg of the dirty-canonical sweep alerts
when untracked docs files in omni_home exceed a count threshold or age.
"""

from __future__ import annotations

import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from omniclaude.nodes.node_skill_docs_dirty_alert_orchestrator.check import (
    DocsDirtyAlertConfig,
    UntrackedFile,
    _collect_untracked_files,
    _run_git_status,
    run_docs_dirty_check,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    tmp_path: Path,
    *,
    count_threshold: int = 50,
    age_threshold_seconds: float = 14_400.0,
) -> DocsDirtyAlertConfig:
    return DocsDirtyAlertConfig(
        omni_home=tmp_path / "omni_home",
        state_dir=tmp_path / "onex_state",
        count_threshold=count_threshold,
        age_threshold_seconds=age_threshold_seconds,
    )


def _make_untracked(path: Path, age_seconds: float, now_ts: float) -> UntrackedFile:
    mtime = now_ts - age_seconds
    return UntrackedFile(
        repo_relative_path=str(path),
        abs_path=path,
        mtime=mtime,
        age_seconds=age_seconds,
    )


# ---------------------------------------------------------------------------
# Tests for _run_git_status
# ---------------------------------------------------------------------------


class TestRunGitStatus:
    def test_returns_untracked_lines_only(self, tmp_path: Path) -> None:
        fake_stdout = (
            "?? docs/handoffs/night-final.md\n"
            " M docs/plans/sprint.md\n"
            "?? docs/evidence/proof.yaml\n"
            "!! docs/deep-dives/ignored.md\n"
        )

        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = fake_stdout
            mock_run.return_value = mock_proc

            lines = _run_git_status(
                tmp_path, ("handoffs", "evidence", "plans", "deep-dives")
            )

        assert "?? docs/handoffs/night-final.md" in lines
        assert "?? docs/evidence/proof.yaml" in lines
        # Modified file does not start with ??
        assert not any("sprint.md" in ln for ln in lines)
        # Ignored file does not start with ??
        assert not any("ignored.md" in ln for ln in lines)

    def test_empty_output_returns_empty_list(self, tmp_path: Path) -> None:
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.stdout = ""
            mock_run.return_value = mock_proc

            lines = _run_git_status(tmp_path, ("handoffs",))

        assert lines == []

    def test_subprocess_error_returns_empty(self, tmp_path: Path) -> None:
        with patch("subprocess.run", side_effect=OSError("git not found")):
            lines = _run_git_status(tmp_path, ("handoffs",))

        assert lines == []

    def test_timeout_returns_empty(self, tmp_path: Path) -> None:
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=30),
        ):
            lines = _run_git_status(tmp_path, ("handoffs",))

        assert lines == []


# ---------------------------------------------------------------------------
# Tests for _collect_untracked_files
# ---------------------------------------------------------------------------


class TestCollectUntrackedFiles:
    def test_single_file_collected(self, tmp_path: Path) -> None:
        (tmp_path / "docs" / "handoffs").mkdir(parents=True)
        f = tmp_path / "docs" / "handoffs" / "night-final.md"
        f.write_text("content")

        now_ts = time.time()
        lines = ["?? docs/handoffs/night-final.md"]
        files = _collect_untracked_files(tmp_path, lines, now_ts=now_ts)

        assert len(files) == 1
        assert files[0].repo_relative_path == "docs/handoffs/night-final.md"
        assert files[0].age_seconds >= 0

    def test_untracked_directory_expands_to_files(self, tmp_path: Path) -> None:
        dir_path = tmp_path / "docs" / "handoffs" / "2026-06-28"
        dir_path.mkdir(parents=True)
        (dir_path / "a.md").write_text("a")
        (dir_path / "b.md").write_text("b")

        now_ts = time.time()
        lines = ["?? docs/handoffs/2026-06-28/"]
        files = _collect_untracked_files(tmp_path, lines, now_ts=now_ts)

        assert len(files) == 2

    def test_missing_file_skipped(self, tmp_path: Path) -> None:
        now_ts = time.time()
        lines = ["?? docs/handoffs/ghost.md"]  # does not exist
        files = _collect_untracked_files(tmp_path, lines, now_ts=now_ts)

        assert files == []

    def test_age_computed_from_mtime(self, tmp_path: Path) -> None:
        (tmp_path / "docs" / "evidence").mkdir(parents=True)
        f = tmp_path / "docs" / "evidence" / "proof.yaml"
        f.write_text("content")

        five_hours_ago = time.time() - 18_000
        import os

        os.utime(f, (five_hours_ago, five_hours_ago))

        now_ts = time.time()
        lines = ["?? docs/evidence/proof.yaml"]
        files = _collect_untracked_files(tmp_path, lines, now_ts=now_ts)

        assert len(files) == 1
        assert files[0].age_seconds > 17_900  # ~5h


# ---------------------------------------------------------------------------
# Tests for run_docs_dirty_check — count threshold
# ---------------------------------------------------------------------------


class TestRunDocsDirtyCheckCountThreshold:
    def test_no_alert_below_threshold(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, count_threshold=50)
        now = datetime.now(UTC)

        # Return 10 untracked lines from git (all young)
        fake_lines = [f"?? docs/handoffs/file{i:03d}.md" for i in range(10)]

        # Create the actual files so _collect_untracked_files can stat them
        (config.omni_home / "docs" / "handoffs").mkdir(parents=True, exist_ok=True)
        for i in range(10):
            (config.omni_home / "docs" / "handoffs" / f"file{i:03d}.md").write_text("x")

        with patch(
            "omniclaude.nodes.node_skill_docs_dirty_alert_orchestrator.check._run_git_status",
            return_value=fake_lines,
        ):
            result = run_docs_dirty_check(config, now=now)

        assert not result.alert_fired
        assert result.friction_path is None

    def test_alert_fires_at_threshold(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, count_threshold=5)
        now = datetime.now(UTC)

        (config.omni_home / "docs" / "handoffs").mkdir(parents=True, exist_ok=True)
        for i in range(5):
            (config.omni_home / "docs" / "handoffs" / f"file{i:03d}.md").write_text("x")

        fake_lines = [f"?? docs/handoffs/file{i:03d}.md" for i in range(5)]

        with patch(
            "omniclaude.nodes.node_skill_docs_dirty_alert_orchestrator.check._run_git_status",
            return_value=fake_lines,
        ):
            result = run_docs_dirty_check(config, now=now)

        assert result.alert_fired
        assert result.friction_path is not None
        assert result.friction_path.exists()
        data = yaml.safe_load(result.friction_path.read_text())
        assert data["surface"] == "docs/dirty-canonical"
        assert data["severity"] == "high"
        assert data["context_ticket_id"] == "OMN-13046"
        assert data["untracked_count"] >= 5


# ---------------------------------------------------------------------------
# Tests for run_docs_dirty_check — age threshold
# ---------------------------------------------------------------------------


class TestRunDocsDirtyCheckAgeThreshold:
    def test_no_alert_young_files(self, tmp_path: Path) -> None:
        config = _make_config(
            tmp_path, count_threshold=100, age_threshold_seconds=14_400
        )
        now = datetime.now(UTC)

        (config.omni_home / "docs" / "handoffs").mkdir(parents=True, exist_ok=True)
        f = config.omni_home / "docs" / "handoffs" / "recent.md"
        f.write_text("x")
        # mtime = now - 1h (within threshold)
        recent_mtime = now.timestamp() - 3600
        import os

        os.utime(f, (recent_mtime, recent_mtime))

        with patch(
            "omniclaude.nodes.node_skill_docs_dirty_alert_orchestrator.check._run_git_status",
            return_value=["?? docs/handoffs/recent.md"],
        ):
            result = run_docs_dirty_check(config, now=now)

        assert not result.alert_fired

    def test_alert_fires_for_old_file(self, tmp_path: Path) -> None:
        config = _make_config(
            tmp_path, count_threshold=100, age_threshold_seconds=14_400
        )
        now = datetime.now(UTC)

        (config.omni_home / "docs" / "handoffs").mkdir(parents=True, exist_ok=True)
        f = config.omni_home / "docs" / "handoffs" / "stale.md"
        f.write_text("x")
        # mtime = now - 5h (exceeds 4h threshold)
        stale_mtime = now.timestamp() - 18_000
        import os

        os.utime(f, (stale_mtime, stale_mtime))

        with patch(
            "omniclaude.nodes.node_skill_docs_dirty_alert_orchestrator.check._run_git_status",
            return_value=["?? docs/handoffs/stale.md"],
        ):
            result = run_docs_dirty_check(config, now=now)

        assert result.alert_fired
        assert any(
            "4h" in reason or ">4" in reason or "5." in reason
            for reason in result.alert_reasons
        )
        friction_data = yaml.safe_load(result.friction_path.read_text())  # type: ignore[union-attr]
        assert "docs/handoffs/stale.md" in str(friction_data)


# ---------------------------------------------------------------------------
# Tests for clean-state (zero untracked)
# ---------------------------------------------------------------------------


class TestRunDocsDirtyCheckClean:
    def test_clean_repo_no_alert(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        now = datetime.now(UTC)

        with patch(
            "omniclaude.nodes.node_skill_docs_dirty_alert_orchestrator.check._run_git_status",
            return_value=[],
        ):
            result = run_docs_dirty_check(config, now=now)

        assert not result.alert_fired
        assert result.untracked_files == []
        assert result.oldest_age_seconds is None
        friction_dir = config.state_dir / "friction"
        if friction_dir.exists():
            assert list(friction_dir.glob("docs-dirty-alert-*.yaml")) == []


# ---------------------------------------------------------------------------
# Tests for friction YAML schema
# ---------------------------------------------------------------------------


class TestFrictionYamlSchema:
    def test_friction_yaml_has_required_fields(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, count_threshold=1)
        now = datetime.now(UTC)

        (config.omni_home / "docs" / "handoffs").mkdir(parents=True, exist_ok=True)
        (config.omni_home / "docs" / "handoffs" / "x.md").write_text("x")

        with patch(
            "omniclaude.nodes.node_skill_docs_dirty_alert_orchestrator.check._run_git_status",
            return_value=["?? docs/handoffs/x.md"],
        ):
            result = run_docs_dirty_check(config, now=now)

        assert result.alert_fired
        data = yaml.safe_load(result.friction_path.read_text())  # type: ignore[union-attr]
        required_fields = {
            "surface",
            "severity",
            "skill",
            "description",
            "untracked_count",
            "timestamp",
            "context_ticket_id",
        }
        for field_name in required_fields:
            assert field_name in data, f"Missing field: {field_name}"
        assert data["skill"] == "docs_dirty_alert"
        assert data["context_ticket_id"] == "OMN-13046"
