# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21343: re-running onboarding with a script that names a newer anchor.

A Mac onboarded at anchor A runs a script naming anchor B. Phase 2 moves every
clone to B's commits; phase 4 rebuilds the running local stack from them, with
``make up-local`` and never a volume removal. The developer's keys and model
order (``~/.omninode/delegation/delegation.sqlite``), the delegation rows the
dashboard reads (the same store, and the stack's volumes) and the saved choices
are left byte for byte as they were. A re-run at the same anchor rebuilds
nothing.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "plugins/onex/skills/_bin/lab-onboarding.sh"
HANDLER = (
    REPO
    / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator"
    / "handler_onboarding_preflight.sh"
)
GUIDE = REPO / "plugins/onex/ONBOARDING.md"
REPOS = ("omnibase_infra", "omnimarket", "omnibase_core", "omnibase_spi")
PINNED = ("omnimarket", "omnibase_core")

T_SIBLING_1 = 1_000_000_000
T_ANCHOR_A = 1_000_002_000
T_SIBLING_2 = 1_000_003_000
T_ANCHOR_B = 1_000_004_000


def _git(repo: Path, *args: str, stdin: str | None = None, when: int = 0) -> str:
    dated = (
        {"GIT_AUTHOR_DATE": f"{when} +0000", "GIT_COMMITTER_DATE": f"{when} +0000"}
        if when
        else {}
    )
    return subprocess.run(
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
    ).stdout.strip()


def _commit(
    repo: Path, text: str, pins: dict[str, str] | None, parent: str | None, when: int
) -> str:
    entries = f"100644 blob {_git(repo, 'hash-object', '-w', '--stdin', stdin=text)}\tREADME\n"
    if pins is not None:
        body = "pins:\n" + "".join(f"  {k}: {v}\n" for k, v in pins.items())
        blob = _git(repo, "hash-object", "-w", "--stdin", stdin=body)
        github = _git(repo, "mktree", stdin=f"100644 blob {blob}\tsibling-pins.yaml\n")
        entries += f"040000 tree {github}\t.github\n"
    tree = _git(repo, "mktree", stdin=entries)
    parents = ["-p", parent] if parent else []
    return _git(repo, "commit-tree", tree, *parents, stdin=text, when=when)


def _section(path: Path, start: str, stop: str | None) -> str:
    lines, on = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(start):
            on = True
        elif stop is not None and line.startswith(stop):
            on = False
        if on:
            lines.append(line)
    assert lines, f"{path.name} has no section starting {start!r}"
    return "\n".join(lines) + "\n"


# The stubs stand in for Docker, the stack and the onex venv. `make` records every
# target it is asked for, so the test reads exactly what phase 4 did to the stack.
_PRELUDE = """
set -uo pipefail
say() { printf '%s\\n' "$*"; }
log() { :; }
retry() { shift; "$@"; }
step() { FAILED_STEP="$1"; shift; "$@"; }
phase_start() { :; }
phase_pass() { printf 'PASS %s\\n' "$*"; }
phase_skip() { printf 'SKIP %s\\n' "$*"; }
phase_fail() { printf 'FAIL %s: %s\\n' "$FAILED_STEP" "$*"; exit 1; }
rerun_note() { printf 'RERUN %s: %s\\n' "$1" "$2"; }
mark_done() { :; }
is_done() { [ -n "${FIXTURE_DONE:-}" ]; }
brew_bin() { printf '/fixture/brew\\n'; }
in_list() { case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
uses_key() { case "$1" in gemini|openrouter|openai) return 0 ;; *) return 1 ;; esac; }
provider_label() { printf '%s' "$1"; }
FAILED_STEP=""
STACK_RUNNING=0
"""

_PHASE4_STUBS = """
make() { printf '%s\\n' "$*" >>"$FIXTURE_MAKE_LOG"; }
docker() { printf 'docker %s\\n' "$*" >>"$FIXTURE_MAKE_LOG"; }
docker_installed() { return 0; }
docker_ready() { return 0; }
size_docker() { return 2; }
wait_for_docker() { return 0; }
compose_ok() { return 0; }
boot_resources_ok() { return 0; }
local_stack_running() { [ -n "${FIXTURE_STACK_UP:-}" ]; }
stack_healthy() { return 0; }
wait_until() { shift 3; "$@"; }
passed_models() { printf 'gemini\\n'; }
register_key_in_stack() { return 0; }
retry_capture() { CAPTURED='{}'; }
accepted_backend() { printf 'byok-gemini\\n'; }
sleep() { :; }
nice() { shift 2; "$@"; }
ram_gb() { printf '32\\n'; }
MODE2_OK=1
DOCKER_MEM_GB=10
DOCKER_CPUS=4
HOST_RESERVE_GB=6
"""


class Mac:
    """One fixture Mac: a home, a workspace and the GitHub remotes it clones."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.workspace = root / "workspace"
        self.remotes = root / "remotes"
        run_dir = root / "run"
        for d in (self.home, self.workspace, self.remotes, run_dir):
            d.mkdir()
        self.make_log = root / "make.log"
        self.phase2 = root / "phase2.sh"
        self.phase2.write_text(
            _section(SCRIPT, "# Phase 2: workspace", "# Phase 3:")
            + _section(HANDLER, "# The anchor: which commit", None)
        )
        self.phase4 = root / "phase4.sh"
        # The anchor line itself, so phase 4 reads INFRA_ANCHOR as the script names it.
        anchor_line = _section(SCRIPT, 'INFRA_ANCHOR="', "#").splitlines()[0]
        self.phase4.write_text(
            anchor_line
            + "\n"
            + _section(SCRIPT, "# Phase 4: containers", "# Phase 5:")
            + _PHASE4_STUBS
        )
        self.env = {
            **scrub_git_location_env(os.environ),
            "HOME": str(self.home),
            "WORKSPACE": str(self.workspace),
            "GITHUB_ORG_URL": str(self.remotes),
            "REPOS": " ".join(REPOS),
            "RUN_DIR": str(run_dir),
            "LOG": str(run_dir / "log"),
            "STATUS": str(run_dir / "status"),
            "STATE_DIR": str(self.home / ".omninode/onboarding"),
            "SHELL": "/bin/zsh",
            "STAMP": "20261030-120000",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "FIXTURE_MAKE_LOG": str(self.make_log),
        }
        siblings: dict[str, tuple[str, str]] = {}
        for name in REPOS[1:]:
            repo = self._bare(name)
            s1 = _commit(repo, f"{name} s1\n", None, None, T_SIBLING_1)
            s2 = _commit(repo, f"{name} s2\n", None, s1, T_SIBLING_2)
            self._dev(name, s2)
            siblings[name] = (s1, s2)
        infra = self._bare("omnibase_infra")
        a = _commit(infra, "A\n", {p: siblings[p][0] for p in PINNED}, None, T_ANCHOR_A)
        b = _commit(infra, "B\n", {p: siblings[p][1] for p in PINNED}, a, T_ANCHOR_B)
        self._dev("omnibase_infra", b)
        self.anchor = {"A": a, "B": b}
        self.expected = {
            "A": {"omnibase_infra": a} | {n: s[0] for n, s in siblings.items()},
            "B": {"omnibase_infra": b} | {n: s[1] for n, s in siblings.items()},
        }

    def _bare(self, name: str) -> Path:
        repo = self.remotes / f"{name}.git"
        repo.mkdir()
        _git(repo, "init", "--bare", "--quiet")
        return repo

    def _dev(self, name: str, sha: str) -> None:
        repo = self.remotes / f"{name}.git"
        _git(repo, "update-ref", "refs/heads/dev", sha)
        _git(repo, "symbolic-ref", "HEAD", "refs/heads/dev")

    def run(
        self, fragment: Path, anchor: str, command: str, **env: str
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                "/bin/bash",
                "-c",
                _PRELUDE + 'source "$1"\n' + command,
                "mac",
                str(fragment),
            ],
            env={**self.env, "ONBOARD_TEST_INFRA_ANCHOR": self.anchor[anchor], **env},
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    def heads(self) -> dict[str, str]:
        return {r: _git(self.workspace / r, "rev-parse", "HEAD") for r in REPOS}

    def onboard(self, anchor: str) -> None:
        """A first run: phase 2, then phase 4 bringing a new stack up."""
        self.run(self.phase2, anchor, "phase2")
        self.run(self.phase4, anchor, "phase4")

    def make_targets(self) -> list[str]:
        lines = self.make_log.read_text().splitlines() if self.make_log.exists() else []
        self.make_log.unlink(missing_ok=True)
        return lines


def _seed_developer_state(home: Path) -> dict[str, str]:
    """What phase 3 and a week of use leave under $HOME: keys, model order,
    delegation rows, the saved answers. Returns each file's sha256."""
    store = home / ".omninode/delegation/delegation.sqlite"
    store.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(store) as db:
        db.execute("create table credentials (provider text, secret text)")
        db.execute("insert into credentials values ('gemini', 'fixture-not-a-key')")
        db.execute("create table model_order (provider text, rank int, model text)")
        db.executemany(
            "insert into model_order values ('gemini', ?, ?)",
            [(1, "fixture-model-b"), (2, "fixture-model-a")],
        )
        db.execute("create table delegation_events (id int, backend_id text)")
        db.executemany(
            "insert into delegation_events values (?, 'byok-gemini')",
            [(i,) for i in range(5)],
        )
    db.close()
    choices = home / ".omninode/onboarding/choices"
    choices.parent.mkdir(parents=True, exist_ok=True)
    choices.write_text("models=gemini\ncontainers=1\n")
    overrides = home / ".omninode/delegation/bifrost_overrides.yaml"
    overrides.write_text("# the developer's own routes\n")
    return _digests(home, [store, choices, overrides])


def _digests(home: Path, files: list[Path]) -> dict[str, str]:
    return {
        str(f.relative_to(home)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in files
    }


@pytest.fixture
def mac(tmp_path: Path) -> Mac:
    return Mac(tmp_path)


def test_rerun_at_a_newer_anchor_moves_clones_and_stack_and_keeps_developer_data(
    mac: Mac,
) -> None:
    mac.onboard("A")
    assert mac.heads() == mac.expected["A"]
    assert "up-local" in " ".join(mac.make_targets())
    kept = _seed_developer_state(mac.home)

    # The newer script: same Mac, every phase recorded as done, the stack up.
    rerun = {"FIXTURE_DONE": "1", "FIXTURE_STACK_UP": "1"}
    phase2 = mac.run(mac.phase2, "B", "phase2", **rerun)
    assert "RERUN 2" in phase2.stdout
    assert mac.heads() == mac.expected["B"]
    for repo in REPOS:
        assert _git(mac.workspace / repo, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    config = mac.workspace / ".onex/workspace-config"
    assert f"# Anchor: omnibase_infra {mac.anchor['B']}" in _git(
        config, "show", "origin/main:config/onex/runtime/runtime_config.yaml"
    )

    phase4 = mac.run(mac.phase4, "B", "phase4", **rerun)
    targets = mac.make_targets()
    assert any(t.endswith(" up-local") for t in targets), phase4.stdout
    assert not any("volume" in t or t.endswith(" down-local") for t in targets), targets
    anchor_file = mac.home / ".omninode/onboarding/stack.anchor"
    assert anchor_file.read_text().strip() == mac.anchor["B"]

    assert _digests(mac.home, [mac.home / p for p in kept]) == kept


def test_rerun_at_the_same_anchor_rebuilds_nothing(mac: Mac) -> None:
    mac.onboard("A")
    mac.make_targets()
    rerun = {"FIXTURE_DONE": "1", "FIXTURE_STACK_UP": "1"}
    assert "PASS already in place" in mac.run(mac.phase2, "A", "phase2", **rerun).stdout
    assert "PASS already running" in mac.run(mac.phase4, "A", "phase4", **rerun).stdout
    assert mac.make_targets() == []
    assert mac.heads() == mac.expected["A"]


def test_guide_says_how_to_choose_and_publish_a_new_pin() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    parts = guide.split("## Moving everyone to a new pin\n", 1)
    assert len(parts) == 2, "ONBOARDING.md has no repin section"
    body = parts[1].split("\n## ", 1)[0]
    for needed in (
        "`INFRA_ANCHOR`",
        "sibling-pins.yaml",
        "shasum -a 256",
        "clean macOS VM",
        "Mailchimp",
        "bash lab-onboarding.sh",
    ):
        assert needed in body, needed
