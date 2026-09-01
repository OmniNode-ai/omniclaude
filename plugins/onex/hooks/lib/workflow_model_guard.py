#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Fail-closed background-agent model guard (OMN-17499).

Why this exists
---------------
On 2026-09-01 one session dispatched 41 workflow scripts whose ``agent()``
calls omitted ``model:``. Every one of those agents inherited the parent
session's model, which was Fable -- banned for background work by memory
``feedback_fable_foreground_orchestration_only``. Measured over that session's
script directory: 131 ``agent()`` call sites in 101 scripts, of which 38 carry
no explicit model by the structural count this module performs (the forensics
pass, counting by hand off a regex, reported 41 -- the discrepancy is itself an
argument for structural parsing). Either way a 29 percent miss rate, invisible
until a forensics pass hours later, after the work had already run on the
banned model.

The control that was supposed to stop this was a memory entry. It failed 41
times, silently, in one session. The default is inherited and invisible: the
omission is unobservable at author time and unobservable at run time. A control
that only surfaces a violation after the fact is not a control.

Two facts decide the shape of the fix:

* Workflow scripts live under ``~/.claude/projects/<project>/workflows/scripts/``
  and are in **no repository**, so a pre-commit hook or a repo CI validator
  never sees them. The dispatch seam is the only place the choice is observable
  before the cost is incurred.
* The ``Agent`` tool has the same hole from the other side. A call with no
  ``model`` inherits the parent's; ``subagent_type: "fork"`` *always* inherits
  the parent's and has no way not to.

So this module is the decision core of a ``PreToolUse`` hook that REFUSES the
call, the same primitive as ``pre_tool_use_worktree_guard.sh`` refusing a
``git worktree add`` outside the canonical root. It is not a linter and not a
warning.

Deliberately NOT built here
---------------------------
The originating spec proposed a second layer: a runtime wrapper that supplies
``sonnet`` when ``model`` is missing. That is not shipped, and the omission is
the point. A wrapper that substitutes a default recreates the exact property
that caused the incident -- an invisible model choice -- and would mask the
omissions this validator exists to make visible. The author makes the cost
choice, per call, or the call does not run.

Parsing
-------
Structural, never a line grep. The spec's own first-draft regex reported 131 of
131 calls missing when 93 of them name a model perfectly well; a regex cannot
tell an options object from a prompt that happens to contain the text
``model:``, and it cannot follow a multi-line or nested one.

``_mask()`` walks the source once and blanks the *contents* of comments, single
and double quoted strings, and template literals -- preserving length, newlines
and delimiters, and correctly re-entering code mode inside ``${...}``
substitutions so a nested template cannot desynchronise the scan. Every
structural decision afterwards is made on the masked text (where no brace,
paren or comma inside a string or comment survives to be miscounted) while
every *value* is read from the original text.

Known limitation, stated rather than hidden: regular-expression literals are
not tokenised. A regex containing an unbalanced brace or paren inside an
``agent()`` argument list would desynchronise the bracket scan. That case
yields an ``unresolvable_call`` finding -- the guard fails closed and says it
could not parse, it never silently passes.

``meta.phases[].model`` is informational only and is not inspected: it declares
UI phase metadata, not the model a dispatched agent runs on. The per-call
``model:`` is the only thing that decides where the work executes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "AllowlistError",
    "DEFAULT_ALLOWLIST_PATH",
    "Finding",
    "check_agent_input",
    "check_workflow_script",
    "load_allowlist",
    "render_block_reason",
]

#: Shipped policy. Resolved from this file's own directory so the module works
#: identically from the source tree and from the plugin cache -- no env var, no
#: cwd contract (the OMN-16983 lesson).
DEFAULT_ALLOWLIST_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent / "config" / "agent_model_allowlist.json"
)

#: Characters that may appear in a JS identifier. Used to reject ``subagent(``
#: and ``x.agent(`` as call sites for the global ``agent()`` helper.
_IDENT_CHARS: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$"
)

_QUOTES: Final[frozenset[str]] = frozenset("'\"`")

_AGENT_CALL: Final[re.Pattern[str]] = re.compile(r"agent\s*\(")

_OPENERS: Final[dict[str, str]] = {"(": ")", "[": "]", "{": "}"}
_CLOSERS: Final[frozenset[str]] = frozenset(")]}")

#: The one-line remedy printed with every block.
FIX_LINE: Final[str] = (
    "Fix: give every agent() options object an explicit model: "
    "'opus' | 'sonnet' | 'haiku'."
)

_AGENT_TOOL_FILE: Final[str] = "<Agent tool call>"


class AllowlistError(RuntimeError):
    """The configured allowlist could not be resolved.

    Raised, never defaulted around. The caller converts this into a block: a
    guard that cannot read its own policy must refuse, not wave the call
    through on a guess (CLAUDE.md rule 8).
    """


@dataclass(frozen=True, slots=True)
class Finding:
    """One refusal-worthy fact about a single dispatch site.

    ``line`` is 1-based within ``file``. It is ``0`` for the ``Agent`` tool,
    which has structured input rather than a source file.
    """

    file: str
    line: int
    label: str
    reason: str

    def render(self) -> str:
        location = f"line {self.line}" if self.line > 0 else self.file
        return f"{location}  label {self.label!r} — {self.reason}"


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------


def load_allowlist(path: Path | None = None) -> frozenset[str]:
    """Read the allowed background models from config.

    Fail-fast on every degenerate shape: a missing file, unreadable bytes,
    malformed JSON, a missing or non-list ``allowed_models``, a non-string or
    blank entry, or an empty list. None of those get a default -- a silently
    empty allowlist would refuse every dispatch, and a silently full one would
    enforce nothing.
    """
    resolved = path if path is not None else DEFAULT_ALLOWLIST_PATH
    try:
        raw = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"allowlist not readable at {resolved}: {exc}"
        raise AllowlistError(msg) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"allowlist at {resolved} is not valid JSON: {exc}"
        raise AllowlistError(msg) from exc

    if not isinstance(parsed, dict):
        msg = f"allowlist at {resolved} must be a JSON object"
        raise AllowlistError(msg)

    models = parsed.get("allowed_models")
    if not isinstance(models, list):
        msg = f"allowlist at {resolved} has no 'allowed_models' list"
        raise AllowlistError(msg)

    cleaned: set[str] = set()
    for entry in models:
        if not isinstance(entry, str) or not entry.strip():
            msg = f"allowlist at {resolved} has a non-string or empty entry: {entry!r}"
            raise AllowlistError(msg)
        cleaned.add(entry.strip())

    if not cleaned:
        msg = f"allowlist at {resolved} is empty; that would refuse every dispatch"
        raise AllowlistError(msg)

    return frozenset(cleaned)


def _allowed(allowlist: frozenset[str]) -> str:
    return ", ".join(sorted(allowlist))


# ---------------------------------------------------------------------------
# Masking scanner
# ---------------------------------------------------------------------------


def _mask_line_comment(source: str, out: list[str], i: int) -> int:
    n = len(source)
    while i < n and source[i] != "\n":
        out[i] = " "
        i += 1
    return i


def _mask_block_comment(source: str, out: list[str], i: int) -> int:
    n = len(source)
    out[i] = " "
    out[i + 1] = " "
    i += 2
    while i < n:
        if source[i] == "*" and i + 1 < n and source[i + 1] == "/":
            out[i] = " "
            out[i + 1] = " "
            return i + 2
        if source[i] != "\n":
            out[i] = " "
        i += 1
    return i


def _mask_quoted(source: str, out: list[str], i: int) -> int:
    """Blank a ``'``- or ``"``-delimited literal, keeping both delimiters."""
    n = len(source)
    quote = source[i]
    i += 1
    while i < n:
        ch = source[i]
        if ch == "\\":
            out[i] = " "
            if i + 1 < n and source[i + 1] != "\n":
                out[i + 1] = " "
            i += 2
            continue
        if ch == quote:
            return i + 1
        if ch != "\n":
            out[i] = " "
        i += 1
    return i


def _mask(source: str) -> str:
    """Blank comment and string-literal *contents*, preserving every offset.

    The returned text has exactly the same length and the same newline
    positions as ``source``, so an index computed on the mask indexes the
    original. Delimiters survive so a later pass can still tell that a value is
    a string; the bytes between them do not, so no brace, paren or comma inside
    a prompt is ever counted as structure.

    ``${...}`` substitutions inside a template literal re-enter code mode, with
    their own brace depth, so a nested template cannot terminate the outer scan
    early. The ``${`` and its matching ``}`` are themselves blanked, which
    keeps brace balance intact for the caller.
    """
    out = list(source)
    n = len(source)
    i = 0
    # Each frame is [kind, brace_depth]. kind is "code", "sub" (inside ${...})
    # or "tmpl" (inside a backtick literal).
    stack: list[list[object]] = [["code", 0]]

    while i < n:
        kind = stack[-1][0]
        ch = source[i]

        if kind == "tmpl":
            if ch == "\\":
                out[i] = " "
                if i + 1 < n and source[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if ch == "`":
                stack.pop()
                i += 1
                continue
            if ch == "$" and i + 1 < n and source[i + 1] == "{":
                out[i] = " "
                out[i + 1] = " "
                stack.append(["sub", 0])
                i += 2
                continue
            if ch != "\n":
                out[i] = " "
            i += 1
            continue

        # code / sub
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            i = _mask_line_comment(source, out, i)
            continue
        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            i = _mask_block_comment(source, out, i)
            continue
        if ch in ("'", '"'):
            i = _mask_quoted(source, out, i)
            continue
        if ch == "`":
            stack.append(["tmpl", 0])
            i += 1
            continue
        if kind == "sub":
            depth = stack[-1][1]
            if not isinstance(depth, int):  # pragma: no cover - shape is internal
                depth = 0
            if ch == "{":
                stack[-1][1] = depth + 1
            elif ch == "}":
                if depth == 0:
                    stack.pop()
                    out[i] = " "
                    i += 1
                    continue
                stack[-1][1] = depth - 1
        i += 1

    return "".join(out)


def _line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _split_arguments(masked: str, open_paren: int) -> list[tuple[int, int]] | None:
    """Split a call's argument list into ``(start, end)`` spans.

    ``open_paren`` indexes the ``(`` of the call. Returns ``None`` when the
    bracket scan cannot be resolved, which the caller turns into a finding --
    an unparseable call is refused, never assumed clean.
    """
    n = len(masked)
    depth = 0
    stack: list[str] = []
    spans: list[tuple[int, int]] = []
    start = open_paren + 1
    i = open_paren
    while i < n:
        ch = masked[i]
        if ch in _OPENERS:
            stack.append(_OPENERS[ch])
            depth += 1
        elif ch in _CLOSERS:
            if not stack or stack[-1] != ch:
                return None
            stack.pop()
            depth -= 1
            if depth == 0:
                spans.append((start, i))
                return [span for span in spans if masked[span[0] : span[1]].strip()]
        elif ch == "," and depth == 1:
            spans.append((start, i))
            start = i + 1
        i += 1
    return None


def _string_literal(source: str, masked: str, start: int, end: int) -> str | None:
    """Return the text of a single plain string literal, else ``None``.

    ``None`` means "not statically knowable": an identifier, a concatenation
    (``'a' + b``), a template carrying a ``${}`` substitution, or anything
    carrying an escape. Every one of those is a value the guard refuses to
    guess at.
    """
    fragment = masked[start:end]
    lead = len(fragment) - len(fragment.lstrip())
    trail = len(fragment) - len(fragment.rstrip())
    inner_start = start + lead
    inner_end = end - trail
    if inner_end - inner_start < 2:
        return None
    quote = masked[inner_start]
    if quote not in _QUOTES:
        return None
    close = masked.find(quote, inner_start + 1)
    if close != inner_end - 1:
        # A second token follows the literal (concatenation, call, ...).
        return None
    raw = source[inner_start + 1 : close]
    if "\\" in raw:
        return None
    if quote == "`" and "${" in raw:
        return None
    return raw


@dataclass(frozen=True, slots=True)
class _Property:
    key: str
    value_start: int
    value_end: int


def _object_properties(
    masked: str, open_brace: int, close_brace: int
) -> tuple[list[_Property], bool]:
    """Top-level ``key: value`` pairs of an object literal, plus a spread flag.

    The spread flag matters: ``{ ...base, label: 'x' }`` may or may not carry a
    ``model``, and nothing static can tell. The caller refuses rather than
    guessing.
    """
    props: list[_Property] = []
    has_spread = False
    i = open_brace + 1
    while i < close_brace:
        ch = masked[i]
        if ch.isspace() or ch == ",":
            i += 1
            continue
        if masked.startswith("...", i):
            has_spread = True
            i += 3
            i = _skip_to_top_level_comma(masked, i, close_brace)
            continue
        if ch in _QUOTES:
            close = masked.find(ch, i + 1)
            if close == -1 or close >= close_brace:
                break
            key = masked[i + 1 : close]
            i = close + 1
        else:
            key_start = i
            while i < close_brace and masked[i] in _IDENT_CHARS:
                i += 1
            if i == key_start:
                # Not a key we understand (computed key, unexpected token).
                i = _skip_to_top_level_comma(masked, i + 1, close_brace)
                continue
            key = masked[key_start:i]
        while i < close_brace and masked[i].isspace():
            i += 1
        if i >= close_brace or masked[i] != ":":
            # Shorthand property (`{ model }`) or a method. Either way the
            # value is not a literal here.
            props.append(_Property(key=key, value_start=i, value_end=i))
            i = _skip_to_top_level_comma(masked, i, close_brace)
            continue
        i += 1
        value_start = i
        i = _skip_to_top_level_comma(masked, i, close_brace)
        props.append(_Property(key=key, value_start=value_start, value_end=i))
    return props, has_spread


def _skip_to_top_level_comma(masked: str, i: int, limit: int) -> int:
    depth = 0
    while i < limit:
        ch = masked[i]
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            if depth == 0:
                return i
            depth -= 1
        elif ch == "," and depth == 0:
            return i
        i += 1
    return limit


def _label_text(source: str, masked: str, props: list[_Property]) -> str:
    for prop in props:
        if prop.key != "label":
            continue
        literal = _string_literal(source, masked, prop.value_start, prop.value_end)
        if literal is not None:
            return literal
        expr = " ".join(source[prop.value_start : prop.value_end].split())
        if expr:
            return expr[:80]
    return "<no label>"


def _call_sites(masked: str) -> list[int]:
    """Offsets of every ``(`` that opens a genuine ``agent(...)`` call."""
    sites: list[int] = []
    for match in _AGENT_CALL.finditer(masked):
        start = match.start()
        if start > 0 and (
            masked[start - 1] in _IDENT_CHARS or masked[start - 1] == "."
        ):
            continue
        sites.append(match.end() - 1)
    return sites


def check_workflow_script(
    source: str,
    allowlist: frozenset[str],
    *,
    filename: str = "<workflow script>",
) -> list[Finding]:
    """Refusal-worthy facts about every ``agent()`` call in a workflow script.

    An empty list means every call named an allowed model explicitly. Anything
    else is a block.
    """
    masked = _mask(source)
    findings: list[Finding] = []

    for open_paren in _call_sites(masked):
        line = _line_of(source, open_paren)
        spans = _split_arguments(masked, open_paren)
        if spans is None:
            findings.append(
                Finding(
                    file=filename,
                    line=line,
                    label="<unparsed>",
                    reason=(
                        "the argument list of this agent( call could not be "
                        "resolved (unbalanced brackets, or a regex literal the "
                        "scanner does not tokenise). The guard fails closed "
                        "rather than assume a model was chosen"
                    ),
                )
            )
            continue

        if len(spans) < 2:
            findings.append(
                Finding(
                    file=filename,
                    line=line,
                    label="<no label>",
                    reason=(
                        "agent() was called with no options object, so no model "
                        "was chosen; the agent inherits the parent session's model"
                    ),
                )
            )
            continue

        opt_start, opt_end = spans[1]
        fragment = masked[opt_start:opt_end]
        lead = len(fragment) - len(fragment.lstrip())
        brace = opt_start + lead
        if brace >= opt_end or masked[brace] != "{":
            expr = " ".join(source[opt_start:opt_end].split())[:80]
            findings.append(
                Finding(
                    file=filename,
                    line=line,
                    label="<no label>",
                    reason=(
                        f"the options argument is {expr!r}, not an object "
                        "literal, so model: cannot be verified before dispatch"
                    ),
                )
            )
            continue

        close = _matching_brace(masked, brace, opt_end)
        if close is None:
            findings.append(
                Finding(
                    file=filename,
                    line=line,
                    label="<unparsed>",
                    reason=(
                        "the options object of this agent( call is unbalanced "
                        "and could not be parsed; the guard fails closed"
                    ),
                )
            )
            continue

        props, has_spread = _object_properties(masked, brace, close)
        label = _label_text(source, masked, props)
        model_props = [prop for prop in props if prop.key == "model"]

        if not model_props:
            reason = (
                "the options object spreads another value and declares no "
                "model: of its own, so the model cannot be verified before "
                "dispatch"
                if has_spread
                else (
                    "the options object has no model: key, so this background "
                    "agent inherits the parent session's model"
                )
            )
            findings.append(
                Finding(file=filename, line=line, label=label, reason=reason)
            )
            continue

        prop = model_props[-1]
        literal = _string_literal(source, masked, prop.value_start, prop.value_end)
        if literal is None:
            expr = " ".join(source[prop.value_start : prop.value_end].split())[:80]
            findings.append(
                Finding(
                    file=filename,
                    line=line,
                    label=label,
                    reason=(
                        f"model: is {expr!r}, not a quoted string literal, so "
                        "its value cannot be verified before dispatch"
                    ),
                )
            )
            continue

        if literal not in allowlist:
            findings.append(
                Finding(
                    file=filename,
                    line=line,
                    label=label,
                    reason=(
                        f"model: {literal!r} is not an allowed background model "
                        f"(allowed: {_allowed(allowlist)})"
                    ),
                )
            )

    return findings


def _matching_brace(masked: str, open_brace: int, limit: int) -> int | None:
    depth = 0
    i = open_brace
    while i < limit:
        ch = masked[i]
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            depth -= 1
            if depth == 0:
                return i
            if depth < 0:
                return None
        i += 1
    return None


# ---------------------------------------------------------------------------
# Agent tool
# ---------------------------------------------------------------------------


def check_agent_input(
    tool_input: dict[str, object],
    allowlist: frozenset[str],
) -> list[Finding]:
    """Refusal-worthy facts about a single ``Agent`` tool call.

    ``subagent_type: "fork"`` is refused outright. A fork resumes the parent's
    conversation and therefore always runs on the parent's model; there is no
    value of ``model`` that makes the choice explicit, so the only honest
    verdict is that a fork cannot be used for background work under this rule.
    """
    subagent_type = tool_input.get("subagent_type")
    description = tool_input.get("description")
    label = (
        description
        if isinstance(description, str) and description.strip()
        else (
            subagent_type
            if isinstance(subagent_type, str) and subagent_type.strip()
            else "<Agent call>"
        )
    )

    if isinstance(subagent_type, str) and subagent_type.strip() == "fork":
        return [
            Finding(
                file=_AGENT_TOOL_FILE,
                line=0,
                label=label,
                reason=(
                    "subagent_type 'fork' always inherits the parent session's "
                    "model, so the background model can never be chosen "
                    "explicitly. Dispatch a normal subagent with an explicit "
                    "model instead"
                ),
            )
        ]

    model = tool_input.get("model")
    if not isinstance(model, str) or not model.strip():
        return [
            Finding(
                file=_AGENT_TOOL_FILE,
                line=0,
                label=label,
                reason=(
                    "the Agent call declares no model, so it inherits the "
                    "parent session's model"
                ),
            )
        ]

    if model.strip() not in allowlist:
        return [
            Finding(
                file=_AGENT_TOOL_FILE,
                line=0,
                label=label,
                reason=(
                    f"model {model.strip()!r} is not an allowed background model "
                    f"(allowed: {_allowed(allowlist)})"
                ),
            )
        ]

    return []


# ---------------------------------------------------------------------------
# Block payload
# ---------------------------------------------------------------------------


def render_block_reason(findings: list[Finding], allowlist: frozenset[str]) -> str:
    """The operator-facing refusal text. Every offending call is named."""
    lines = [
        "BLOCKED: background agent model not chosen explicitly (OMN-17499).",
        "",
        "A background agent with no explicit model inherits this session's "
        "model. That is how 41 agents ran on a banned model on 2026-09-01 "
        "without anyone seeing it.",
        "",
        "Offending calls:",
    ]
    lines.extend(f"  - {finding.render()}" for finding in findings)
    lines.extend(
        [
            "",
            FIX_LINE,
            f"Allowed models: {_allowed(allowlist)} "
            f"(config: {DEFAULT_ALLOWLIST_PATH}).",
            "To disable this guard deliberately: "
            "onex hooks disable PRE_TOOL_AGENT_DISPATCH_GATE",
        ]
    )
    return "\n".join(lines)


def _block(reason: str) -> int:
    sys.stdout.write(json.dumps({"decision": "block", "reason": reason}) + "\n")
    return 3


def _resolve_script_source(tool_input: dict[str, object]) -> str:
    """The workflow script text, from ``script`` or from ``scriptPath`` on disk.

    Raises on anything unreadable. The caller converts that into a block: a
    script the guard cannot read is a script whose model choices are unknown.
    """
    script = tool_input.get("script")
    if isinstance(script, str) and script.strip():
        return script

    script_path = tool_input.get("scriptPath")
    if isinstance(script_path, str) and script_path.strip():
        candidate = Path(script_path).expanduser()
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError as exc:
            msg = f"scriptPath {candidate} is not readable: {exc}"
            raise AllowlistError(msg) from exc

    msg = "the Workflow call carries neither an inline 'script' nor a 'scriptPath'"
    raise AllowlistError(msg)


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. Reads the PreToolUse JSON on stdin.

    Exit codes: ``0`` allow, ``3`` block (payload on stdout), ``1`` the guard
    itself could not decide. The shell wrapper treats ``1`` as a block too --
    an undecidable model choice is refused, never assumed.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=None,
        help="override the shipped allowlist config (tests only)",
    )
    args = parser.parse_args(argv)

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"unparseable hook JSON on stdin: {exc}\n")
        return 1
    if not isinstance(payload, dict):
        sys.stderr.write("hook JSON on stdin is not an object\n")
        return 1

    tool_name = payload.get("tool_name")
    if tool_name not in ("Workflow", "Agent"):
        return 0

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        sys.stderr.write(f"{tool_name} call carries no tool_input object\n")
        return 1

    try:
        allowlist = load_allowlist(args.allowlist)
    except AllowlistError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    if tool_name == "Agent":
        findings = check_agent_input(tool_input, allowlist)
    else:
        try:
            source = _resolve_script_source(tool_input)
        except AllowlistError as exc:
            return _block(
                "BLOCKED: the Workflow script could not be read, so its "
                f"agent() model choices cannot be verified ({exc}). "
                "An unverifiable dispatch is refused, never assumed clean."
            )
        name = tool_input.get("scriptPath")
        filename = name if isinstance(name, str) and name else "<workflow script>"
        findings = check_workflow_script(source, allowlist, filename=filename)

    if findings:
        return _block(render_block_reason(findings, allowlist))
    return 0


if __name__ == "__main__":
    sys.exit(main())
