# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Shell-level tests for pre_tool_use_bash_guard.sh worktree enforcement (OMN-9896).

The Python ``bash_guard.py`` is unit-tested separately in
``test_bash_guard_worktree.py``. These tests cover the shell-level worktree
gate that runs *before* Python — the gate that was blocking valid worktree
creation on machines whose ``$OMNI_HOME`` differs from the previous
hardcoded default.

OMN-9896 covers:
  1. ``$OMNI_HOME``-based canonical root resolution (no hardcoded paths).
  2. Fail-fast when ``OMNI_HOME`` is unset and no override is provided.

OMN-9906: the legacy ``ONEX_WORKTREE_GUARD=off`` env-var opt-out was migrated
to ``ONEX_HOOKS_MASK``. Disable via: ``onex hooks disable WORKTREE_GUARD``
(sets ``ONEX_HOOKS_MASK`` with the WORKTREE_GUARD bit cleared).

WORKTREE_GUARD bit value: 0x800000000000000 (bit 59).
Mask with WORKTREE_GUARD cleared (all other bits on): 0x7ffffffffffffff
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = (
    REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "pre_tool_use_bash_guard.sh"
)


def _run_hook(
    command: str,
    *,
    env_overrides: dict[str, str | None] | None = None,
    sandbox_home: Path | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the shell hook with *command* on stdin and return the completed process.

    Inherits the parent test environment so ``ONEX_STATE_DIR`` /
    ``CLAUDE_PLUGIN_ROOT`` / venv discovery all work; *env_overrides* may
    override or unset specific vars (set value to ``None`` to delete).

    When *sandbox_home* is provided, ``HOME`` is repointed there so the hook's
    ``~/.omnibase/.env`` auto-source (in ``common.sh``) reads from a sandbox
    dir instead of the developer's real env file. Without this, env vars set
    in ``env_overrides`` would be silently re-overwritten by ``set -a; source
    ~/.omnibase/.env`` inside ``common.sh``.
    """
    env = os.environ.copy()
    # Pin CLAUDE_PLUGIN_ROOT to this checkout so the hook sources the
    # script-local helpers regardless of where pytest was invoked from.
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT / "plugins" / "onex")
    if sandbox_home is not None:
        env["HOME"] = str(sandbox_home)
        # Keep ONEX_STATE_DIR pointing somewhere writable in the sandbox.
        env["ONEX_STATE_DIR"] = str(sandbox_home / ".onex_state")
    if env_overrides:
        for key, value in env_overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value

    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return subprocess.run(  # noqa: S603
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
        cwd=cwd,
    )


@pytest.fixture
def sandbox_home(tmp_path: Path) -> Path:
    """A clean ``$HOME`` with no ``~/.omnibase/.env`` so the hook does not
    pick up developer-machine env vars."""
    home = tmp_path / "fake_home"
    home.mkdir()
    return home


_WORKTREE_GUARD_BIT = 0x800000000000000
_MASK_WORKTREE_GUARD_OFF = hex(0xFFFFFFFFFFFFFFFF & ~_WORKTREE_GUARD_BIT)


@pytest.mark.unit
class TestWorktreeGuardToggle:
    """OMN-9906: opt-out via ONEX_HOOKS_MASK (WORKTREE_GUARD bit cleared)."""

    def test_mask_with_worktree_guard_cleared_short_circuits(self) -> None:
        """Clearing the WORKTREE_GUARD bit in ONEX_HOOKS_MASK bypasses the guard.

        OMN-9906: replaces the legacy ONEX_WORKTREE_GUARD=off env-var opt-out.
        Without the toggle, ``git worktree add /tmp/anywhere`` is blocked
        because ``/tmp`` is not under any canonical worktree root.
        """
        result = _run_hook(
            "git worktree add /tmp/non-canonical-but-allowed -b feat/test",
            env_overrides={"ONEX_HOOKS_MASK": _MASK_WORKTREE_GUARD_OFF},
        )
        assert result.returncode == 0, (
            f"ONEX_HOOKS_MASK with WORKTREE_GUARD cleared should bypass the guard, "
            f"got exit {result.returncode}.\nstderr: {result.stderr}"
        )

    def test_default_mask_enforces_guard(
        self, tmp_path: Path, sandbox_home: Path
    ) -> None:
        """With default mask (WORKTREE_GUARD bit set), out-of-root path is blocked."""
        result = _run_hook(
            "git worktree add /tmp/non-canonical -b feat/test",
            env_overrides={
                "ONEX_HOOKS_MASK": None,
                "ONEX_WORKTREES_ROOT": str(tmp_path / "wt"),
                "OMNI_WORKTREES_DIR": None,
            },
            sandbox_home=sandbox_home,
        )
        assert result.returncode == 2, (
            f"Without mask override, /tmp path must be blocked. Got exit "
            f"{result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # Block message must mention how to disable the guard.
        body = result.stdout
        assert "WORKTREE_GUARD" in body or "onex hooks disable" in body, (
            f"BLOCKED message should advertise the bitmask opt-out. Got: {body!r}"
        )

    def test_legacy_onex_worktree_guard_env_var_no_longer_bypasses(
        self, tmp_path: Path, sandbox_home: Path
    ) -> None:
        """OMN-9906: ONEX_WORKTREE_GUARD=off no longer bypasses the guard."""
        result = _run_hook(
            "git worktree add /tmp/non-canonical -b feat/test",
            env_overrides={
                "ONEX_WORKTREE_GUARD": "off",
                "ONEX_WORKTREES_ROOT": str(tmp_path / "wt"),
                "OMNI_WORKTREES_DIR": None,
                "OMNI_HOME": None,
                "ONEX_HOOKS_MASK": None,
            },
            sandbox_home=sandbox_home,
        )
        assert result.returncode == 2, (
            "ONEX_WORKTREE_GUARD=off must no longer bypass the guard after OMN-9906. "
            f"Got exit {result.returncode}.\nstdout: {result.stdout}"
        )


@pytest.mark.unit
class TestWorktreeGuardRootResolution:
    """OMN-9896: canonical worktree root resolution from $OMNI_HOME / overrides."""

    def test_uses_omni_home_when_no_override(
        self, tmp_path: Path, sandbox_home: Path
    ) -> None:
        """With OMNI_HOME set and no explicit override, root = $OMNI_HOME/omni_worktrees."""
        omni_home = tmp_path / "omni_home_fake"
        omni_home.mkdir()
        result = _run_hook(
            f"git worktree add {omni_home}/omni_worktrees/OMN-1/repo -b feat/x",
            env_overrides={
                "OMNI_HOME": str(omni_home),
                "ONEX_WORKTREES_ROOT": None,
                "OMNI_WORKTREES_DIR": None,
            },
            sandbox_home=sandbox_home,
        )
        assert result.returncode == 0, (
            f"Path under $OMNI_HOME/omni_worktrees should pass.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_blocks_path_outside_omni_home_root(
        self, tmp_path: Path, sandbox_home: Path
    ) -> None:
        """Paths outside $OMNI_HOME/omni_worktrees are blocked."""
        omni_home = tmp_path / "omni_home_fake"
        omni_home.mkdir()
        result = _run_hook(
            "git worktree add /tmp/elsewhere -b feat/x",
            env_overrides={
                "OMNI_HOME": str(omni_home),
                "ONEX_WORKTREES_ROOT": None,
                "OMNI_WORKTREES_DIR": None,
                "ONEX_HOOKS_MASK": None,
            },
            sandbox_home=sandbox_home,
        )
        assert result.returncode == 2
        body = result.stdout
        assert "BLOCKED" in body
        assert str(omni_home / "omni_worktrees") in body, (
            f"Block reason should name the resolved canonical root.\nGot: {body}"
        )

    def test_blocks_dotdot_escape_from_canonical_root(
        self, tmp_path: Path, sandbox_home: Path
    ) -> None:
        """Normalized containment blocks paths that escape with ``..``."""
        root = tmp_path / "wt"
        result = _run_hook(
            f"git worktree add {root}/../outside/repo -b feat/x",
            env_overrides={
                "ONEX_WORKTREES_ROOT": str(root),
                "OMNI_WORKTREES_DIR": None,
                "ONEX_HOOKS_MASK": None,
            },
            sandbox_home=sandbox_home,
        )
        assert result.returncode == 2
        body = result.stdout
        assert str(tmp_path / "outside" / "repo") in body
        assert str(root) in body

    def test_allows_relative_path_resolved_from_original_cwd(
        self, tmp_path: Path, sandbox_home: Path
    ) -> None:
        """Relative worktree paths resolve against the cwd before the hook cd's home."""
        root = tmp_path / "wt"
        root.mkdir()
        result = _run_hook(
            "git worktree add wt/OMN-1/repo -b feat/x",
            env_overrides={
                "ONEX_WORKTREES_ROOT": str(root),
                "OMNI_WORKTREES_DIR": None,
            },
            sandbox_home=sandbox_home,
            cwd=tmp_path,
        )
        assert result.returncode == 0, (
            f"Relative path under normalized root should pass.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_explicit_override_wins_over_omni_home(
        self, tmp_path: Path, sandbox_home: Path
    ) -> None:
        """ONEX_WORKTREES_ROOT takes precedence over $OMNI_HOME."""
        override_root = tmp_path / "alt_wt_root"
        override_root.mkdir()
        omni_home = tmp_path / "omni_home_fake"
        omni_home.mkdir()
        result = _run_hook(
            f"git worktree add {override_root}/OMN-1/repo -b feat/x",
            env_overrides={
                "OMNI_HOME": str(omni_home),
                "ONEX_WORKTREES_ROOT": str(override_root),
                "OMNI_WORKTREES_DIR": None,
            },
            sandbox_home=sandbox_home,
        )
        assert result.returncode == 0, (
            f"Override path should pass even though it differs from "
            f"$OMNI_HOME/omni_worktrees.\nstdout: {result.stdout}"
        )

    def test_fail_fast_when_omni_home_unset_and_no_override(
        self, sandbox_home: Path
    ) -> None:
        """No OMNI_HOME + no override = block with actionable message (rule #8)."""
        result = _run_hook(
            "git worktree add /tmp/wt -b feat/x",
            env_overrides={
                "OMNI_HOME": None,
                "ONEX_WORKTREES_ROOT": None,
                "OMNI_WORKTREES_DIR": None,
                "ONEX_HOOKS_MASK": None,
            },
            sandbox_home=sandbox_home,
        )
        assert result.returncode == 2
        body = result.stdout
        # Block message must explain how to recover (set OMNI_HOME, set
        # ONEX_WORKTREES_ROOT, or disable via the bitmask).
        assert "OMNI_HOME" in body
        assert "WORKTREE_GUARD" in body or "onex hooks disable" in body, (
            "Fail-fast message should advertise the bitmask opt-out so non-OmniNode "
            f"users can recover. Got: {body!r}"
        )


@pytest.mark.unit
class TestWorktreeGuardNonWorktreeCommands:
    """Non-worktree commands must pass through regardless of env state."""

    def test_git_status_unaffected(self) -> None:
        result = _run_hook("git status")
        # The Python downstream guard may have its own opinions, but the
        # worktree shell gate must not block ``git status``.
        assert result.returncode == 0, (
            f"git status must not be blocked by worktree gate.\nstderr: {result.stderr}"
        )

    def test_commit_message_with_worktree_string_unaffected(self) -> None:
        result = _run_hook('git commit -m "fix git worktree add path resolution"')
        assert result.returncode == 0, (
            f"Quoted 'worktree add' in commit message must not trigger guard.\n"
            f"stderr: {result.stderr}"
        )
