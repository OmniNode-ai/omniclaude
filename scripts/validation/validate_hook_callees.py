# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Refuse a hook script that calls a function defined nowhere (OMN-18702).

A call to an undefined shell function exits 127. Every script on the hook
edge is fail-open by design, so the caller swallows that 127, exits 0, and
the event is simply gone -- no error, no log line, no failing check.

That is not hypothetical. `emit_to_journal` was defined by omniclaude#2209,
deleted by #2214 as collateral in a 293-line removal of a neighbouring
function, and left ten call sites across six scripts calling nothing for a
day and a half. Nine event classes -- skill started and completed, agent
action, response stopped, session outcome, routing feedback, llm cost,
utilization scoring, and one variable-typed site -- emitted nothing at all.

Two guards already read that surface and both stayed green throughout,
because both match the CALL SITE as text and neither asks whether the callee
exists. This gate asks. It runs as a pre-commit hook and in the unit suite
behind the required `Tests Gate`, so a deletion like #2214's is refused at
the commit that makes it rather than found by reading a journal later.

Deliberately stdlib-only: a gate that needs a dependency installed to run is
a gate that does not run on the machine where it matters most.

Exit status: 0 clean, 1 findings (each printed as path:line: word).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_DIR = _REPO_ROOT / "plugins" / "onex"
_HOOKS_DIR = _PLUGIN_DIR / "hooks"
_SCRIPTS_DIR = _HOOKS_DIR / "scripts"


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
# word immediately followed by `=` is excluded rather than reported.
_CALL_WORD = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*)(?:\s|$)")
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


def _defined_function_names(plugin_dir: Path | None = None) -> set[str]:
    """Every shell function defined anywhere under the hooks tree.

    Tree-wide rather than per-script on purpose: which lib a given script
    sources is a detail that moves, but a callee defined NOWHERE cannot be
    reached from anywhere, and that is the class of defect this catches.
    """
    names: set[str] = set()
    for path in sorted((plugin_dir or _PLUGIN_DIR).rglob("*.sh")):
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

    Deliberately conservative -- a word is only reported when it has the
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
                match = _CALL_WORD.match(fragment)
                if not match:
                    continue
                word = match.group(1)
                if word in known or word in _SHELL_RESERVED:
                    continue
                if not _HELPER_SHAPE.match(word) or "_" not in word:
                    continue
                remainder = fragment[len(word) :].lstrip()
                # An assignment is not a call, and `word)` is a case pattern.
                if remainder.startswith(("=", "+=", ")")):
                    continue
                if shutil.which(word) is not None:
                    continue
                findings.append((path, number, word))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scripts-dir",
        type=Path,
        default=_SCRIPTS_DIR,
        help="Directory of hook scripts to scan (default: the hooks tree).",
    )
    parser.add_argument(
        "--plugin-dir",
        type=Path,
        default=None,
        help=(
            "Tree to collect function DEFINITIONS from (default: the plugin "
            "tree). Separating it from --scripts-dir is what lets this gate "
            "be run against a historical checkout and shown to report the "
            "regression it was written for, rather than only a synthetic one."
        ),
    )
    args = parser.parse_args(argv)

    defined = _defined_function_names(args.plugin_dir) if args.plugin_dir else None
    findings = undefined_shell_callees(args.scripts_dir, defined=defined)
    if not findings:
        print("hook-callee gate PASSED (no undefined callees)")
        return 0

    print(
        "hook-callee gate FAILED: these hook scripts call functions that are "
        "defined nowhere under plugins/onex/**, are not shell builtins, and "
        "are not on PATH. Each call exits 127, and this edge is fail-open, so "
        "the event is dropped silently:",
        file=sys.stderr,
    )
    for path, number, word in findings:
        try:
            shown = path.relative_to(_REPO_ROOT)
        except ValueError:
            shown = path
        print(f"  {shown}:{number}: {word}", file=sys.stderr)
    print(
        "\nDefine the function, or remove the call. Do not add a suppression: "
        "a suppression here is a call site that emits nothing.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
