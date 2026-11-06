# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A read-only ``git status`` in the plugin never takes the clone's index lock (OMN-22779).

Plain ``git status`` refreshes the index and holds ``.git/index.lock`` while it
does. A git killed inside that window strands a zero-byte lock that blocks the
canonical-clone sync for hours (666 ``index.lock present`` refusals for one
clone, 2026-10-19 to 2026-11-06). ``--no-optional-locks`` makes the read take no
lock at all.

Each test puts a recording ``git`` first on PATH, drives one plugin call site
against a real repository, and asserts that every ``status`` it ran carried
``--no-optional-locks`` before the subcommand, or ran with ``GIT_OPTIONAL_LOCKS=0``
(git reads the two the same way). A test also asserts that at least
one ``status`` ran, so a call site that stops reading status cannot pass by
running nothing.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
from types import ModuleType

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_HOOKS = _REPO_ROOT / "plugins" / "onex" / "hooks"
_ENGINE_PATH = _HOOKS / "lib" / "canonical_clone_sync.py"
_READBACK_PATH = _HOOKS / "lib" / "plugin_deploy_readback.py"
_STATUSLINE = _HOOKS / "scripts" / "statusline.sh"
_SEP = "\x1f"


def _load(name: str, path: pathlib.Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class GitRecorder:
    """A ``git`` first on PATH that logs its argv and runs the real git."""

    def __init__(self, tmp: pathlib.Path, real_git: str) -> None:
        self.log = tmp / "git-argv.log"
        bin_dir = tmp / "shim-bin"
        bin_dir.mkdir()
        shim = bin_dir / "git"
        shim.write_text(
            "#!/bin/sh\n"
            f'printf "optlocks=%s{_SEP}" "$GIT_OPTIONAL_LOCKS" >> "{self.log}"\n'
            f'for a in "$@"; do printf "%s{_SEP}" "$a" >> "{self.log}"; done\n'
            f'printf "\\n" >> "{self.log}"\n'
            f'exec "{real_git}" "$@"\n'
        )
        shim.chmod(0o755)
        self.bin_dir = bin_dir

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [
            line.rstrip(_SEP).split(_SEP)
            for line in self.log.read_text().splitlines()
            if line
        ]

    def status_calls(self) -> list[list[str]]:
        return [c for c in self.calls() if "status" in c[1:]]

    def assert_status_reads_take_no_lock(self) -> None:
        status_calls = self.status_calls()
        assert status_calls, f"no git status ran; saw {self.calls()}"
        for call in status_calls:
            before_status = call[1 : call.index("status", 1)]
            by_flag = "--no-optional-locks" in before_status
            by_env = call[0] == "optlocks=0"
            assert by_flag or by_env, f"git status would hold the index lock: {call}"


@pytest.fixture
def recorder(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> GitRecorder:
    real_git = shutil.which("git")
    assert real_git is not None
    rec = GitRecorder(tmp_path, real_git)
    monkeypatch.setenv("PATH", f"{rec.bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("GIT_OPTIONAL_LOCKS", raising=False)
    return rec


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    clone = tmp_path / "clone"
    clone.mkdir()
    real_git = shutil.which("git")
    assert real_git is not None
    env = scrub_git_location_env(os.environ)
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t@example.invalid"],
        ["config", "user.name", "t"],
    ):
        subprocess.run([real_git, *args], cwd=clone, env=env, check=True)
    (clone / "f.txt").write_text("one\n")
    subprocess.run([real_git, "add", "f.txt"], cwd=clone, env=env, check=True)
    subprocess.run(
        [real_git, "commit", "-q", "-m", "seed"], cwd=clone, env=env, check=True
    )
    return clone


def test_the_sync_engine_reads_dirty_entries_without_the_index_lock(
    recorder: GitRecorder, repo: pathlib.Path
) -> None:
    engine = _load("canonical_clone_sync", _ENGINE_PATH)
    (repo / "f.txt").write_text("two\n")

    dirty = engine._dirty_entries(repo)

    assert dirty == ([], ["f.txt"])
    recorder.assert_status_reads_take_no_lock()


def test_the_deploy_readback_reads_dirty_count_without_the_index_lock(
    recorder: GitRecorder, repo: pathlib.Path
) -> None:
    readback = _load("plugin_deploy_readback", _READBACK_PATH)
    (repo / "f.txt").write_text("two\n")

    state = readback.read_git_state(repo, fetch=False)

    assert state.dirty_files == 1
    recorder.assert_status_reads_take_no_lock()


@pytest.mark.skipif(shutil.which("jq") is None, reason="statusline.sh needs jq")
def test_the_statusline_reads_dirty_without_the_index_lock(
    recorder: GitRecorder, repo: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    (repo / "f.txt").write_text("two\n")
    payload = f'{{"workspace": {{"project_dir": "{repo}"}}}}'
    env = scrub_git_location_env(os.environ)
    env["HOME"] = str(tmp_path)
    env["OMNICLAUDE_MODE"] = "full"  # lite mode exits before any git call

    # The exit code is not asserted: the script's last section can refuse for a
    # missing database host, long after the git reads this test records.
    subprocess.run(
        ["bash", str(_STATUSLINE)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )

    recorder.assert_status_reads_take_no_lock()
