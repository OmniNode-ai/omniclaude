# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for deploy-local-plugin --level flag skill tier filtering.

Tests verify that deploy.sh correctly includes/excludes skills based on the
level: and debug: SKILL.md frontmatter fields (OMN-3453).

Strategy: exercise the internal bash helper functions (_level_rank,
_skill_frontmatter_value, _skill_passes_filter) via direct sourcing of
_filter_helpers.sh — the extracted, independently-testable library module.
This avoids spinning up the full deploy pipeline (jq, rsync, Python >= 3.12,
etc.) while still testing the filtering logic against real fixtures.

Integration-level arg-parsing tests invoke deploy.sh directly via subprocess.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

# Path to the skill directory under test
_SKILL_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "skills"
    / "deploy_local_plugin"
)
_FILTER_HELPERS_SH = _SKILL_DIR / "_filter_helpers.sh"
_DEPLOY_SH = _SKILL_DIR / "deploy.sh"


def _make_skill(tmp_path: Path, name: str, level: str, debug: bool) -> Path:
    """Create a minimal skill directory with a SKILL.md frontmatter."""
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True)
    debug_str = "true" if debug else "false"
    (skill_dir / "SKILL.md").write_text(
        textwrap.dedent(
            f"""\
            ---
            name: {name}
            description: Test skill {name}
            version: 1.0.0
            level: {level}
            debug: {debug_str}
            category: test
            ---

            # {name}
            """
        )
    )
    return skill_dir


def _run_filter_check(
    tmp_path: Path,
    skill_name: str,
    level_filter: str,
    include_debug: bool,
    level_explicit: bool | None = None,
) -> bool:
    """Source _filter_helpers.sh and call _skill_passes_filter for one skill dir.

    Returns True if the filter passes (skill should be included).

    ``level_explicit`` defaults to True when level_filter != "advanced" and to
    False when level_filter == "advanced" (mirrors deploy.sh runtime behaviour).
    """
    skill_dir = tmp_path / skill_name
    include_debug_val = "true" if include_debug else "false"

    if level_explicit is None:
        # Match deploy.sh: _LEVEL_EXPLICIT is true only when --level was explicitly passed.
        # For the default-advanced case (no flag), _LEVEL_EXPLICIT=false so debug skills
        # are not excluded (backwards-compatible behaviour).
        _explicit = "false" if level_filter == "advanced" else "true"
    else:
        _explicit = "true" if level_explicit else "false"

    script = textwrap.dedent(
        f"""\
        #!/bin/bash
        set -euo pipefail
        LEVEL_FILTER="{level_filter}"
        INCLUDE_DEBUG="{include_debug_val}"
        _LEVEL_EXPLICIT="{_explicit}"
        source "{_FILTER_HELPERS_SH}"
        if _skill_passes_filter "{skill_dir}"; then
            echo "PASS"
        else
            echo "FAIL"
        fi
        """
    )
    script_path = tmp_path / f"_check_{skill_name}.sh"
    script_path.write_text(script)
    script_path.chmod(0o755)

    result = subprocess.run(
        ["/bin/bash", str(script_path)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"_run_filter_check script failed (exit {result.returncode}):\n"
            f"  stdout: {result.stdout!r}\n"
            f"  stderr: {result.stderr!r}"
        )
    output = result.stdout.strip()
    if output not in {"PASS", "FAIL"}:
        raise AssertionError(f"Unexpected helper output: {output!r}")
    return output == "PASS"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    """Build a small fixture skills directory covering all tier/debug combos."""
    _make_skill(tmp_path, "skill_basic_nodebug", level="basic", debug=False)
    _make_skill(tmp_path, "skill_basic_debug", level="basic", debug=True)
    _make_skill(
        tmp_path, "skill_intermediate_nodebug", level="intermediate", debug=False
    )
    _make_skill(tmp_path, "skill_intermediate_debug", level="intermediate", debug=True)
    _make_skill(tmp_path, "skill_advanced_nodebug", level="advanced", debug=False)
    _make_skill(tmp_path, "skill_advanced_debug", level="advanced", debug=True)
    # Internal support dir (underscore prefix) — always included
    internal = tmp_path / "_lib"
    internal.mkdir()
    (internal / "helpers.md").write_text("# internal helpers\n")
    return tmp_path


# ---------------------------------------------------------------------------
# Tests: --level basic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLevelBasic:
    """--level basic: includes only basic skills; debug:true excluded unless --include-debug."""

    def test_basic_nodebug_included(self, skills_dir: Path) -> None:
        assert _run_filter_check(skills_dir, "skill_basic_nodebug", "basic", False)

    def test_basic_debug_excluded_without_flag(self, skills_dir: Path) -> None:
        assert not _run_filter_check(skills_dir, "skill_basic_debug", "basic", False)

    def test_basic_debug_included_with_flag(self, skills_dir: Path) -> None:
        assert _run_filter_check(skills_dir, "skill_basic_debug", "basic", True)

    def test_intermediate_excluded(self, skills_dir: Path) -> None:
        assert not _run_filter_check(
            skills_dir, "skill_intermediate_nodebug", "basic", False
        )

    def test_advanced_excluded(self, skills_dir: Path) -> None:
        assert not _run_filter_check(
            skills_dir, "skill_advanced_nodebug", "basic", False
        )

    def test_internal_lib_included(self, skills_dir: Path) -> None:
        assert _run_filter_check(skills_dir, "_lib", "basic", False)


# ---------------------------------------------------------------------------
# Tests: --level intermediate
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLevelIntermediate:
    """--level intermediate: includes basic + intermediate; advanced excluded."""

    def test_basic_included(self, skills_dir: Path) -> None:
        assert _run_filter_check(
            skills_dir, "skill_basic_nodebug", "intermediate", False
        )

    def test_intermediate_included(self, skills_dir: Path) -> None:
        assert _run_filter_check(
            skills_dir, "skill_intermediate_nodebug", "intermediate", False
        )

    def test_intermediate_debug_excluded(self, skills_dir: Path) -> None:
        assert not _run_filter_check(
            skills_dir, "skill_intermediate_debug", "intermediate", False
        )

    def test_intermediate_debug_included_with_flag(self, skills_dir: Path) -> None:
        assert _run_filter_check(
            skills_dir, "skill_intermediate_debug", "intermediate", True
        )

    def test_advanced_excluded(self, skills_dir: Path) -> None:
        assert not _run_filter_check(
            skills_dir, "skill_advanced_nodebug", "intermediate", False
        )

    def test_internal_lib_included(self, skills_dir: Path) -> None:
        assert _run_filter_check(skills_dir, "_lib", "intermediate", False)


# ---------------------------------------------------------------------------
# Tests: --level advanced (default — no filtering)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLevelAdvanced:
    """--level advanced: all skills included; backwards-compatible default.

    When no --level flag is used (_LEVEL_EXPLICIT=false), debug:true skills are
    NOT excluded — this preserves pre-OMN-3453 behaviour.
    """

    def test_advanced_nodebug_included(self, skills_dir: Path) -> None:
        assert _run_filter_check(
            skills_dir, "skill_advanced_nodebug", "advanced", False
        )

    def test_advanced_debug_included_by_default(self, skills_dir: Path) -> None:
        # No explicit --level → _LEVEL_EXPLICIT=false → debug skills pass through
        assert _run_filter_check(
            skills_dir, "skill_advanced_debug", "advanced", False, level_explicit=False
        )

    def test_basic_included(self, skills_dir: Path) -> None:
        assert _run_filter_check(skills_dir, "skill_basic_nodebug", "advanced", False)

    def test_intermediate_included(self, skills_dir: Path) -> None:
        assert _run_filter_check(
            skills_dir, "skill_intermediate_nodebug", "advanced", False
        )

    def test_internal_lib_included(self, skills_dir: Path) -> None:
        assert _run_filter_check(skills_dir, "_lib", "advanced", False)


# ---------------------------------------------------------------------------
# Tests: argument parsing validation (deploy.sh invocation)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestArgParsing:
    """deploy.sh rejects invalid --level values and handles edge cases."""

    def test_invalid_level_exits_nonzero(self) -> None:
        result = subprocess.run(
            ["/bin/bash", str(_DEPLOY_SH), "--level=bogus"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={**os.environ, "HOME": os.environ.get("HOME", "/tmp")},
        )
        assert result.returncode != 0
        assert "basic" in result.stderr or "advanced" in result.stderr

    def test_level_without_value_exits_nonzero(self) -> None:
        result = subprocess.run(
            ["/bin/bash", str(_DEPLOY_SH), "--level"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={**os.environ, "HOME": os.environ.get("HOME", "/tmp")},
        )
        assert result.returncode != 0

    def test_help_flag_exits_zero(self) -> None:
        result = subprocess.run(
            ["/bin/bash", str(_DEPLOY_SH), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={**os.environ, "HOME": os.environ.get("HOME", "/tmp")},
        )
        assert result.returncode == 0
        assert "--level" in result.stdout
        assert "--include-debug" in result.stdout
