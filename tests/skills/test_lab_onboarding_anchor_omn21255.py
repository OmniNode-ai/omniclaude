# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21255: onboarding installs the code set of one omnibase_infra commit.

The script names INFRA_ANCHOR. Phase 2 checks omnibase_infra out there, takes every
pinned sibling from that commit's sibling-pins.yaml and every unpinned repo from
origin's default branch at the anchor's time, and writes the workspace runtime
config as one commit that is a function of the anchor. Moving ``dev`` afterwards
changes nothing a run installs.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "_bin"
    / "lab-onboarding.sh"
)
HANDLER = (
    Path(__file__).resolve().parents[2]
    / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator"
    / "handler_onboarding_preflight.sh"
)
REPOS = ("omnibase_infra", "omnimarket", "omnibase_core", "omnibase_spi")
PINNED = ("omnimarket", "omnibase_core")
CONFIG_REL = "config/onex/runtime/runtime_config.yaml"

T_SIBLING_1 = 1_000_000_000
T_ANCHOR = 1_000_002_000
T_SIBLING_2 = 1_000_003_000
T_INFRA_2 = 1_000_004_000
T_MOVED = 1_000_009_000

pytestmark = pytest.mark.unit

# OMN-18434: git's hook-exported location vars override cwd and -C.
_GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CEILING_DIRECTORIES",
    "GIT_NAMESPACE",
)


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if k not in _GIT_LOCATION_VARS}


def _git(
    repo: Path, *args: str, stdin: str | None = None, when: int | None = None
) -> str:
    dated = {}
    if when is not None:
        dated = {
            "GIT_AUTHOR_DATE": f"{when} +0000",
            "GIT_COMMITTER_DATE": f"{when} +0000",
        }
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin,
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
        env={
            **scrub_git_location_env(os.environ),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            **dated,
        },
    )
    return result.stdout.strip()


def _commit(
    repo: Path, content: str, pins: dict[str, str] | None, parent: str | None, when: int
) -> str:
    blob = _git(repo, "hash-object", "-w", "--stdin", stdin=content)
    entries = f"100644 blob {blob}\tREADME\n"
    if pins is not None:
        text = "pins:\n" + "".join(f"  {k}: {v}\n" for k, v in pins.items())
        pin_blob = _git(repo, "hash-object", "-w", "--stdin", stdin=text)
        github = _git(
            repo, "mktree", stdin=f"100644 blob {pin_blob}\tsibling-pins.yaml\n"
        )
        entries += f"040000 tree {github}\t.github\n"
    tree = _git(repo, "mktree", stdin=entries)
    parents = ["-p", parent] if parent else []
    return _git(repo, "commit-tree", tree, *parents, stdin=content, when=when)


class Harness:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.workspace = root / "workspace"
        self.remotes = root / "remotes"
        self.run_dir = root / "run"
        for directory in (self.home, self.workspace, self.remotes, self.run_dir):
            directory.mkdir()
        self.fragment = root / "fragment.sh"
        # Source only phase 2; never execute bare main.
        extracted = subprocess.run(
            [
                "awk",
                r"""
                /^# Phase 2: workspace/ { phase = 1 }
                /^# Phase 3:/ { phase = 0 }
                phase { print }
                """,
                str(SCRIPT),
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        # The anchor functions live in the node's bash handler, which the script
        # sources whole; here only that section is sourced, as it has no side effects.
        anchor = subprocess.run(
            [
                "awk",
                "/^# The anchor: which commit/ { on = 1 } on { print }",
                str(HANDLER),
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        assert "anchored_commit()" in anchor.stdout
        self.fragment.write_text(extracted.stdout + anchor.stdout)
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "WORKSPACE": str(self.workspace),
            "GITHUB_ORG_URL": str(self.remotes),
            "REPOS": " ".join(REPOS),
            "RUN_DIR": str(self.run_dir),
            "LOG": str(self.run_dir / "log"),
            "STATUS": str(self.run_dir / "status"),
            "SHELL": "/bin/zsh",
            "STAMP": "20261022-120000",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        self.tips: dict[str, str] = {}
        self.expected: dict[str, str] = {}
        self.anchor = ""

    def run(self, commands: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "/bin/bash",
                "-c",
                """
                set -uo pipefail
                say() { printf '%s\n' "$*"; }
                retry() { shift; "$@"; }
                step() { FAILED_STEP="$1"; shift; "$@"; }
                phase_start() { :; }
                phase_pass() { printf 'PASS %s\n' "$*"; }
                phase_fail() { printf 'FAIL %s: %s\n' "$FAILED_STEP" "$*"; exit 1; }
                mark_done() { :; }
                is_done() { return 1; }
                brew_bin() { printf '/fixture/brew\n'; }
                FAILED_STEP=""
                source "$1"
                """
                + commands,
                "harness",
                str(self.fragment),
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def make_remotes(self) -> None:
        """Siblings at s1 then s2; infra at a1 (pins s1, the anchor) then a2."""
        siblings: dict[str, tuple[str, str]] = {}
        for name in REPOS[1:]:
            repo = self._bare(name)
            s1 = _commit(repo, f"{name} s1\n", None, None, T_SIBLING_1)
            s2 = _commit(repo, f"{name} s2\n", None, s1, T_SIBLING_2)
            self._advance(name, s2)
            siblings[name] = (s1, s2)
        repo = self._bare("omnibase_infra")
        a1 = _commit(repo, "a1\n", {p: siblings[p][0] for p in PINNED}, None, T_ANCHOR)
        a2 = _commit(repo, "a2\n", {p: siblings[p][1] for p in PINNED}, a1, T_INFRA_2)
        self._advance("omnibase_infra", a2)
        self.anchor = a1
        self.env["ONBOARD_TEST_INFRA_ANCHOR"] = a1
        self.expected = {"omnibase_infra": a1} | {n: s[0] for n, s in siblings.items()}

    def move_dev(self) -> None:
        """Every remote's dev gains a commit; infra's pins name the new commits."""
        for name in REPOS[1:]:
            tip = _commit(
                self._repo(name), f"{name} moved\n", None, self.tips[name], T_MOVED
            )
            self._advance(name, tip)
        tip = _commit(
            self._repo("omnibase_infra"),
            "moved\n",
            {p: self.tips[p] for p in PINNED},
            self.tips["omnibase_infra"],
            T_MOVED,
        )
        self._advance("omnibase_infra", tip)

    def use_workspace(self, name: str) -> Path:
        self.workspace = self.root / name
        self.workspace.mkdir()
        self.env["WORKSPACE"] = str(self.workspace)
        return self.workspace

    def heads(self) -> dict[str, str]:
        return {r: _git(self.workspace / r, "rev-parse", "HEAD") for r in REPOS}

    def _repo(self, name: str) -> Path:
        return self.remotes / f"{name}.git"

    def _bare(self, name: str) -> Path:
        repo = self._repo(name)
        repo.mkdir()
        _git(repo, "init", "--bare", "--quiet")
        return repo

    def _advance(self, name: str, sha: str) -> None:
        _git(self._repo(name), "update-ref", "refs/heads/dev", sha)
        _git(self._repo(name), "symbolic-ref", "HEAD", "refs/heads/dev")
        self.tips[name] = sha


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    h = Harness(tmp_path)
    h.make_remotes()
    return h


def _passed(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def test_script_names_one_infra_anchor_commit() -> None:
    anchors = re.findall(
        r'^INFRA_ANCHOR="\$\{ONBOARD_TEST_INFRA_ANCHOR:-([0-9a-f]{40})\}"$',
        SCRIPT.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert len(anchors) == 1, anchors


def test_phase2_checks_infra_out_at_the_anchor_not_dev(harness: Harness) -> None:
    result = harness.run("phase2")
    _passed(result)
    assert harness.heads() == harness.expected
    assert harness.tips["omnibase_infra"] != harness.anchor
    for repo in REPOS:
        assert _git(harness.workspace / repo, "rev-parse", "--abbrev-ref", "HEAD") == (
            "HEAD"
        )
    assert f"omnibase_infra: anchor {harness.anchor[:12]}" in result.stdout
    _passed(harness.run("phase2_verified"))


def _config_commit(workspace: Path) -> str:
    return _git(workspace / ".onex" / "workspace-config", "rev-parse", "origin/main")


def test_same_commits_install_after_dev_moves(harness: Harness) -> None:
    _passed(harness.run("phase2"))
    first = harness.heads()
    config = _config_commit(harness.workspace)
    harness.move_dev()
    assert all(harness.tips[r] != first[r] for r in REPOS)
    _passed(harness.run("phase2"))
    assert harness.heads() == first
    assert _config_commit(harness.workspace) == config
    harness.use_workspace("workspace-b")
    _passed(harness.run("phase2"))
    assert harness.heads() == first == harness.expected
    assert _config_commit(harness.workspace) == config


def test_workspace_runtime_config_is_materialised_from_the_anchor(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The config commit is built from the anchor alone, so its sha is too."""
    from omnibase_infra.handlers.handler_workspace_runtime_config_materializer import (
        HandlerWorkspaceRuntimeConfigMaterializer,
    )

    _passed(harness.run("phase2"))
    root = harness.workspace / ".onex" / "workspace-config"
    config = _git(root, "show", f"origin/main:{CONFIG_REL}").splitlines()
    assert f"# Anchor: omnibase_infra {harness.anchor}" in config
    # A commit's sha hashes exactly these fields: with no parent, a fixed
    # identity, the anchor's date and a message naming it, nothing else varies.
    header, _, message = _git(root, "cat-file", "commit", "origin/main").partition(
        "\n\n"
    )
    fields = [line.split(" ", 1) for line in header.splitlines()]
    assert [k for k, _ in fields] == ["tree", "author", "committer"]
    identity = f"omninode-dev-setup <dev-setup@omninode.invalid> {T_ANCHOR} +0000"
    assert dict(fields)["author"] == identity
    assert dict(fields)["committer"] == identity
    assert message == (
        f"workspace runtime config for omnibase_infra {harness.anchor} "
        "(omninode-dev-setup)"
    )
    assert _git(root, "rev-parse", "main") == _git(root, "rev-parse", "origin/main")
    monkeypatch.setenv("ONEX_WORKSPACE_CONFIG_ROOT", str(root))
    outcome = HandlerWorkspaceRuntimeConfigMaterializer().materialize(harness.workspace)
    assert outcome.ok, outcome.detail
    assert outcome.sha == _config_commit(harness.workspace)


def test_guide_says_what_the_anchor_is_and_how_fixes_arrive() -> None:
    guide = (SCRIPT.parents[2] / "ONBOARDING.md").read_text(encoding="utf-8")
    section = guide.split("### What the script installs: its anchor\n", 1)
    assert len(section) == 2, "ONBOARDING.md has no anchor section"
    body = section[1].split("\n### ", 1)[0]
    assert "`INFRA_ANCHOR`" in body
    assert "omnibase_infra" in body
    assert "sibling-pins.yaml" in body
    assert "**A fix reaches you through a new email, never through `dev`.**" in body
    assert "a new email pins that\nscript by commit and sha256" in body
