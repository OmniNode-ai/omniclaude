# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20961: every hook shell script must parse under macOS /bin/bash 3.2.

On 2026-10-11 a one-word comment edit inside a ``$( ... )`` block of
``pre_tool_use_bash_guards.sh`` (an apostrophe in ``session's``) reached the
Mac by a canonical-clone fast-forward at 08:59:37Z. bash 5 on the Linux CI
runners parses that file; macOS ``/bin/bash`` 3.2 matches quotes inside
comments while it scans a command substitution, reads to end of file looking
for the closing quote, and refuses the whole script. Every Bash tool call on
the Mac was refused for about two hours.

Two layers, because CI runs on Linux and cannot run bash 3.2:

* a static scan, run everywhere, that refuses any quote character (``'``,
  ``"`` or a backtick) in a comment that sits inside an open ``$(``;
* ``bash -n`` over every script, which is ``/bin/bash`` 3.2 when the runner is
  macOS (the ground truth the static scan approximates) and the PATH bash
  elsewhere. Neither leg is skipped on any platform.

The positive controls prove the scan fires on the exact pre-image that
caused the outage, so a zero-finding run is evidence and not a broken scan.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
HOOK_DIRS = (
    ROOT / "plugins/onex/hooks/scripts",
    ROOT / "plugins/onex/hooks/lib",
)
QUOTE_CHARS = frozenset("'\"`")
MAC_BASH = Path("/bin/bash")


class Finding(NamedTuple):
    path: str
    line: int
    text: str

    def render(self) -> str:
        return (
            f"{self.path}:{self.line}: quote character in a comment inside $( ): "
            f"{self.text.strip()}"
        )


def hook_shell_scripts() -> list[Path]:
    """Every shell script under the hook script and lib trees."""
    found: set[Path] = set()
    for base in HOOK_DIRS:
        for path in base.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix == ".sh":
                found.add(path)
            elif path.suffix == "":
                try:
                    head = path.read_bytes()[:64]
                except OSError:
                    continue
                if head.startswith(b"#!") and b"bash" in head.split(b"\n", 1)[0]:
                    found.add(path)
    return sorted(found)


def _heredoc_terminator(line: str, start: int) -> tuple[str, bool] | None:
    """Return (word, strip_tabs) when ``<<`` at ``start`` opens a heredoc."""
    rest = line[start + 2 :]
    if rest.startswith("<"):  # here-string, not a heredoc
        return None
    strip_tabs = rest.startswith("-")
    rest = rest[1:] if strip_tabs else rest
    rest = rest.lstrip()
    word = ""
    i = 0
    quote = ""
    while i < len(rest):
        ch = rest[i]
        if quote:
            if ch == quote:
                quote = ""
            else:
                word += ch
        elif ch in "'\"":
            quote = ch
        elif ch == "\\":
            pass
        elif ch.isalnum() or ch in "_-.":
            word += ch
        else:
            break
        i += 1
    return (word, strip_tabs) if word else None


def scan_comment_quotes_in_command_substitution(text: str, path: str) -> list[Finding]:
    """Flag comments inside an open ``$(`` that contain a quote character.

    A small state machine over the script: a stack of contexts (``cmd`` for an
    open ``$(``, ``paren`` for a plain parenthesis inside one, ``dq`` for a
    double-quoted string), single quotes, ``${ }`` expansions, backslash
    escapes, comments and heredoc bodies. It is an approximation of the bash
    grammar, built to have no false positives on this tree; ``/bin/bash -n``
    on macOS is the ground truth.
    """
    findings: list[Finding] = []
    stack: list[str] = []
    lines = text.split("\n")
    pending_heredocs: list[tuple[str, bool]] = []
    in_heredoc: tuple[str, bool] | None = None
    in_sq = False  # a single-quoted string can span lines
    for lineno, line in enumerate(lines, start=1):
        if in_heredoc is not None:
            word, strip_tabs = in_heredoc
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate == word:
                in_heredoc = pending_heredocs.pop(0) if pending_heredocs else None
            continue
        i = 0
        n = len(line)
        while i < n:
            ch = line[i]
            top = stack[-1] if stack else ""
            if in_sq:
                if ch == "'":
                    in_sq = False
                i += 1
                continue
            if ch == "\\":
                i += 2
                continue
            if top == "dq":
                if ch == '"':
                    stack.pop()
                elif line.startswith("$(", i):
                    stack.append("cmd")
                    i += 2
                    continue
                elif line.startswith("${", i):
                    i = _skip_brace(line, i + 2)
                    continue
                i += 1
                continue
            # Unquoted context (top level, cmd or paren).
            if ch == "#" and (i == 0 or line[i - 1] in " \t;|&()"):
                if "cmd" in stack and QUOTE_CHARS.intersection(line[i:]):
                    findings.append(Finding(path, lineno, line))
                break
            if ch == "'":
                in_sq = True
            elif ch == '"':
                stack.append("dq")
            elif line.startswith("$(", i):
                stack.append("cmd")
                i += 2
                continue
            elif line.startswith("${", i):
                i = _skip_brace(line, i + 2)
                continue
            elif ch == "$" and i + 1 < n and line[i + 1] in "#'\"":
                # $# is a parameter; $'...' and $"..." are quotes handled next.
                i += 2 if line[i + 1] == "#" else 1
                continue
            elif ch == "(" and "cmd" in stack:
                stack.append("paren")
            elif ch == ")" and stack and stack[-1] in ("cmd", "paren"):
                stack.pop()
            elif line.startswith("<<", i) and top != "dq":
                opened = _heredoc_terminator(line, i)
                if opened is not None:
                    pending_heredocs.append(opened)
                    i += 2
                    continue
            i += 1
        if pending_heredocs and in_heredoc is None:
            in_heredoc = pending_heredocs.pop(0)
    return findings


def _skip_brace(line: str, i: int) -> int:
    """Skip a ``${ ... }`` expansion that opened just before ``i``."""
    depth = 1
    n = len(line)
    while i < n and depth:
        ch = line[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return i


# The exact construct that took the Mac down (pre-image of OMN-20961).
OUTAGE_PREIMAGE = """\
if [[ $_obg_lane_read -eq 1 ]]; then
    _OBG_LANE_OUT="$(
        # The session's mode goes to the node, which treats nobody as a lane in lite
        _OBG_MODE="full"
        printf '%s\\n' "$_OBG_INPUT"
    )"
fi
"""


def test_scan_fires_on_the_outage_preimage() -> None:
    findings = scan_comment_quotes_in_command_substitution(
        OUTAGE_PREIMAGE, "fixture.sh"
    )
    assert [f.line for f in findings] == [3], findings


@pytest.mark.parametrize(
    "snippet",
    [
        'x=$(\n  # say "hi"\n  echo hi\n)\n',
        "x=$(\n  # run `date`\n  date\n)\n",
        'x="$(\n  ( cd /tmp\n    # nested subshell, it\'s still inside\n  )\n)"\n',
    ],
)
def test_scan_fires_on_every_quote_kind_and_nesting(snippet: str) -> None:
    assert scan_comment_quotes_in_command_substitution(snippet, "fixture.sh")


@pytest.mark.parametrize(
    "snippet",
    [
        "# it's fine at top level\necho hi\n",
        "x=$(echo \"a # b's\")\n# don't worry, the substitution closed\n",
        "x=$(echo ${#arr[@]})\n# it's closed\n",
        "cat <<'EOF'\n$(\n# it's text\nEOF\n# isn't inside anything\n",
        "y=$(\n  # plain comment, no quote\n  echo ok\n)\n",
    ],
)
def test_scan_is_quiet_where_bash32_parses(snippet: str) -> None:
    assert scan_comment_quotes_in_command_substitution(snippet, "fixture.sh") == []


def test_hook_tree_has_scripts() -> None:
    # Positive control for the tree walk: an empty list would pass every check.
    scripts = hook_shell_scripts()
    names = {p.name for p in scripts}
    assert "pre_tool_use_bash_guards.sh" in names
    assert "common.sh" in names
    assert len(scripts) > 50


def test_no_hook_script_has_a_quote_in_a_comment_inside_command_substitution() -> None:
    findings: list[Finding] = []
    for path in hook_shell_scripts():
        text = path.read_text(encoding="utf-8", errors="replace")
        findings.extend(
            scan_comment_quotes_in_command_substitution(
                text, str(path.relative_to(ROOT))
            )
        )
    assert not findings, (
        "macOS /bin/bash 3.2 refuses these scripts (OMN-20961); remove the quote "
        "character from the comment:\n" + "\n".join(f.render() for f in findings)
    )


def _parse_bash() -> Path:
    """The bash that parses the scripts: /bin/bash 3.2 on macOS, else the PATH bash.

    The legs below used to be ``skipif`` off macOS. A test that is collected and
    never executed on the Linux runner proves nothing and grows the skip-count
    baseline, so each leg now runs everywhere and states what it proves on the
    platform it runs on.
    """
    if platform.system() == "Darwin" and MAC_BASH.exists():
        return MAC_BASH
    found = shutil.which("bash")
    assert found, "no bash on PATH: the hook scripts cannot be parsed at all"
    return Path(found)


def test_every_hook_script_parses_under_the_platform_bash() -> None:
    # macOS: /bin/bash 3.2, the ground truth the static scan approximates.
    # Elsewhere: the PATH bash, which still refuses a script with a real syntax error.
    bash = _parse_bash()
    failures: list[str] = []
    for path in hook_shell_scripts():
        proc = subprocess.run(
            [str(bash), "-n", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if proc.returncode != 0:
            failures.append(f"{path.relative_to(ROOT)}: {proc.stderr.strip()}")
    assert not failures, "\n".join(failures)


def test_the_outage_preimage_is_refused_by_mac_bash_and_accepted_elsewhere(
    tmp_path: Path,
) -> None:
    # Positive control for the parse leg. On macOS the pre-image must fail under
    # /bin/bash 3.2. On any other bash it parses, which is the whole reason CI
    # cannot see this outage and the static scan above exists; the scan firing on
    # the same text is asserted in test_scan_fires_on_the_outage_preimage.
    bash = _parse_bash()
    script = tmp_path / "preimage.sh"
    script.write_text(OUTAGE_PREIMAGE, encoding="utf-8")
    proc = subprocess.run(
        [str(bash), "-n", str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if bash == MAC_BASH:
        assert proc.returncode != 0, proc.stderr
    else:
        assert proc.returncode == 0, proc.stderr
