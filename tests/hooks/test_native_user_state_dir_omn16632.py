# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A user outside our workspace (no OMNI_HOME, no ONEX_STATE_DIR) is not locked out (OMN-16632).

Before: ``pre_tool_use_bash_guards.sh`` refused every Bash call, ``ls`` included, with
"refusal log path is unresolved". Now the state directory defaults to the per-user XDG
one, every guard that can act still acts, and a guard that needs the workspace says so
once and allows.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = "plugins/onex/hooks/scripts/pre_tool_use_bash_guards.sh"
ROTATION = "kubectl -n onex-dev delete secret operator-k8s"
WORKTREE_ADD = "git worktree add /tmp/native-user-stray/wt -b native-user-wt"
_TOOLS = [
    "bash",
    "cat",
    "date",
    "dirname",
    "basename",
    "mkdir",
    "grep",
    "egrep",
    "sed",
    "tr",
    "head",
    "tail",
    "env",
    "uname",
    "touch",
    "rm",
    "stat",
    "cut",
    "sort",
    "wc",
    "sleep",
    "mktemp",
    "ls",
    "id",
    "readlink",
    "awk",
    "find",
    "cp",
    "mv",
    "jq",
    "git",
]


@pytest.fixture
def plugin(tmp_path: Path) -> Path:
    """A copy of the plugin with no repo ``.venv`` above it, as a marketplace install has."""
    dest = tmp_path / "install" / "plugins" / "onex"
    shutil.copytree(ROOT / "plugins/onex/hooks", dest / "hooks")
    shutil.copytree(ROOT / "plugins/onex/lib", dest / "lib")
    return dest


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    (path / "repo").mkdir(parents=True)
    # An OmniNode-marked repo (repo_guard.sh marker 3): the guards act here. In an
    # unmarked repo they are no-ops by design, so `plain` only proves `ls` is not refused.
    (path / "repo" / "CLAUDE.md").write_text("omniclaude workspace\n")
    (path / "plain").mkdir()
    subprocess.run(
        ["git", "init", "-q", str(path / "repo")],
        env=scrub_git_location_env(os.environ),
        check=True,
    )
    return path


def _env(home: Path, plugin: Path, **extra: str) -> dict[str, str]:
    env = {
        "HOME": str(home),
        "PATH": os.environ["PATH"],
        "CLAUDE_PLUGIN_ROOT": str(plugin),
        "OMNICLAUDE_MODE": "lite",
    }
    env.update(extra)
    return env


def _run(
    home: Path, plugin: Path, command: str, repo: str = "repo", **extra: str
) -> subprocess.CompletedProcess[str]:
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(home / repo),
            "session_id": "native-user",
        }
    )
    return subprocess.run(
        ["bash", str(plugin / "hooks/scripts/pre_tool_use_bash_guards.sh")],
        input=payload,
        env=_env(home, plugin, **extra),
        cwd=home / repo,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("repo", ["repo", "plain"])
def test_ls_is_allowed_with_neither_variable(
    plugin: Path, home: Path, repo: str
) -> None:
    result = _run(home, plugin, "ls", repo=repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert "refusal log path is unresolved" not in result.stderr


def test_state_dir_defaults_to_the_home_xdg_dir(plugin: Path, home: Path) -> None:
    _run(home, plugin, "ls")
    assert (home / ".local/state/omniclaude/hooks/logs").is_dir()


def test_xdg_state_home_is_honoured_and_a_relative_one_is_not(
    plugin: Path, home: Path, tmp_path: Path
) -> None:
    xdg = tmp_path / "xdg"
    assert _run(home, plugin, "ls", XDG_STATE_HOME=str(xdg)).returncode == 0
    assert (xdg / "omniclaude/hooks/logs").is_dir()
    assert _run(home, plugin, "ls", XDG_STATE_HOME="relative/state").returncode == 0
    assert (home / ".local/state/omniclaude/hooks/logs").is_dir()


def test_a_guarded_dangerous_command_is_still_refused(plugin: Path, home: Path) -> None:
    result = _run(home, plugin, ROTATION)
    assert result.returncode == 2, result.stdout + result.stderr
    verdict = json.loads(result.stdout)
    assert verdict["decision"] == "block"
    assert "OMN-17957" in verdict["reason"]
    assert "refusal log path is unresolved" not in verdict["reason"]


def test_worktree_guard_without_a_workspace_says_so_once_and_allows(
    plugin: Path, home: Path
) -> None:
    first = _run(home, plugin, WORKTREE_ADD)
    assert first.returncode == 0, first.stdout + first.stderr
    assert first.stdout == ""
    assert "worktree destinations are not checked" in first.stderr
    second = _run(home, plugin, WORKTREE_ADD)
    assert second.returncode == 0
    assert "worktree destinations are not checked" not in second.stderr


def test_our_session_with_omni_home_unset_keeps_the_worktree_guard(
    plugin: Path, home: Path, tmp_path: Path
) -> None:
    # ONEX_STATE_DIR set explicitly is not the native-user default: no weakening.
    result = _run(home, plugin, WORKTREE_ADD, ONEX_STATE_DIR=str(tmp_path / "state"))
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["decision"] == "block"


def test_our_session_with_omni_home_set_still_judges_the_worktree(
    plugin: Path, home: Path, tmp_path: Path
) -> None:
    registry = tmp_path / "registry"
    registry.mkdir()
    result = _run(home, plugin, WORKTREE_ADD, OMNI_HOME=str(registry))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "omni_worktrees" in json.loads(result.stdout)["reason"]


@pytest.mark.parametrize(
    "extra",
    [{"OMNI_HOME": "relative/registry"}, {"ONEX_STATE_DIR": "relative/state"}],
)
def test_a_relative_explicit_setting_is_still_refused(
    plugin: Path, home: Path, extra: dict[str, str]
) -> None:
    result = _run(home, plugin, "ls", **extra)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "refusal log path is unresolved" in result.stdout


@pytest.mark.parametrize("xdg", [None, "/custom/xdg"])
def test_onex_paths_and_the_entrypoint_agree(
    plugin: Path, home: Path, xdg: str | None
) -> None:
    extra = {"XDG_STATE_HOME": xdg} if xdg else {}
    out = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{plugin}/hooks/scripts/onex-paths.sh" && '
            'printf "%s %s" "$ONEX_STATE_DIR" "$ONEX_STATE_DIR_DEFAULTED"',
        ],
        env=_env(home, plugin, **extra),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    expected = (xdg or f"{home}/.local/state") + "/omniclaude"
    assert out == f"{expected} 1"


def test_missing_python3_fails_with_one_line_naming_it(
    plugin: Path, home: Path, tmp_path: Path
) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in _TOOLS:
        found = shutil.which(tool)
        if found:
            (bindir / tool).symlink_to(found)
    result = subprocess.run(
        [
            str(bindir / "bash"),
            "-c",
            f'PLUGIN_ROOT="{plugin}"; HOOKS_DIR="{plugin}/hooks"; '
            f'source "{plugin}/hooks/scripts/common.sh"',
        ],
        env={**_env(home, plugin), "PATH": str(bindir)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    lines = [ln for ln in result.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1, result.stderr
    assert "python3" in lines[0]
