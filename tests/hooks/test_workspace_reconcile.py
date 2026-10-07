# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the OMN-17190 workspace-reconcile pair.

Two hooks, one job: keep the canonical clones and the locally-installed venvs
tracking ``dev`` without anyone typing a command, and make the answer visible at
session start instead of at the first failed dispatch.

* ``workspace_reconcile_tick.sh`` — PostToolUse, throttled. Delegates to
  ``onex-host-reconcile`` (OMN-17311, OMN-20670; the legacy ``reconcile-host.sh``
  is a fallback) and writes a receipt
  line plus a one-line verdict. It performs no repair of its own: it used to
  fetch and ``git pull --ff-only`` each clone and report ``status=PULLED`` on
  the pull's EXIT CODE, which is the OMN-17307 defect -- a clone with
  ``core.bare=true`` fetches cleanly forever while every checkout fails.
* ``session_start_workspace_sync.sh`` — SessionStart. Prints that verdict with
  its age.

Everything here runs the real scripts as subprocesses against a hermetic
``$OMNI_HOME`` built from local git repos. Nothing reaches the network, no real
clone is touched, and the reconciler is a recording stub (its own behaviour is
covered by omnibase_infra's ``tests/scripts/test_reconcile_host_omn17307.py``)
so these tests prove the hooks' WIRING and their two hard safety properties:

    the tick performs no repair of its own, and it can never fail a tool call.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Mapping
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
def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    """Drop the git location variables before shelling out to git (OMN-14891).

    Git exports these into EVERY hook environment and they override both ``cwd=``
    and ``git -C``. A fixture that shells out to git while a pre-push hook is
    running would therefore operate on the REAL invoking worktree rather than on
    ``tmp_path`` -- so this suite's own setup could rewrite the repository it is
    being pushed from (OMN-18434).
    """
    scrubbed = dict(env)
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        scrubbed.pop(key, None)
    return scrubbed


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
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
        ["git", "clone", "--quiet", "--bare", str(seed), str(upstream)],
        check=True,
        env=scrub_git_location_env(os.environ),
    )

    clone = root / name
    subprocess.run(
        ["git", "clone", "--quiet", "-b", "dev", str(upstream), str(clone)],
        check=True,
        env=scrub_git_location_env(os.environ),
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

        self.infra_scripts = self.root / "omnibase_infra" / "scripts"
        self.infra_scripts.mkdir(parents=True)
        # OMN-17311: the tick delegates to the ONE host reconciler. Its own
        # behaviour -- fetch, fast-forward, refuse a dirty clone, and prove by
        # readback that every surface reached its target -- is covered by
        # omnibase_infra's tests/scripts/test_reconcile_host_omn17307.py. Here
        # it is a recording stub, because what these tests pin is the WIRING.
        self.reconciler = self.infra_scripts / "reconcile-host.sh"
        self.reconcile_log = root / "reconcile.log"
        self.set_reconciler_exit(0)
        # OMN-20670 / OMN-17427: the canonical reconciler is the
        # ``onex-host-reconcile`` console script of the omnibase_internal
        # project, installed into that clone's own ``.venv`` (by its
        # ``onex-internal-clone-sync`` timer) -- never into the dispatch venv.
        # It is NOT installed by default here, so every pre-existing test keeps
        # exercising the legacy script path; the tests below install it.
        self.internal = root / "omnibase_internal"
        self.canonical = self.internal / ".venv" / "bin" / "onex-host-reconcile"
        self.canonical_log = root / "canonical.log"

    def set_reconciler_exit(self, code: int) -> None:
        """Recording stub for ``reconcile-host.sh``.

        Exit codes are the reconciler's own: 0 every surface proven at target,
        2 a surface could not be proven, 3 indeterminate configuration.
        """
        self.reconciler.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> "{self.reconcile_log}"\n'
            f"exit {code}\n",
            encoding="utf-8",
        )
        self.reconciler.chmod(0o755)

    def remove_reconciler(self) -> None:
        self.reconciler.unlink()

    def install_canonical(self, code: int = 0) -> None:
        """Recording stub for ``onex-host-reconcile`` (same exit-code table)."""
        self.canonical.parent.mkdir(parents=True, exist_ok=True)
        self.canonical.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> "{self.canonical_log}"\n'
            f"exit {code}\n",
            encoding="utf-8",
        )
        self.canonical.chmod(0o755)

    def canonical_calls(self) -> list[str]:
        if not self.canonical_log.exists():
            return []
        return [
            line
            for line in self.canonical_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

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
    ws.set_reconciler_exit(2)

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
# Delegation -- one reconciler, every machine (OMN-17311)
# --------------------------------------------------------------------------- #
def test_the_tick_delegates_and_does_not_reimplement_the_clone_loop(
    ws: _Workspace,
) -> None:
    """The tick owns throttling, detachment and the status line. Nothing else.

    Before OMN-17311 this hook fetched every clone, ran ``git pull --ff-only``,
    and wrote ``status=PULLED`` on THE PULL'S EXIT CODE. That is the OMN-17307
    defect sitting in the scheduler: a clone with ``core.bare=true`` fetches
    cleanly forever while every checkout fails with exit 128 (OMN-17291), and
    nothing here ever re-read HEAD to notice.
    """
    _advance_remote(ws.seed, "omnimarket", ws.root, "two")

    ws.run_tick()

    calls = ws.reconcile_calls()
    assert calls, "the tick did not delegate to the host reconciler at all"
    assert any("--omni-home" in c for c in calls), (
        f"the reconciler must be handed the root explicitly; calls were {calls!r}"
    )
    receipts = ws.receipts.read_text(encoding="utf-8")
    assert "reconciler_exit=0" in receipts
    assert "status=PULLED" not in receipts, (
        "the tick is still reporting a pull of its own; the delegate owns that "
        "and owns the readback that proves it"
    )


def test_the_tick_never_pulls_a_clone_itself(ws: _Workspace) -> None:
    """A stubbed reconciler that does nothing must leave every clone untouched.

    This is the structural half of the assertion above: if the tick still had a
    pull loop, the clone would advance even though the delegate is a no-op.
    """
    before = _git("rev-parse", "HEAD", cwd=ws.clone)
    _advance_remote(ws.seed, "omnimarket", ws.root, "two")

    ws.run_tick()

    assert _git("rev-parse", "HEAD", cwd=ws.clone) == before, (
        "the tick advanced a clone by itself; repair belongs to reconcile-host.sh "
        "so that both hosts run identical logic and one readback covers both"
    )


def test_a_failing_reconcile_surfaces_as_drift_not_as_in_sync(ws: _Workspace) -> None:
    """Exit 2 is 'a surface could not be proven at target'."""
    ws.set_reconciler_exit(2)

    result = ws.run_tick()

    assert result.returncode == 0, "a tick must never fail the tool call that fired it"
    status = ws.status_file.read_text(encoding="utf-8")
    assert "DRIFT" in status
    assert "in sync" not in status
    assert "reconciler_exit=2" in ws.receipts.read_text(encoding="utf-8")


def test_an_indeterminate_reconcile_is_not_reported_as_in_sync(ws: _Workspace) -> None:
    """Exit 3 is a configuration the reconciler could not resolve.

    'Could not determine' is never 'fine' -- the same fail-closed posture the
    verdict table takes on an unreadable surface.
    """
    ws.set_reconciler_exit(3)

    ws.run_tick()

    status = ws.status_file.read_text(encoding="utf-8")
    assert "DRIFT" in status
    assert "INDETERMINATE" in status


def test_a_missing_reconciler_is_reported_not_silently_skipped(ws: _Workspace) -> None:
    """An uncovered host must say so at session start.

    A tick that quietly does nothing on a host with no reconciler is the
    OMN-17291 condition -- the workspace looks governed while it drifts.
    """
    ws.remove_reconciler()

    ws.run_tick()

    status = ws.status_file.read_text(encoding="utf-8")
    assert "DRIFT" in status
    assert "reconciler" in status


def test_bootstrap_advances_omnibase_infra_only_while_the_reconciler_is_absent(
    ws: _Workspace,
) -> None:
    """The one ordering problem delegation creates, and its bounded answer.

    On a host whose omnibase_infra clone predates OMN-17307 the reconciler does
    not exist, and nothing else advances the clone that would deliver it. So the
    tick advances THAT ONE repo, only while the reconciler is missing -- and it
    verifies the result by re-reading HEAD, because a bootstrap that trusted
    ``git pull``'s exit status would be the same defect in the last place anyone
    would look for it.
    """
    infra_clone, infra_seed = _make_clone_with_remote(ws.root, "omnibase_infra_src")
    # Point the tick's bootstrap at a real clone by relocating it into place.
    import shutil

    shutil.rmtree(ws.root / "omnibase_infra")
    shutil.move(str(infra_clone), str(ws.root / "omnibase_infra"))
    target = _advance_remote(infra_seed, "omnibase_infra_src", ws.root, "two")

    ws.run_tick()

    assert _git("rev-parse", "HEAD", cwd=ws.root / "omnibase_infra") == target
    receipts = ws.receipts.read_text(encoding="utf-8")
    assert "bootstrap=omnibase_infra" in receipts
    assert target[:12] in receipts


def test_bootstrap_does_not_run_once_the_reconciler_exists(ws: _Workspace) -> None:
    ws.run_tick()
    assert "bootstrap=" not in ws.receipts.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# The canonical command replaces the shell script (OMN-20670)
# --------------------------------------------------------------------------- #
def test_the_tick_runs_the_canonical_command_when_it_is_installed(
    ws: _Workspace,
) -> None:
    """``onex-host-reconcile`` is the one reconciler; the script is retired.

    omnibase_infra deletes ``scripts/reconcile-host.sh`` once the command ships,
    so with the script gone the tick must still reconcile -- not report
    ``DRIFT: no workspace reconciler`` (the 2026-10-07 incident).
    """
    ws.remove_reconciler()
    ws.install_canonical(0)

    ws.run_tick()

    calls = ws.canonical_calls()
    assert calls, "the tick did not run the canonical command"
    assert f"--omni-home {ws.root}" in calls[0]
    receipts = ws.receipts.read_text(encoding="utf-8")
    assert "reconciler_exit=0" in receipts
    assert "bootstrap=" not in receipts, (
        "the command is not delivered by the infra clone"
    )
    assert "in sync" in ws.status_file.read_text(encoding="utf-8")


def test_the_canonical_command_wins_over_the_legacy_script(ws: _Workspace) -> None:
    ws.install_canonical(0)

    ws.run_tick()

    assert ws.canonical_calls(), "the canonical command was not run"
    assert not ws.reconcile_calls(), (
        "the legacy script ran beside the canonical command"
    )


def test_the_legacy_script_still_runs_until_the_command_is_installed(
    ws: _Workspace,
) -> None:
    """Merge order must not matter: no host loses its reconciler in between."""
    ws.run_tick()

    assert ws.reconcile_calls(), "no reconciler ran although the legacy script exists"
    assert not ws.canonical_calls()
    assert "in sync" in ws.status_file.read_text(encoding="utf-8")


def test_a_failing_canonical_reconcile_surfaces_as_drift(ws: _Workspace) -> None:
    ws.remove_reconciler()
    ws.install_canonical(2)

    result = ws.run_tick()

    assert result.returncode == 0
    status = ws.status_file.read_text(encoding="utf-8")
    assert "DRIFT" in status
    assert "in sync" not in status
    assert "reconciler_exit=2" in ws.receipts.read_text(encoding="utf-8")


def test_no_reconciler_at_all_names_the_canonical_command(ws: _Workspace) -> None:
    ws.remove_reconciler()

    ws.run_tick()

    status = ws.status_file.read_text(encoding="utf-8")
    assert "DRIFT" in status
    assert "onex-host-reconcile" in status


def test_the_declared_internal_home_locates_the_canonical_command(
    ws: _Workspace, tmp_path: Path
) -> None:
    """OMNIBASE_INTERNAL_HOME is the one declaration, and it wins."""
    ws.remove_reconciler()
    declared = tmp_path / "elsewhere" / "omnibase_internal"
    ws.canonical = declared / ".venv" / "bin" / "onex-host-reconcile"
    ws.install_canonical(0)

    ws.run_tick(OMNIBASE_INTERNAL_HOME=str(declared))

    assert ws.canonical_calls()


def test_a_declared_internal_home_is_not_searched_past(
    ws: _Workspace, tmp_path: Path
) -> None:
    """A declaration that holds no command is an ABSENT reconciler, not a guess.

    The sibling clone holds the command here, and the declaration points
    somewhere else: falling through to the sibling would run a clone the
    operator did not name.
    """
    ws.remove_reconciler()
    ws.install_canonical(0)
    empty = tmp_path / "declared-but-empty"
    empty.mkdir()

    ws.run_tick(OMNIBASE_INTERNAL_HOME=str(empty))

    assert not ws.canonical_calls()
    status = ws.status_file.read_text(encoding="utf-8")
    assert "DRIFT: no workspace reconciler" in status
    assert str(empty / ".venv" / "bin" / "onex-host-reconcile") in status


def test_the_dispatch_venv_is_not_where_the_command_is_looked_for(
    ws: _Workspace,
) -> None:
    """The 2026-10-07 defect: the tick looked in a venv that never held it."""
    ws.remove_reconciler()
    in_dispatch_venv = ws.root / ".onex-dispatch-venv" / "bin" / "onex-host-reconcile"
    in_dispatch_venv.parent.mkdir(parents=True)
    in_dispatch_venv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    in_dispatch_venv.chmod(0o755)

    ws.run_tick()

    status = ws.status_file.read_text(encoding="utf-8")
    assert "DRIFT: no workspace reconciler" in status
    assert ".onex-dispatch-venv" not in status


def test_a_stale_sibling_beside_a_symlinked_omni_home_is_passed_over(
    tmp_path: Path,
) -> None:
    """h201's shape: OMNI_HOME is a symlink, and a stale clone sits beside the link.

    the registry root under the home directory is a symlink into a data volume;
    the ``omnibase_internal`` beside the link is an old copy with no command, and
    the one beside the link's target is the clone the timer keeps current. The first directory is the wrong answer; the
    first directory that holds the command is the right one.
    """
    real = tmp_path / "data"
    ws = _Workspace(real)
    ws.remove_reconciler()
    ws.install_canonical(0)
    link_dir = tmp_path / "home"
    link_dir.mkdir()
    link = link_dir / ws.root.name
    link.symlink_to(ws.root)
    stale = link_dir / "omnibase_internal"
    stale.mkdir()

    ws.run_tick(OMNI_HOME=str(link))

    assert ws.canonical_calls(), "the clone beside the resolved target was not used"
    assert "in sync" in ws.status_file.read_text(encoding="utf-8")


def test_the_sibling_as_written_wins_when_it_holds_the_command(
    tmp_path: Path,
) -> None:
    real = tmp_path / "data"
    ws = _Workspace(real)
    ws.remove_reconciler()
    link_dir = tmp_path / "home"
    link_dir.mkdir()
    link = link_dir / ws.root.name
    link.symlink_to(ws.root)
    written = link_dir / "omnibase_internal" / ".venv" / "bin" / "onex-host-reconcile"
    written.parent.mkdir(parents=True)
    log = tmp_path / "written.log"
    written.write_text(f'#!/usr/bin/env bash\necho ran >> "{log}"\n', encoding="utf-8")
    written.chmod(0o755)
    ws.install_canonical(0)

    ws.run_tick(OMNI_HOME=str(link))

    assert log.exists(), "the sibling as written was passed over"
    assert not ws.canonical_calls()


def test_a_non_executable_command_is_not_run(ws: _Workspace) -> None:
    ws.remove_reconciler()
    ws.install_canonical(0)
    ws.canonical.chmod(0o644)

    ws.run_tick()

    assert not ws.canonical_calls()
    assert "DRIFT: no workspace reconciler" in ws.status_file.read_text(
        encoding="utf-8"
    )


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
    ws.set_reconciler_exit(2)

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


def test_session_line_prints_drift_when_a_surface_could_not_be_proven(
    ws: _Workspace,
) -> None:
    """The reconciler said a surface is not at target; the session must say so.

    This is the whole reason the status line exists: drift becomes visible
    before any work is planned, rather than at the first failed dispatch.
    """
    ws.set_reconciler_exit(2)
    ws.run_tick()

    result = ws.run_session_line()

    assert result.returncode == 0
    assert "DRIFT" in result.stdout
    assert "in sync" not in result.stdout


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


# --------------------------------------------------------------------------- #
# Host-drift surface (OMN-17427)
# --------------------------------------------------------------------------- #
_HOST_OK = (
    "host-drift: OK 4/4 hosts reporting, 2 open drift within bound "
    "as of 2026-10-07T05:30:00Z"
)
_HOST_ALERT = (
    "host-drift: ALERT 3 — h202 heartbeat stale 52m; "
    "h201 unit:onex-internal-clone-sync drift past bound 1h05m "
    "(service Result=exit-code) as of 2026-10-07T05:30:00Z"
)


def _write_host_status(ws: _Workspace, line: str, age_minutes: int = 2) -> Path:
    status = ws.state / "hooks" / "host-drift.status"
    # Only the first line belongs in the transcript; support no final newline.
    status.write_text(f"{line}\nsecond line must not be printed", encoding="utf-8")
    old = time.time() - 60 * age_minutes
    os.utime(status, (old, old))
    return status


def test_host_drift_absent_is_silent(ws: _Workspace) -> None:
    ws.status_file.write_text("clones/venv: in sync as of now\n", encoding="utf-8")

    result = ws.run_session_line(OMNICLAUDE_SESSION_INTENT="normal")

    assert result.returncode == 0, result.stderr
    assert "[workspace-sync] clones/venv: in sync" in result.stdout
    assert "[host-drift]" not in result.stdout


@pytest.mark.parametrize("line", [_HOST_OK, _HOST_ALERT], ids=["ok", "alert"])
@pytest.mark.parametrize(
    "workspace_age", [2, 40], ids=["workspace-fresh", "workspace-stale"]
)
def test_host_drift_fresh_is_printed_after_workspace_verdict(
    ws: _Workspace, line: str, workspace_age: int
) -> None:
    ws.status_file.write_text("clones/venv: in sync as of now\n", encoding="utf-8")
    old = time.time() - 60 * workspace_age
    os.utime(ws.status_file, (old, old))
    _write_host_status(ws, line)

    result = ws.run_session_line(OMNICLAUDE_SESSION_INTENT="normal")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == f"[host-drift] {line} (checked 2m ago)"
    assert "second line" not in result.stdout
    assert result.stdout.index("[workspace-sync]") < result.stdout.index("[host-drift]")


@pytest.mark.parametrize("age_minutes", [35, 36, 40])
def test_host_drift_staleness_bound(ws: _Workspace, age_minutes: int) -> None:
    ws.status_file.write_text("clones/venv: in sync as of now\n", encoding="utf-8")
    _write_host_status(ws, _HOST_OK, age_minutes)

    result = ws.run_session_line(OMNICLAUDE_SESSION_INTENT="normal")

    assert result.returncode == 0, result.stderr
    if age_minutes <= 35:
        assert result.stdout.splitlines()[-1] == (
            f"[host-drift] {_HOST_OK} (checked {age_minutes}m ago)"
        )
    else:
        assert result.stdout.splitlines()[-2:] == [
            f"[host-drift] {_HOST_OK}",
            f"[host-drift]   (host-drift verdict is {age_minutes}m old — "
            "the drift check itself has stopped reporting; treat it as an ALERT)",
        ]


def test_host_drift_prints_when_workspace_status_is_absent(ws: _Workspace) -> None:
    _write_host_status(ws, _HOST_ALERT)

    result = ws.run_session_line(OMNICLAUDE_SESSION_INTENT="normal")

    assert result.returncode == 0, result.stderr
    assert (
        "[workspace-sync] UNKNOWN: no reconcile tick has run yet on this host."
        in result.stdout
    )
    assert "reconcile-workspace-venvs.sh --check" in result.stdout
    assert (
        result.stdout.splitlines()[-1] == f"[host-drift] {_HOST_ALERT} (checked 2m ago)"
    )


@pytest.mark.parametrize("intent", ["quiet", "tick"])
def test_host_drift_respects_silent_intent(
    ws: _Workspace, tmp_path: Path, intent: str
) -> None:
    import shutil

    # The planted healthy tree controls the independent load-path alarm.
    clone, _ = _plant_hook_tree(tmp_path, "omniclaude")
    shutil.copytree(
        _REPO_ROOT / "plugins" / "onex" / "lib", clone / "plugins" / "onex" / "lib"
    )
    _write_host_status(ws, _HOST_ALERT, 40)
    result = subprocess.run(
        [
            "bash",
            str(clone / "plugins" / "onex" / "hooks" / "scripts" / _SESSION_LINE.name),
        ],
        input=_STDIN,
        capture_output=True,
        text=True,
        env=ws.env(OMNICLAUDE_SESSION_INTENT=intent),
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize("unknown_status", ["workspace-reconcile", "host-drift"])
def test_host_drift_survives_unknown_age(
    ws: _Workspace, tmp_path: Path, unknown_status: str
) -> None:
    import shlex
    import shutil

    ws.status_file.write_text("clones/venv: in sync as of now\n", encoding="utf-8")
    _write_host_status(ws, _HOST_OK)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Fail only the chosen mtime probe; the current clock still works.
    for command in ("date", "stat"):
        real = shutil.which(command)
        assert real is not None
        wrapper = bin_dir / command
        wrapper.write_text(
            "#!/bin/bash\n"
            f'case "$*" in *{unknown_status}.status*) exit 1 ;; esac\n'
            f'exec {shlex.quote(real)} "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)

    result = ws.run_session_line(
        OMNICLAUDE_SESSION_INTENT="normal", PATH=f"{bin_dir}:{os.environ['PATH']}"
    )

    assert result.returncode == 0, result.stderr
    if unknown_status == "workspace-reconcile":
        assert (
            "[workspace-sync]   (verdict age UNKNOWN — treat it as unproven)"
            in result.stdout
        )
        assert (
            result.stdout.splitlines()[-1]
            == f"[host-drift] {_HOST_OK} (checked 2m ago)"
        )
    else:
        assert result.stdout.splitlines()[-2:] == [
            f"[host-drift] {_HOST_OK}",
            "[host-drift]   (host-drift verdict age UNKNOWN — "
            "the drift check itself has stopped reporting; treat it as an ALERT)",
        ]


def test_host_drift_respects_lite_mode(ws: _Workspace) -> None:
    _write_host_status(ws, _HOST_ALERT)

    result = ws.run_session_line(OMNICLAUDE_MODE="lite")

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_host_drift_first_line_without_final_newline(ws: _Workspace) -> None:
    status = _write_host_status(ws, _HOST_ALERT)
    status.write_text(_HOST_ALERT, encoding="utf-8")

    result = ws.run_session_line(OMNICLAUDE_SESSION_INTENT="normal")

    assert result.returncode == 0, result.stderr
    assert (
        result.stdout.splitlines()[-1] == f"[host-drift] {_HOST_ALERT} (checked 0m ago)"
    )


# --------------------------------------------------------------------------- #
# The load path this hook executes from (OMN-16497)
# --------------------------------------------------------------------------- #
#
# Measured 2026-09-14: $OMNI_HOME/omniclaude carried core.bare=true and sat 15
# commits behind origin/dev for three days. It is the symlink target of the
# plugin every live PreToolUse hook runs from, so every guard merged in that
# window was dark on every running session. This line reported
# "clones/venv: in sync" throughout, truthfully: the reconciler it quotes
# checks core.bare, but only over SIBLING_CLONE_MANIFEST, and `omniclaude` is
# not in that list.
#
# These tests run the REAL script from inside a throwaway clone, so
# ${BASH_SOURCE[0]} genuinely resolves there. Nothing is stubbed and no env
# override exists — an override would be the bypass this check exists to close.


def _plant_hook_tree(root: Path, name: str) -> tuple[Path, Path]:
    """A clone containing a real copy of the hook tree, with a real upstream.

    The hook resolves its load path from its own location, so the only faithful
    test is one where the script really lives inside the repository under test.
    """
    import shutil

    seed = root / "_lp_seed" / name
    (seed / "plugins" / "onex").mkdir(parents=True)
    shutil.copytree(
        _REPO_ROOT / "plugins" / "onex" / "hooks", seed / "plugins" / "onex" / "hooks"
    )
    _git("init", "--quiet", "-b", "dev", cwd=seed)
    _git("config", "user.email", "test@example.com", cwd=seed)
    _git("config", "user.name", "Test", cwd=seed)
    _git("add", "-A", cwd=seed)
    _git("commit", "--quiet", "-m", "hook tree", cwd=seed)

    upstream = root / "_lp_upstream" / f"{name}.git"
    upstream.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(seed), str(upstream)],
        check=True,
        env=scrub_git_location_env(os.environ),
    )
    clone = root / "_lp" / name
    clone.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--quiet", "-b", "dev", str(upstream), str(clone)],
        check=True,
        env=scrub_git_location_env(os.environ),
    )
    return clone, seed


def _run_from_tree(clone: Path, ws: _Workspace) -> subprocess.CompletedProcess[str]:
    script = (
        clone
        / "plugins"
        / "onex"
        / "hooks"
        / "scripts"
        / "session_start_workspace_sync.sh"
    )
    return subprocess.run(
        ["bash", str(script)],
        input=_STDIN,
        capture_output=True,
        text=True,
        env=ws.env(),
        check=False,
    )


def test_load_path_healthy_raises_no_alarm(ws: _Workspace, tmp_path: Path) -> None:
    """Positive control. Without this, an always-ALARM bug reads as a pass."""
    clone, _ = _plant_hook_tree(tmp_path, "omniclaude")
    result = _run_from_tree(clone, ws)
    assert result.returncode == 0, result.stderr
    assert "ALARM" not in result.stdout, result.stdout
    assert "[workspace-sync]" in result.stdout, result.stdout


def test_load_path_bare_clone_raises_an_alarm(ws: _Workspace, tmp_path: Path) -> None:
    clone, _ = _plant_hook_tree(tmp_path, "omniclaude")
    _git("config", "core.bare", "true", cwd=clone)
    result = _run_from_tree(clone, ws)
    assert result.returncode == 0, result.stderr
    assert "ALARM" in result.stdout, result.stdout
    assert "core.bare=true" in result.stdout, result.stdout
    # The alarm must name the tree and the repair, not just the condition.
    assert str(clone) in result.stdout, result.stdout
    assert "core.bare false" in result.stdout, result.stdout
    # A new session is the only surface that re-reads hooks.json.
    assert "NEW session" in result.stdout, result.stdout


def test_load_path_behind_upstream_raises_an_alarm(
    ws: _Workspace, tmp_path: Path
) -> None:
    clone, seed = _plant_hook_tree(tmp_path, "omniclaude")
    (seed / "marker.txt").write_text("moved on\n", encoding="utf-8")
    _git("add", "-A", cwd=seed)
    _git("commit", "--quiet", "-m", "upstream moves on", cwd=seed)
    _git(
        "push",
        "--quiet",
        str(tmp_path / "_lp_upstream" / "omniclaude.git"),
        "dev",
        cwd=seed,
    )
    # The clone fetches (refs advance) and does NOT fast-forward — the measured
    # shape. `behind` is read from the remote-tracking ref already on disk.
    _git("fetch", "--quiet", "origin", cwd=clone)

    result = _run_from_tree(clone, ws)
    assert result.returncode == 0, result.stderr
    assert "ALARM" in result.stdout, result.stdout
    assert "1 commit(s) behind" in result.stdout, result.stdout
    assert "pull --ff-only" in result.stdout, result.stdout


def test_load_path_alarm_never_blocks_and_still_prints_the_verdict(
    ws: _Workspace, tmp_path: Path
) -> None:
    """The alarm is additive: the cached verdict line must still be printed."""
    clone, _ = _plant_hook_tree(tmp_path, "omniclaude")
    _git("config", "core.bare", "true", cwd=clone)
    ws.status_file.write_text("clones/venv: in sync as of now\n", encoding="utf-8")
    result = _run_from_tree(clone, ws)
    assert result.returncode == 0, result.stderr
    assert "ALARM" in result.stdout, result.stdout
    assert "clones/venv: in sync" in result.stdout, result.stdout


def test_load_path_probe_survives_a_non_git_tree(
    ws: _Workspace, tmp_path: Path
) -> None:
    """A hook tree outside any repository is not an alarm — it is unknowable,
    and a hook that cannot answer must not block or invent a verdict."""
    import shutil

    plain = tmp_path / "_lp_plain" / "plugins" / "onex"
    plain.mkdir(parents=True)
    shutil.copytree(_REPO_ROOT / "plugins" / "onex" / "hooks", plain / "hooks")
    result = subprocess.run(
        ["bash", str(plain / "hooks" / "scripts" / "session_start_workspace_sync.sh")],
        input=_STDIN,
        capture_output=True,
        text=True,
        env={**ws.env(), "GIT_CEILING_DIRECTORIES": str(tmp_path)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ALARM" not in result.stdout, result.stdout


# --------------------------------------------------------------------------- #
# A half-applied clone (OMN-18358)
# --------------------------------------------------------------------------- #
#
# The OMN-16497 reference-transaction guard used to abort a refused branch
# switch AFTER git had already written the target tree and index, leaving the
# clone on the target tree with HEAD behind and every changed path staged.
# git writes no reflog entry for an aborted transaction, so the only visible
# trace was phantom staged paths in a clone nobody was looking at. Measured on
# $OMNI_HOME/omniclaude 2026-09-14T07:0xZ: 420 staged, 0 worktree-modified, 0
# untracked.
#
# The guard now restores the tree itself. This alarm is the backstop for the
# case it declines -- a half-applied clone it could not account for, or one
# half-applied by a git version or a path that predates the fix.


def _half_apply(clone: Path) -> None:
    """Stage a change without touching the worktree relative to the index.

    That is the exact signature: the index differs from HEAD, and the worktree
    agrees with the index. An ordinary dirty tree does NOT look like this, which
    is why the alarm can tell them apart.
    """
    (clone / "half_applied.txt").write_text(
        "staged by a refused checkout\n", encoding="utf-8"
    )
    _git("add", "half_applied.txt", cwd=clone)


def test_load_path_half_applied_clone_raises_an_alarm(
    ws: _Workspace, tmp_path: Path
) -> None:
    clone, _ = _plant_hook_tree(tmp_path, "omniclaude")
    _half_apply(clone)

    result = _run_from_tree(clone, ws)

    assert result.returncode == 0, result.stderr
    assert "ALARM" in result.stdout, result.stdout
    assert "half-applied" in result.stdout, result.stdout
    # The alarm must name the tree and the sanctioned repair, not just the
    # condition -- an alarm nobody can act on is noise that gets filtered.
    assert str(clone) in result.stdout, result.stdout
    assert "converge-canonical-clone.sh" in result.stdout, result.stdout


def test_load_path_half_apply_alarm_is_silent_on_a_clean_clone(
    ws: _Workspace, tmp_path: Path
) -> None:
    """Positive control for the probe above: an always-ALARM bug would make the
    test above pass against any clone at all."""
    clone, _ = _plant_hook_tree(tmp_path, "omniclaude")

    result = _run_from_tree(clone, ws)

    assert result.returncode == 0, result.stderr
    assert "half-applied" not in result.stdout, result.stdout


def test_load_path_half_apply_alarm_does_not_fire_on_an_ordinary_dirty_tree(
    ws: _Workspace, tmp_path: Path
) -> None:
    """An unstaged local edit is ordinary work, not a half-apply.

    Reporting it here would make the alarm fire on every session where someone
    was mid-edit, and an alarm that fires constantly is one nobody reads.
    """
    clone, _ = _plant_hook_tree(tmp_path, "omniclaude")
    (clone / "scratch.txt").write_text("just editing\n", encoding="utf-8")

    result = _run_from_tree(clone, ws)

    assert result.returncode == 0, result.stderr
    assert "half-applied" not in result.stdout, result.stdout


# --------------------------------------------------------------------------- #
# A decline is recorded as a decline, never as "in sync" (OMN-18608)
# --------------------------------------------------------------------------- #
def test_a_declined_reconcile_is_not_recorded_as_in_sync(ws: _Workspace) -> None:
    """Exit 4 is 'I did nothing, a live peer holds the lock'.

    The reconciler used to return 0 for that, and this verdict table then wrote
    ``verdict="in sync"`` on a run that reconciled nothing. That is precisely
    what hid the 2026-09-17 outage for 35 minutes, in the log meant to reveal
    it: every tick reported success while a leaked lock stopped all work.
    """
    ws.set_reconciler_exit(4)

    result = ws.run_tick()

    assert result.returncode == 0, "a tick must never fail the tool call that fired it"
    receipts = ws.receipts.read_text(encoding="utf-8")
    assert "reconciler_exit=4" in receipts
    assert "declined" in receipts
    assert "in sync" not in receipts, (
        f"a run that reconciled nothing was recorded as in sync: {receipts!r}"
    )


def test_a_decline_does_not_raise_a_drift_alarm(ws: _Workspace) -> None:
    """Declining is the NORMAL outcome of concurrent ticks, not a defect.

    Several hook ticks fire at once by design, so most declines are healthy.
    Reporting DRIFT on each would make the common case look broken, and a status
    surface that cries wolf on every tick is one nobody reads -- which is how
    the real failure went unnoticed. Fixing an unreliable receipt by making it
    noisy is not a fix.
    """
    ws.set_reconciler_exit(4)

    ws.run_tick()

    assert not ws.status_file.exists() or "DRIFT" not in ws.status_file.read_text(
        encoding="utf-8"
    )


def test_a_decline_does_not_overwrite_a_verdict_a_real_run_earned(
    ws: _Workspace,
) -> None:
    """The status file keeps the last verdict some run actually proved.

    A decline proves nothing in either direction, so it must not claim the host
    is in sync AND must not erase a finding a previous run did earn. This is the
    pair to the test above: together they say a decline leaves the file alone,
    rather than merely not writing DRIFT to it.
    """
    ws.set_reconciler_exit(2)
    ws.run_tick()
    earned = ws.status_file.read_text(encoding="utf-8")
    assert "DRIFT" in earned

    ws.set_reconciler_exit(4)
    ws.run_tick(ONEX_RECONCILE_TICK_SECONDS="0")

    assert ws.status_file.read_text(encoding="utf-8") == earned, (
        "a decline overwrote the verdict a real run had earned"
    )
