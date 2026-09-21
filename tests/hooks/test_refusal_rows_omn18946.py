# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18946 — a hook refusal reaches an aggregated surface, or this fails.

Three kinds of fact, and the third is the one that keeps the other two true
next month.

BEHAVIOUR: the recorder writes a well-formed ledger row, redacts what must
never reach an append-only shared file, and never raises.

RATE LIMIT: one row per dedupe key per window, with the suppressed count
carried forward. This is load-bearing rather than tidy — a guard in a retry
loop refusing thousands of times would make the ledger unreadable, which is
the same failure as writing nothing, reached from the other side.

RATCHET: every hook REGISTERED in `hooks.json` that can refuse must record
the refusal. Wiring fifteen scripts once is worth little if the sixteenth
lands next week without a row; the ratchet is the part that survives this
lane. It is derived from the live registration surface rather than a
hand-maintained list, so a newly registered guard is in scope the moment it
is registered.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "plugins" / "onex" / "hooks"
SCRIPTS_DIR = HOOKS_DIR / "scripts"
LIB_DIR = HOOKS_DIR / "lib"
HOOKS_JSON = HOOKS_DIR / "hooks.json"
ERROR_GUARD = SCRIPTS_DIR / "error-guard.sh"
RECORDER = LIB_DIR / "hook_refusal_recorder.py"

#: The shell function every deny path must call.
RECORD_FN = "hook_record_refusal"

#: A deny path in this codebase is `exit 2`. Matched on a real statement
#: rather than anywhere in the file, so a mention in a comment does not count
#: as a deny path and does not silently satisfy the ratchet.
_EXIT_TWO = re.compile(r"^\s*exit 2\s*$", re.MULTILINE)


def _load_recorder():
    spec = importlib.util.spec_from_file_location("hook_refusal_recorder", RECORDER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recorder = _load_recorder()


class TestTheRowIsWellFormed:
    def test_a_row_carries_every_field_a_reader_triages_on(self) -> None:
        row = recorder.build_row(
            guard="pre_tool_use_bash_guard.sh",
            reason="compound-line-cannot-be-tokenised",
            lane="omn18946-lane",
            lane_source="sidecar",
            detail="BLOCKED: this command could not be tokenised",
            key="abc123def456",
            suppressed=4,
            timestamp="2026-09-21T05:00:00Z",
        )
        for field in (
            "| FRICTION |",
            "lane=omn18946-lane",
            "class=refusal",
            "guard=pre_tool_use_bash_guard.sh",
            "reason=compound-line-cannot-be-tokenised",
            "dedupe=abc123def456",
            "suppressed_since_last_row=4",
        ):
            assert field in row, field

    def test_a_row_is_one_line(self) -> None:
        """The ledger is line-oriented. A row spanning two lines is two rows
        to every reader, and the second is malformed.
        """
        row = recorder.build_row(
            guard="g",
            reason="r",
            lane="l",
            lane_source="sidecar",
            detail="first line\nsecond line",
            key="k",
            suppressed=0,
            timestamp="2026-09-21T05:00:00Z",
        )
        assert "\n" not in row

    def test_an_unresolved_lane_is_named_not_guessed(self) -> None:
        """A row attributing one lane's friction to a neighbour is worse than
        a row naming no lane at all.
        """
        row = recorder.build_row(
            guard="g",
            reason="r",
            lane="",
            lane_source="unresolved",
            detail="",
            key="k",
            suppressed=0,
            timestamp="2026-09-21T05:00:00Z",
        )
        assert "lane=unresolved" in row
        assert "lane_source=unresolved" in row


class TestRedaction:
    @pytest.mark.parametrize(
        "secret",
        [
            "ghp_" + "a" * 36,
            "github_pat_" + "b" * 30,
            "xoxb-" + "1" * 20,
            "sk-" + "c" * 32,
            "AKIA" + "D" * 16,
            "password=hunter2",
        ],
    )
    def test_credential_shapes_never_reach_the_row(self, secret: str) -> None:
        """A refusal message quotes the command that was refused, and a
        refused command is exactly the kind that carries a token. The ledger
        is append-only and shared, so this is not recoverable after the fact.
        """
        cleaned = recorder.redact(f"BLOCKED: refused `curl -H {secret}`")
        assert secret not in cleaned
        assert "[redacted]" in cleaned

    def test_positive_control_ordinary_text_survives_redaction(self) -> None:
        """Without this, a redactor that blanked everything would pass every
        test above and destroy the only useful field in the row.
        """
        text = "BLOCKED: this command overrides the hooks path"
        assert recorder.redact(text) == text

    @pytest.mark.parametrize("breaker", ["|", "\n", "\r"])
    def test_field_breakers_cannot_forge_a_column_or_a_row(self, breaker: str) -> None:
        cleaned = recorder.redact(f"left{breaker}right")
        assert breaker not in cleaned


class TestTheReasonBecomesAStableKey:
    def test_the_same_class_on_two_paths_is_one_key(self) -> None:
        """The rate limit is worthless if the key varies per instance. A guard
        refusing the same class on twenty files is one recurring friction.
        """
        a = recorder.normalise_reason("Worktree path outside canonical root: /a/b/c")
        b = recorder.normalise_reason("Worktree path outside canonical root: /x/y/z")
        assert a == b == "worktree-path-outside-canonical-root"

    def test_positive_control_two_different_classes_are_two_keys(self) -> None:
        """The control against a normaliser that collapses everything to one
        token, which would hide every refusal but the first behind one row.
        """
        a = recorder.normalise_reason("worktree path outside canonical root")
        b = recorder.normalise_reason("command could not be tokenised")
        assert a != b

    def test_a_bare_number_is_dropped_and_a_ticket_id_is_kept(self) -> None:
        with_line = recorder.normalise_reason("refused at line 412")
        other_line = recorder.normalise_reason("refused at line 9")
        assert with_line == other_line
        assert "omn" in recorder.normalise_reason("refused by OMN-18335")

    def test_an_empty_reason_still_groups(self) -> None:
        assert recorder.normalise_reason("   ") == "unspecified"

    def test_two_lanes_hitting_one_guard_stay_two_rows(self) -> None:
        """The fact that turns "a lane is stuck" into "the guard is wrong"."""
        assert recorder.dedupe_key("g", "r", "lane-a") != recorder.dedupe_key(
            "g", "r", "lane-b"
        )


class TestTheRateLimit:
    def test_the_first_refusal_is_recorded_immediately(self, tmp_path: Path) -> None:
        """A refusal must not wait an hour to be recorded."""
        emit, suppressed = recorder.should_emit(
            "k", now=1000.0, window_seconds=3600, directory=tmp_path
        )
        assert emit is True
        assert suppressed == 0

    def test_a_looping_refusal_is_one_row_not_thousands(self, tmp_path: Path) -> None:
        recorder.should_emit("k", now=1000.0, window_seconds=3600, directory=tmp_path)
        emitted = sum(
            recorder.should_emit(
                "k", now=1000.0 + i, window_seconds=3600, directory=tmp_path
            )[0]
            for i in range(1, 2000)
        )
        assert emitted == 0

    def test_the_suppressed_count_is_carried_to_the_next_row(
        self, tmp_path: Path
    ) -> None:
        """The volume is reported, not lost — a looping refusal must be
        visibly a loop rather than a single tidy row.
        """
        recorder.should_emit("k", now=1000.0, window_seconds=3600, directory=tmp_path)
        for i in range(1, 6):
            recorder.should_emit(
                "k", now=1000.0 + i, window_seconds=3600, directory=tmp_path
            )
        emit, suppressed = recorder.should_emit(
            "k", now=1000.0 + 4000, window_seconds=3600, directory=tmp_path
        )
        assert emit is True
        assert suppressed == 5

    def test_a_different_key_is_not_suppressed_by_a_busy_neighbour(
        self, tmp_path: Path
    ) -> None:
        """The control against a rate limit keyed on nothing, which would let
        one noisy guard silence every other guard on the machine.
        """
        recorder.should_emit("a", now=1000.0, window_seconds=3600, directory=tmp_path)
        emit, _ = recorder.should_emit(
            "b", now=1000.0, window_seconds=3600, directory=tmp_path
        )
        assert emit is True

    def test_an_unreadable_state_file_emits_rather_than_skips(
        self, tmp_path: Path
    ) -> None:
        """Failure direction. Losing a refusal is the bug this fixes; an extra
        row is merely noise.
        """
        (tmp_path / "k.json").write_text("{ not json", encoding="utf-8")
        emit, _ = recorder.should_emit(
            "k", now=time.time(), window_seconds=3600, directory=tmp_path
        )
        assert emit is True

    def test_an_unwritable_state_directory_does_not_raise(self, tmp_path: Path) -> None:
        blocker = tmp_path / "blocked"
        blocker.write_text("i am a file, not a directory", encoding="utf-8")
        emit, _ = recorder.should_emit(
            "k", now=time.time(), window_seconds=3600, directory=blocker
        )
        assert emit is True


class TestTheProcessNeverBreaksAGuard:
    """It runs behind a hook that is already refusing a tool call."""

    def _run(self, args: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RECORDER), *args],
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(tmp_path),
                "ONEX_HOOK_REFUSAL_STATE_DIR": str(tmp_path / "state"),
            },
        )

    def test_it_prints_a_row_and_exits_zero(self, tmp_path: Path) -> None:
        result = self._run(
            [
                "--guard",
                "pre_tool_use_bash_guard.sh",
                "--reason",
                "compound line could not be tokenised",
                "--detail",
                "BLOCKED: the whole line was judged",
                "--print-row",
            ],
            tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert "| FRICTION |" in result.stdout
        assert "compound-line-could-not-be-tokenised" in result.stdout

    def test_it_exits_zero_with_no_omni_home_and_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        """No ledger reachable is a dropped row, never a broken guard."""
        result = self._run(["--guard", "g", "--reason", "r", "--detail", "d"], tmp_path)
        assert result.returncode == 0, result.stderr

    def test_a_second_run_inside_the_window_prints_nothing(
        self, tmp_path: Path
    ) -> None:
        args = ["--guard", "g", "--reason", "same class", "--print-row"]
        first = self._run(args, tmp_path)
        second = self._run(args, tmp_path)
        assert first.stdout.strip()
        assert not second.stdout.strip()


class TestItAppendsThroughTheLockedWriter:
    def test_the_row_goes_through_ledger_lock_and_never_to_the_file(
        self, tmp_path: Path
    ) -> None:
        """The ledger is a shared append-only file many lanes write at once.
        A direct write would be the collision class rule 19 exists to remove,
        so the recorder must invoke the locked writer and nothing else.
        """
        ledger = tmp_path / "LEDGER.md"
        ledger.write_text("existing\n", encoding="utf-8")
        fake_locker = tmp_path / "ledger_lock.py"
        fake_locker.write_text(
            "import sys, pathlib\n"
            "ledger = pathlib.Path(sys.argv[1])\n"
            "row = sys.argv[sys.argv.index('--append') + 1]\n"
            "ledger.write_text(ledger.read_text() + row + '\\n')\n",
            encoding="utf-8",
        )
        ok = recorder.append_row(
            "2026-09-21T05:00:00Z | FRICTION | lane=x",
            ledger=ledger,
            locker=fake_locker,
            timeout="5s",
        )
        assert ok is True
        assert "FRICTION" in ledger.read_text()

    def test_a_missing_locker_is_a_dropped_row_not_a_direct_write(
        self, tmp_path: Path
    ) -> None:
        ledger = tmp_path / "LEDGER.md"
        ledger.write_text("existing\n", encoding="utf-8")
        ok = recorder.append_row(
            "row", ledger=ledger, locker=tmp_path / "nope.py", timeout="5s"
        )
        assert ok is False
        assert ledger.read_text() == "existing\n"


def _registered_hook_scripts() -> list[Path]:
    """Every script `hooks.json` registers, resolved to a path in this tree.

    Derived from the live registration surface rather than a hand-maintained
    list: a guard registered next week is in scope the moment it is
    registered, which is the property that makes this a ratchet instead of a
    snapshot.
    """
    data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
    paths: list[Path] = []
    for matchers in data.values():
        for matcher in matchers:
            for hook in matcher.get("hooks", []):
                command = hook.get("command", "")
                name = command.rsplit("/", 1)[-1].strip()
                candidate = SCRIPTS_DIR / name
                if candidate.is_file():
                    paths.append(candidate)
    return sorted(set(paths))


class TestEveryRegisteredRefusalIsRecorded:
    """The ratchet. This is the part that outlives the lane that wired them."""

    def test_positive_control_the_registration_surface_is_readable(self) -> None:
        """Guards the whole class against a vacuous pass: if `hooks.json`
        moved or its shape changed, the parametrised test below would silently
        run over zero scripts and report green.
        """
        scripts = _registered_hook_scripts()
        assert len(scripts) >= 10, f"only {len(scripts)} registered scripts resolved"

    def test_positive_control_some_registered_hook_can_refuse(self) -> None:
        """And that at least one of them has a deny path at all, so the
        parametrised test is not skipping its way to green.
        """
        refusing = [
            p
            for p in _registered_hook_scripts()
            if _EXIT_TWO.search(p.read_text(encoding="utf-8"))
        ]
        assert len(refusing) >= 10, f"only {len(refusing)} registered hooks refuse"

    @pytest.mark.parametrize(
        "script",
        [
            p
            for p in _registered_hook_scripts()
            if _EXIT_TWO.search(p.read_text(encoding="utf-8"))
        ],
        ids=lambda p: p.name,
    )
    def test_a_registered_hook_that_refuses_records_the_refusal(
        self, script: Path
    ) -> None:
        source = script.read_text(encoding="utf-8")
        assert RECORD_FN in source, (
            f"{script.name} has a deny path (`exit 2`) but never calls "
            f"`{RECORD_FN}`, so its refusal reaches this turn's terminal and a "
            "per-hook log nobody reads, and no aggregated surface at all. Add "
            f'`{RECORD_FN} "<reason>" "<detail>"` on the deny path; the '
            "function is defined in error-guard.sh, which every hook already "
            "sources first (OMN-18946)."
        )


class TestTheSeamItself:
    def test_error_guard_defines_the_function(self) -> None:
        assert f"{RECORD_FN}()" in ERROR_GUARD.read_text(encoding="utf-8")

    def test_the_recorder_it_invokes_exists(self) -> None:
        """The OMN-18702 failure exactly: ten call sites survived a refactor
        that deleted their callee, every one exited 127 for a day, and the
        guards watching that surface matched the call-site token as text and
        never asked whether the callee existed.
        """
        source = ERROR_GUARD.read_text(encoding="utf-8")
        assert "hook_refusal_recorder.py" in source
        assert RECORDER.is_file()

    def test_the_call_is_backgrounded(self) -> None:
        """The operator's refusal message must never wait on a ledger lock."""
        source = ERROR_GUARD.read_text(encoding="utf-8")
        body = source.split(f"{RECORD_FN}()", 1)[1]
        assert "disown" in body.split("\n}\n", 1)[0]

    def test_the_function_always_returns_zero(self) -> None:
        """A recorder that could break a guard would be worse than the gap."""
        source = ERROR_GUARD.read_text(encoding="utf-8")
        body = source.split(f"{RECORD_FN}()", 1)[1].split("\n}\n", 1)[0]
        assert "return 0" in body


class TestTheLockIsTakenOnlyWhenARowIsWritten:
    """A suppressed refusal must not touch the ledger lock.

    `ledger_lock.py` holds one exclusive lock across stage-and-append with a
    long default timeout. A PreToolUse hook runs on the tool-call path, so a
    suppressed refusal that queued for that lock would serialise every lane's
    tool calls behind one noisy guard — turning a fix for silence into a
    fleet-wide stall. The dedupe decision is therefore made first, and this
    pins that ordering rather than trusting it.
    """

    def _run(
        self, tmp_path: Path, ledger: Path, locker: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(RECORDER),
                "--guard",
                "g",
                "--reason",
                "same refusal class",
                "--ledger",
                str(ledger),
            ],
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(tmp_path),
                "OMNI_HOME": str(tmp_path / "root"),
                "ONEX_HOOK_REFUSAL_STATE_DIR": str(tmp_path / "state"),
            },
        )

    def test_a_suppressed_refusal_never_invokes_the_locked_writer(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "root"
        (root / "scripts").mkdir(parents=True)
        ledger = tmp_path / "LEDGER.md"
        ledger.write_text("existing\n", encoding="utf-8")
        marker = tmp_path / "invocations.txt"
        # A stand-in for ledger_lock.py that records that it ran at all.
        (root / "scripts" / "ledger_lock.py").write_text(
            "import pathlib, sys\n"
            f"pathlib.Path({str(marker)!r}).open('a').write('ran\\n')\n"
            "ledger = pathlib.Path(sys.argv[1])\n"
            "row = sys.argv[sys.argv.index('--append') + 1]\n"
            "ledger.write_text(ledger.read_text() + row + '\\n')\n",
            encoding="utf-8",
        )

        assert self._run(tmp_path, ledger, root).returncode == 0
        first = marker.read_text().count("ran")
        assert first == 1, "the first refusal must be written immediately"

        for _ in range(5):
            assert self._run(tmp_path, ledger, root).returncode == 0

        assert marker.read_text().count("ran") == 1, (
            "a suppressed refusal invoked the locked ledger writer. The dedupe "
            "check must precede the lock, or every lane's tool calls queue "
            "behind one looping guard."
        )
        assert ledger.read_text().count("FRICTION") == 1
