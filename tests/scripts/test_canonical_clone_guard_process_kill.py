# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Behavioural tests for the process-kill deny class of
``scripts/user-hooks/canonical-clone-guard.py`` (OMN-16742).

Rule 21 of the workspace CLAUDE.md forbids ``pkill`` (it matches every process on the
host, so one lane's cleanup kills seven peers' pushes) but nothing refused it. The
guard now denies ``pkill``, ``killall`` and ``kill`` aimed at a process group or at
a pid list computed by a pattern match, and names the sanctioned form:
``kill <your own pid>``.

DENIED must refuse, ALLOWED near misses must pass (a guard that blocks
``kill -0 <pid>`` or ``echo pkill`` trains agents to route around it), and every
deny reason must carry the sanctioned alternative.
"""

from __future__ import annotations

import pytest

from tests.scripts.test_canonical_clone_guard_bypass import (
    Registry,
    bash,
    registry,  # noqa: F401  (pytest fixture, reused so the registry env is built in one place)
)


def _run(registry: Registry, command: str) -> tuple[bool, str]:  # noqa: F811
    verdict = bash(registry, command)
    return verdict.denied, verdict.reason


DENIED = [
    ("pkill -f", 'pkill -f "pytest"'),
    ("pkill bare", "pkill node"),
    ("pkill -9", "pkill -9 -f prepush"),
    ("pkill after &&", "cd /tmp && pkill -f x"),
    ("pkill absolute path", "/usr/bin/pkill -f x"),
    ("pkill under sudo", "sudo pkill -f x"),
    ("pkill under env", "env FOO=1 pkill x"),
    ("pkill in bash -c", "bash -c 'pkill -f x'"),
    ("pkill over ssh", 'ssh -o BatchMode=yes remote "pkill -f x"'),
    ("pkill after pipe", "echo hi | pkill -f x"),
    ("killall", "killall Python"),
    ("killall -9", "killall -9 node"),
    ("kill negative pgid", "kill -- -1234"),
    ("kill signal then pgid", "kill -9 -1234"),
    ("kill -TERM pgid", "kill -TERM -4321"),
    ("kill -s pgid", "kill -s TERM -4321"),
    ("kill bare pgid", "kill -4321"),
    ("kill all processes", "kill -9 -1"),
    ("kill own group 0", "kill -TERM 0"),
    ("sudo kill -9 -1", "sudo kill -9 -1"),
    ("nohup kill pgid", "nohup kill -9 -1234"),
    ("kill -s 9 -1", "kill -s 9 -1"),
    ("kill --signal=9 -1", "kill --signal=9 -1"),
    ("kill via pgrep", "kill $(pgrep -f pytest)"),
    ("kill via pgrep backticks", "kill `pgrep -f pytest`"),
    ("kill via pidof", "kill -9 $(pidof node)"),
    ("xargs kill", "pgrep -f x | xargs kill"),
    ("xargs kill -9", "ps aux | awk '{print $2}' | xargs kill -9"),
]

ALLOWED = [
    ("kill own pid", "kill 12345"),
    ("kill -9 own pid", "kill -9 12345"),
    ("kill -TERM own pid", "kill -TERM 12345"),
    ("kill -s own pid", "kill -s TERM 12345"),
    ("kill own pid var", 'kill "$PID"'),
    ("kill -0 liveness", "kill -0 12345"),
    ("kill -l list", "kill -l"),
    ("kill two pids", "kill 111 222"),
    ("pgrep read only", "pgrep -f pytest"),
    ("echo mentioning pkill", 'echo "never run pkill -f x"'),
    ("grep for pkill", "grep -rn pkill docs/"),
    ("git commit message", 'git commit -m "guard refuses pkill"'),
    ("gh pr body", 'gh pr create --body "refuses pkill and killall"'),
    ("heredoc documenting", "cat <<'EOF'\npkill -f x\nEOF"),
    ("file named pkill", "ls scripts/pkill_helper.sh"),
    ("kill -0 negative-looking var", "kill -0 $$"),
]


@pytest.mark.unit
@pytest.mark.parametrize(("label", "command"), DENIED, ids=[d[0] for d in DENIED])
def test_denied(registry: Registry, label: str, command: str) -> None:  # noqa: F811
    denied, reason = _run(registry, command)
    assert denied, f"{label}: expected deny for {command!r}"
    assert "kill <your own pid>" in reason
    assert "rule 21" in reason.lower()


@pytest.mark.unit
@pytest.mark.parametrize(("label", "command"), ALLOWED, ids=[a[0] for a in ALLOWED])
def test_allowed(registry: Registry, label: str, command: str) -> None:  # noqa: F811
    denied, reason = _run(registry, command)
    assert not denied, f"{label}: unexpected deny for {command!r}: {reason}"
