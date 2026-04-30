# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for post-skill-delegation-enforcer.sh foreground_orchestrator opt-out (OMN-10261).

Verifies:
- Skill with foreground_orchestrator: true frontmatter → hook exits without enforcer
- Skill without foreground_orchestrator field → hook emits enforcer
- Skill with foreground_orchestrator: false → hook emits enforcer
- Skill with no frontmatter → hook falls through, emits enforcer, no crash
- Missing SKILL.md → hook falls through, emits enforcer, no crash
- Namespaced skill name (onex:skill_name) is resolved to bare name correctly
"""

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[4]
_HOOK_SCRIPT = "plugins/onex/hooks/scripts/post-skill-delegation-enforcer.sh"


def run_enforcer(
    skill_name: str,
    plugin_root: str | None = None,
    session_id: str = "test-session-enforcer",
) -> tuple[int, str, str]:
    payload = json.dumps(
        {
            "tool_name": "Skill",
            "session_id": session_id,
            "tool_input": {"skill": skill_name},
        }
    )
    env: dict[str, str] = {
        **os.environ,
        "OMNICLAUDE_MODE": "full",
        "OMNICLAUDE_HOOKS_DISABLE": "0",
        # Prevent daemon side-effects
        "HOOK_RUNTIME_SOCKET": "/tmp/nonexistent-test-socket-enforcer",
        # Suppress lite-mode short-circuit
        "ONEX_HOOK_MODE": "full",
    }
    if plugin_root is not None:
        env["CLAUDE_PLUGIN_ROOT"] = plugin_root

    proc = subprocess.run(
        ["bash", _HOOK_SCRIPT],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _write_skill_md(skill_dir: Path, content: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(textwrap.dedent(content))


@pytest.mark.unit
def test_foreground_orchestrator_true_skips_enforcer(tmp_path: Path) -> None:
    """Skill with foreground_orchestrator: true must not emit the DELEGATION ENFORCER."""
    skills_dir = tmp_path / "skills"
    _write_skill_md(
        skills_dir / "my_orchestrator",
        """\
        ---
        description: An orchestrator skill
        foreground_orchestrator: true
        ---
        # My Orchestrator
        """,
    )
    rc, stdout, _ = run_enforcer("my_orchestrator", plugin_root=str(tmp_path))
    assert rc == 0
    assert "DELEGATION ENFORCER" not in stdout


@pytest.mark.unit
def test_foreground_orchestrator_true_emits_empty_hook_output(tmp_path: Path) -> None:
    """When bypassing enforcer, hook must emit valid hookSpecificOutput JSON."""
    skills_dir = tmp_path / "skills"
    _write_skill_md(
        skills_dir / "my_orchestrator",
        """\
        ---
        description: orchestrator
        foreground_orchestrator: true
        ---
        """,
    )
    rc, stdout, _ = run_enforcer("my_orchestrator", plugin_root=str(tmp_path))
    assert rc == 0
    data = json.loads(stdout)
    assert "hookSpecificOutput" in data


@pytest.mark.unit
def test_skill_without_foreground_orchestrator_emits_enforcer(tmp_path: Path) -> None:
    """Skill without foreground_orchestrator field must trigger the delegation enforcer."""
    skills_dir = tmp_path / "skills"
    _write_skill_md(
        skills_dir / "regular_skill",
        """\
        ---
        description: A regular delegatable skill
        ---
        # Regular Skill
        """,
    )
    rc, stdout, _ = run_enforcer("regular_skill", plugin_root=str(tmp_path))
    assert rc == 0
    assert "DELEGATION ENFORCER" in stdout


@pytest.mark.unit
def test_foreground_orchestrator_false_emits_enforcer(tmp_path: Path) -> None:
    """foreground_orchestrator: false must not suppress the enforcer."""
    skills_dir = tmp_path / "skills"
    _write_skill_md(
        skills_dir / "opt_out_false",
        """\
        ---
        description: Skill with explicit false
        foreground_orchestrator: false
        ---
        """,
    )
    rc, stdout, _ = run_enforcer("opt_out_false", plugin_root=str(tmp_path))
    assert rc == 0
    assert "DELEGATION ENFORCER" in stdout


@pytest.mark.unit
def test_no_frontmatter_falls_through_to_enforcer(tmp_path: Path) -> None:
    """Skill with no YAML frontmatter must fall through and emit the enforcer."""
    skills_dir = tmp_path / "skills"
    _write_skill_md(
        skills_dir / "no_frontmatter",
        """\
        # Skill With No Frontmatter

        Just a heading and content.
        """,
    )
    rc, stdout, _ = run_enforcer("no_frontmatter", plugin_root=str(tmp_path))
    assert rc == 0
    assert "DELEGATION ENFORCER" in stdout


@pytest.mark.unit
def test_missing_skill_md_falls_through_gracefully(tmp_path: Path) -> None:
    """Non-existent SKILL.md must not crash the hook; enforcer still emits."""
    rc, stdout, _ = run_enforcer("nonexistent_skill_xyz", plugin_root=str(tmp_path))
    assert rc == 0
    assert "DELEGATION ENFORCER" in stdout


@pytest.mark.unit
def test_namespaced_skill_name_resolved(tmp_path: Path) -> None:
    """Namespaced skill name (onex:my_orchestrator) resolves to bare directory name."""
    skills_dir = tmp_path / "skills"
    _write_skill_md(
        skills_dir / "my_orchestrator",
        """\
        ---
        description: orchestrator with namespace
        foreground_orchestrator: true
        ---
        """,
    )
    rc, stdout, _ = run_enforcer("onex:my_orchestrator", plugin_root=str(tmp_path))
    assert rc == 0
    assert "DELEGATION ENFORCER" not in stdout


@pytest.mark.unit
def test_real_epic_team_skill_bypasses_enforcer() -> None:
    """epic_team skill in the actual plugin must have foreground_orchestrator: true."""
    plugin_root = _REPO_ROOT / "plugins" / "onex"
    rc, stdout, _ = run_enforcer("epic_team", plugin_root=str(plugin_root))
    assert rc == 0
    assert "DELEGATION ENFORCER" not in stdout, (
        "epic_team should have foreground_orchestrator: true and bypass the enforcer"
    )


@pytest.mark.unit
def test_real_wave_scheduler_skill_bypasses_enforcer() -> None:
    """wave_scheduler skill must have foreground_orchestrator: true."""
    plugin_root = _REPO_ROOT / "plugins" / "onex"
    rc, stdout, _ = run_enforcer("wave_scheduler", plugin_root=str(plugin_root))
    assert rc == 0
    assert "DELEGATION ENFORCER" not in stdout


@pytest.mark.unit
def test_real_overnight_skill_no_longer_bypasses_enforcer() -> None:
    """overnight is retired and must not opt out as an active foreground orchestrator."""
    plugin_root = _REPO_ROOT / "plugins" / "onex"
    rc, stdout, _ = run_enforcer("overnight", plugin_root=str(plugin_root))
    assert rc == 0
    assert "DELEGATION ENFORCER" in stdout


@pytest.mark.unit
def test_real_dispatch_engine_skill_bypasses_enforcer() -> None:
    """dispatch_engine skill must have foreground_orchestrator: true."""
    plugin_root = _REPO_ROOT / "plugins" / "onex"
    rc, stdout, _ = run_enforcer("dispatch_engine", plugin_root=str(plugin_root))
    assert rc == 0
    assert "DELEGATION ENFORCER" not in stdout


@pytest.mark.unit
def test_real_autopilot_skill_no_longer_bypasses_enforcer() -> None:
    """autopilot is retired and must not opt out as an active foreground orchestrator."""
    plugin_root = _REPO_ROOT / "plugins" / "onex"
    rc, stdout, _ = run_enforcer("autopilot", plugin_root=str(plugin_root))
    assert rc == 0
    assert "DELEGATION ENFORCER" in stdout
