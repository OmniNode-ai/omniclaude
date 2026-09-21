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
    omni_root: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the hook with a controlled environment.

    ``kb_path=None`` means the variable is absent, not empty — the two are the
    same to the hook by design (an empty string is no more a usable path than an
    unset one), but the unset case is the one the contract names.
    """
    env = os.environ.copy()
    env.pop("KNOWLEDGE_BASE_INTERNAL_PATH", None)
    # OMN-18954: the stale banner reads the morning tick's failure notice under
    # $OMNI_HOME. Popped unconditionally so no case inherits the developer's
    # real state directory; `omni_root=` opts a case back in, hermetically.
    env.pop("OMNI_HOME", None)
    if omni_root is not None:
        env["OMNI_HOME"] = omni_root
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


# --------------------------------------------------------------------------- #
# OMN-18954 — the four dropped-work counts, and the cause behind a STALE goal
# --------------------------------------------------------------------------- #
#
# The morning ground state gained four sections that name work NOBODY is
# driving: a red integration head, a plan that stopped moving, a ticket minted
# and never started, and the dispatch candidates ranked from those. They exist
# because the enforcement-integration plan sat Backlog/unassigned for four days
# while every daily surface reported truthfully and none of them could see it.
#
# They are worth nothing unread, and this hook is where a session reads them.

# Spelled independently of the hook. A test that read the key list out of the
# script it checks would pass on a script that had renamed every key.
_DROPPED_KEYS = (
    "dropped_work",
    "red_on_dev_head",
    "stale_plans",
    "unstarted_work_by_age",
    "proposed_dispatch",
)

_DROPPED_BLOCK = """dropped_work: beta/tracking/2026-09-20-dropped-work.md · derived 2026-09-20T04:41:02Z · sections 4/4 conformant
red_on_dev_head: 3 repo(s) with a failing or absent required context · 2 head sha(s) with no PASS lab-pass receipt · last deploy-agent success 9h ago
stale_plans: 4 of 17 dated plans contradicted by live Linear · 2 unstarted-only · oldest 8d since minted
unstarted_work_by_age: 26 ticket(s) >48h old with no assignee and no PR · across 7 epic(s) · oldest 12d
proposed_dispatch: 10 candidate(s) · top: OMN-18528 BLOCKING-MERGE
"""


def _write_goal_with_dropped_block(root: Path, state_as_of: str) -> Path:
    beta = root / "beta"
    beta.mkdir(parents=True, exist_ok=True)
    goal = beta / "GOAL.md"
    goal.write_text(
        f"state_as_of: {state_as_of}\n"
        "rows_examined: 45\n"
        "rows_open: 12\n"
        f"{_DROPPED_BLOCK}"
        f"{_GOAL_BODY}"
    )
    return goal


def _write_tick_notice(
    omni_root: Path, *, phase: str, ts: str, first_line: str
) -> Path:
    """Write the notice the launchd tick leaves behind on a failed run."""
    notices = omni_root / ".onex_state" / "morning-workflows" / "notifications"
    notices.mkdir(parents=True, exist_ok=True)
    path = notices / "morning-ground-state.failure.json"
    path.write_text(
        "{\n"
        '  "exit": 1,\n'
        '  "fire_id": "20260920T084305Z-morning-ground-state",\n'
        f'  "first_line": "{first_line}",\n'
        f'  "phase": "{phase}",\n'
        f'  "ts": "{ts}",\n'
        '  "workflow": "morning-ground-state"\n'
        "}\n"
    )
    return path


def test_dropped_work_counts_are_printed_under_the_banner(tmp_path: Path) -> None:
    """AC-4: all four sections' headline counts reach the session."""
    _write_goal_with_dropped_block(tmp_path, _iso(timedelta(hours=-1)))
    res = _run(str(tmp_path))

    assert res.returncode == 0
    assert "--- dropped work (nobody is driving these) ---" in res.stdout
    for key in _DROPPED_KEYS:
        assert f"{key}:" in res.stdout, (
            f"the hook must print the '{key}' count; a section nobody reads is "
            "the failure these sections were added to close"
        )
    # The counts themselves, not just the keys.
    assert "3 repo(s) with a failing or absent required context" in res.stdout
    assert "26 ticket(s) >48h old" in res.stdout


def test_a_goal_file_with_no_dropped_counts_says_so(tmp_path: Path) -> None:
    """An absent block is REPORTED, never skipped.

    A goal written by a run whose dropped-work phase produced nothing looks
    identical to one written before the sections existed, and both look
    identical to a clean zero. Silence cannot distinguish them; a line can.
    """
    _write_goal(tmp_path, _iso(timedelta(hours=-1)))
    res = _run(str(tmp_path))

    assert res.returncode == 0
    assert "dropped work: NO COUNTS" in res.stdout
    assert "--- dropped work (nobody is driving these) ---" not in res.stdout


def test_the_added_output_stays_within_its_budget(tmp_path: Path) -> None:
    """The session-start surface is shared; this block is five lines plus one."""
    _write_goal_with_dropped_block(tmp_path, _iso(timedelta(hours=-1)))
    with_block = _run(str(tmp_path)).stdout.splitlines()
    _write_goal(tmp_path, _iso(timedelta(hours=-1)))
    without_block = _run(str(tmp_path)).stdout.splitlines()

    added = len(with_block) - len(without_block)
    assert added <= 12, (
        f"the dropped-work block added {added} lines; the budget is ~12. "
        "SessionStart output is a shared surface and every hook pays into it."
    )


def test_a_stale_goal_names_the_last_tick_failure(tmp_path: Path) -> None:
    """AC-4's other half: the staleness AND its cause.

    On 2026-09-20 all three morning timers died on a session limit and the only
    durable record was a receipt journal nothing read. The staleness showed and
    the cause did not, which sends the reader to re-run a workflow that will
    fail the same way.
    """
    kb = tmp_path / "kb"
    omni = tmp_path / "omni"
    _write_goal(kb, _iso(timedelta(hours=-30)))
    _write_tick_notice(
        omni,
        phase="failed",
        ts="2026-09-20T08:43:14Z",
        first_line="session limit reached",
    )

    res = _run(str(kb), omni_root=str(omni))

    assert res.returncode == 0
    assert "STALE: older than 12h" in res.stdout
    assert "last tick outcome: failed at 2026-09-20T08:43:14Z" in res.stdout
    assert "session limit reached" in res.stdout
    assert _REBASELINE_FRAGMENT in res.stdout


def test_the_cause_line_decodes_the_escapes_the_tick_writes(tmp_path: Path) -> None:
    """The notice is JSON; this hook has no JSON parser and must not leak one.

    Observed live on 2026-09-21: the real notice carried the separator as a
    six-character escape, and the hook printed it raw into an operator-facing
    line. Only the escapes that actually occur are decoded; the rest are left
    literal, because a visible backslash beats a wrong decoding.
    """
    kb = tmp_path / "kb"
    omni = tmp_path / "omni"
    _write_goal(kb, _iso(timedelta(hours=-30)))
    _write_tick_notice(
        omni,
        phase="failed",
        ts="2026-09-21T00:04:55Z",
        first_line="You've hit your session limit \\u00b7 resets 10:20pm",
    )

    res = _run(str(kb), omni_root=str(omni))

    assert res.returncode == 0
    assert "session limit \u00b7 resets 10:20pm" in res.stdout
    assert "\\u00b7" not in res.stdout


def test_a_stale_goal_with_no_notice_says_the_fire_was_missed(tmp_path: Path) -> None:
    """A missed fire and a failed fire are different defects; do not conflate."""
    kb = tmp_path / "kb"
    omni = tmp_path / "omni"
    omni.mkdir()
    _write_goal(kb, _iso(timedelta(hours=-30)))

    res = _run(str(kb), omni_root=str(omni))

    assert res.returncode == 0
    assert "MISSED fire, not a failed one" in res.stdout


def test_a_stale_goal_applies_no_default_for_an_unset_registry_root(
    tmp_path: Path,
) -> None:
    """Rule 8: an unset variable is named, never guessed around."""
    _write_goal(tmp_path, _iso(timedelta(hours=-30)))

    res = _run(str(tmp_path))

    assert res.returncode == 0
    assert "last tick outcome: UNRESOLVED" in res.stdout
    assert "OMNI_HOME is unset" in res.stdout
    assert "No default is applied" in res.stdout


def test_a_fresh_goal_does_not_read_the_tick_notice(tmp_path: Path) -> None:
    """The cause line belongs to the stale path only.

    A fresh goal means the tick that mattered worked. Printing a stale failure
    notice beside it would report a failure that has since been superseded.
    """
    kb = tmp_path / "kb"
    omni = tmp_path / "omni"
    _write_goal(kb, _iso(timedelta(hours=-1)))
    _write_tick_notice(
        omni, phase="failed", ts="2026-09-19T08:43:14Z", first_line="an old failure"
    )

    res = _run(str(kb), omni_root=str(omni))

    assert res.returncode == 0
    assert "an old failure" not in res.stdout
    assert "last tick outcome" not in res.stdout


def _write_deferral(omni_root: Path, *, refire_at: str) -> Path:
    """Write the record the tick leaves when it defers a re-fire (OMN-18961)."""
    d = omni_root / ".onex_state" / "morning-workflows" / "deferred"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "morning-ground-state.json"
    path.write_text(
        "{\n"
        '  "note": "one deferral per original fire",\n'
        '  "origin_fire_id": "20260921T024828Z-morning-ground-state",\n'
        f'  "refire_at": "{refire_at}",\n'
        '  "waiter_pid": 4242,\n'
        '  "workflow": "morning-ground-state"\n'
        "}\n"
    )
    return path


def test_a_pending_refire_is_announced_beside_the_staleness(tmp_path: Path) -> None:
    """A stale goal with a re-fire coming is a different state.

    Without this line the two look identical, and the reader re-baselines by
    hand against a limit that is about to clear on its own.
    """
    kb = tmp_path / "kb"
    omni = tmp_path / "omni"
    _write_goal(kb, _iso(timedelta(hours=-30)))
    _write_tick_notice(
        omni,
        phase="failed",
        ts="2026-09-21T00:04:55Z",
        first_line="session limit reached",
    )
    _write_deferral(omni, refire_at="2026-09-21T02:23:00Z")

    res = _run(str(kb), omni_root=str(omni))

    assert res.returncode == 0
    assert "a re-fire IS scheduled for 2026-09-21T02:23:00Z" in res.stdout
    # The cause still prints; the deferral is an addition, not a replacement.
    assert "session limit reached" in res.stdout


def test_no_deferral_record_means_no_refire_claim(tmp_path: Path) -> None:
    """Silence is the honest output when nothing is scheduled.

    Announcing a re-fire that does not exist is worse than announcing none:
    it tells the reader to wait for something nobody is going to send.
    """
    kb = tmp_path / "kb"
    omni = tmp_path / "omni"
    omni.mkdir()
    _write_goal(kb, _iso(timedelta(hours=-30)))

    res = _run(str(kb), omni_root=str(omni))

    assert res.returncode == 0
    assert "re-fire IS scheduled" not in res.stdout


def test_a_fresh_goal_does_not_announce_a_deferral(tmp_path: Path) -> None:
    """Same reasoning as the failure cause: the stale branch owns both."""
    kb = tmp_path / "kb"
    omni = tmp_path / "omni"
    _write_goal(kb, _iso(timedelta(hours=-1)))
    _write_deferral(omni, refire_at="2026-09-21T02:23:00Z")

    res = _run(str(kb), omni_root=str(omni))

    assert res.returncode == 0
    assert "re-fire IS scheduled" not in res.stdout


def test_the_hook_declares_exactly_these_five_keys() -> None:
    """The key list in the script must match the one spelled here.

    Every other case in this block writes its own fixture, so a rename inside
    the script plus a matching rename in a fixture would pass all of them while
    the hook printed nothing against a real goal file. This is the one check
    that compares the script's own list against a list spelled independently
    of it.

    The cross-repo half has no mechanical home. The writer is the morning
    workflow in the registry repository, and neither repo's CI checks out the
    other, so a comparison here could only ever skip on a runner -- and a test
    that never executes proves nothing (the skip-count ratchet refuses exactly
    that, which is how this test arrived at its current shape). Each side
    instead pins its own list against an independently spelled tuple: this
    case, and `test_the_five_goal_header_keys_are_declared` over there. A
    rename is a two-file change by construction, and either half alone goes
    red.
    """
    src = _SCRIPT.read_text()
    assert "_DROPPED_KEYS=(" in src, "the hook must declare its key list once"
    block = src.split("_DROPPED_KEYS=(", 1)[1].split(")", 1)[0]
    declared = tuple(re.findall(r'"([a-z_]+)"', block))
    assert declared == _DROPPED_KEYS, (
        "the hook greps keys the morning workflow may no longer write; "
        f"script declares {declared}, this test expects {_DROPPED_KEYS}"
    )
