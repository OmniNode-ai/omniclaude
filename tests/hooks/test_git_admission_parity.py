# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Compare the canonical handler with the pre-conversion implementation."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import scrub_git_location_env

from omniclaude.nodes.node_git_effect.handlers import handler_git_admission as guard
from omniclaude.nodes.node_git_effect.models.model_git_admission import (
    ModelGitAdmissionRequest,
)

BASE = "966d61ce9"
ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.unit


@pytest.fixture
def old_guard(tmp_path: Path):
    folder = tmp_path / "old" / "lib"
    folder.mkdir(parents=True)
    for name in ("shared_tree_git_guard.py", "shell_words.py"):
        result = subprocess.run(
            ["git", "show", f"{BASE}:plugins/onex/hooks/lib/{name}"],
            cwd=ROOT,
            env=scrub_git_location_env(os.environ),
            check=True,
            capture_output=True,
        )
        (folder / name).write_bytes(result.stdout)
    config = folder.parent / "config"
    config.mkdir()
    result = subprocess.run(
        [
            "git",
            "show",
            f"{BASE}:plugins/onex/hooks/config/shared_tree_git_guard_policy.json",
        ],
        cwd=ROOT,
        env=scrub_git_location_env(os.environ),
        check=True,
        capture_output=True,
    )
    (config / "shared_tree_git_guard_policy.json").write_bytes(result.stdout)
    spec = importlib.util.spec_from_file_location(
        "parity_old_git_guard", folder / "shared_tree_git_guard.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "command",
    [
        "git reset --hard origin/main",
        "git clean -fd",
        "git checkout -b feature",
        "git switch main",
        "git rebase origin/main",
        "git merge origin/main",
        "git merge --ff-only origin/main",
        "git status",
        "git diff",
        "git push origin feature",
        "git push --force origin main",
        "git checkout -- docs/tracking/ROLLING_WORK_LEDGER.md",
        "git branch -d main",
        "git branch feature",
        "echo 'git reset --hard'",
        "# git reset\ngit status",
        "git reset 'unterminated",
        "printf 'unterminated",
        "git fetch origin",
        "git ls-remote https://github.com/OmniNode-ai/omniclaude.git",
    ],
)
def test_verdict_parity(
    old_guard, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
):
    root = tmp_path / "registry"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    monkeypatch.setenv("OMNI_HOME", str(root))
    monkeypatch.delenv("ONEX_LANE", raising=False)
    before = old_guard.evaluate_bash_command(
        command, old_guard.load_policy(), root, root, ()
    )
    request = ModelGitAdmissionRequest(
        raw_payload=json.dumps({"tool_input": {"command": command}, "cwd": str(root)})
    )
    after = guard.HandlerGitAdmission().handle(request)
    assert (after.blocked, after.reason, tuple(after.notes)) == (
        before.blocked,
        before.reason,
        before.notes,
    )


@pytest.mark.parametrize(
    "raw", ["broken JSON", "[]", "{}", '{"tool_input":{"command":"echo hello"}}']
)
def test_payload_parity(old_guard, raw: str, monkeypatch: pytest.MonkeyPatch, capsys):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    code = old_guard.main([])
    output = capsys.readouterr().out
    result = guard.HandlerGitAdmission().handle(
        ModelGitAdmissionRequest(raw_payload=raw)
    )
    assert (2 if result.blocked else 0) == code
    if result.blocked:
        assert result.reason == json.loads(output)["reason"]


@pytest.mark.parametrize("dirty", [False, True])
@pytest.mark.parametrize(
    "command",
    [
        "git restore file.txt",
        "git checkout HEAD -- file.txt",
        "git restore --staged file.txt",
    ],
)
def test_restore_parity(
    old_guard,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dirty: bool,
    command: str,
):
    from tests.hooks.test_dirty_path_restore_guard import _git, _init

    fleet = tmp_path / "fleet"
    repo = fleet / "repo"
    _init(repo)
    (repo / "file.txt").write_text("committed\n")
    _git("add", "file.txt", cwd=repo)
    _git("commit", "-qm", "fixture", cwd=repo)
    if dirty:
        (repo / "file.txt").write_text("uncommitted\n")
    monkeypatch.setenv("OMNI_HOME", str(fleet))
    before = old_guard.evaluate_bash_command(
        command, old_guard.load_policy(), repo, fleet, ()
    )
    result = guard.HandlerGitAdmission().handle(
        ModelGitAdmissionRequest(
            raw_payload=json.dumps(
                {"tool_input": {"command": command}, "cwd": str(repo)}
            )
        )
    )
    assert (result.blocked, result.reason, result.notes) == (
        before.blocked,
        before.reason,
        before.notes,
    )
    assert (repo / "file.txt").read_text() == (
        "uncommitted\n" if dirty else "committed\n"
    )


@pytest.mark.parametrize(
    "command",
    [
        "git fetch origin",
        "git pull --ff-only origin main",
        "git ls-remote origin",
        "git remote update origin",
    ],
)
def test_lane_fetch_parity(
    old_guard, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
):
    from tests.hooks.test_dirty_path_restore_guard import _git, _init

    repo = tmp_path / "repo"
    _init(repo)
    _git(
        "remote",
        "add",
        "origin",
        "https://github.com/OmniNode-ai/omniclaude.git",
        cwd=repo,
    )
    monkeypatch.setenv("ONEX_LANE", "parity-lane")
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    before = old_guard.evaluate_bash_command(
        command, old_guard.load_policy(), repo, None, ()
    )
    result = guard.HandlerGitAdmission().handle(
        ModelGitAdmissionRequest(
            raw_payload=json.dumps(
                {"tool_input": {"command": command}, "cwd": str(repo)}
            ),
            clone_sync_engine=str(old_guard.CLONE_SYNC_ENGINE),
        )
    )
    assert (result.blocked, result.reason, result.notes) == (
        before.blocked,
        before.reason,
        before.notes,
    )
