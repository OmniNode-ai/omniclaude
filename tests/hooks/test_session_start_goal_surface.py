# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the SessionStart goal-surface hook [OMN-17168].

The hook prints the durable session goal (`<KNOWLEDGE_BASE_INTERNAL_PATH>/beta/
GOAL.md`) at session start: its ``state_as_of``, its age, and its first rows;
and when that goal is missing or stale, the exact re-baseline command.

Four contracted cases, each proved here against a real subprocess run of the
script (not a re-implementation of its logic in Python):

* **present + fresh** — prints the declared ``state_as_of``, the age, and the
  rows, and does NOT print the re-baseline command;
* **present + stale** (>12h) — prints all of the above AND the re-baseline
  command, because a goal older than the last ground state is not this
  session's goal;
* **missing** — prints the full path it looked at plus the re-baseline command;
* **unset env** — prints the exact missing variable name and the expected value,
  and applies no default.

The invariant across all four is ``exit 0``: a SessionStart hook that can fail a
session is worse than one that prints nothing, and this one only prints.

Hermetic: every case builds its own kb-internal tree under ``tmp_path``. No real
clone is read, and ``OMNICLAUDE_MODE=full`` pins mode resolution so the result
does not depend on where pytest happens to be invoked from.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = (
    _REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "session_start_goal_surface.sh"
)

_REBASELINE_FRAGMENT = "Workflow({ name: 'morning-ground-state'"

_GOAL_BODY = """# Session goal — beta

| # | row | state |
|---|-----|-------|
| 1 | staging repin | HOLD until OMN-16804 |
| 2 | Infisical resolver identity | blocked on OMN-16984 |
| 3 | pre-push capacity pool | h101 promoted |
"""


def _run(
    kb_path: str | None,
    *,
    stdin: str = '{"session_id":"sess-goal-01","cwd":"/tmp"}',
) -> subprocess.CompletedProcess[str]:
    """Run the hook with a controlled environment.

    ``kb_path=None`` means the variable is absent, not empty — the two are the
    same to the hook by design (an empty string is no more a usable path than an
    unset one), but the unset case is the one the contract names.
    """
    env = os.environ.copy()
    env.pop("KNOWLEDGE_BASE_INTERNAL_PATH", None)
    # Pin mode so the lite-mode early exit cannot swallow the output depending on
    # the invoking cwd or a developer's ~/.config/omniclaude/mode.
    env["OMNICLAUDE_MODE"] = "full"
    if kb_path is not None:
        env["KNOWLEDGE_BASE_INTERNAL_PATH"] = kb_path
    return subprocess.run(
        ["bash", str(_SCRIPT)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
    )


def _write_goal(root: Path, state_as_of: str | None) -> Path:
    """Create ``<root>/beta/GOAL.md``; omit the frontmatter when ts is None."""
    beta = root / "beta"
    beta.mkdir(parents=True, exist_ok=True)
    goal = beta / "GOAL.md"
    if state_as_of is None:
        goal.write_text(_GOAL_BODY)
    else:
        goal.write_text(f"---\nstate_as_of: {state_as_of}\n---\n{_GOAL_BODY}")
    return goal


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Case 1 — present and fresh
# --------------------------------------------------------------------------- #


def test_fresh_goal_prints_state_as_of_age_and_rows(tmp_path: Path) -> None:
    """A 2h-old goal renders its timestamp, its age, and its rows."""
    ts = _iso(timedelta(hours=-2))
    _write_goal(tmp_path, ts)

    result = _run(str(tmp_path))

    assert result.returncode == 0, result.stderr
    assert ts in result.stdout, (
        f"The declared state_as_of must be printed verbatim so it can be compared "
        f"against today's ground state. stdout:\n{result.stdout}"
    )
    assert "age 2h" in result.stdout, (
        f"Age must be rendered in hours — a raw timestamp alone still has to be "
        f"mentally differenced against now. stdout:\n{result.stdout}"
    )
    assert "staging repin" in result.stdout, (
        f"The goal rows themselves must be printed; a hook that says only 'a goal "
        f"exists' does not put the goal in the session. stdout:\n{result.stdout}"
    )
    assert str(tmp_path / "beta" / "GOAL.md") in result.stdout, (
        "The absolute source path must be printed so the reader can open or "
        "re-baseline the exact file that was read."
    )


def test_fresh_goal_does_not_nag_to_rebaseline(tmp_path: Path) -> None:
    """A fresh goal must NOT print the re-baseline command.

    If the instruction printed unconditionally it would be ignored within a day,
    which is how the foreground rule ended up corrected by hand ~61 times
    (``docs/tracking/2026-08-29-beta-off-the-rails-analysis.md``). The line has to
    mean something when it appears.
    """
    _write_goal(tmp_path, _iso(timedelta(hours=-2)))

    result = _run(str(tmp_path))

    assert result.returncode == 0
    assert _REBASELINE_FRAGMENT not in result.stdout, (
        f"A fresh goal must not carry the re-baseline instruction. "
        f"stdout:\n{result.stdout}"
    )
    assert "STALE" not in result.stdout


@pytest.mark.parametrize(
    "state_as_of",
    [
        "2026-08-30T06:59:00Z",
        "2026-08-30 06:59:00",
        "2026-08-30T06:59:00+00:00",
        "2026-08-30T06:59:00.123456Z",
    ],
    ids=["z", "naked-space", "explicit-offset", "fractional"],
)
def test_state_as_of_timestamp_shapes_are_parsed(
    tmp_path: Path, state_as_of: str
) -> None:
    """Common ISO-8601 spellings parse rather than silently falling back to mtime.

    A fallback to mtime is not a harmless degradation: the file was just written
    by the fixture, so mtime says "fresh" no matter how old the declared goal is.
    An unparsed timestamp therefore turns a stale goal into a fresh-looking one —
    the exact inversion this hook exists to prevent. The hook labels that fallback
    explicitly, and this test asserts the label is absent.
    """
    _write_goal(tmp_path, state_as_of)

    result = _run(str(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "unparsable" not in result.stdout, (
        f"{state_as_of!r} must parse. An unparsed timestamp falls back to mtime, "
        f"which reports a stale goal as fresh. stdout:\n{result.stdout}"
    )
    assert "from file mtime" not in result.stdout


# --------------------------------------------------------------------------- #
# Case 2 — present and stale
# --------------------------------------------------------------------------- #


def test_stale_goal_prints_the_rebaseline_workflow_command(tmp_path: Path) -> None:
    """A goal older than 12h is flagged STALE and carries the exact command."""
    _write_goal(tmp_path, _iso(timedelta(hours=-30)))

    result = _run(str(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "STALE" in result.stdout
    assert _REBASELINE_FRAGMENT in result.stdout, (
        f"The instruction must be the literal runnable call, not a prose "
        f"description of it. stdout:\n{result.stdout}"
    )
    today = datetime.now().strftime("%Y-%m-%d")
    assert f"date: '{today}'" in result.stdout, (
        f"The command must be pre-filled with today's date so it is copy-runnable. "
        f"stdout:\n{result.stdout}"
    )
    # Still shows the stale content: knowing what the old goal said is how you
    # tell whether the re-baseline actually changed anything.
    assert "staging repin" in result.stdout


def test_goal_at_the_threshold_boundary_is_not_stale(tmp_path: Path) -> None:
    """11h59m is fresh; 12h01m is stale. The boundary is asserted, not assumed."""
    _write_goal(tmp_path, _iso(timedelta(hours=-11, minutes=-59)))
    fresh = _run(str(tmp_path))
    assert fresh.returncode == 0
    assert "STALE" not in fresh.stdout, fresh.stdout

    _write_goal(tmp_path, _iso(timedelta(hours=-12, minutes=-1)))
    stale = _run(str(tmp_path))
    assert stale.returncode == 0
    assert "STALE" in stale.stdout, stale.stdout


def test_goal_without_state_as_of_is_labelled_as_mtime_derived(
    tmp_path: Path,
) -> None:
    """No ``state_as_of`` line ⇒ mtime is used AND the substitution is disclosed.

    An undisclosed mtime fallback would let `touch GOAL.md` reset the age of a
    goal nobody re-derived.
    """
    _write_goal(tmp_path, None)

    result = _run(str(tmp_path))

    assert result.returncode == 0
    assert "no state_as_of line" in result.stdout, result.stdout
    assert "from file mtime" in result.stdout, result.stdout


# --------------------------------------------------------------------------- #
# Case 3 — missing
# --------------------------------------------------------------------------- #


def test_missing_goal_prints_path_and_rebaseline_command(tmp_path: Path) -> None:
    """A kb-internal clone with no GOAL.md reports the path it looked at."""
    (tmp_path / "beta").mkdir(parents=True)

    result = _run(str(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "MISSING" in result.stdout
    assert str(tmp_path / "beta" / "GOAL.md") in result.stdout, (
        f"The absolute path looked at must be printed — 'no goal found' with no "
        f"path cannot be acted on. stdout:\n{result.stdout}"
    )
    assert _REBASELINE_FRAGMENT in result.stdout


def test_missing_clone_directory_is_reported_without_failing(tmp_path: Path) -> None:
    """A KNOWLEDGE_BASE_INTERNAL_PATH pointing nowhere is a config error, not a crash."""
    result = _run(str(tmp_path / "does-not-exist"))

    assert result.returncode == 0, result.stderr
    assert "UNRESOLVED" in result.stdout
    assert str(tmp_path / "does-not-exist") in result.stdout


# --------------------------------------------------------------------------- #
# Case 4 — env var unset (CLAUDE.md rule 8)
# --------------------------------------------------------------------------- #


def test_unset_env_names_the_variable_and_the_expected_value() -> None:
    """Unset ⇒ name the variable and the expected value; apply no default.

    Rule 8 exists because a silent default is indistinguishable from success. Here
    the specific harm is sharp: a defaulted clone path would print some other
    checkout's goal, with a credible age, as this session's goal.
    """
    result = _run(None)

    assert result.returncode == 0, result.stderr
    assert "KNOWLEDGE_BASE_INTERNAL_PATH" in result.stdout, (
        f"The exact missing variable must be named. stdout:\n{result.stdout}"
    )
    assert "Expected value" in result.stdout, (
        f"Naming the variable without saying what it should hold leaves the reader "
        f"to guess the shape. stdout:\n{result.stdout}"
    )
    assert "beta/GOAL.md" in result.stdout, (
        "The message must state the file the variable resolves to, so the expected "
        "value is checkable rather than merely named."
    )
    assert _REBASELINE_FRAGMENT not in result.stdout, (
        "An unset variable is a configuration problem; re-running the workflow "
        "would not fix it, and printing that command would send the reader down "
        "the wrong path."
    )


# --------------------------------------------------------------------------- #
# Cross-cutting invariants
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "case",
    ["fresh", "stale", "no-state-as-of", "missing-file", "missing-dir", "unset"],
)
def test_every_case_exits_zero_and_stays_silent_on_stderr(
    tmp_path: Path, case: str
) -> None:
    """No contracted case may exit non-zero or write to stderr.

    A SessionStart hook that exits 2 blocks the session; one that writes to stderr
    surfaces as a hook failure. Either outcome makes the goal surface a liability,
    and the first time it fired on a broken clone it would be turned off — which is
    how OMN-13244 started.
    """
    if case == "unset":
        result = _run(None)
    elif case == "missing-dir":
        result = _run(str(tmp_path / "nope"))
    elif case == "missing-file":
        (tmp_path / "beta").mkdir(parents=True)
        result = _run(str(tmp_path))
    else:
        ts = {
            "fresh": _iso(timedelta(hours=-1)),
            "stale": _iso(timedelta(days=-5)),
            "no-state-as-of": None,
        }[case]
        _write_goal(tmp_path, ts)
        result = _run(str(tmp_path))

    assert result.returncode == 0, (
        f"case={case} exited {result.returncode}. Every contracted outcome exits 0; "
        f"only an existing-but-unreadable GOAL.md may exit non-zero.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.stderr == "", (
        f"case={case} wrote to stderr, which Claude Code surfaces as a hook "
        f"failure: {result.stderr!r}"
    )


def test_empty_stdin_does_not_break_the_hook(tmp_path: Path) -> None:
    """The hook drains stdin but must not depend on the SessionStart payload."""
    _write_goal(tmp_path, _iso(timedelta(hours=-1)))

    result = _run(str(tmp_path), stdin="")

    assert result.returncode == 0, result.stderr
    assert "staging repin" in result.stdout


def test_unreadable_goal_reports_full_paths_and_exits_three(tmp_path: Path) -> None:
    """The one non-zero path: present but unreadable.

    Exit 3 is deliberate — it is non-zero (so the condition is visible) but is not
    ``2``, the only code that blocks a SessionStart. Both the unreadable file and
    the hook itself are named by absolute path, since a permissions fault is
    diagnosed on the filesystem, not in the transcript.
    """
    goal = _write_goal(tmp_path, _iso(timedelta(hours=-1)))
    goal.chmod(0o000)
    try:
        if os.access(goal, os.R_OK):  # pragma: no cover - root or permissive FS
            pytest.skip("filesystem/user ignores mode 000; unreadable case unprovable")
        result = _run(str(tmp_path))
    finally:
        goal.chmod(0o644)

    assert result.returncode == 3, (
        f"An existing-but-unreadable goal is an internal error, not a missing goal "
        f"— reporting it as MISSING would send the reader to re-run a workflow that "
        f"would then fail to write the same file. stdout:\n{result.stdout}"
    )
    assert result.returncode != 2, "exit 2 would block the session"
    assert str(goal) in result.stdout
    assert str(_SCRIPT.name) in result.stdout, (
        "The hook must name itself, so the failure is attributable without grepping "
        "every SessionStart registration."
    )


def test_hook_performs_no_network_or_write_calls() -> None:
    """Static check: the script contains no network client and no write redirect.

    The SessionStart budget is <50ms (repo CLAUDE.md, Performance Budgets). A
    single curl against an unreachable host would blow that by two orders of
    magnitude, and a write would put session state somewhere nothing reconciles.
    Cheaper to assert on the source than to sandbox the network.
    """
    # Comment lines carry prose that legitimately contains these words ("through
    # the", "Python resolution"), so scan executable lines only.
    code = "\n".join(
        line
        for line in _SCRIPT.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )

    for forbidden in ("curl", "wget", "nc", "python", "python3", "jq", "gh"):
        assert not re.search(rf"(?:^|[|&;(\s]){re.escape(forbidden)}\b", code), (
            f"session_start_goal_surface.sh must stay pure bash with no network and "
            f"no interpreter spin-up; found an invocation of {forbidden!r}. A hook "
            f"with no interpreter cannot resolve to the wrong one (CLAUDE.md rule 11, "
            f"and the OMN-16996 regression class)."
        )

    # Only the two documented redirects are allowed: draining stdin, and silencing
    # probe stderr. Neither writes a file.
    assert ">>" not in code, "the goal-surface hook must not append to any file"
