#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
r"""Prose-sink backtick command-substitution admission gate (OMN-18750).

Why this exists
---------------
Inside a double-quoted shell string a backtick pair is command substitution.
Markdown uses backticks to quote a command name. Lanes write prose about
commands into ledgers, checkpoints, pull-request bodies and commit messages
constantly, in the house style, and when that prose is carried in a
double-quoted ``echo`` the shell runs it.

Measured twice on 2026-09-18, at 15:47:38Z and 18:21:31Z. Both lanes wrote a
checkpoint note reading ``\`uv run onex\``` and both tool calls came back
with::

    error: Failed to spawn: `onex`
      Caused by: No such file or directory (os error 2)

The substitution's empty stdout was written into the note in place of the
words it was quoting, and the spawn error surfaced on the tool result, where
for most of a working day it read as a broken PostToolUse hook rather than a
quoting mistake. Every hook in the plugin was run against a fixture payload
before the real cause was found.

The damage was small only because the quoted text named a command that does
not exist on the PATH ``uv`` searches. The identical construction quoting a
destructive command executes it, silently, as a side effect of writing a note
about it.

What this refuses, and what it deliberately does not
----------------------------------------------------
A shell segment is refused when BOTH hold:

* it carries an unescaped backtick command substitution that sits inside a
  DOUBLE-QUOTED string (a bare backtick substitution outside quotes is a
  deliberate, if dated, substitution -- not this hazard), and
* its destination is a PROSE SINK: a ``>``/``>>`` redirect or a ``tee``
  whose target basename matches the prose suffixes or stems declared in
  ``prose_command_substitution_policy.json``, or a text-bearing option from
  that file's ``prose_text_flags`` whose value carries the substitution.

Everything else passes. In particular a backtick substitution in a command
that writes no prose is out of scope: this guard is about prose being
executed, not about backtick style. Single-quoted prose is out of scope
because single quotes already suppress substitution, which is one of the two
corrections the refusal offers.

Quote-state scanning, not regex
-------------------------------
Whether a backtick is a substitution depends entirely on the quote state it
appears in, and quote state is not a regular language. The scanner below
walks the command once, tracking none/single/double state and backslash
escapes exactly as the shell does, and reports the substitutions it finds
along with the state they were found in. A regex over the raw text would
refuse a backtick inside single quotes (harmless) and admit one in a nested
double-quoted region (the hazard).

Fail-closed
-----------
An unreadable payload that carries a backtick anywhere is refused. A payload
the guard cannot parse is a payload whose substitutions it cannot enumerate,
and admitting it would make malformed input the bypass. A payload with no
backtick at all cannot be this shape and is admitted without parsing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "prose_command_substitution_policy.json"
)

#: Shell operators that separate one command from the next. Split only ever
#: happens at an operator found in the unquoted state.
#:
#: A single ``|`` is deliberately ABSENT. A pipeline is one write: in
#: ``echo "...`x`..." | tee -a notes.md`` the substitution is in the first
#: stage and the prose sink is in the last, and splitting there would leave
#: each half looking innocent. ``||`` still splits, because it is matched
#: before ``&`` and is a control operator rather than a pipe.
SEGMENT_OPERATORS = (";", "&&", "||", "&", "\n")

#: Within a segment, the pipeline stages. Used only to find a ``tee``.
PIPELINE_OPERATOR = "|"


@dataclass(frozen=True)
class Substitution:
    """One backtick command substitution and the quote state enclosing it."""

    text: str
    in_double_quotes: bool


@dataclass
class Decision:
    """The guard's verdict over one Bash command."""

    blocked: bool
    reason: str = ""
    notes: list[str] = field(default_factory=list)


def load_policy(policy_path: Path | None = None) -> dict:
    """Read the declared vocabulary. A missing or unreadable policy is fatal.

    Rule 8: a silent default here would be a guard that quietly stops
    recognising the sinks it was configured for, which is indistinguishable
    from a guard that passes everything.
    """
    path = policy_path or DEFAULT_POLICY_PATH
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def scan_substitutions(command: str) -> list[Substitution]:
    """Walk ``command`` once, returning every backtick substitution found.

    The walk mirrors POSIX shell quoting:

    * unquoted: ``\\`` escapes the next character, ``'`` opens single quotes,
      ``"`` opens double quotes, ``` ` ``` opens a substitution;
    * single-quoted: nothing is special until the closing ``'`` -- there are
      no escapes inside single quotes, which is why single-quoting prose is a
      correction this guard recommends;
    * double-quoted: ``\\`` escapes the next character, ``"`` closes, and
      ``` ` ``` opens a substitution.

    An unterminated substitution (no closing backtick) is still reported, so a
    truncated or hand-mangled command cannot hide one.
    """
    found: list[Substitution] = []
    index = 0
    length = len(command)
    in_single = False
    in_double = False

    while index < length:
        char = command[index]

        if char == "\\" and not in_single:
            # The escape consumes the next character in both the unquoted and
            # the double-quoted state. An escaped backtick is literal -- it is
            # exactly the correct form this guard tells lanes to write.
            index += 2
            continue

        if char == "'" and not in_double:
            in_single = not in_single
            index += 1
            continue

        if char == '"' and not in_single:
            in_double = not in_double
            index += 1
            continue

        if char == "`" and not in_single:
            closing = _find_closing_backtick(command, index + 1)
            if closing is None:
                found.append(Substitution(command[index + 1 :], in_double))
                break
            found.append(Substitution(command[index + 1 : closing], in_double))
            index = closing + 1
            continue

        index += 1

    return found


def _find_closing_backtick(command: str, start: int) -> int | None:
    """Return the index of the substitution's closing backtick, or None."""
    index = start
    while index < len(command):
        if command[index] == "\\":
            index += 2
            continue
        if command[index] == "`":
            return index
        index += 1
    return None


def split_segments(command: str) -> list[str]:
    """Split ``command`` on shell operators found in the UNQUOTED state.

    Splitting on raw text would cut a command in half at an operator that is
    part of a quoted note -- and notes about shell commands contain ``&&``
    and ``|`` routinely.
    """
    segments: list[str] = []
    current: list[str] = []
    index = 0
    length = len(command)
    in_single = False
    in_double = False
    in_backticks = False

    while index < length:
        char = command[index]

        if char == "\\" and not in_single:
            current.append(command[index : index + 2])
            index += 2
            continue

        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "`" and not in_single:
            in_backticks = not in_backticks

        if not in_single and not in_double and not in_backticks:
            matched = next(
                (op for op in SEGMENT_OPERATORS if command.startswith(op, index)), None
            )
            if matched is not None:
                segments.append("".join(current))
                current = []
                index += len(matched)
                continue

        current.append(char)
        index += 1

    segments.append("".join(current))
    return [segment.strip() for segment in segments if segment.strip()]


def _is_prose_path(target: str, policy: dict) -> bool:
    """True when a write target's basename reads as a prose surface."""
    basename = os.path.basename(target.strip().strip("\"'")).lower()
    if not basename:
        return False
    if any(basename.endswith(suffix) for suffix in policy["prose_path_suffixes"]):
        return True
    return any(stem in basename for stem in policy["prose_path_stems"])


def _redirect_targets(segment: str) -> list[str]:
    """Return every ``>``/``>>`` target in ``segment``, unquoted state only."""
    targets: list[str] = []
    index = 0
    length = len(segment)
    in_single = False
    in_double = False
    in_backticks = False

    while index < length:
        char = segment[index]

        if char == "\\" and not in_single:
            index += 2
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            index += 1
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            index += 1
            continue
        if char == "`" and not in_single:
            in_backticks = not in_backticks
            index += 1
            continue

        if char == ">" and not in_single and not in_double and not in_backticks:
            index += 2 if segment.startswith(">>", index) else 1
            while index < length and segment[index] in " \t":
                index += 1
            start = index
            while index < length and segment[index] not in " \t;|&<>":
                index += 1
            if index > start:
                targets.append(segment[start:index])
            continue

        index += 1

    return targets


def split_pipeline_stages(segment: str) -> list[str]:
    """Split one segment at each unquoted single ``|``."""
    stages: list[str] = []
    current: list[str] = []
    index = 0
    length = len(segment)
    in_single = False
    in_double = False
    in_backticks = False

    while index < length:
        char = segment[index]

        if char == "\\" and not in_single:
            current.append(segment[index : index + 2])
            index += 2
            continue

        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "`" and not in_single:
            in_backticks = not in_backticks

        if (
            char == PIPELINE_OPERATOR
            and not in_single
            and not in_double
            and not in_backticks
        ):
            stages.append("".join(current))
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    stages.append("".join(current))
    return [stage.strip() for stage in stages if stage.strip()]


def _tee_targets(segment: str, policy: dict) -> list[str]:
    """Return the file arguments of any ``tee`` in ``segment``'s pipeline.

    ``tee`` is a redirect spelled as a program, so its target is judged on the
    same terms. Options are skipped; everything else after the program name is
    a file it writes. Every pipeline stage is examined, because the ``tee``
    that receives a note is by construction not the stage that wrote it.
    """
    import shlex

    targets: list[str] = []
    for stage in split_pipeline_stages(segment):
        try:
            tokens = shlex.split(stage, comments=False, posix=True)
        except ValueError:
            continue
        if not tokens:
            continue
        if os.path.basename(tokens[0]) not in policy["tee_programs"]:
            continue
        targets.extend(token for token in tokens[1:] if not token.startswith("-"))
    return targets


def _prose_flag_carrying_substitution(segment: str, policy: dict) -> str | None:
    """Return a text-bearing flag whose value carries a substitution, if any.

    The check is positional rather than textual: a flag token is found in the
    unquoted state, and the substitution must fall inside the value that
    follows it. ``--body`` mentioned inside a note is not a flag.
    """
    flags = set(policy["prose_text_flags"])
    index = 0
    length = len(segment)
    in_single = False
    in_double = False
    token_start = 0
    tokens: list[tuple[int, int]] = []

    while index <= length:
        at_end = index == length
        char = "" if at_end else segment[index]

        if not at_end and char == "\\" and not in_single:
            index += 2
            continue
        if not at_end and char == "'" and not in_double:
            in_single = not in_single
            index += 1
            continue
        if not at_end and char == '"' and not in_single:
            in_double = not in_double
            index += 1
            continue

        if at_end or (char in " \t" and not in_single and not in_double):
            if index > token_start:
                tokens.append((token_start, index))
            token_start = index + 1
            if at_end:
                break
            index += 1
            continue

        index += 1

    for position, (start, end) in enumerate(tokens):
        raw = segment[start:end]
        # `--body=<text>` carries its value in the same token.
        if "=" in raw:
            name, _, _ = raw.partition("=")
            if name in flags and _has_double_quoted_substitution(segment[start:end]):
                return name
        if raw not in flags:
            continue
        if position + 1 >= len(tokens):
            continue
        value_start, value_end = tokens[position + 1]
        if _has_double_quoted_substitution(segment[value_start:value_end]):
            return raw
    return None


def _has_double_quoted_substitution(fragment: str) -> bool:
    """True when ``fragment`` carries a substitution inside double quotes.

    A fragment sliced out of a larger command starts in the unquoted state, so
    a value token that begins with its own ``"`` is scanned correctly.
    """
    return any(sub.in_double_quotes for sub in scan_substitutions(fragment))


def _build_reason(substitutions: list[Substitution], sink: str) -> str:
    quoted = ", ".join(f"`{sub.text.strip()}`" for sub in substitutions)
    return (
        "BLOCKED: this command carries an unescaped backtick command substitution "
        f"inside a double-quoted string that is written to {sink} (OMN-18750). "
        f"The shell will EXECUTE {quoted} and write its output into the text, "
        "rather than writing the backticks you meant as markdown. This is not "
        "hypothetical: on 2026-09-18 two lanes wrote a checkpoint note quoting "
        "`uv run onex` and the shell ran it, losing the quoted words from the "
        "note and surfacing a spawn error that read as a broken hook for most of "
        "a working day. A note quoting a destructive command would have run that "
        "instead. Two corrections: use $( ) when you actually intend a "
        "substitution, or escape the backticks (\\`like this\\`) or single-quote "
        "the prose when the text is markdown. To disable this guard deliberately: "
        "onex hooks disable BASH_GUARD"
    )


def evaluate_bash_command(command: str, policy: dict) -> Decision:
    """Decide one Bash command. Returns a blocking Decision or an allowing one."""
    notes: list[str] = []

    for segment in split_segments(command):
        substitutions = [s for s in scan_substitutions(segment) if s.in_double_quotes]
        if not substitutions:
            continue

        prose_targets = [
            target
            for target in _redirect_targets(segment) + _tee_targets(segment, policy)
            if _is_prose_path(target, policy)
        ]
        if prose_targets:
            return Decision(
                blocked=True,
                reason=_build_reason(
                    substitutions, f"the prose surface {prose_targets[0]}"
                ),
            )

        flag = _prose_flag_carrying_substitution(segment, policy)
        if flag is not None:
            return Decision(
                blocked=True,
                reason=_build_reason(substitutions, f"the text argument of {flag}"),
            )

        notes.append(
            "double-quoted backtick substitution present but no prose sink in this segment"
        )

    return Decision(blocked=False, notes=notes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="path to the policy file (defaults to the plugin's config copy)",
    )
    args = parser.parse_args(argv)

    raw = sys.stdin.read()

    try:
        payload = json.loads(raw)
    except ValueError:
        # Fail closed, but only for a payload that could carry the shape at
        # all. An unreadable payload with no backtick in it is not this hazard
        # and refusing it would make every malformed payload a wall.
        if "`" in raw:
            print(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": (
                            "BLOCKED: the PreToolUse payload for this Bash call carries a "
                            "backtick but is not readable JSON, so the guard cannot tell "
                            "whether a command substitution sits inside quoted prose "
                            "(OMN-18750). An unverifiable payload is refused, never assumed "
                            "safe. To disable this guard: onex hooks disable BASH_GUARD"
                        ),
                    }
                )
            )
            return 2
        print(
            json.dumps(
                {"decision": "allow", "notes": ["unparseable payload, no backtick"]}
            )
        )
        return 0

    if payload.get("tool_name") != "Bash":
        print(json.dumps({"decision": "allow", "notes": ["not a Bash call"]}))
        return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    if "`" not in command:
        print(json.dumps({"decision": "allow", "notes": ["no backtick in command"]}))
        return 0

    try:
        policy = load_policy(args.policy)
    except (OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": (
                        "BLOCKED: the OMN-18750 prose-substitution policy could not be read "
                        f"({exc}), so this command's backticks cannot be judged. A gate that "
                        "cannot read its own vocabulary has not passed; it has not run. "
                        "Repair the plugin install, or disable the guard deliberately: "
                        "onex hooks disable BASH_GUARD"
                    ),
                }
            )
        )
        return 2

    decision = evaluate_bash_command(command, policy)
    if decision.blocked:
        print(json.dumps({"decision": "block", "reason": decision.reason}))
        return 2

    print(json.dumps({"decision": "allow", "notes": list(decision.notes)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
