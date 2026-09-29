# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Run the REAL hook entrypoints the way Claude Code does (OMN-20109).

Claude Code, for one tool call, looks up the hooks registered for the event and
the tool name in ``hooks.json``, starts each as its own process, writes the hook
payload JSON to its stdin, and waits for it to exit (cancelling it after a
timeout). This module does the same, against an isolated state directory and
journal, and adds three things a unit test cannot: it tags every process the
hooks start, it samples the process table while they run, and it kills the whole
process group of a hook that overruns its budget so a failing test cannot itself
become the leak it is looking for.

What this module does not do: it does not mock a hook, a library, the journal or
the bus. The unit tests in ``tests/hooks`` own those. A test here is green only
when the shipped scripts behave.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO_ROOT / "plugins" / "onex"
HOOKS_DIR = PLUGIN_DIR / "hooks"
HOOKS_JSON = HOOKS_DIR / "hooks.json"

TOKEN_ENV = "ONEX_HOOK_SYSTEST_TOKEN"

# Sampling interval of the process watcher. Small enough to see a short-lived
# `jq`, large enough not to be the load it measures.
_SAMPLE_INTERVAL_S = 0.003
# A full token scan walks every process on the host, so it runs on a slower
# cadence than the child-tree walk.
_SCAN_EVERY_N_SAMPLES = 20

_SESSION_ID = "sess-omn20109-systest"


# ---------------------------------------------------------------------------
# Registration: which hooks Claude Code would run for one tool call
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegisteredHook:
    """One ``command`` hook resolved out of ``hooks.json``."""

    event: str
    matcher: str
    argv: tuple[str, ...]

    @property
    def script(self) -> Path:
        return Path(self.argv[0])

    @property
    def name(self) -> str:
        return self.script.name


def _resolve_command(command: str) -> tuple[str, ...]:
    expanded = command.replace("${CLAUDE_PLUGIN_ROOT}", str(PLUGIN_DIR))
    return tuple(shlex.split(expanded))


def registered_hooks(event: str, tool_name: str | None = None) -> list[RegisteredHook]:
    """The hooks Claude Code runs for ``event`` (and ``tool_name``).

    Read from the shipped ``hooks.json``, so a hook added there is part of every
    budget the moment it is registered. A matcher is a regular expression that
    must match the whole tool name, which is how the harness applies it.
    """
    document = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    found: list[RegisteredHook] = []
    for group in document.get("hooks", {}).get(event, []):
        matcher = group.get("matcher", "")
        if tool_name is not None and matcher:
            if re.fullmatch(matcher, tool_name) is None:
                continue
        for hook in group.get("hooks", []):
            if hook.get("type") != "command":
                continue
            found.append(
                RegisteredHook(
                    event=event,
                    matcher=matcher,
                    argv=_resolve_command(hook["command"]),
                )
            )
    return found


def hook_payload(
    event: str,
    *,
    tool_name: str = "Bash",
    command: str = "true",
    skill: str | None = None,
    tool_use_id: str | None = None,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """A harmless payload of the shape Claude Code sends for ``event``."""
    payload: dict[str, Any] = {
        "hook_event_name": event,
        "session_id": _SESSION_ID,
        "transcript_path": str(REPO_ROOT / ".onex_state" / "systest-transcript.jsonl"),
        "cwd": str(cwd or REPO_ROOT),
        "permission_mode": "default",
        "tool_name": tool_name,
        "tool_use_id": tool_use_id or f"toolu_{uuid.uuid4().hex[:24]}",
    }
    if tool_name == "Skill":
        payload["tool_input"] = {"skill": skill or "onex:delegate"}
    elif tool_name == "Bash":
        payload["tool_input"] = {"command": command, "description": "systest"}
    else:
        payload["tool_input"] = {}
    if event == "PostToolUse":
        payload["tool_response"] = {"stdout": "", "stderr": "", "interrupted": False}
        payload["duration_ms"] = 12
    return payload


# ---------------------------------------------------------------------------
# The isolated rig
# ---------------------------------------------------------------------------


@dataclass
class Rig:
    """An isolated state directory, journal and environment for one test."""

    root: Path
    token: str
    state_dir: Path
    journal_dir: Path
    spawn_log: Path
    env: dict[str, str] = field(default_factory=dict)

    def shim_pids(self) -> dict[int, str]:
        """Every PATH-resolved command the hooks ran, by pid: exact, not sampled."""
        found: dict[int, str] = {}
        try:
            lines = self.spawn_log.read_text(encoding="utf-8").splitlines()
        except OSError:
            return found
        for line in lines:
            pid, _, name = line.partition(" ")
            if pid.isdigit():
                found[int(pid)] = name
        return found

    def journal_files(self) -> list[Path]:
        if not self.journal_dir.is_dir():
            return []
        return sorted(
            p
            for p in self.journal_dir.iterdir()
            if p.is_file() and p.name.endswith(".json") and not p.name.startswith(".")
        )

    def log_tail(self, limit: int = 2000) -> str:
        logs = self.state_dir / "hooks" / "logs"
        if not logs.is_dir():
            return "<no hook logs written>"
        chunks = []
        for log in sorted(logs.glob("*.log")):
            text = log.read_text(encoding="utf-8", errors="replace")[-limit:]
            if text.strip():
                chunks.append(f"--- {log.name}\n{text}")
        return "\n".join(chunks) or "<hook logs empty>"


SPAWN_LOG_ENV = "ONEX_HOOK_SYSTEST_SPAWNLOG"

# Commands a hook script reaches through PATH. Each gets a two-line wrapper that
# appends its pid to the spawn log and execs the real binary, so the process
# count is exact for everything a hook starts by name rather than a sample.
_SHIMMED_COMMANDS = (
    "awk", "basename", "cat", "chmod", "cp", "curl", "cut", "date", "dirname",
    "env", "find", "git", "grep", "head", "hostname", "id", "jq", "kill",
    "ln", "mkdir", "mktemp", "mv", "pgrep", "ps", "readlink", "realpath", "rm",
    "sed", "shasum", "sleep", "sort", "ssh", "stat", "tail", "tee", "touch",
    "tr", "uname", "uniq", "wc", "xargs",
)  # fmt: skip


def _install_shims(shim_dir: Path, spawn_log: Path, path: str) -> Path:
    shim_dir.mkdir(parents=True, exist_ok=True)
    for name in _SHIMMED_COMMANDS:
        real = shutil.which(name, path=path)
        if real is None:
            continue
        wrapper = shim_dir / name
        wrapper.write_text(
            "#!/bin/sh\n"
            f"printf '%s %s\\n' \"$$\" {shlex.quote(name)} >> {shlex.quote(str(spawn_log))}\n"
            f'exec {shlex.quote(real)} "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
    return shim_dir


def _python_shim(shim_dir: Path, spawn_log: Path) -> Path:
    """The hook interpreter, counted. ``PLUGIN_PYTHON_BIN`` is the first thing
    ``find_python`` in common.sh consults, so the hooks run this wrapper, which
    execs the interpreter that is running the tests (the repo venv)."""
    shim_dir.mkdir(parents=True, exist_ok=True)
    wrapper = shim_dir / "hook-python"
    wrapper.write_text(
        "#!/bin/sh\n"
        f"printf '%s %s\\n' \"$$\" python >> {shlex.quote(str(spawn_log))}\n"
        f'exec {shlex.quote(sys.executable)} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


def _write_drainer_status(root: Path) -> None:
    """A drainer status that lists the event classes as publishable.

    ``hook_claude_capture`` journals nothing unless the drainer beside the
    journal says ``hook.event`` is publishable, so without this file the
    capture hook exits early and every test that touches it is vacuous.
    """
    now = time.time()
    status = {
        "last_cycle_at": now,
        "last_publish_at": now,
        "published_total": 1,
        "pid": os.getpid(),
        "refused_event_types": [],
        "publishable_event_types": [
            "hook.event",
            "tool.executed",
            "skill.started",
            "skill.completed",
            "session.started",
            "session.ended",
        ],
    }
    (root / "hook_emit_drainer_status.json").write_text(
        json.dumps(status), encoding="utf-8"
    )


def make_rig(root: Path) -> Rig:
    """Build a rig under ``root``. Nothing here can touch the live spool."""
    state_dir = root / "state"
    journal_dir = root / "journal"
    state_dir.mkdir(parents=True, exist_ok=True)
    journal_dir.mkdir(parents=True, exist_ok=True)
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    # Several registered hooks write under $HOME (checkpoints, changeset events)
    # or act on $OMNI_HOME (the reconcile tick, the merge clone sync). A test
    # must never touch the operator home or the shared clones, so both are
    # replaced: HOME by an empty directory, OMNI_HOME removed, which those hooks
    # read as "not a workspace" and exit.
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    env["OMNI_HOME"] = str(workspace)
    env["HOME"] = str(home)
    env.pop("CLAUDE_PLUGIN_DATA", None)
    spawn_log = root / "spawn.log"
    spawn_log.write_text("", encoding="utf-8")
    shim_dir = _install_shims(root / "shims", spawn_log, env["PATH"])
    env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"
    env["PLUGIN_PYTHON_BIN"] = str(_python_shim(root / "shims", spawn_log))
    env[SPAWN_LOG_ENV] = str(spawn_log)
    _write_drainer_status(root)
    env.update(
        {
            TOKEN_ENV: token,
            "ONEX_STATE_DIR": str(state_dir),
            "ONEX_HOOK_EMIT_JOURNAL_DIR": str(journal_dir),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN_DIR),
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "OMNICLAUDE_PROJECT_ROOT": str(REPO_ROOT),
            # Pinned so a mask or mode exported by the surrounding session
            # cannot make a hook exit at its first guard and read as a pass:
            # a hook that never ran is the failure this suite exists to catch.
            "ONEX_HOOKS_MASK": "",
            "OMNICLAUDE_MODE": "full",
            "ONEX_CORRELATION_ID": _SESSION_ID,
            # The bus is never reachable from a test. The hook edge is
            # journal-only, so this must be invisible to it; the broken-emit
            # test overrides it with an address that swallows connections.
            "KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:1",
        }
    )
    # A slack alert from a HARD_BLOCK guard must never leave the machine.
    for key in [k for k in env if k.startswith("SLACK_")]:
        env.pop(key)
    return Rig(
        root=root,
        token=token,
        state_dir=state_dir,
        journal_dir=journal_dir,
        spawn_log=spawn_log,
        env=env,
    )


# ---------------------------------------------------------------------------
# Process observation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    ppid: int
    created: float
    cmdline: str


def _info(proc: psutil.Process) -> ProcInfo | None:
    try:
        return ProcInfo(
            pid=proc.pid,
            ppid=proc.ppid(),
            created=proc.create_time(),
            cmdline=" ".join(proc.cmdline())[:240],
        )
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
        return None


def tagged_processes(token: str) -> dict[tuple[int, float], ProcInfo]:
    """Every live process whose environment carries ``token``.

    The token is inherited by everything a hook forks, so this finds children
    that were disowned, that changed process group, or that were reparented to
    pid 1, which a walk of the child tree cannot.
    """
    found: dict[tuple[int, float], ProcInfo] = {}
    me = os.getpid()
    for proc in psutil.process_iter():
        if proc.pid == me:
            continue
        try:
            if proc.status() == psutil.STATUS_ZOMBIE:
                continue
            if proc.environ().get(TOKEN_ENV) != token:
                continue
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
            OSError,
        ):
            continue
        info = _info(proc)
        if info is not None:
            found[(info.pid, info.created)] = info
    return found


class ProcessLedger:
    """Record every distinct process the hooks under test start.

    Runs a sampling thread for the life of the ``with`` block. ``seen`` is the
    set of distinct processes observed, a LOWER BOUND on what was spawned.
    ``peak_tagged`` is the largest number of tagged processes alive at one
    sample of the full scan.
    """

    def __init__(self, rig: Rig, root_pids: Iterable[int] = ()) -> None:
        self.rig = rig
        self.token = rig.token
        self._roots: set[int] = set(root_pids)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.seen: dict[tuple[int, float], ProcInfo] = {}
        self.peak_tagged = 0

    def add_root(self, pid: int) -> None:
        with self._lock:
            self._roots.add(pid)

    def _sample_tree(self) -> None:
        with self._lock:
            roots = list(self._roots)
        for pid in roots:
            try:
                root = psutil.Process(pid)
                members = [root, *root.children(recursive=True)]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            for proc in members:
                info = _info(proc)
                if info is not None:
                    self.seen.setdefault((info.pid, info.created), info)

    def _run(self) -> None:
        n = 0
        while not self._stop.is_set():
            self._sample_tree()
            n += 1
            if n % _SCAN_EVERY_N_SAMPLES == 0:
                scan = tagged_processes(self.token)
                self.peak_tagged = max(self.peak_tagged, len(scan))
                for key, info in scan.items():
                    self.seen.setdefault(key, info)
            time.sleep(_SAMPLE_INTERVAL_S)

    def __enter__(self) -> ProcessLedger:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        scan = tagged_processes(self.token)
        self.peak_tagged = max(self.peak_tagged, len(scan))
        for key, info in scan.items():
            self.seen.setdefault(key, info)

    @property
    def spawned(self) -> int:
        """Distinct processes the hooks started.

        The union, by pid, of three sources: every hook root the caller
        registered, every command the PATH shims saw (exact), and every process
        the sampler saw. Bash subshells that live under one sampling interval
        are the one thing none of them sees, so this is a lower bound, and the
        budget ceiling is set with this same instrument.
        """
        pids = {pid for pid, _created in self.seen}
        pids |= self._roots
        pids |= set(self.rig.shim_pids())
        return len(pids)

    def processes(self) -> str:
        names = self.rig.shim_pids()
        rows = [
            f"  pid={pid} {names.get(pid, self._name_of(pid))}"
            for pid in sorted(self._all_pids())
        ]
        return "\n".join(rows)

    def _all_pids(self) -> set[int]:
        return {pid for pid, _c in self.seen} | self._roots | set(self.rig.shim_pids())

    def _name_of(self, pid: int) -> str:
        for (seen_pid, _c), info in self.seen.items():
            if seen_pid == pid:
                return info.cmdline
        return "hook root" if pid in self._roots else "?"


def wait_for_settle(token: str, seconds: float) -> dict[tuple[int, float], ProcInfo]:
    """Wait up to ``seconds`` for every tagged process to exit; return leftovers."""
    deadline = time.monotonic() + seconds
    leftovers = tagged_processes(token)
    while leftovers and time.monotonic() < deadline:
        time.sleep(0.1)
        leftovers = tagged_processes(token)
    return leftovers


def kill_tagged(token: str) -> None:
    """Kill every tagged process. Called from fixture teardown so a red test
    never leaves its own children behind."""
    for _ in range(3):
        remaining = tagged_processes(token)
        if not remaining:
            return
        for pid, _created in remaining:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(0.2)


def describe(procs: Iterable[ProcInfo]) -> str:
    return "\n".join(
        f"  pid={p.pid} ppid={p.ppid} {p.cmdline}"
        for p in sorted(procs, key=lambda p: p.pid)
    )


# ---------------------------------------------------------------------------
# Running a hook
# ---------------------------------------------------------------------------


@dataclass
class HookRun:
    hook: str
    returncode: int | None
    stdout: str
    stderr: str
    wall_seconds: float
    timed_out: bool
    pid: int

    def summary(self) -> str:
        return (
            f"{self.hook}: rc={self.returncode} timed_out={self.timed_out} "
            f"wall={self.wall_seconds:.2f}s stderr={self.stderr[-400:]!r}"
        )


def _reap_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def start_hook(
    hook: RegisteredHook | Sequence[str],
    payload: dict[str, Any],
    rig: Rig,
    *,
    extra_env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> tuple[subprocess.Popen[str], float]:
    argv = list(hook.argv) if isinstance(hook, RegisteredHook) else list(hook)
    env = dict(rig.env)
    if extra_env:
        env.update(extra_env)
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(cwd or REPO_ROOT),
        # Its own session, as a harness gives a hook: a group kill reaches
        # every child the hook did not detach, and a child that DID detach is
        # still found by the environment token.
        start_new_session=True,
    )
    assert proc.stdin is not None
    try:
        proc.stdin.write(json.dumps(payload))
        proc.stdin.close()
    except BrokenPipeError:
        pass
    # communicate() would flush a closed stdin and raise; the payload is sent.
    proc.stdin = None
    return proc, started


def finish_hook(
    name: str,
    proc: subprocess.Popen[str],
    started: float,
    budget_seconds: float,
) -> HookRun:
    """Wait up to ``budget_seconds`` for ``proc``; kill its group when it overruns."""
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=budget_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _reap_group(proc.pid)
        stdout, stderr = proc.communicate()
    return HookRun(
        hook=name,
        returncode=proc.returncode,
        stdout=stdout or "",
        stderr=stderr or "",
        wall_seconds=time.monotonic() - started,
        timed_out=timed_out,
        pid=proc.pid,
    )


def run_hook(
    hook: RegisteredHook | Sequence[str],
    payload: dict[str, Any],
    rig: Rig,
    *,
    budget_seconds: float,
    extra_env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> HookRun:
    proc, started = start_hook(hook, payload, rig, extra_env=extra_env, cwd=cwd)
    name = hook.name if isinstance(hook, RegisteredHook) else Path(hook[0]).name
    return finish_hook(name, proc, started, budget_seconds)


def entrypoint(name: str) -> RegisteredHook:
    """A hook by script name, resolved from ``hooks.json`` so it is the shipped
    registration and not a path the test invented."""
    for event in (
        "PreToolUse",
        "PostToolUse",
        "SessionStart",
        "Stop",
        "UserPromptSubmit",
    ):
        for hook in registered_hooks(event):
            if hook.name == name:
                return hook
    raise AssertionError(f"{name} is not registered in {HOOKS_JSON}")
