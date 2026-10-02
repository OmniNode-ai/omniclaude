# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19381 — a hook refusal row names the lane whenever an honest operand can.

The OMN-18946 recorder wrote 584 rows to the live ledger and 579 of them said
``lane=unresolved``. ``hook_record_refusal`` handed the recorder the
transcript path, session id and agent id from the ENVIRONMENT, which no
PreToolUse guard sets, and the hook's cwd, which on this fleet is the
workspace root where the registry walk stops by design. The facts that name a
lane are in the hook's own stdin payload, and nothing passed it on.

Every test here drives the recorder the way a guard does: a bash process that
sources ``error-guard.sh``, reads a PreToolUse-shaped payload from its stdin
into ``TOOL_INFO`` and calls ``hook_record_refusal``. The row is read back from
a scratch ledger written through a stand-in for the locked writer.

The resolution order under test, first hit wins:

    sidecar   the harness's ``agent-<id>.meta.json`` (Agent-tool and Workflow)
    env       the session's lane variables, only when the payload has no agent id
    registry  the lane registry, for the cwd and every worktree path the tool names
    claim     exactly one open CLAIM row naming that worktree (or its ticket)
    worktree  ``wt:<dir>/<repo>``
    unresolved
"""

from __future__ import annotations

import json
import os
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
ERROR_GUARD = SCRIPTS_DIR / "error-guard.sh"

SESSION_ID = "5f0c2a8e-1111-4222-8333-944455556666"
AGENT_ID = "a3f9c1d2e4b5a6c7"

#: A stand-in for uv run --project omnibase_internal onex-ledger.
_FAKE_LOCKER = (
    f"#!{sys.executable}\n"
    "import pathlib, sys\n"
    "sys.argv = sys.argv[5:]\n"
    "ledger = pathlib.Path(sys.argv[1])\n"
    "row = sys.argv[sys.argv.index('--append') + 1]\n"
    "with ledger.open('a', encoding='utf-8') as fh:\n"
    "    fh.write(row + '\\n')\n"
)

#: A guard's shape, reduced to the two lines that matter here: the payload is
#: read from stdin into TOOL_INFO, and the deny path calls the recorder.
_GUARD_SHAPE = """
_OMNICLAUDE_HOOK_NAME="${TEST_HOOK_NAME}"
source "${TEST_ERROR_GUARD}"
TOOL_INFO=$(cat)
hook_record_refusal "worktree path outside canonical root: /x/y" "BLOCKED: test refusal"
trap - EXIT
exit 0
"""


class Sandbox:
    """A scratch registry root: ledger, locked writer, lane registry, sessions."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "registry_root"
        self.home.mkdir()
        project = tmp_path / "omnibase_internal"
        project.mkdir()
        (project / "pyproject.toml").write_text("")
        stub = tmp_path / "uv"
        stub.write_text(_FAKE_LOCKER, encoding="utf-8")
        stub.chmod(0o755)
        self.ledger = self.home / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md"
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_text("# ledger\n", encoding="utf-8")
        self.worktrees = self.home / "omni_worktrees"
        self.worktrees.mkdir()
        self.projects = tmp_path / "projects" / "-registry-root"
        self.projects.mkdir(parents=True)
        self.transcript = self.projects / f"{SESSION_ID}.jsonl"
        self.transcript.write_text("", encoding="utf-8")
        self.session_dir = self.projects / SESSION_ID

    # --- fixtures a test composes -------------------------------------------

    def worktree(self, ticket_dir: str, repo: str = "omniclaude") -> Path:
        path = self.worktrees / ticket_dir / repo
        path.mkdir(parents=True, exist_ok=True)
        return path

    def sidecar(self, meta: dict[str, object], *, workflow_run: str | None) -> Path:
        base = self.session_dir / "subagents"
        if workflow_run:
            base = base / "workflows" / workflow_run
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"agent-{AGENT_ID}.meta.json"
        path.write_text(json.dumps(meta), encoding="utf-8")
        return path

    def register(self, worktree: Path, lane: str, ticket: str = "OMN-1") -> None:
        import hashlib

        registry = self.home / ".onex_state" / "lane_identity"
        registry.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(str(worktree.resolve()).encode()).hexdigest()[:32]
        (registry / f"{key}.json").write_text(
            json.dumps({"lane": lane, "ticket": ticket, "worktree": str(worktree)}),
            encoding="utf-8",
        )

    def ledger_rows(self, *rows: str) -> None:
        with self.ledger.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(row + "\n")

    def payload(
        self,
        command: str = "ls",
        *,
        agent_id: str | None = None,
        tool_input: dict[str, object] | None = None,
    ) -> dict[str, object]:
        data: dict[str, object] = {
            "session_id": SESSION_ID,
            "transcript_path": str(self.transcript),
            "cwd": str(self.home),
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": tool_input or {"command": command},
        }
        if agent_id:
            data["agent_id"] = agent_id
        return data

    # --- the act --------------------------------------------------------------

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = {
            "PATH": f"{self.tmp}:" + os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.tmp),
            "OMNI_HOME": str(self.home),
            "CLAUDE_PROJECT_DIR": str(self.home),
            "CLAUDE_PROJECTS_DIR": str(self.tmp / "projects"),
            "ONEX_HOOK_REFUSAL_STATE_DIR": str(self.tmp / "refusal_state"),
            "PYTHON_CMD": sys.executable,
            "TMPDIR": str(self.tmp),
            "TEST_ERROR_GUARD": str(ERROR_GUARD),
            "TEST_HOOK_NAME": "pre_tool_use_worktree_guard.sh",
        }
        env.update(extra or {})
        return env

    def refuse(
        self, payload: dict[str, object], env: dict[str, str] | None = None
    ) -> str:
        """Fire one refusal through hook_record_refusal and return its row."""
        before = self.ledger.read_text(encoding="utf-8").count("| FRICTION |")
        result = subprocess.run(
            ["bash", "-c", _GUARD_SHAPE],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            env=self.env(env),
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            rows = [
                line
                for line in self.ledger.read_text(encoding="utf-8").splitlines()
                if "| FRICTION |" in line and "actor=hook" in line
            ]
            if len(rows) > before:
                return rows[-1]
            time.sleep(0.05)
        raise AssertionError("no refusal row reached the ledger within 20s")


def _cell(row: str, key: str) -> str:
    match = re.search(rf"\| {re.escape(key)}=([^|]*?) \|", row)
    assert match, f"{key}= missing from {row}"
    return match.group(1)


@pytest.fixture
def box(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


# =============================================================================
# AC1 / AC2 — the ticket's named falsifiers
# =============================================================================


class TestTheTicketFalsifiers:
    def test_refusal_row_names_dispatched_lane(self, box: Sandbox) -> None:
        """AC1: a refusal raised inside a dispatched lane names that lane.

        The payload carries the transcript path and agent id; the harness
        wrote the lane's sidecar beside the session. Nothing in the
        environment names anything.
        """
        box.sidecar(
            {"agentType": "omn19381-refusal-lane", "name": "omn19381-refusal-lane"},
            workflow_run=None,
        )
        row = box.refuse(box.payload(agent_id=AGENT_ID))
        assert _cell(row, "lane") == "omn19381-refusal-lane"
        assert _cell(row, "lane_source") == "sidecar"

    def test_refusal_row_unattributable_stays_unresolved(self, box: Sandbox) -> None:
        """AC2: nothing honest names a lane, so the row says unresolved.

        Every near-miss is present and must not be mistaken for an answer: a
        sidecar that carries only the generic agent type, a session lane
        variable that names the PARENT (a subagent inherits it), an
        unregistered cwd at the workspace root, and a ledger holding an open
        CLAIM for a worktree this call never touched.
        """
        box.sidecar(
            {"agentType": "general-purpose", "model": "opus", "spawnDepth": 1},
            workflow_run=None,
        )
        box.worktree("OMN-7")
        box.ledger_rows(
            "2026-10-01T00:00:00Z | CLAIM | lane=elsewhere | ticket=OMN-7 | "
            "worktree=omni_worktrees/OMN-7/omniclaude | est ~1 lane-hours"
        )
        row = box.refuse(
            box.payload("git status", agent_id=AGENT_ID),
            env={"ONEX_LANE": "the-parent-lane"},
        )
        assert _cell(row, "lane") == "unresolved"
        assert _cell(row, "lane_source") == "unresolved"


# =============================================================================
# One test per operand
# =============================================================================


class TestEachOperand:
    def test_workflow_sidecar_names_the_lane(self, box: Sandbox) -> None:
        """A Workflow agent's sidecar sits under subagents/workflows/<run>/,
        carries the generic type ``workflow-subagent`` and its label as
        ``description``. The type is not a lane; the label is.
        """
        box.sidecar(
            {
                "agentType": "workflow-subagent",
                "description": "verify-build-drive",
                "model": "opus",
                "spawnDepth": 1,
            },
            workflow_run="wf_8c1d2e3f",
        )
        row = box.refuse(box.payload(agent_id=AGENT_ID))
        assert _cell(row, "lane") == "verify-build-drive"
        assert _cell(row, "lane_source") == "sidecar"

    def test_workflow_sidecar_of_another_session_is_not_read(
        self, box: Sandbox
    ) -> None:
        """The workflow lookup is scoped to this payload's session directory."""
        other = box.projects / "other-session" / "subagents" / "workflows" / "wf_1"
        other.mkdir(parents=True)
        (other / f"agent-{AGENT_ID}.meta.json").write_text(
            json.dumps({"agentType": "workflow-subagent", "description": "stranger"}),
            encoding="utf-8",
        )
        row = box.refuse(box.payload(agent_id=AGENT_ID))
        assert _cell(row, "lane") == "unresolved"

    def test_lane_env_names_the_lane_when_no_agent_id(self, box: Sandbox) -> None:
        """The operator's own session (or a headless lane) declares its lane."""
        row = box.refuse(box.payload(), env={"ONEX_LANE": "omn19381-refusal-lane"})
        assert _cell(row, "lane") == "omn19381-refusal-lane"
        assert _cell(row, "lane_source") == "env"

    def test_lane_env_ignored_when_payload_has_agent_id(self, box: Sandbox) -> None:
        """A subagent inherits its session's env, so the env names the parent
        lane for a child's refusal. With an agent id in the payload the env
        is not an operand at all; the worktree operand still is.
        """
        wt = box.worktree("OMN-42")
        row = box.refuse(
            box.payload(f"git -C {wt} status", agent_id=AGENT_ID),
            env={"ONEX_LANE_ID": "the-parent-lane"},
        )
        assert _cell(row, "lane") != "the-parent-lane"
        assert _cell(row, "lane") == "wt:OMN-42/omniclaude"
        assert _cell(row, "lane_source") == "worktree"

    def test_registry_resolves_a_git_dash_c_worktree_path(self, box: Sandbox) -> None:
        wt = box.worktree("OMN-55")
        box.register(wt, "registered-lane", ticket="OMN-55")
        row = box.refuse(box.payload(f"git -C {wt} push origin HEAD"))
        assert _cell(row, "lane") == "registered-lane"
        assert _cell(row, "lane_source") == "registry"

    def test_registry_resolves_an_unexpanded_registry_root_variable(
        self, box: Sandbox
    ) -> None:
        """Commands are written with ``$OMNI_HOME`` left for the shell."""
        wt = box.worktree("OMN-56")
        box.register(wt, "registered-lane-56", ticket="OMN-56")
        row = box.refuse(
            box.payload(
                'cd "$OMNI_HOME/omni_worktrees/OMN-56/omniclaude" && git status'
            )
        )
        assert _cell(row, "lane") == "registered-lane-56"
        assert _cell(row, "lane_source") == "registry"

    def test_registry_resolves_an_edit_file_path(self, box: Sandbox) -> None:
        wt = box.worktree("OMN-57")
        box.register(wt, "editing-lane", ticket="OMN-57")
        row = box.refuse(
            box.payload(
                tool_input={"file_path": str(wt / "src" / "x.py"), "content": "x"}
            )
        )
        assert _cell(row, "lane") == "editing-lane"
        assert _cell(row, "lane_source") == "registry"

    def test_a_single_open_claim_names_the_lane(self, box: Sandbox) -> None:
        wt = box.worktree("OMN-60")
        box.ledger_rows(
            "2026-10-01T00:00:00Z | CLAIM | lane=claim-lane-60 | ticket=OMN-60 | "
            "actor=claude | worktree=omni_worktrees/OMN-60/omniclaude | est ~1 lane-hours"
        )
        row = box.refuse(box.payload(f"git -C {wt} commit -m x"))
        assert _cell(row, "lane") == "claim-lane-60"
        assert _cell(row, "lane_source") == "claim"

    def test_a_claim_matches_on_ticket_when_it_names_no_worktree(
        self, box: Sandbox
    ) -> None:
        wt = box.worktree("OMN-61")
        box.ledger_rows(
            "2026-10-01T00:00:00Z | CLAIM | lane=claim-lane-61 | ticket=OMN-61 | "
            "actor=claude | worktree=none | est ~1 lane-hours"
        )
        row = box.refuse(box.payload(f"git -C {wt} status"))
        assert _cell(row, "lane") == "claim-lane-61"
        assert _cell(row, "lane_source") == "claim"

    def test_two_open_claims_are_ambiguous_and_fall_through(self, box: Sandbox) -> None:
        """Two lanes claim the worktree, so neither is named."""
        wt = box.worktree("OMN-62")
        box.ledger_rows(
            "2026-10-01T00:00:00Z | CLAIM | lane=lane-a | ticket=OMN-62 | "
            "worktree=omni_worktrees/OMN-62/omniclaude | est ~1 lane-hours",
            "2026-10-01T00:01:00Z | CLAIM | lane=lane-b | ticket=OMN-62 | "
            "worktree=omni_worktrees/OMN-62/omniclaude | est ~1 lane-hours",
        )
        row = box.refuse(box.payload(f"git -C {wt} status"))
        assert _cell(row, "lane") == "wt:OMN-62/omniclaude"
        assert _cell(row, "lane_source") == "worktree"

    def test_a_claim_closed_by_a_terminal_is_not_open(self, box: Sandbox) -> None:
        wt = box.worktree("OMN-63")
        box.ledger_rows(
            "2026-10-01T00:00:00Z | CLAIM | lane=done-lane | ticket=OMN-63 | "
            "worktree=omni_worktrees/OMN-63/omniclaude | est ~1 lane-hours",
            "2026-10-01T01:00:00Z | TERMINAL | lane=done-lane | ticket=OMN-63 | "
            "friction=none | worktree=removed:omni_worktrees/OMN-63/omniclaude",
        )
        row = box.refuse(box.payload(f"git -C {wt} status"))
        assert _cell(row, "lane") == "wt:OMN-63/omniclaude"
        assert _cell(row, "lane_source") == "worktree"

    def test_the_worktree_label_is_the_last_honest_operand(self, box: Sandbox) -> None:
        wt = box.worktree("OMN-64", repo="omnibase_core")
        row = box.refuse(box.payload(f"cd {wt} && git status"))
        assert _cell(row, "lane") == "wt:OMN-64/omnibase_core"
        assert _cell(row, "lane_source") == "worktree"

    def test_the_dedupe_key_follows_the_resolved_lane(self, box: Sandbox) -> None:
        """Two lanes refused by one guard stay two rows inside one window."""
        a = box.refuse(box.payload(), env={"ONEX_LANE": "lane-one"})
        b = box.refuse(box.payload(), env={"ONEX_LANE": "lane-two"})
        assert _cell(a, "dedupe") != _cell(b, "dedupe")


# =============================================================================
# The seam: payload handling and latency
# =============================================================================


class TestThePayloadSeam:
    def test_the_payload_is_never_passed_on_argv(self) -> None:
        """A payload is the size of a Workflow script and may quote a token;
        argv is world-readable in the process table and capped in size.
        """
        source = (HOOKS_DIR / "lib" / "hook_refusal.sh").read_text(encoding="utf-8")
        body = source.split("hook_record_refusal()", 1)[1].split("\n}\n", 1)[0]
        assert "--payload-stdin" in body
        # OMN-20389: a here-string deadlocks Homebrew bash 5.3 under macOS pipe
        # pressure, so the payload reaches stdin through a process substitution.
        assert re.search(r"<\s*<\(printf '%s\\n' \"\$payload\"\)", body), body
        assert not re.search(r'--payload\s+"\$', body)

    def test_hook_record_refusal_returns_before_a_slow_recorder(
        self, box: Sandbox, tmp_path: Path
    ) -> None:
        """The guard's own output is captured by ``$(...)`` in the Bash-guard
        entrypoint. A backgrounded recorder that held that pipe open would make
        every refusal wait for the ledger lock.
        """
        slow = tmp_path / "slow-python"
        slow.write_text("#!/bin/sh\ncat >/dev/null\nsleep 5\n", encoding="utf-8")
        slow.chmod(0o755)
        script = (
            '_OMNICLAUDE_HOOK_NAME="t.sh"; source "${TEST_ERROR_GUARD}"; '
            "TOOL_INFO='{}'; "
            'out=$(hook_record_refusal "r" "d"; echo done); trap - EXIT; echo "$out"'
        )
        started = time.monotonic()
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            check=False,
            env=box.env({"PYTHON_CMD": str(slow)}),
            stdin=subprocess.DEVNULL,
            timeout=30,
        )
        elapsed = time.monotonic() - started
        assert result.stdout.strip() == "done", result.stderr
        assert elapsed < 3, f"hook_record_refusal held the caller for {elapsed:.1f}s"


# =============================================================================
# AC3 — every guard that records a refusal is named on its row
# =============================================================================

_RECORD_CALL = re.compile(r"^\s*[^#\n]*\bhook_record_refusal\s+\S", re.MULTILINE)
_NAME_SET = re.compile(r"^\s*_OMNICLAUDE_HOOK_NAME=", re.MULTILINE)
_SOURCES_SEAM = re.compile(
    r"^\s*(?:source|\.)\s+\S*(?:error-guard\.sh|hook_refusal\.sh)", re.MULTILINE
)
_SOURCES_ERROR_GUARD = re.compile(
    r"^\s*(?:source|\.)\s+\S*error-guard\.sh", re.MULTILINE
)


def _recording_scripts() -> list[Path]:
    """Every hook script with a call to the recorder, derived from the tree."""
    return sorted(
        p
        for p in SCRIPTS_DIR.glob("*.sh")
        if p.name != "error-guard.sh"
        and _RECORD_CALL.search(p.read_text(encoding="utf-8"))
    )


def _error_guard_sourcing_scripts() -> list[Path]:
    return sorted(
        p
        for p in SCRIPTS_DIR.glob("*.sh")
        if p.name != "error-guard.sh"
        and _SOURCES_ERROR_GUARD.search(p.read_text(encoding="utf-8"))
    )


class TestEveryGuardIsNamed:
    def test_refusal_row_guard_named_positive_control(self) -> None:
        """Guards against a vacuous pass over zero scripts."""
        assert len(_recording_scripts()) >= 15, _recording_scripts()
        assert len(_error_guard_sourcing_scripts()) >= 15

    @pytest.mark.parametrize("script", _recording_scripts(), ids=lambda p: p.name)
    def test_refusal_row_guard_named_before_recording(self, script: Path) -> None:
        """A script that reaches ``hook_record_refusal`` without setting its
        hook name records as ``guard=unknown-hook`` -- 150 of the 584 live rows.
        The name must be set before the seam is sourced (error-guard.sh keys
        its per-hook log on it at source time) and before the first call.
        """
        source = script.read_text(encoding="utf-8")
        name = _NAME_SET.search(source)
        assert name, (
            f"{script.name} records refusals but never sets _OMNICLAUDE_HOOK_NAME"
        )
        seam = _SOURCES_SEAM.search(source)
        call = _RECORD_CALL.search(source)
        assert call is not None
        assert name.start() < call.start(), (
            f"{script.name} names itself after recording"
        )
        if seam is not None:
            assert name.start() < seam.start(), (
                f"{script.name} sources the refusal seam before naming itself"
            )

    @pytest.mark.parametrize("script", _recording_scripts(), ids=lambda p: p.name)
    def test_refusal_row_guard_named_and_the_recorder_is_in_scope(
        self, script: Path
    ) -> None:
        """A call to a function the script never sourced is a command-not-found
        that ``2>/dev/null || true`` silences: the refusal is recorded nowhere.
        """
        source = script.read_text(encoding="utf-8")
        assert _SOURCES_SEAM.search(source), (
            f"{script.name} calls hook_record_refusal but sources neither "
            "error-guard.sh nor lib/hook_refusal.sh, so the call never runs"
        )

    @pytest.mark.parametrize(
        "script", _error_guard_sourcing_scripts(), ids=lambda p: p.name
    )
    def test_refusal_row_guard_named_for_every_error_guard_script(
        self, script: Path
    ) -> None:
        """The ticket's falsifier, literally: every hook script that sources
        error-guard.sh sets its hook name first, whether or not it records a
        refusal today, so the next deny path added to it is named.
        """
        source = script.read_text(encoding="utf-8")
        name = _NAME_SET.search(source)
        seam = _SOURCES_ERROR_GUARD.search(source)
        assert seam is not None
        assert name is not None and name.start() < seam.start(), (
            f"{script.name} sources error-guard.sh without setting "
            "_OMNICLAUDE_HOOK_NAME first, so it logs and records as unknown-hook"
        )

    def test_refusal_row_guard_named_on_the_row(self, box: Sandbox) -> None:
        row = box.refuse(box.payload(), env={"TEST_HOOK_NAME": "pre_tool_use_x.sh"})
        assert _cell(row, "guard") == "pre_tool_use_x.sh"


class TestARelativelySourcedSeamSurvivesACd:
    def test_refusal_row_written_after_the_guard_cds_home(self, box: Sandbox) -> None:
        """Several guards ``cd "$HOME"`` after sourcing error-guard.sh. A seam
        sourced by a relative path must still find its recorder afterwards.
        """
        script = (
            'cd "$(dirname "${TEST_ERROR_GUARD}")" && '
            '_OMNICLAUDE_HOOK_NAME="relative.sh" && source ./error-guard.sh && '
            'cd "$HOME" && TOOL_INFO=$(cat) && '
            'hook_record_refusal "relative seam" "d"; trap - EXIT'
        )
        before = box.ledger.read_text(encoding="utf-8").count("guard=relative.sh")
        result = subprocess.run(
            ["bash", "-c", script],
            input=json.dumps(box.payload()),
            capture_output=True,
            text=True,
            check=False,
            env=box.env({"ONEX_LANE": "relative-lane"}),
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            text = box.ledger.read_text(encoding="utf-8")
            if text.count("guard=relative.sh") > before:
                break
            time.sleep(0.05)
        row = [line for line in text.splitlines() if "guard=relative.sh" in line][-1]
        assert _cell(row, "lane") == "relative-lane"
