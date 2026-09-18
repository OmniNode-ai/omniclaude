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
        "produced a tool.executed row and zero skill.* rows."
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
        f"{sorted({r.get('event_type') for r in _journal_records(journal_dir)})}"
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

_SHELL_RESERVED = frozenset(
    [
        "if",
        "then",
        "else",
        "elif",
        "fi",
        "for",
        "while",
        "until",
        "do",
        "done",
        "case",
        "esac",
        "function",
        "select",
        "time",
        "in",
        "coproc",
        "return",
        "break",
        "continue",
        "exit",
        "local",
        "declare",
        "typeset",
        "readonly",
        "export",
        "unset",
        "eval",
        "exec",
        "source",
        "shift",
        "set",
        "shopt",
        "trap",
        "wait",
        "echo",
        "printf",
        "read",
        "cd",
        "pwd",
        "test",
        "true",
        "false",
        "let",
        "alias",
        "unalias",
        "builtin",
        "command",
        "type",
        "getopts",
        "hash",
        "umask",
        "ulimit",
        "jobs",
        "kill",
        "fg",
        "bg",
        "disown",
        "mapfile",
        "readarray",
        "caller",
        "enable",
        "logout",
        "suspend",
        "times",
        "compgen",
        "complete",
        "compopt",
        "dirs",
        "popd",
        "pushd",
        "help",
        "history",
        "bind",
    ]
)

# The naming convention every function in this tree follows: lowercase
# snake_case carrying at least one underscore. Bounding the scan to that
# shape is what keeps it from reporting English prose and jq filter words as
# calls; the cost is stated in the test's own docstring rather than hidden.
_HELPER_SHAPE = re.compile(r"^[a-z_][a-z0-9_]*$")

# A call is the first word of a statement. An assignment is not a call, so a
# token immediately followed by `=` is excluded rather than reported.
_CALL_TOKEN = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)(?:\s|$)")
_STATEMENT_SPLIT = re.compile(r"(?:[;&|]|&&|\|\||\bthen\b|\bdo\b|\belse\b|\{|\()")
_HEREDOC_OPEN = re.compile(r"<<-?\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?")

# Spans that are data rather than code, innermost first. An awk or jq program,
# a log message, and the body of `$(( ... ))` all contain bare words that read
# as call tokens and are not.
_SUBSTITUTION = re.compile(r"\$\([^()]*\)")
_BACKTICK = re.compile(r"`[^`]*`")

# `word)` and `a|b|c)` open a case arm. The words in them are patterns, not
# calls, and they are the one construct where a bare word legitimately leads a
# statement without being invoked.
_CASE_ARM = re.compile(r"^\(?[A-Za-z0-9_*?.@/+|\[\]-]+\)")


def _defined_function_names() -> set[str]:
    """Every shell function defined anywhere under the hooks tree.

    Tree-wide rather than per-script on purpose: which lib a given script
    sources is a detail that moves, but a callee defined NOWHERE cannot be
    reached from anywhere, and that is the class of defect this catches.
    """
    names: set[str] = set()
    for path in sorted(PLUGIN_DIR.rglob("*.sh")):
        for match in re.finditer(
            r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_.-]*)\s*\(\)\s*\{",
            path.read_text(encoding="utf-8", errors="replace"),
            re.MULTILINE,
        ):
            names.add(match.group(1))
    return names


def _strip_arithmetic(line: str) -> str:
    """Blank every `(( ... ))` and `$(( ... ))` span, nesting included.

    A regex cannot do this: `$(((_ms % 1000) / 100))` nests, and a
    non-greedy `[^()]*` body simply fails to match it, which is how
    `_timeout_ms` and `_age_secs` read as calls. A subshell `( ... )` is
    deliberately NOT stripped -- its body is code and does contain calls.
    """
    index = 0
    out: list[str] = []
    while index < len(line):
        start = index
        if line.startswith("$((", index):
            start = index + 1
        elif not line.startswith("((", index):
            out.append(line[index])
            index += 1
            continue
        depth = 0
        cursor = start
        while cursor < len(line):
            if line[cursor] == "(":
                depth += 1
            elif line[cursor] == ")":
                depth -= 1
                if depth == 0:
                    break
            cursor += 1
        if depth != 0:
            out.append(line[index])
            index += 1
            continue
        out.append(" " * (cursor + 1 - index))
        index = cursor + 1
    return "".join(out)


def _strip_literals(line: str) -> str:
    """Remove substitutions and arithmetic from a shell line.

    Quoted spans are already blanked by the character scanner. What remains
    here is bare shell words, which is the only place a function call can
    appear. Without this, `TOTAL=$(( _in + _out ))` reports `_in` as an
    undefined callee.
    """
    previous = None
    while previous != line:
        previous = line
        line = _strip_arithmetic(line)
        line = _SUBSTITUTION.sub(" ", line)
    line = _BACKTICK.sub(" ", line)
    return line


def _blank_heredoc_bodies(text: str) -> str:
    """Replace every heredoc body with blank lines of the same count.

    A line pre-pass, deliberately ahead of the character scanner rather than
    inside it. `DIRECTIVE="$("$PY" - "$F" <<'PYEOF'` opens its heredoc while
    a naive scanner still believes it is inside the double quote that opened
    the command substitution, so the scanner never sees the `<<` and reads
    the whole inlined Python program as shell. Finding the opener on the raw
    line does not depend on getting the quote nesting right, and a heredoc
    body is the single largest source of words that are not code.
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    terminator: str | None = None
    for raw in lines:
        if terminator is not None:
            out.append("\n" if raw.endswith("\n") else "")
            if raw.strip() == terminator:
                terminator = None
            continue
        out.append(raw)
        stripped = raw.strip()
        if stripped.startswith("#"):
            continue
        opened = _HEREDOC_OPEN.search(raw)
        if opened is not None:
            terminator = opened.group(1)
    return "".join(out)


def _shell_statement_lines(text: str) -> list[tuple[int, str]]:
    """The lines of a script that are shell statements, and only those.

    A single character pass over the whole file, because quoting in shell is
    not a per-line property: an awk program, a jq filter and a multi-line log
    message all open a quote on one line and close it several lines later.
    Counting quotes per line gets each of those wrong.

    Heredoc bodies (inline Python, jq programs, injected prompt text), quoted
    spans and comments are DATA, not code. They come back as blanks so the
    line numbers still line up with the file, while nothing inside them can
    be read as a call. Scanning them is how a text-level check starts
    reporting on English and then gets suppressed into uselessness -- which
    is the failure mode this whole file exists to replace.
    """
    text = _blank_heredoc_bodies(text)
    out: list[list[str]] = [[]]
    index = 0
    length = len(text)
    state = "code"  # code | single | double | comment | heredoc
    # Quoting restarts inside a command substitution, so `"$(jq -n '{...}'`
    # opens a single-quoted jq program even though the outer double quote is
    # still open. Without this stack that program is read as shell.
    saved_states: list[str] = []
    substitution_depth: list[int] = []
    heredoc_terminator = ""
    pending_heredoc = ""
    line_start = True

    def push(char: str) -> None:
        if char == "\n":
            out.append([])
        else:
            out[-1].append(char)

    while index < length:
        char = text[index]

        if char == "\n":
            if state in ("comment", "single_line"):
                state = "code"
            if state == "code" and pending_heredoc:
                state = "heredoc"
                heredoc_terminator = pending_heredoc
                pending_heredoc = ""
            push("\n")
            index += 1
            line_start = True
            continue

        if state == "heredoc":
            end = text.find("\n", index)
            end = length if end == -1 else end
            if text[index:end].strip() == heredoc_terminator:
                state = "code"
            push(" " * (end - index))
            index = end
            continue

        if state == "comment":
            push(" ")
            index += 1
            continue

        if state == "single":
            if char == "'":
                state = "code"
            push(" ")
            index += 1
            continue

        if state == "double" and text.startswith("$(", index):
            saved_states.append(state)
            substitution_depth.append(0)
            state = "code"
            push("  ")
            index += 2
            continue

        if state == "double":
            if char == "\\" and index + 1 < length:
                # A line continuation still ends a line: swallowing its newline
                # silently shifts every subsequent finding's line number.
                push(" ")
                push("\n" if text[index + 1] == "\n" else " ")
                index += 2
                continue
            if char == '"':
                state = "code"
            push(" ")
            index += 1
            continue

        # state == "code"
        if char == "\\" and index + 1 < length:
            push(" ")
            if text[index + 1] == "\n":
                push("\n")
                line_start = True
            else:
                push(" ")
                line_start = False
            index += 2
            continue
        if char == "#" and (line_start or text[index - 1] in " \t;&|("):
            state = "comment"
            push(" ")
            index += 1
            continue
        if char == "'":
            state = "single"
            push(" ")
            index += 1
            line_start = False
            continue
        if char == '"':
            state = "double"
            push(" ")
            index += 1
            line_start = False
            continue
        if text.startswith("$((", index) or text.startswith("((", index):
            # Arithmetic, not a command substitution. `$((_ms % 1000) / 100)`
            # nests, so the span is walked with a depth counter rather than
            # matched; its body is values, never calls.
            start = index + 1 if text[index] == "$" else index
            depth = 0
            cursor = start
            while cursor < length:
                if text[cursor] == "(":
                    depth += 1
                elif text[cursor] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                cursor += 1
            if depth == 0 and cursor < length:
                for blanked in text[index : cursor + 1]:
                    push("\n" if blanked == "\n" else " ")
                index = cursor + 1
                line_start = False
                continue

        if text.startswith("$(", index):
            saved_states.append(state)
            substitution_depth.append(0)
            push("  ")
            index += 2
            line_start = False
            continue
        if substitution_depth:
            if char == "(":
                substitution_depth[-1] += 1
            elif char == ")":
                if substitution_depth[-1] == 0:
                    substitution_depth.pop()
                    state = saved_states.pop()
                    push(" ")
                    index += 1
                    line_start = False
                    continue
                substitution_depth[-1] -= 1
        if char == "<" and text.startswith("<<", index):
            opened = _HEREDOC_OPEN.match(text, index)
            if opened is not None:
                pending_heredoc = opened.group(1)
                push(" " * (opened.end() - index))
                index = opened.end()
                line_start = False
                continue
        push(char)
        index += 1
        if not char.isspace():
            line_start = False

    lines: list[tuple[int, str]] = []
    for number, chars in enumerate(out, start=1):
        code = "".join(chars).strip()
        if code:
            lines.append((number, code))
    return lines


def undefined_shell_callees(
    scripts_dir: Path, defined: set[str] | None = None
) -> list[tuple[Path, int, str]]:
    """Call tokens resolving to nothing: not a function, builtin, or on PATH.

    Deliberately conservative -- a token is only reported when it has the
    tree's own helper shape AND all three resolutions fail. The bound is real
    and is stated rather than implied: a deleted callee named without an
    underscore would not be reported. What it does catch is the class that
    actually occurred, and it catches it without a suppression list.
    """
    known = _defined_function_names() if defined is None else defined
    findings: list[tuple[Path, int, str]] = []
    for path in sorted(scripts_dir.glob("*.sh")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in _shell_statement_lines(text):
            code = _strip_literals(line)
            if _CASE_ARM.match(code):
                continue
            for fragment in _STATEMENT_SPLIT.split(code):
                fragment = fragment.strip()
                if not fragment:
                    continue
                match = _CALL_TOKEN.match(fragment)
                if not match:
                    continue
                token = match.group(1)
                if token in known or token in _SHELL_RESERVED:
                    continue
                if not _HELPER_SHAPE.match(token) or "_" not in token:
                    continue
                remainder = fragment[len(token) :].lstrip()
                # An assignment is not a call, and `word)` is a case pattern.
                if remainder.startswith(("=", "+=", ")")):
                    continue
                if shutil.which(token) is not None:
                    continue
                findings.append((path, number, token))
    return findings


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
