# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the OMN-17190 workspace-reconcile pair.

Two hooks, one job: keep the canonical clones and the locally-installed venvs
tracking ``dev`` without anyone typing a command, and make the answer visible at
session start instead of at the first failed dispatch.

* ``workspace_reconcile_tick.sh`` — PostToolUse, throttled. Fetches each
  canonical clone, fast-forwards the CLEAN ones, runs the reconciler, and
  writes a receipt line plus a one-line verdict.
* ``session_start_workspace_sync.sh`` — SessionStart. Prints that verdict with
  its age.

Everything here runs the real scripts as subprocesses against a hermetic
``$OMNI_HOME`` built from local git repos. Nothing reaches the network, no real
clone is touched, and the reconciler is a recording stub (its own behaviour is
covered by omnibase_infra's ``tests/scripts/test_reconcile_workspace_venvs.py``)
so these tests prove the hooks' WIRING and their two hard safety properties:

    the tick never pulls into a dirty clone, and it can never fail a tool call.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts"
_TICK = _SCRIPTS / "workspace_reconcile_tick.sh"
_SESSION_LINE = _SCRIPTS / "session_start_workspace_sync.sh"

_STDIN = '{"session_id":"sess-ws-01","cwd":"/tmp"}'


# --------------------------------------------------------------------------- #
# Hermetic workspace
# --------------------------------------------------------------------------- #
def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def _make_clone_with_remote(root: Path, name: str) -> tuple[Path, Path]:
    """A canonical-clone-shaped repo on ``dev`` with a real (local) origin."""
    upstream = root / "_upstream" / f"{name}.git"
    seed = root / "_seed" / name
    seed.mkdir(parents=True)
    _git("init", "--quiet", "-b", "dev", cwd=seed)
    _git("config", "user.email", "test@example.com", cwd=seed)
    _git("config", "user.name", "Test", cwd=seed)
    (seed / "f.txt").write_text("one", encoding="utf-8")
    _git("add", "f.txt", cwd=seed)
    _git("commit", "--quiet", "-m", "one", cwd=seed)

    upstream.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(seed), str(upstream)], check=True
    )

    clone = root / name
    subprocess.run(
        ["git", "clone", "--quiet", "-b", "dev", str(upstream), str(clone)], check=True
    )
    _git("config", "user.email", "test@example.com", cwd=clone)
    _git("config", "user.name", "Test", cwd=clone)
    return clone, seed


def _advance_remote(seed: Path, upstream_name: str, root: Path, text: str) -> str:
    """Push a new commit so the clone is genuinely behind its origin."""
    (seed / "f.txt").write_text(text, encoding="utf-8")
    _git("add", "f.txt", cwd=seed)
    _git("commit", "--quiet", "-m", text, cwd=seed)
    _git(
        "push",
        "--quiet",
        str(root / "_upstream" / f"{upstream_name}.git"),
        "dev",
        cwd=seed,
    )
    return _git("rev-parse", "HEAD", cwd=seed)


class _Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root / "omni_home"
        self.root.mkdir(parents=True)
        self.state = root / "state"
        (self.state / "hooks").mkdir(parents=True)
        (self.state / "logs").mkdir(parents=True)

        self.clone, self.seed = _make_clone_with_remote(self.root, "omnimarket")

        infra_scripts = self.root / "omnibase_infra" / "scripts"
        infra_scripts.mkdir(parents=True)
        self.reconciler = infra_scripts / "reconcile-workspace-venvs.sh"
        self.reconcile_log = root / "reconcile.log"
        self.set_reconciler_exit(0)

    def set_reconciler_exit(self, code: int, *, check_code: int | None = None) -> None:
        """Recording stub. ``check_code`` lets --check answer differently."""
        checked = code if check_code is None else check_code
        self.reconciler.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> "{self.reconcile_log}"\n'
            'for a in "$@"; do\n'
            f'  if [[ "$a" == "--check" ]]; then exit {checked}; fi\n'
            "done\n"
            f"exit {code}\n",
            encoding="utf-8",
        )
        self.reconciler.chmod(0o755)

    @property
    def status_file(self) -> Path:
        return self.state / "hooks" / "workspace-reconcile.status"

    @property
    def stamp_file(self) -> Path:
        return self.state / "hooks" / "workspace-reconcile.stamp"

    @property
    def receipts(self) -> Path:
        return self.state / "logs" / "workspace-reconcile.log"

    def env(self, **overrides: str) -> dict[str, str]:
        env = {
            **os.environ,
            "OMNI_HOME": str(self.root),
            "ONEX_STATE_DIR": str(self.state),
            "ONEX_HOOKS_STATE_DIR": str(self.state / "hooks"),
            "ONEX_LOG_DIR": str(self.state / "logs"),
            # Pin mode resolution so the result never depends on where pytest
            # was invoked from.
            "OMNICLAUDE_MODE": "full",
        }
        env.update(overrides)
        return env

    def run_tick(
        self, *, expect_body: bool = True, **overrides: str
    ) -> subprocess.CompletedProcess[str]:
        """Run the tick and wait for its detached body.

        ``expect_body=False`` for a run the throttle is expected to swallow:
        waiting the full timeout for a body that will never be written is
        30 wasted seconds per such test, and the assertion that follows is
        what actually proves the throttle held.
        """
        before = self._completed_bodies()
        result = subprocess.run(
            ["bash", str(_TICK)],
            input=_STDIN,
            capture_output=True,
            text=True,
            env=self.env(**overrides),
            check=False,
        )
        self._await_detached_body(before, timeout=30.0 if expect_body else 1.0)
        return result

    def _completed_bodies(self) -> int:
        if not self.receipts.exists():
            return 0
        return self.receipts.read_text(encoding="utf-8").count("tick=complete")

    def _await_detached_body(self, before: int, timeout: float = 30.0) -> None:
        """The tick backgrounds its body on purpose; wait for THIS run to land.

        Counting completions rather than testing for presence is what makes a
        second run in the same test observable -- waiting for "a completion"
        would return instantly on the previous one. Polling a real artifact
        rather than sleeping a fixed interval keeps the suite fast on a quiet
        machine and non-flaky on a loaded one. A throttled tick writes no
        completion at all, so the timeout is also the throttle's proof.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._completed_bodies() > before:
                return
            time.sleep(0.05)

    def run_session_line(self, **overrides: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(_SESSION_LINE)],
            input=_STDIN,
            capture_output=True,
            text=True,
            env=self.env(**overrides),
            check=False,
        )

    def reconcile_calls(self) -> list[str]:
        if not self.reconcile_log.exists():
            return []
        return [
            line
            for line in self.reconcile_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


@pytest.fixture
def ws(tmp_path: Path) -> _Workspace:
    return _Workspace(tmp_path)


# --------------------------------------------------------------------------- #
# Both scripts must exist, be executable, and never block
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("script", [_TICK, _SESSION_LINE])
def test_script_exists_and_is_executable(script: Path) -> None:
    assert script.is_file(), f"missing hook: {script}"
    assert os.access(script, os.X_OK), f"hook not executable: {script}"


@pytest.mark.parametrize("script", [_TICK, _SESSION_LINE])
def test_hook_is_pure_bash_with_no_interpreter_spinup(script: Path) -> None:
    """No python3/uv on the hook path.

    A hook with no interpreter cannot resolve to the wrong one, which is the
    strongest available form of compliance with CLAUDE.md rule 11 (the macOS
    LAN-grant / one-project-python constraint) and sidesteps the OMN-16996
    regression class where hook Python resolved to the adhoc-signed
    ``omniclaude/.venv``. The tick DOES shell out to git and to the reconciler
    -- those are the work -- but it never starts an interpreter itself.
    """
    body = script.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )
    for forbidden in ("python3 ", "python ", "uv run", "jq "):
        assert forbidden not in code, (
            f"{script.name} spins up an interpreter ({forbidden.strip()!r}) on a "
            "hook path contracted to stay free of one"
        )


def test_tick_exits_zero_even_when_the_reconciler_fails(ws: _Workspace) -> None:
    """A tick can never fail a tool call. Ever.

    The reconciler's failure is real and is recorded in the receipt and the
    status line -- but the enforcement surface is the `onex` CLI guard, which
    refuses where a stale venv would actually produce bad results. A hook that
    could fail an unrelated tool call would be a strictly worse place to learn
    the same fact.
    """
    _advance_remote(ws.seed, "omnimarket", ws.root, "two")
    ws.set_reconciler_exit(1, check_code=1)

    result = ws.run_tick()

    assert result.returncode == 0, result.stdout + result.stderr


def test_tick_is_silent_without_omni_home(ws: _Workspace) -> None:
    """A machine with no canonical registry has nothing to reconcile.

    Fail SILENT, not fast: this fires on every tool call, so an unset-variable
    banner would be printed hundreds of times a session on a host the hook has
    no business acting on at all.
    """
    env = ws.env()
    env.pop("OMNI_HOME")
    result = subprocess.run(
        ["bash", str(_TICK)],
        input=_STDIN,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert ws.reconcile_calls() == []


# --------------------------------------------------------------------------- #
# Pull behaviour
# --------------------------------------------------------------------------- #
def test_clone_behind_origin_is_fast_forwarded_and_reconciled(
    ws: _Workspace,
) -> None:
    before = _git("rev-parse", "HEAD", cwd=ws.clone)
    after = _advance_remote(ws.seed, "omnimarket", ws.root, "two")
    assert before != after

    ws.run_tick()

    assert _git("rev-parse", "HEAD", cwd=ws.clone) == after, (
        "the clone was behind origin/dev on a clean tree and was not pulled"
    )
    receipts = ws.receipts.read_text(encoding="utf-8")
    assert "status=PULLED" in receipts
    assert before[:12] in receipts and after[:12] in receipts, (
        "the receipt must name the old -> new SHA, not merely that something moved"
    )
    assert ws.reconcile_calls(), "clone moved but the venv reconcile never ran"


def test_dirty_clone_is_reported_and_never_pulled(ws: _Workspace) -> None:
    """The hard safety property.

    Pulling into a dirty canonical clone would either fail noisily mid-tick or,
    worse, succeed and entangle someone's uncommitted work with a fast-forward
    they did not ask for. Committing in a canonical clone is already a policy
    violation, so a dirty clone is a thing to surface, not to resolve.
    """
    before = _git("rev-parse", "HEAD", cwd=ws.clone)
    _advance_remote(ws.seed, "omnimarket", ws.root, "two")
    (ws.clone / "f.txt").write_text("uncommitted local edit", encoding="utf-8")

    result = ws.run_tick()

    assert result.returncode == 0
    assert _git("rev-parse", "HEAD", cwd=ws.clone) == before, (
        "a DIRTY canonical clone was pulled -- this can entangle uncommitted work"
    )
    assert (ws.clone / "f.txt").read_text(encoding="utf-8") == "uncommitted local edit"

    receipts = ws.receipts.read_text(encoding="utf-8")
    assert "status=DIRTY" in receipts
    assert "action=none" in receipts
    assert "DRIFT" in ws.status_file.read_text(encoding="utf-8"), (
        "a clone that could not be pulled must surface as DRIFT at session start, "
        "not be silently absorbed"
    )


def test_clone_on_a_feature_branch_is_left_alone(ws: _Workspace) -> None:
    """Only the tracking branches are ours to advance."""
    _git("checkout", "--quiet", "-b", "jonah/some-work", cwd=ws.clone)
    before = _git("rev-parse", "HEAD", cwd=ws.clone)
    _advance_remote(ws.seed, "omnimarket", ws.root, "two")

    ws.run_tick()

    assert _git("rev-parse", "HEAD", cwd=ws.clone) == before
    assert _git("branch", "--show-current", cwd=ws.clone) == "jonah/some-work"


def test_up_to_date_clone_still_verifies_the_venv(ws: _Workspace) -> None:
    """Nothing pulled is not the same as nothing drifted.

    Another session's pull-all, or a `uv sync` someone ran by hand, moves the
    venv independently of this clone. A tick that only looked at git would call
    that state clean.
    """
    ws.run_tick()

    calls = ws.reconcile_calls()
    assert calls, "a no-movement tick never checked the venv at all"
    assert any("--check" in c for c in calls), (
        f"a no-movement tick must use the read-only probe; calls were {calls!r}"
    )


def test_check_drift_without_movement_triggers_a_repair(ws: _Workspace) -> None:
    ws.set_reconciler_exit(0, check_code=1)  # --check says DRIFT, repair succeeds

    ws.run_tick()

    calls = ws.reconcile_calls()
    assert any("--check" in c for c in calls)
    assert any("--check" not in c for c in calls), (
        f"--check reported drift and no repair followed; calls were {calls!r}"
    )
    assert "in sync" in ws.status_file.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Throttle
# --------------------------------------------------------------------------- #
def test_second_tick_inside_the_interval_does_nothing(ws: _Workspace) -> None:
    ws.run_tick()
    first = len(ws.reconcile_calls())

    ws.run_tick(expect_body=False)

    assert len(ws.reconcile_calls()) == first, (
        "the tick ran twice inside its interval; on a PostToolUse hook that is a "
        "`uv sync` per tool call"
    )


def test_interval_is_claimed_before_the_work_not_after(ws: _Workspace) -> None:
    """The stamp is written up front, deliberately.

    Hooks fire concurrently -- several tool calls can be in flight at once --
    and a stamp written after the reconcile would let every one of them start
    its own `uv sync` against the same venv. uv serialises those on an exclusive
    flock, so a stampede becomes a pile-up of processes each waiting on the
    last: the OMN-15590 stall shape, reproduced by design.
    """
    _advance_remote(ws.seed, "omnimarket", ws.root, "two")
    ws.set_reconciler_exit(1, check_code=1)

    ws.run_tick()

    assert ws.stamp_file.exists(), (
        "no stamp was written for a tick whose reconcile FAILED -- the next tool "
        "call would immediately start another one"
    )


def test_zero_interval_allows_an_immediate_re_tick(ws: _Workspace) -> None:
    """The throttle is configurable, and the knob is proven, not assumed."""
    ws.run_tick()
    first = len(ws.reconcile_calls())

    ws.run_tick(ONEX_RECONCILE_TICK_SECONDS="0")

    assert len(ws.reconcile_calls()) > first


# --------------------------------------------------------------------------- #
# SessionStart line
# --------------------------------------------------------------------------- #
def test_session_line_prints_the_in_sync_verdict_with_its_age(
    ws: _Workspace,
) -> None:
    ws.run_tick()

    result = ws.run_session_line()

    assert result.returncode == 0
    assert "clones/venv: in sync as of" in result.stdout
    assert "ago" in result.stdout, (
        "the verdict is cached, so its age must always be printed -- a bare "
        "'in sync' invites reading a stale answer as a current one"
    )


def test_session_line_prints_drift_when_a_clone_could_not_be_pulled(
    ws: _Workspace,
) -> None:
    _advance_remote(ws.seed, "omnimarket", ws.root, "two")
    (ws.clone / "f.txt").write_text("uncommitted", encoding="utf-8")
    ws.run_tick()

    result = ws.run_session_line()

    assert result.returncode == 0
    assert "DRIFT" in result.stdout
    assert "omnimarket" in result.stdout


def test_session_line_reports_unknown_rather_than_in_sync_when_no_tick_has_run(
    ws: _Workspace,
) -> None:
    """Absence of evidence must never render as evidence of sync."""
    assert not ws.status_file.exists()

    result = ws.run_session_line()

    assert result.returncode == 0
    assert "UNKNOWN" in result.stdout
    assert "in sync" not in result.stdout
    assert "reconcile-workspace-venvs.sh --check" in result.stdout, (
        "an unknown verdict must name the command that settles it"
    )


def test_session_line_labels_a_stale_verdict_as_unproven(ws: _Workspace) -> None:
    ws.status_file.write_text(
        "clones/venv: in sync as of 2020-01-01T00:00:00Z\n", encoding="utf-8"
    )
    old = time.time() - (60 * 60 * 24)
    os.utime(ws.status_file, (old, old))

    result = ws.run_session_line()

    assert result.returncode == 0
    assert "unproven" in result.stdout


def test_session_line_is_silent_without_omni_home(ws: _Workspace) -> None:
    env = ws.env()
    env.pop("OMNI_HOME")
    result = subprocess.run(
        ["bash", str(_SESSION_LINE)],
        input=_STDIN,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_session_line_never_mutates_anything(ws: _Workspace) -> None:
    """It is a print. It must not pull, reconcile, or write state."""
    ws.run_tick()
    before = len(ws.reconcile_calls())
    head_before = _git("rev-parse", "HEAD", cwd=ws.clone)
    _advance_remote(ws.seed, "omnimarket", ws.root, "two")

    ws.run_session_line()

    assert len(ws.reconcile_calls()) == before
    assert _git("rev-parse", "HEAD", cwd=ws.clone) == head_before
