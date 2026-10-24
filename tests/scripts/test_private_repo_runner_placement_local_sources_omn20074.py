# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20074: the runner-placement hook judges a lane's commit from local sources.

A lane's GitHub reads are refused, so every live read the hook makes fails
there. OMN-20141 gave visibility and the variable scopes a dated snapshot, but
only through ``PRRP_VARIABLES_SNAPSHOT``, which a lane may not have exported,
and a ``uses:`` job's called workflow still had only the live contents read: a
private repository that calls one shared reusable could not commit a workflow
change from any lane. These tests run the hook as pre-commit does (the script
as a subprocess) under a stub ``gh`` that refuses every read, with ``HOME`` and
``OMNI_HOME`` pointed into the test's own directory.

* AC1: the snapshot the publisher puts at ``~/.omninode/prrp/`` answers when no
  path is configured, and a stale one there is still exit 2;
* AC2: a called workflow pinned to a full sha or a tag present in the clone's
  refs/tags is read from a clone of the called repository holding that commit
  on an origin branch, and a hosted placement there is still a finding;
* AC3: a commit on no origin branch, a clone of another repository, a mutable
  branch ref, an absent tag and a run inside GitHub Actions answer nothing
  locally: exit 2.

The test ids carry the names the contract's falsifiers select with ``-k``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

from omnibase_core.validators.no_unguarded_git_subprocess import scrub_git_location_env

if TYPE_CHECKING:
    import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "private_repo_runner_placement_gate.py"

SLUG = "OmniNode-ai/fixture"
CALLED = "OmniNode-ai/fixture-called"
REUSABLE = ".github/workflows/shared-reusable.yml"
FLEET_JOB = (
    "on:\n  workflow_call: {}\njobs:\n"
    "  check:\n    runs-on: [self-hosted, omnibase-ci]\n"
    "    steps:\n      - run: true\n"
)
HOSTED_JOB = (
    "on:\n  workflow_call: {}\njobs:\n"
    "  check:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: true\n"
)
LITERAL_FLEET_CALLER = (
    "name: CI\non:\n  pull_request: {}\njobs:\n"
    "  build:\n    runs-on: [self-hosted, omnibase-ci]\n"
    "    steps:\n      - run: true\n"
)
LANE_REFUSAL = "REFUSED lane=prrp-fixture raw GitHub read budget=0"

STUB_GH = """#!/bin/sh
# A lane's gh: every read is refused.
echo "$*" >> "$STUB_GH_LOG"
echo "$STUB_GH_LANE_REFUSAL" >&2
exit 1
"""


def _module() -> ModuleType:
    if "placement_gate" in sys.modules:
        return sys.modules["placement_gate"]
    spec = importlib.util.spec_from_file_location("placement_gate", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["placement_gate"] = module
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            **scrub_git_location_env(os.environ),
            "GIT_AUTHOR_NAME": "fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        },
    ).stdout.strip()


def _called_clone(
    root: Path,
    body: str,
    *,
    origin: str = CALLED,
    published: bool = True,
    tag: str | None = None,
) -> str:
    """A clone of the called repository under `root`; returns the pinned sha."""
    clone = root / CALLED.split("/", 1)[1]
    (clone / REUSABLE).parent.mkdir(parents=True)
    (clone / REUSABLE).write_text(body, encoding="utf-8")
    _git(clone, "init", "-q")
    _git(clone, "remote", "add", "origin", f"git@github.com:{origin}.git")
    _git(clone, "add", REUSABLE)
    _git(clone, "commit", "-q", "-m", "reusable")
    sha = _git(clone, "rev-parse", "HEAD")
    if tag is not None:
        _git(clone, "tag", tag, sha)
    if published:
        _git(clone, "update-ref", "refs/remotes/origin/dev", sha)
    # The working tree moves on, so a read of the working file is not the pin.
    (clone / REUSABLE).write_text(HOSTED_JOB if body == FLEET_JOB else FLEET_JOB)
    return sha


def _caller(tmp_path: Path, ref: str) -> Path:
    workflows = tmp_path / "tree" / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(
        "name: CI\non:\n  pull_request: {}\njobs:\n"
        f"  shared:\n    uses: {CALLED}/{REUSABLE}@{ref}\n",
        encoding="utf-8",
    )
    return tmp_path / "tree"


def _literal_tree(tmp_path: Path) -> Path:
    workflows = tmp_path / "tree" / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(LITERAL_FLEET_CALLER, encoding="utf-8")
    return tmp_path / "tree"


def _published_snapshot(home: Path, *, age: timedelta = timedelta(hours=1)) -> Path:
    path = home / ".omninode" / "prrp" / "variables-snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "captured_at": (datetime.now(UTC) - age).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "visibility": {SLUG: "private"},
                "scopes": {"org:OmniNode-ai": {}, f"repo:{SLUG}": {}},
            }
        ),
        encoding="utf-8",
    )
    return path


def _run_hook(
    tmp_path: Path,
    tree: Path,
    *,
    actions: bool = False,
    git_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """The hook as pre-commit runs it inside a lane: no PRRP_VARIABLES_SNAPSHOT."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(STUB_GH, encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = {
        key: value
        for key, value in scrub_git_location_env(os.environ).items()
        if key
        not in {
            "GITHUB_ACTIONS",
            "PRRP_VARIABLES_SNAPSHOT",
            "GITHUB_REPOSITORY",
            "OMNI_HOME",
        }
    }
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["HOME"] = str(tmp_path / "home")
    env["OMNI_HOME"] = str(tmp_path / "registry")
    env["STUB_GH_LOG"] = str(tmp_path / "gh-calls.log")
    env["STUB_GH_LANE_REFUSAL"] = LANE_REFUSAL
    env["GH_TOKEN"] = "stub-session-token"
    env["ONEX_LEDGER_PATH"] = ""
    if actions:
        env["GITHUB_ACTIONS"] = "true"
    if git_dir is not None:
        env["GIT_DIR"] = str(git_dir)  # what git exports into a hook
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tree), "--repo", SLUG],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=tmp_path,
    )


# --- AC1 ---------------------------------------------------------------------


def test_published_snapshot_answers_without_configuration(tmp_path: Path) -> None:
    """No PRRP_VARIABLES_SNAPSHOT: the publisher's copy under HOME answers."""
    path = _published_snapshot(tmp_path / "home")
    result = _run_hook(tmp_path, _literal_tree(tmp_path))
    assert result.returncode == 0, result.stderr
    assert f"visibility of {SLUG} is private, read from snapshot {path}" in (
        result.stderr
    )
    calls = (tmp_path / "gh-calls.log").read_text(encoding="utf-8")
    assert f"api repos/{SLUG}" in calls, "the live read must be tried first"


def test_published_snapshot_stale_still_refuses(tmp_path: Path) -> None:
    _published_snapshot(tmp_path / "home", age=timedelta(hours=25))
    result = _run_hook(tmp_path, _literal_tree(tmp_path))
    assert result.returncode == 2
    assert "stale" in result.stderr
    assert "THE GATE DID NOT RUN" in result.stderr


def test_published_snapshot_absent_keeps_the_refusal(tmp_path: Path) -> None:
    result = _run_hook(tmp_path, _literal_tree(tmp_path))
    assert result.returncode == 2
    assert f"Missing input: the visibility of {SLUG}" in result.stderr


# --- AC2 ---------------------------------------------------------------------


def test_local_clone_answers_a_sha_pinned_called_workflow(tmp_path: Path) -> None:
    _published_snapshot(tmp_path / "home")
    sha = _called_clone(tmp_path / "registry", FLEET_JOB)
    result = _run_hook(tmp_path, _caller(tmp_path, sha))
    assert result.returncode == 0, result.stderr
    assert f"called workflow {CALLED}/{REUSABLE}@{sha} read from the local clone" in (
        result.stderr
    )
    calls = (tmp_path / "gh-calls.log").read_text(encoding="utf-8")
    assert f"repos/{CALLED}/contents/{REUSABLE}" in calls, "live is tried first"


def test_local_clone_answers_under_the_hook_git_dir(tmp_path: Path) -> None:
    """GIT_DIR names the committing repository in a hook; the clone is still read."""
    _published_snapshot(tmp_path / "home")
    sha = _called_clone(tmp_path / "registry", FLEET_JOB)
    committing = tmp_path / "committing"
    committing.mkdir()
    _git(committing, "init", "-q")
    result = _run_hook(tmp_path, _caller(tmp_path, sha), git_dir=committing / ".git")
    assert result.returncode == 0, result.stderr
    assert "read from the local clone" in result.stderr


def test_local_clone_hosted_called_workflow_still_refused(tmp_path: Path) -> None:
    """The pinned commit is judged, not the clone's working tree (which is fleet)."""
    _published_snapshot(tmp_path / "home")
    sha = _called_clone(tmp_path / "registry", HOSTED_JOB)
    result = _run_hook(tmp_path, _caller(tmp_path, sha))
    assert result.returncode == 1, result.stderr
    assert "ubuntu-latest" in result.stderr


def test_local_clone_answers_a_tag_pinned_called_workflow(tmp_path: Path) -> None:
    _published_snapshot(tmp_path / "home")
    tag = "dev-20261024032229-7063070cf578"
    sha = _called_clone(tmp_path / "registry", FLEET_JOB, tag=tag)
    result = _run_hook(tmp_path, _caller(tmp_path, tag))
    assert result.returncode == 0, result.stderr
    assert "read from the local clone" in result.stderr
    assert f"at its pinned commit {sha}" in result.stderr
    calls = (tmp_path / "gh-calls.log").read_text(encoding="utf-8")
    assert f"repos/{CALLED}/commits/{tag}" not in calls


def test_local_clone_tag_pin_hosted_still_refused(tmp_path: Path) -> None:
    """The tag's commit is judged, not the clone's working tree (which is fleet)."""
    _published_snapshot(tmp_path / "home")
    tag = "dev-20261024032229-7063070cf578"
    sha = _called_clone(tmp_path / "registry", HOSTED_JOB, tag=tag)
    result = _run_hook(tmp_path, _caller(tmp_path, tag))
    assert result.returncode == 1, result.stderr
    assert "ubuntu-latest" in result.stderr
    assert f"(ref {tag} -> {sha})" in result.stderr


# --- AC3 ---------------------------------------------------------------------


def _assert_not_run(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 2, result.stdout + result.stderr
    assert "THE GATE DID NOT RUN" in result.stderr
    assert "read from the local clone" not in result.stderr


def test_local_clone_refuses_a_commit_on_no_origin_branch(tmp_path: Path) -> None:
    _published_snapshot(tmp_path / "home")
    sha = _called_clone(tmp_path / "registry", FLEET_JOB, published=False)
    result = _run_hook(tmp_path, _caller(tmp_path, sha))
    _assert_not_run(result)
    assert "whose origin branches hold that commit" in result.stderr


def test_local_clone_refuses_a_clone_of_another_repository(tmp_path: Path) -> None:
    _published_snapshot(tmp_path / "home")
    sha = _called_clone(
        tmp_path / "registry", FLEET_JOB, origin="OmniNode-ai/someone-else"
    )
    _assert_not_run(_run_hook(tmp_path, _caller(tmp_path, sha)))


def test_local_clone_refuses_a_mutable_ref(tmp_path: Path) -> None:
    _published_snapshot(tmp_path / "home")
    _called_clone(tmp_path / "registry", FLEET_JOB)
    _assert_not_run(_run_hook(tmp_path, _caller(tmp_path, "dev")))


def test_local_clone_refuses_a_tag_absent_from_the_clone(tmp_path: Path) -> None:
    _published_snapshot(tmp_path / "home")
    _called_clone(tmp_path / "registry", FLEET_JOB)
    _assert_not_run(
        _run_hook(tmp_path, _caller(tmp_path, "dev-20261024032229-7063070cf578"))
    )


def test_local_clone_refuses_a_tag_on_no_origin_branch(tmp_path: Path) -> None:
    _published_snapshot(tmp_path / "home")
    tag = "dev-20261024032229-7063070cf578"
    _called_clone(tmp_path / "registry", FLEET_JOB, published=False, tag=tag)
    _assert_not_run(_run_hook(tmp_path, _caller(tmp_path, tag)))


def test_local_clone_refuses_a_branch_named_like_the_tag_pin(tmp_path: Path) -> None:
    _published_snapshot(tmp_path / "home")
    pin = "dev-20261024032229-7063070cf578"
    root = tmp_path / "registry"
    sha = _called_clone(root, FLEET_JOB)
    clone = root / CALLED.split("/", 1)[1]
    _git(clone, "update-ref", f"refs/heads/{pin}", sha)
    _git(clone, "update-ref", f"refs/remotes/origin/{pin}", sha)
    _assert_not_run(_run_hook(tmp_path, _caller(tmp_path, pin)))


def test_local_clone_tag_pin_never_read_inside_github_actions(tmp_path: Path) -> None:
    _published_snapshot(tmp_path / "home")
    tag = "dev-20261024032229-7063070cf578"
    _called_clone(tmp_path / "registry", FLEET_JOB, tag=tag)
    _assert_not_run(_run_hook(tmp_path, _caller(tmp_path, tag), actions=True))


def test_local_clone_is_never_read_inside_github_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actions resolves live: neither the published snapshot nor a clone answers."""
    _published_snapshot(tmp_path / "home")
    sha = _called_clone(tmp_path / "registry", FLEET_JOB)
    result = _run_hook(tmp_path, _caller(tmp_path, sha), actions=True)
    _assert_not_run(result)
    assert "read from snapshot" not in result.stderr

    gate = _module()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OMNI_HOME", str(tmp_path / "registry"))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert gate.local_clone_roots(tmp_path / "registry") == []
    assert gate.published_snapshot_path() is None
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert gate.local_clone_roots(tmp_path / "tree") == [
        (tmp_path / "registry").resolve()
    ]
    assert gate.published_snapshot_path() == (
        tmp_path / "home" / ".omninode" / "prrp" / "variables-snapshot.json"
    )


def test_the_ci_step_and_the_paired_hook_collect_this_file() -> None:
    name = Path(__file__).name
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    hooks = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    step = next(
        line
        for line in ci.splitlines()
        if "test_private_repo_runner_placement_gate.py" in line
    )
    entry = next(
        line
        for line in hooks.splitlines()
        if "test_private_repo_runner_placement_gate.py" in line
    )
    assert name in step
    assert name in entry
