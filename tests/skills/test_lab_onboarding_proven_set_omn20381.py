# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20381: install CI-proven siblings and stamp only after delegation passes."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
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
REPOS = ("omnibase_infra", "omnimarket", "omnibase_core", "omnibase_spi")

pytestmark = pytest.mark.unit

# OMN-18434: git exports GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE /
# GIT_COMMON_DIR into every hook environment, and those OVERRIDE both ``cwd=``
# and ``git -C``. A fixture that shells out to git under a pre-commit hook
# would therefore rewrite the REAL invoking worktree rather than tmp_path.
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


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
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
        },
    )
    return result.stdout.strip()


def _tree(repo: Path, content: str, pins: str | None) -> str:
    blob = _git(repo, "hash-object", "-w", "--stdin", stdin=content)
    entries = f"100644 blob {blob}\tREADME\n"
    if pins is not None:
        pin_blob = _git(repo, "hash-object", "-w", "--stdin", stdin=pins)
        github_tree = _git(
            repo, "mktree", stdin=f"100644 blob {pin_blob}\tsibling-pins.yaml\n"
        )
        entries += f"040000 tree {github_tree}\t.github\n"
    return _git(repo, "mktree", stdin=entries)


class Harness:
    def __init__(self, root: Path) -> None:
        self.home = root / "home"
        self.workspace = root / "workspace"
        self.remotes = root / "remotes"
        self.run_dir = root / "run"
        for directory in (self.home, self.workspace, self.remotes, self.run_dir):
            directory.mkdir()
        self.fragment = root / "fragment.sh"
        # Source only the marked phase and functions; never execute bare main.
        extracted = subprocess.run(
            [
                "awk",
                r"""
                /^# Phase 2: workspace/ { phase = 1 }
                /^# Phase 3:/ { phase = 0 }
                phase { print }
                /^receipt_field\(\)/ { print }
                /^(delegate_hello|stamp_proven_floor)\(\)/ { fn = 1 }
                fn { print }
                fn && /^}/ { fn = 0 }
                """,
                str(SCRIPT),
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        self.fragment.write_text(extracted.stdout)
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
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        self.commits: dict[str, tuple[str, str]] = {}

    def make_remotes(self, *, pins_present: bool = True) -> None:
        # Infra is created last so its tree names the siblings' older commits.
        for name in (*REPOS[1:], REPOS[0]):
            repo = self.remotes / f"{name}.git"
            repo.mkdir()
            _git(repo, "init", "--bare", "--quiet")
            pins = None
            if name == "omnibase_infra" and pins_present:
                pins = "pins:\n" + "".join(
                    f"  {sibling}: {self.commits[sibling][0]}\n"
                    for sibling in ("omnimarket", "omnibase_core")
                )
            older = _git(
                repo, "commit-tree", _tree(repo, "older\n", pins), stdin="older\n"
            )
            newer = _git(
                repo,
                "commit-tree",
                _tree(repo, "newer\n", pins),
                "-p",
                older,
                stdin="newer\n",
            )
            _git(repo, "update-ref", "refs/heads/dev", newer)
            _git(repo, "symbolic-ref", "HEAD", "refs/heads/dev")
            self.commits[name] = (older, newer)

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

    def dispatch_python(self) -> Path:
        venv = self.workspace / ".onex-dispatch-venv"
        (venv / "bin").mkdir(parents=True)
        (venv / "bin" / "python").symlink_to(sys.executable)
        sites = venv / "lib" / "python3.13" / "site-packages"
        sites.mkdir(parents=True)
        return sites


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def _passed(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def test_phase2_installs_detached_proven_siblings_without_a_floor(
    harness: Harness,
) -> None:
    harness.make_remotes()
    result = harness.run("phase2")
    _passed(result)
    for name in REPOS:
        clone = harness.workspace / name
        older, newer = harness.commits[name]
        pinned = name in ("omnimarket", "omnibase_core")
        assert _git(clone, "rev-parse", "HEAD") == (older if pinned else newer)
        assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD") == (
            "HEAD" if pinned else "dev"
        )
        if pinned:
            assert f"{name}: proven {older[:12]}" in result.stdout
    assert (
        "Default branch (no proven pin): omnibase_infra omnibase_spi" in result.stdout
    )
    assert not (harness.workspace / ".onex-workspace-floor.json").exists()


def test_phase2_resume_checks_pins_and_repins_dev_head(harness: Harness) -> None:
    harness.make_remotes()
    _passed(harness.run("phase2"))
    clone = harness.workspace / "omnimarket"
    _git(clone, "checkout", "--quiet", "dev")
    assert harness.run("phase2_verified").returncode == 1
    _passed(harness.run('is_done() { [ "$1" = 2 ]; }; phase2'))
    assert _git(clone, "rev-parse", "HEAD") == harness.commits["omnimarket"][0]
    _passed(harness.run("phase2_verified"))


def test_dirty_clone_fails_without_moving_head_or_floor(harness: Harness) -> None:
    harness.make_remotes()
    _passed(harness.run("phase2"))
    clone = harness.workspace / "omnimarket"
    _git(clone, "checkout", "--quiet", "dev")
    (clone / "README").write_text("uncommitted change\n")
    floor = harness.workspace / ".onex-workspace-floor.json"
    before = b'{"proven": "previous"}\n'
    floor.write_bytes(before)
    result = harness.run("phase2")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "omnimarket: clone has uncommitted changes" in result.stdout
    assert "FAIL check out the proven commit of omnimarket" in result.stdout
    assert "move your changes out" in result.stdout
    assert "another --workspace" in result.stdout
    assert _git(clone, "rev-parse", "HEAD") == harness.commits["omnimarket"][1]
    assert floor.read_bytes() == before


def test_missing_pins_fails_instead_of_accepting_dev_head(harness: Harness) -> None:
    harness.make_remotes(pins_present=False)
    result = harness.run("phase2")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "FAIL read the proven set (omnibase_infra/.github/sibling-pins.yaml)" in (
        result.stdout
    )
    assert "PASS" not in result.stdout
    assert harness.run("phase2_verified").returncode == 1
    assert not (harness.workspace / ".onex-workspace-floor.json").exists()


def test_delegate_hello_uses_dispatch_entrypoint_and_receipt(harness: Harness) -> None:
    harness.dispatch_python()
    record = harness.run_dir / "delegate.json"
    receipt = harness.run_dir / "receipt.json"
    receipt.write_text('{"endpoint": "provider", "model": "proven-model"}\n')
    onex = harness.workspace / ".onex-dispatch-venv" / "bin" / "onex"
    onex.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"Path({str(record)!r}).write_text(json.dumps({{\n"
        "    'argv': sys.argv[1:], 'cwd': os.getcwd(),\n"
        "    'pythonpath': os.environ.get('PYTHONPATH')}))\n"
        'print(\'{"status": "success"}\')\n'
        f"print('delegate artifacts: {receipt}', file=sys.stderr)\n"
    )
    onex.chmod(0o755)
    harness.env["PYTHONPATH"] = "/ambient/must/be/removed"
    result = harness.run(
        'onex_run() { echo "WRAPPER CALLED" >&2; return 91; }; delegate_hello'
    )
    _passed(result)
    assert result.stdout == receipt.read_text()
    assert "WRAPPER CALLED" not in result.stderr
    assert json.loads(record.read_text()) == {
        "argv": ["delegate", "--json", "Reply with exactly one word: hello"],
        "cwd": str(harness.home),
        "pythonpath": None,
    }


def test_phase3_builds_proven_and_stamps_only_at_both_passes() -> None:
    text = SCRIPT.read_text()
    phase3 = text.split("phase3() {", 1)[1].split("phase3_ollama() {", 1)[0]
    reconcile = next(
        line for line in phase3.splitlines() if "reconcile-workspace-venvs.sh" in line
    )
    assert '--omni-home "$WORKSPACE" --proven' in reconcile
    calls = re.findall(r'^  step "[^"]+" stamp_proven_floor \|\|\n', text, re.M)
    assert len(calls) == 2
    assert len(re.findall(r"\bstamp_proven_floor\b", text)) == 3  # definition + calls
    for name in ("phase3", "phase3_ollama"):
        body = text.split(f"{name}() {{", 1)[1].split("\n}", 1)[0]
        assert re.search(
            r'  step "[^"]+" stamp_proven_floor \|\|\n'
            r'    phase_fail "[^"\n]+"\n'
            r'  phase_pass "model:[^"\n]+"$',
            body,
        )
        assert body.index("stamp_proven_floor") > body.index(
            'say "  Delegation answered'
        )
    stamp = text.split("stamp_proven_floor() {", 1)[1].split("\n}", 1)[0]
    assert '--output "$WORKSPACE/.onex-workspace-floor.json"' in stamp
    # Every mention of the output path belongs to this function: no redirect,
    # assignment, or second CLI elsewhere can stamp it before a passing run.
    assert (
        text.count(".onex-workspace-floor.json")
        == stamp.count(".onex-workspace-floor.json")
        == 1
    )


@pytest.mark.parametrize("exit_code", [1, 0])
def test_stamp_floor_uses_venv_cli_and_preserves_previous_on_failure(
    harness: Harness, exit_code: int
) -> None:
    sites = harness.dispatch_python()
    scripts = harness.workspace / "omnibase_infra" / "scripts"
    scripts.mkdir(parents=True)
    record = harness.run_dir / "stamp.json"
    (scripts / "reconcile_verify_movement.py").write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        f"Path({str(record)!r}).write_text(json.dumps(sys.argv[1:]))\n"
        f"sys.exit({exit_code})\n"
    )
    floor = harness.workspace / ".onex-workspace-floor.json"
    before = b'{"previous": "proven", "bytes": "unchanged"}\n'
    floor.write_bytes(before)
    result = harness.run("stamp_proven_floor")
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert floor.read_bytes() == before
    assert json.loads(record.read_text()) == [
        "floor-from-venv",
        "--site-packages",
        str(sites),
        "--lock",
        str(harness.workspace / "omnibase_infra" / "uv.lock"),
        "--omni-home",
        str(harness.workspace),
        "--output",
        str(floor),
    ]


def test_verify_phase_asks_the_wrapper_and_never_reconciles() -> None:
    text = SCRIPT.read_text()
    # reconcile-host.sh fast-forwards the clones to origin/dev, reinstalls the
    # dispatch venv from them and restamps the floor: the one mid-run restamp
    # the proven set exists to prevent. Phase 3's --proven reconcile is the only
    # reconcile in the script.
    assert "reconcile-host" not in text.replace("# reconcile-host", "")
    assert len(re.findall(r"^\s*(?:retry .*)?bash .*reconcile-", text, re.M)) == 1
    floor = text.split("workspace_floor() {", 1)[1].split("\n}", 1)[0]
    assert 'onex_run delegate --json "Reply with exactly one word: hello"' in floor
    assert "reconcile" not in floor
    phase6 = text.split("phase6() {", 1)[1].split("\n}", 1)[0]
    assert "workspace_floor" in phase6
