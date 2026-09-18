# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The hook edge's journal callee exists and actually writes (OMN-18702).

Written RED against `origin/dev`, where `emit_to_journal` is called at ten
sites across six hook scripts and defined nowhere. It was added by
`0477e64f6` (OMN-18471, omniclaude#2209) at `common.sh:720` and deleted by
`7924f64b7` (OMN-18471 AC5, omniclaude#2214) as collateral in a 293-line
removal of `emit_via_daemon` and its counter surface -- the function sat in
the middle of the block that was cut. Every call has exited 127 since
2026-09-17T06:50Z.

Two existing guards read the same token and both stayed green through the
outage: `test_hook_edge_lane.py` and `test_hook_emit_health.py` scan `.sh`
text for `emit_to_journal ` and parse the class name out of the next quoted
word. Neither sources `common.sh`; neither asks whether the callee exists.
A check that proves a CALLER is present while never executing it cannot tell
a working edge from a 127.

So the tests here are of two kinds, and the second is the durable half:

* behavioural -- run the real hook script against a temp journal and assert
  a record of the right class lands. This is what the text scans could not do.
* structural -- `undefined_shell_callees()` reports any call token in a hook
  script that resolves to no function defined anywhere under
  `plugins/onex/hooks/**`, is not a shell builtin, and is not on PATH. It is
  proven by construction rather than asserted: one test runs it against a
  fixture tree carrying a deliberately undefined callee and requires it to be
  found, so a check that silently stopped reporting would fail here first.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO_ROOT / "plugins" / "onex"
HOOKS_DIR = PLUGIN_DIR / "hooks"
SCRIPTS_DIR = HOOKS_DIR / "scripts"
COMMON_SH = SCRIPTS_DIR / "common.sh"
HOOKS_JSON = HOOKS_DIR / "hooks.json"
PRE_SKILL_HOOK = SCRIPTS_DIR / "pre_tool_use_skill_started.sh"
POST_QUALITY_HOOK = SCRIPTS_DIR / "post-tool-use-quality.sh"

# The journal writer every working class on this edge already uses; see
# post_tool_use_bus_mirror.sh, which is the reason tool.executed survived the
# same deletion.
JOURNAL_WRITER = "hook_emit_append.py"

RUN_ID = "toolu_omn18702redproof"
SESSION_ID = "sess-omn18702"
SKILL_NAME = "onex:delegate"

# A record may be written by a backgrounded subshell, so the behavioural
# tests poll rather than read once.
_POLL_SECONDS = 20.0
_POLL_INTERVAL = 0.2


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _hook_env(tmp_path: Path) -> dict[str, str]:
    """A hook environment whose journal and logs are redirected to tmp_path.

    `ONEX_HOOK_EMIT_JOURNAL_DIR` is the override `hook_emit_journal.py`
    reads first, so nothing here can append to the operator's live spool.
    """
    state_dir = tmp_path / "state"
    journal_dir = tmp_path / "journal"
    state_dir.mkdir(parents=True, exist_ok=True)
    journal_dir.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.update(
        {
            "ONEX_STATE_DIR": str(state_dir),
            "ONEX_HOOK_EMIT_JOURNAL_DIR": str(journal_dir),
            "CLAUDE_PLUGIN_ROOT": str(HOOKS_DIR.parent),
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "OMNICLAUDE_PROJECT_ROOT": str(REPO_ROOT),
            # The bitmask gates default open, but pin them so a mask exported
            # by the surrounding session cannot silently skip the hook and
            # make this test read as a pass.
            "ONEX_HOOKS_MASK": "",
            # Pinned, and NOT incidental -- measured, because the unpinned
            # form passed locally and failed on CI. The quality hook exits 0
            # at its lite-mode guard before doing anything at all. Proven as
            # a pair against the real script: `lite` gives exit 0 and zero
            # records, which is exactly the CI symptom; `full` gives exit 0
            # and the records.
            #
            # Unpinned, this test is green locally and green on CI for
            # opposite reasons -- one because the hook worked,
            # one because the hook never ran. That is the failure mode this
            # whole file exists to catch, so it is not tolerated in the file
            # itself. `pre_tool_use_skill_started.sh` carries no lite guard,
            # which is why it ran in both places and hid the asymmetry.
            "OMNICLAUDE_MODE": "full",
            "ONEX_CORRELATION_ID": SESSION_ID,
        }
    )
    return env


def _journal_records(journal_dir: Path) -> list[dict]:
    records: list[dict] = []
    for path in sorted(journal_dir.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            continue
        for chunk in text.splitlines() if "\n" in text else [text]:
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                parsed = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
    return records


def _await_record(journal_dir: Path, event_type: str) -> dict | None:
    """Poll for one record of `event_type`; None if none arrives in time."""
    deadline = time.monotonic() + _POLL_SECONDS
    while time.monotonic() < deadline:
        for record in _journal_records(journal_dir):
            if record.get("event_type") == event_type:
                return record
        time.sleep(_POLL_INTERVAL)
    return None


def _diagnostics(result: subprocess.CompletedProcess, tmp_path: Path) -> str:
    """Why a hook produced no record, gathered at the point of failure.

    A bare "no record" tells the next reader nothing and costs a CI cycle to
    turn into a fact. The hook's own log is where every early exit on this
    edge announces itself.
    """
    parts = [f"exit={result.returncode}"]
    if result.stderr.strip():
        parts.append(f"stderr={result.stderr[-1500:]}")
    logs = tmp_path / "state" / "hooks" / "logs"
    if logs.is_dir():
        for log in sorted(logs.glob("*.log")):
            tail = log.read_text(encoding="utf-8", errors="replace")[-1500:]
            if tail.strip():
                parts.append(f"{log.name}:\n{tail}")
    else:
        parts.append(
            "the hook wrote no log at all, so it exited before its logging "
            "was set up -- the lite-mode guard is the first such exit"
        )
    return "\n".join(parts)


def _run_hook(
    script: Path, payload: dict, tmp_path: Path
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        # The exit status is asserted by the caller, because a hook on this
        # edge is fail-open and a non-zero exit is itself a finding.
        check=False,
        env=_hook_env(tmp_path),
        cwd=str(REPO_ROOT),
        timeout=180,
    )


# ---------------------------------------------------------------------------
# AC2 -- the callee exists, exactly once, and delegates to the shared writer
# ---------------------------------------------------------------------------


def test_emit_to_journal_is_defined_exactly_once_in_common_sh() -> None:
    """RED on dev: zero definitions for ten call sites.

    Exactly once rather than at-least-once: two definitions in a sourced file
    means the later silently wins, which is how a delivery path acquires a
    second, untested shape.
    """
    definitions = re.findall(
        r"^emit_to_journal\s*\(\)", COMMON_SH.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert len(definitions) == 1, (
        f"emit_to_journal is defined {len(definitions)} time(s) in common.sh; "
        f"expected exactly 1. It is CALLED at "
        f"{len(_call_sites())} site(s) across the hook scripts, and a call to "
        f"an undefined shell function exits 127 and drops the event."
    )


def test_emit_to_journal_delegates_to_the_shared_journal_writer() -> None:
    """No second transport. The same writer tool.executed already uses.

    Pins the contract-native shape: this is a shell function handing off to
    `hook_emit_append.py`, not a new daemon, socket or client class. The
    class this replaced (`emit_via_daemon`) failed exactly because it had a
    private transport of its own.
    """
    body = _function_body(COMMON_SH.read_text(encoding="utf-8"), "emit_to_journal")
    assert body, "emit_to_journal has no body to inspect in common.sh"
    assert JOURNAL_WRITER in body, (
        f"emit_to_journal does not invoke {JOURNAL_WRITER}. The hook edge has "
        f"one delivery path and this is it; a second transport is the defect "
        f"OMN-18471 was retiring, not a fix for it."
    )
    for forbidden in ("emit.sock", "emit_client_wrapper.py", "node_event_emit_effect"):
        assert forbidden not in body, (
            f"emit_to_journal reaches for {forbidden!r}. That is the retired "
            f"path (a socket deleted 2026-06-08) or the per-call Pydantic "
            f"import OMN-17224 removed from this edge."
        )


def _call_sites() -> list[tuple[Path, int, str]]:
    """Every `emit_to_journal <class>` call in the hook scripts, uncommented."""
    sites: list[tuple[Path, int, str]] = []
    for path in sorted(SCRIPTS_DIR.glob("*.sh")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if stripped.startswith("#") or "emit_to_journal " not in stripped:
                continue
            sites.append((path, number, stripped))
    return sites


def _function_body(text: str, name: str) -> str:
    """The lines of a top-level `name() { ... }` definition, or ''."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(name)}\s*\(\)", line):
            collected: list[str] = []
            for candidate in lines[index + 1 :]:
                if candidate.startswith("}"):
                    return "\n".join(collected)
                collected.append(candidate)
    return ""


# ---------------------------------------------------------------------------
# AC1 / AC4 -- the behavioural proof the text scans could not give
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("jq") is None, reason="hook scripts require jq")
def test_pre_tool_use_skill_started_writes_a_skill_started_record(
    tmp_path: Path,
) -> None:
    """AC1, RED first.

    On dev this script reaches `emit_to_journal "skill.started" ...`, gets
    127, and exits 0 anyway because the whole edge is fail-open -- which is
    precisely why the outage was silent. The falsifier is stated on the
    ticket: if this passes before the fix, the finding is wrong.
    """
    journal_dir = tmp_path / "journal"
    result = _run_hook(
        PRE_SKILL_HOOK,
        {
            "session_id": SESSION_ID,
            "tool_use_id": RUN_ID,
            "tool_name": "Skill",
            "tool_input": {"skill": SKILL_NAME},
            "cwd": str(REPO_ROOT),
        },
        tmp_path,
    )
    # The hook is fail-open by design and must stay that way; its exit status
    # is not the signal. The record is.
    assert result.returncode == 0, (
        f"the skill-started hook must never fail a session: exit "
        f"{result.returncode}, stderr={result.stderr[-2000:]}"
    )

    record = _await_record(journal_dir, "skill.started")
    assert record is not None, (
        "no skill.started record reached the journal. Records present: "
        f"{sorted({r.get('event_type') for r in _journal_records(journal_dir)})}. "
        "This is the live defect: a Skill invocation at 2026-09-18T12:27:51Z "
        "produced a tool.executed row and zero skill.* rows.\n"
        + _diagnostics(result, tmp_path)
    )
    payload = record.get("payload") or {}
    assert payload.get("run_id") == RUN_ID, (
        "the record must key on Claude's own tool_use_id -- the hook never "
        f"invents an invocation id: {payload!r}"
    )
    assert payload.get("skill_name") == SKILL_NAME


@pytest.mark.skipif(shutil.which("jq") is None, reason="hook scripts require jq")
def test_post_tool_use_quality_writes_a_matching_skill_completed_record(
    tmp_path: Path,
) -> None:
    """AC4 -- the PostToolUse half, which shares the defect.

    The pair is what makes the class usable: a `skill.started` with no
    terminal record is indistinguishable from a skill that never returned,
    so both sites have to be proven, not just the one in the ticket title.
    """
    journal_dir = tmp_path / "journal"
    result = _run_hook(
        POST_QUALITY_HOOK,
        {
            "session_id": SESSION_ID,
            "tool_use_id": RUN_ID,
            "tool_name": "Skill",
            "tool_input": {"skill": SKILL_NAME},
            "tool_response": {},
            "cwd": str(REPO_ROOT),
        },
        tmp_path,
    )
    assert result.returncode == 0, (
        f"the quality hook must never fail a session: exit {result.returncode}, "
        f"stderr={result.stderr[-2000:]}"
    )

    record = _await_record(journal_dir, "skill.completed")
    assert record is not None, (
        "no skill.completed record reached the journal. Records present: "
        f"{sorted({r.get('event_type') for r in _journal_records(journal_dir)})}\n"
        + _diagnostics(result, tmp_path)
    )
    payload = record.get("payload") or {}
    assert payload.get("run_id") == RUN_ID, (
        f"skill.completed must carry the same tool_use_id the PreToolUse "
        f"record used, or the two cannot be joined: {payload!r}"
    )
    assert payload.get("status") == "success"


# ---------------------------------------------------------------------------
# AC3 -- the structural check that would have caught the deletion
# ---------------------------------------------------------------------------

# The scanner itself lives in `scripts/validation/validate_hook_callees.py`,
# not here. It is a pre-commit hook and a CLI as well as these tests, and a
# gate with two implementations is a gate that can disagree with itself --
# which is the shape of the defect this file exists for. One implementation,
# three callers.
sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))

from validate_hook_callees import (  # noqa: E402
    _defined_function_names,
    undefined_shell_callees,
)

PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
CALLEE_VALIDATOR = REPO_ROOT / "scripts" / "validation" / "validate_hook_callees.py"


def test_no_hook_script_calls_a_function_defined_nowhere() -> None:
    """AC3. The gate the two text scans were standing in for.

    On dev this reports `emit_to_journal` at ten sites. After the fix it
    reports nothing.
    """
    findings = undefined_shell_callees(SCRIPTS_DIR)
    rendered = "\n".join(
        f"  {path.relative_to(REPO_ROOT)}:{number}: {token}"
        for path, number, token in findings
    )
    assert not findings, (
        "hook scripts call functions that are defined nowhere under "
        "plugins/onex/hooks/**, are not shell builtins, and are not on PATH. "
        "A call to an undefined shell function exits 127 and, on this "
        "fail-open edge, drops the event silently:\n" + rendered
    )


def test_the_undefined_callee_check_finds_a_planted_callee(tmp_path: Path) -> None:
    """The positive control. Without it, a zero here means nothing.

    Rule 16: an empty result is not evidence of absence. This plants a call
    to a function that exists nowhere and requires the check to report it, so
    a check that quietly stopped matching fails HERE rather than going green
    across a second outage.
    """
    planted = tmp_path / "scripts"
    planted.mkdir()
    (planted / "planted_hook.sh").write_text(
        "#!/bin/bash\n"
        "set -uo pipefail\n"
        '# emit_to_journal "commented.out" "$P" "$C"  <- a comment is not a call\n'
        'a_function_that_does_not_exist "skill.started" "$PAYLOAD"\n',
        encoding="utf-8",
    )
    findings = undefined_shell_callees(planted, defined=_defined_function_names())
    tokens = {token for _, _, token in findings}
    assert "a_function_that_does_not_exist" in tokens, (
        "the undefined-callee check did not report a planted undefined "
        f"callee, so a clean result from it proves nothing. Reported: {tokens}"
    )
    assert "emit_to_journal" not in tokens, (
        "the check matched inside a comment; that is how a text scan starts "
        "reporting on documentation about itself rather than on code"
    )


# ---------------------------------------------------------------------------
# AC5 -- the matcher registration the records depend on
# ---------------------------------------------------------------------------


def test_hooks_json_registers_both_skill_matchers() -> None:
    """A defined callee still emits nothing if no Skill matcher fires it.

    Asserted against the parsed registration rather than a text count, and
    against the SCRIPT each matcher runs, because a `"matcher": "Skill"`
    group pointing at some other script would satisfy a grep and capture
    nothing.
    """
    registration = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    hooks = registration.get("hooks", registration)

    def commands_for(event: str) -> set[str]:
        found: set[str] = set()
        for group in hooks.get(event, []):
            if group.get("matcher") != "Skill":
                continue
            for entry in group.get("hooks", []):
                found.add(Path(entry.get("command", "")).name)
        return found

    assert PRE_SKILL_HOOK.name in commands_for("PreToolUse"), (
        "no PreToolUse Skill matcher runs "
        f"{PRE_SKILL_HOOK.name}, so skill.started can never fire"
    )
    assert POST_QUALITY_HOOK.name in commands_for("PostToolUse"), (
        "no PostToolUse Skill matcher runs "
        f"{POST_QUALITY_HOOK.name}, so skill.completed can never fire"
    )


# ---------------------------------------------------------------------------
# Rule 5 -- the check is wired, not merely written
# ---------------------------------------------------------------------------


def test_the_callee_gate_is_registered_as_a_pre_commit_hook() -> None:
    """Detection that is not wired is advisory, and advisory gets ignored.

    Asserted on the registration rather than trusted, because the whole
    finding behind this file is a guard that existed, ran, and proved the
    wrong thing. A gate deleted from the config is exactly as silent as the
    function that was deleted from `common.sh`.

    The merge-blocking half needs no assertion here: these tests run in the
    unit suite behind `Tests Gate`, a live required context on `dev`. This
    hook is the local fail-fast half, which is where a deletion like
    omniclaude#2214's should have been refused -- at the commit that made it.
    """
    config = PRE_COMMIT_CONFIG.read_text(encoding="utf-8")
    assert "id: hook-callee-gate" in config, (
        "the undefined-callee gate is not registered in .pre-commit-config.yaml. "
        "Removing the registration silently disarms it; if it fired wrongly, "
        "fix the scanner rather than unwiring the check."
    )
    assert "validate_hook_callees.py" in config, (
        "the hook-callee-gate registration does not invoke "
        "scripts/validation/validate_hook_callees.py, so it runs something else"
    )


def test_the_callee_gate_cli_fails_on_a_planted_callee(tmp_path: Path) -> None:
    """The CLI exits non-zero, which is the only thing pre-commit reads.

    A scanner that returns findings to Python but exits 0 is a hook that
    always passes. This asserts the exit status of the same entrypoint the
    pre-commit registration names, not the function behind it.
    """
    planted = tmp_path / "scripts"
    planted.mkdir()
    (planted / "planted_hook.sh").write_text(
        '#!/bin/bash\na_callee_that_does_not_exist "skill.started" "$P"\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(CALLEE_VALIDATOR), "--scripts-dir", str(planted)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 1, (
        f"the callee gate CLI exited {result.returncode} on a planted "
        f"undefined callee; pre-commit reads the exit status and nothing "
        f"else, so a zero here is a hook that can never fail. "
        f"stdout={result.stdout[-800:]} stderr={result.stderr[-800:]}"
    )
    assert "a_callee_that_does_not_exist" in result.stderr, (
        "the gate failed without naming the offending callee, which leaves "
        f"the author nothing to act on: {result.stderr[-800:]}"
    )


def test_the_callee_gate_passes_on_the_current_tree() -> None:
    """The committed tree is clean, asserted through the CLI's exit status."""
    result = subprocess.run(
        [sys.executable, str(CALLEE_VALIDATOR)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"the callee gate fails on the committed tree: {result.stderr[-2000:]}"
    )


# ---------------------------------------------------------------------------
# OMN-18750 -- no hook may reach the onex CLI through uv
# ---------------------------------------------------------------------------

# Why this check lives beside the undefined-callee one: both describe the same
# failure shape, a hook that runs and accomplishes nothing. An undefined callee
# exits 127; a `uv run onex` that falls through to PATH fails to spawn. On this
# fail-open edge each is silent, and on 2026-09-18 a full working day went into
# testing the hypothesis that a hook was doing the second of those. It was not
# -- the real cause was a quoting mistake in an agent's own prose (OMN-18750) --
# but the search is what a standing check is cheaper than.

from validate_hook_callees import uv_mediated_onex_invocations  # noqa: E402


def test_no_hook_script_reaches_onex_through_uv() -> None:
    """OMN-18750 AC4. Zero on the live tree, and the bar going forward."""
    findings = uv_mediated_onex_invocations(SCRIPTS_DIR)
    rendered = "\n".join(
        f"  {path.relative_to(REPO_ROOT)}:{number}: {statement}"
        for path, number, statement in findings
    )
    assert not findings, (
        "hook scripts reach the onex CLI through uv. uv does not pin the "
        "command to the project environment, so it falls through to PATH, "
        "where the sanctioned onex is a shell alias uv cannot see. Use the "
        "wrapper resolved through $OMNI_HOME (operating rule 11):\n" + rendered
    )


def test_the_uv_onex_check_finds_a_planted_invocation(tmp_path: Path) -> None:
    """The positive control. Rule 16: a zero with no control proves nothing."""
    planted = tmp_path / "scripts"
    planted.mkdir()
    (planted / "planted_uv_hook.sh").write_text(
        "#!/bin/bash\n"
        "set -uo pipefail\n"
        "RESULT=$(uv run onex run-node node_x --input '{}')\n",
        encoding="utf-8",
    )
    findings = uv_mediated_onex_invocations(planted)
    assert findings, (
        "the uv-mediated onex check did not report a planted invocation, so a "
        "clean result from it proves nothing."
    )


def test_the_uv_onex_check_ignores_a_comment(tmp_path: Path) -> None:
    """A comment naming the forbidden form is documentation, not a call.

    Workspace rule 15: a gate that fires on prose about the gate is the
    OCC#7213 shape. This module's own docstrings name the form; so do the
    refusal messages the scanner prints.
    """
    planted = tmp_path / "scripts"
    planted.mkdir()
    (planted / "commented_hook.sh").write_text(
        "#!/bin/bash\n"
        "set -uo pipefail\n"
        "# Never reach the CLI with uv run onex -- use the wrapper instead.\n"
        'echo "done"\n',
        encoding="utf-8",
    )
    assert not uv_mediated_onex_invocations(planted), (
        "the check fired on a comment, which would refuse the documentation "
        "that explains the rule."
    )
