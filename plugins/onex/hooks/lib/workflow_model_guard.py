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
and double quoted strings, template literals **and regular-expression
literals** -- preserving length, newlines and delimiters, and correctly
re-entering code mode inside ``${...}`` substitutions so a nested template
cannot desynchronise the scan. Every structural decision afterwards is made on
the masked text (where no brace, paren, comma, quote or slash inside a string,
comment or pattern survives to be miscounted) while every *value* is read from
the original text.

Regex tokenisation is not a nicety (OMN-17499 follow-up). The first shipped
revision did not tokenise patterns, and its own docstring claimed the residual
failed closed. It did not. A regex is ordinary code to a scanner that cannot
see it, so ``/^https?:\\/\\//`` read as a line comment and blanked the rest of
its line -- including an ``agent(`` token that followed it -- and
``/[^'"]+/`` opened a "string" at the quote inside the character class that ran
until some later line's quote closed it, blanking every ``agent(`` in between.
Both cases exited 0. The claim that an unparseable call fails closed held only
when the desynchronisation landed *inside* an argument list; when it landed
before the call, the call stopped existing.

So the mask now reports what it could not resolve instead of guessing:

* ``/`` is classified the way a JavaScript lexer classifies it -- pattern in
  expression position, division after a value -- and patterns are parsed with
  character classes and escapes, so ``\\/`` and ``[a/b]`` do not terminate one.
* ``)``, ``]`` and ``}`` are the one position where both readings are
  grammatical (``(a + b) / 2`` versus ``if (ok) /x/.test(s)``). Division is
  assumed only when the two readings cannot disagree about the rest of the
  file; when the candidate pattern carries a quote, a backslash, a bracket or
  a comment opener, the script is refused.
* A single- or double-quoted string that never closes on its line is not valid
  JavaScript, so it is proof the scan desynchronised. Same for an unterminated
  template or block comment.

Any of those voids the whole scan, not just the construct it tripped on: a
desynchronised mask reclassifies every byte after it. ``check_workflow_script``
returns one finding naming the position and the reason, and the dispatch is
refused.

The scanner also refuses a *reference* to the ``agent`` helper that is not a
call -- ``const a = agent``, ``[agent]``, a destructure. Dispatches through an
alias are invisible to a scanner looking for ``agent(``, and a control that
only holds against the accident it was built for is not a control. Measured on
the live corpus of 1895 workflow scripts, no real script carries one.

Routing contract (OMN-17427)
----------------------------
A named model is not yet a justified one. The sibling contract_agent_routing.yaml
carries the task-complexity routing contract (OMN-17427): seven scored
dimensions, bands B0 to B5 with the models and efforts each allows, and the hard
floors (R=3 or J=3 means Opus at least). Every ``agent()`` options object and
every ``Agent`` input must carry one line in its prompt or label::

    ROUTE: band=<B> score=<n> dims=S<s>A<a>R<r>V<v>N<n>C<c>J<j> dest=<d> model=<m> effort=<e>

The gate refuses a missing or unparsable ROUTE like a missing model, and a ROUTE
whose model is not the declared model or not in the band's set, whose effort is
not in the band's set, whose score is not the sum of its dims, that sits below a
hard floor, or that sits below the band its score implies. The contract is
parsed with the standard library only (a strict in-module YAML-subset parser,
because PyYAML cannot be assumed), on the same fail-closed path.

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
    "DEFAULT_ROUTING_CONTRACT_PATH",
    "Finding",
    "Routing",
    "check_agent_input",
    "check_workflow_script",
    "load_allowlist",
    "load_routing",
    "render_block_reason",
]

#: Shipped policy. Resolved from this file's own directory so the module works
#: identically from the source tree and from the plugin cache -- no env var, no
#: cwd contract (the OMN-16983 lesson).
DEFAULT_ALLOWLIST_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent / "config" / "agent_model_allowlist.json"
)

#: Shipped routing contract (OMN-17427), a sibling of the allowlist.
DEFAULT_ROUTING_CONTRACT_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent / "config" / "contract_agent_routing.yaml"
)

#: Characters that may appear in a JS identifier. Used to reject ``subagent(``
#: and ``x.agent(`` as call sites for the global ``agent()`` helper.
_IDENT_CHARS: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$"
)

_QUOTES: Final[frozenset[str]] = frozenset("'\"`")

#: The bare global helper, with a trailing identifier boundary. The *leading*
#: boundary is checked in code, because a lookbehind cannot also reject the
#: ``.`` of ``x.agent``.
_AGENT_IDENT: Final[re.Pattern[str]] = re.compile(r"agent(?![A-Za-z0-9_$])")

#: Keywords after which a ``/`` opens a regular-expression literal rather than
#: dividing. Everything else that can precede a regex is punctuation, which
#: ``_slash_context`` handles positionally.
_REGEX_AFTER_KEYWORD: Final[frozenset[str]] = frozenset(
    {
        "await",
        "case",
        "delete",
        "do",
        "else",
        "in",
        "instanceof",
        "new",
        "of",
        "return",
        "throw",
        "typeof",
        "void",
        "yield",
    }
)

#: Characters that, inside a candidate pattern, make the regex reading and the
#: division reading of an ambiguous ``/`` structurally different: quotes open
#: strings, a backslash hides a delimiter, brackets shift nesting depth.
_SLASH_AMBIGUITY_CHARS: Final[frozenset[str]] = frozenset("'\"`\\()[]{}")

_OPENERS: Final[dict[str, str]] = {"(": ")", "[": "]", "{": "}"}
_CLOSERS: Final[frozenset[str]] = frozenset(")]}")

#: The one-line remedy printed with every block.
FIX_LINE: Final[str] = (
    "Fix: give every agent() options object an explicit model: "
    "'opus' | 'sonnet' | 'haiku'."
)

#: The one-line remedy for a missing or refused ROUTE line (OMN-17427).
ROUTE_FIX_LINE: Final[str] = (
    "Fix: carry one line in the prompt or label: ROUTE: band=<B> score=<n> "
    "dims=S<s>A<a>R<r>V<v>N<n>C<c>J<j> dest=<d> model=<m> effort=<e> "
    "(band B2 to B5 for a Claude agent; the model and effort must be in the "
    "band's set, and R=3 or J=3 needs band B4 or B5)."
)

_ROUTE_MARKER: Final[str] = "ROUTE:"

#: ``dest`` stops at whitespace or a backslash, and ``model``/``effort`` at the
#: first character outside their alphabet, so a JS ``\n`` escape ends a token.
_ROUTE_RE: Final[re.Pattern[str]] = re.compile(
    r"ROUTE: band=(?P<band>B1c|B[0-5]) score=(?P<score>\d+) "
    r"dims=S(?P<S>[0-3])A(?P<A>[0-3])R(?P<R>[0-3])V(?P<V>[0-3])"
    r"N(?P<N>[0-3])C(?P<C>[0-3])J(?P<J>[0-3]) "
    r"dest=(?P<dest>[^\s\\]+) model=(?P<model>[A-Za-z0-9_.-]+) "
    r"effort=(?P<effort>[A-Za-z0-9_.-]+)"
)

_DIMENSION_KEYS: Final[tuple[str, ...]] = tuple("SARVNCJ")
_BAND_NAMES: Final[tuple[str, ...]] = ("B0", "B1", "B1c", "B2", "B3", "B4", "B5")
#: B1c is a typed-choice variant of B1, so it ranks with it.
_BAND_RANK: Final[dict[str, int]] = {
    "B0": 0,
    "B1": 1,
    "B1c": 1,
    "B2": 2,
    "B3": 3,
    "B4": 4,
    "B5": 5,
}

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
# Routing contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Dimension:
    key: str
    name: str
    max_value: int


@dataclass(frozen=True, slots=True)
class Band:
    name: str
    score_min: int | None
    score_max: int | None
    models: frozenset[str]
    efforts: frozenset[str]
    timeout_s: int
    max_concurrent: int | None
    destination: str


@dataclass(frozen=True, slots=True)
class HardFloor:
    dimension: str
    value: int
    min_band: str


@dataclass(frozen=True, slots=True)
class Routing:
    """The routing contract: dimensions, bands and the hard floors."""

    dimensions: tuple[Dimension, ...]
    bands: dict[str, Band]
    hard_floors: tuple[HardFloor, ...]


def _routing_error(path: Path, detail: str) -> AllowlistError:
    return AllowlistError(f"routing contract at {path}: {detail}")


def _string_set(raw: object, path: Path, where: str) -> frozenset[str]:
    if not isinstance(raw, list):
        raise _routing_error(path, f"{where} must be a list")
    out: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise _routing_error(path, f"{where} has a non-string or empty entry")
        out.add(entry.strip())
    return frozenset(out)


def _optional_int(raw: object, path: Path, where: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise _routing_error(path, f"{where} must be null or a non-negative integer")
    return raw


_INT_RE: Final[re.Pattern[str]] = re.compile(r"\d+")


def _yaml_scalar(cell: str, path: Path, lineno: int) -> object:
    """One scalar of the contract subset: quoted string, integer, null, bare word."""
    if cell.startswith('"'):
        if len(cell) < 2 or not cell.endswith('"') or '"' in cell[1:-1]:
            raise _routing_error(path, f"line {lineno}: malformed quoted string")
        return cell[1:-1]
    if " #" in cell or cell.startswith(("'", "{", "&", "*", "!", "|", ">", "[")):
        raise _routing_error(path, f"line {lineno}: unsupported scalar {cell!r}")
    if cell == "null":
        return None
    if _INT_RE.fullmatch(cell):
        return int(cell)
    return cell


def _yaml_value(cell: str, path: Path, lineno: int) -> object:
    """A value after ``key:`` or ``-``: a one-line flow list or a scalar."""
    if cell.startswith("["):
        if not cell.endswith("]"):
            raise _routing_error(path, f"line {lineno}: unterminated flow list")
        inner = cell[1:-1].strip()
        if not inner:
            return []
        return [_yaml_scalar(part.strip(), path, lineno) for part in inner.split(",")]
    return _yaml_scalar(cell, path, lineno)


def _parse_contract_yaml(text: str, path: Path) -> object:
    """Parse the contract's YAML subset with the standard library only.

    The fail-closed path cannot depend on PyYAML, so this reads exactly what
    ``contract_agent_routing.yaml`` uses: ``#`` comment and blank lines,
    two-space block mappings, block sequences of scalars or of mappings, one-line
    flow lists of scalars, double-quoted strings, non-negative integers, ``null``
    and bare words. Anything else, a tab, a duplicate key or a bad indent raises
    ``AllowlistError`` rather than being guessed at.
    """
    lines: list[tuple[int, int, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw:
            raise _routing_error(path, f"line {lineno}: tab characters are not allowed")
        body = raw.strip()
        if not body or body.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise _routing_error(path, f"line {lineno}: indent must be a multiple of 2")
        lines.append((lineno, indent, body))
    if not lines:
        raise _routing_error(path, "is empty")

    pos = 0

    def parse_block(indent: int) -> object:
        nonlocal pos
        if lines[pos][2].startswith("- ") or lines[pos][2] == "-":
            return parse_sequence(indent)
        return parse_mapping(indent)

    def parse_mapping(indent: int, first: tuple[int, str] | None = None) -> object:
        nonlocal pos
        out: dict[str, object] = {}
        pending = first
        while True:
            if pending is not None:
                lineno, body = pending
                pending = None
            else:
                if pos >= len(lines):
                    return out
                lineno, line_indent, body = lines[pos]
                if line_indent < indent:
                    return out
                if line_indent > indent:
                    raise _routing_error(path, f"line {lineno}: unexpected indent")
                if body.startswith("-"):
                    return out
                pos += 1
            key, sep, rest = body.partition(":")
            if not sep or not key or key != key.strip() or " " in key:
                raise _routing_error(path, f"line {lineno}: expected 'key: value'")
            if key in out:
                raise _routing_error(path, f"line {lineno}: duplicate key {key!r}")
            rest = rest.strip()
            if rest:
                out[key] = _yaml_value(rest, path, lineno)
            elif pos < len(lines) and lines[pos][1] > indent:
                out[key] = parse_block(lines[pos][1])
            elif (
                pos < len(lines)
                and lines[pos][1] == indent
                and lines[pos][2].startswith("- ")
            ):
                out[key] = parse_sequence(indent)
            else:
                out[key] = None

    def parse_sequence(indent: int) -> object:
        nonlocal pos
        items: list[object] = []
        while pos < len(lines):
            lineno, line_indent, body = lines[pos]
            if line_indent != indent or not (body.startswith("- ") or body == "-"):
                break
            pos += 1
            rest = body[1:].strip()
            if not rest:
                raise _routing_error(path, f"line {lineno}: empty sequence item")
            key, sep, _ = rest.partition(":")
            if sep and key and " " not in key and not rest.startswith(("[", '"')):
                items.append(parse_mapping(indent + 2, first=(lineno, rest)))
            else:
                items.append(_yaml_value(rest, path, lineno))
        return items

    first_indent = lines[0][1]
    if first_indent != 0:
        raise _routing_error(
            path, f"line {lines[0][0]}: top level must not be indented"
        )
    result = parse_block(0)
    if pos < len(lines):
        raise _routing_error(path, f"line {lines[pos][0]}: unparsed content")
    return result


def load_routing(path: Path | None = None) -> Routing:
    """Read the routing contract (``contract_agent_routing.yaml``).

    Fail-fast like ``load_allowlist``: a missing section, a missing dimension or
    band, a malformed band, or a hard floor naming an unknown dimension or band
    raises ``AllowlistError``. A guard that cannot read its contract refuses.
    """
    resolved = path if path is not None else DEFAULT_ROUTING_CONTRACT_PATH
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise _routing_error(resolved, f"not readable: {exc}") from exc
    parsed = _parse_contract_yaml(text, resolved)
    if not isinstance(parsed, dict):
        raise _routing_error(resolved, "must be a mapping")

    raw_dims = parsed.get("dimensions")
    if not isinstance(raw_dims, list):
        raise _routing_error(resolved, "has no 'dimensions' list")
    dimensions: list[Dimension] = []
    for entry in raw_dims:
        if not isinstance(entry, dict):
            raise _routing_error(resolved, "a dimension is not an object")
        key, name, top = entry.get("key"), entry.get("name"), entry.get("max")
        if (
            not isinstance(key, str)
            or not isinstance(name, str)
            or isinstance(top, bool)
            or not isinstance(top, int)
            or top < 1
        ):
            raise _routing_error(resolved, f"malformed dimension {entry!r}")
        dimensions.append(Dimension(key=key, name=name, max_value=top))
    if tuple(d.key for d in dimensions) != _DIMENSION_KEYS:
        raise _routing_error(
            resolved, f"dimensions must be exactly {''.join(_DIMENSION_KEYS)} in order"
        )

    raw_bands = parsed.get("bands")
    if not isinstance(raw_bands, dict):
        raise _routing_error(resolved, "has no 'bands' object")
    bands: dict[str, Band] = {}
    for name in _BAND_NAMES:
        entry = raw_bands.get(name)
        if not isinstance(entry, dict):
            raise _routing_error(resolved, f"band {name} is missing")
        timeout = entry.get("timeout_s")
        destination = entry.get("destination")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or timeout <= 0
            or not isinstance(destination, str)
        ):
            raise _routing_error(resolved, f"band {name} is malformed")
        bands[name] = Band(
            name=name,
            score_min=_optional_int(
                entry.get("score_min"), resolved, f"{name}.score_min"
            ),
            score_max=_optional_int(
                entry.get("score_max"), resolved, f"{name}.score_max"
            ),
            models=_string_set(entry.get("models"), resolved, f"{name}.models"),
            efforts=_string_set(entry.get("efforts"), resolved, f"{name}.efforts"),
            timeout_s=timeout,
            max_concurrent=_optional_int(
                entry.get("max_concurrent"), resolved, f"{name}.max_concurrent"
            ),
            destination=destination,
        )
    if extra := set(raw_bands) - set(_BAND_NAMES):
        raise _routing_error(resolved, f"unknown band(s): {', '.join(sorted(extra))}")

    raw_floors = parsed.get("hard_floors")
    if not isinstance(raw_floors, list):
        raise _routing_error(resolved, "has no 'hard_floors' list")
    floors: list[HardFloor] = []
    for entry in raw_floors:
        if not isinstance(entry, dict):
            raise _routing_error(resolved, "a hard floor is not an object")
        dim, value, min_band = (
            entry.get("dimension"),
            entry.get("value"),
            entry.get("min_band"),
        )
        if (
            dim not in _DIMENSION_KEYS
            or isinstance(value, bool)
            or not isinstance(value, int)
            or min_band not in _BAND_NAMES
        ):
            raise _routing_error(resolved, f"malformed hard floor {entry!r}")
        floors.append(HardFloor(dimension=dim, value=value, min_band=min_band))

    return Routing(dimensions=tuple(dimensions), bands=bands, hard_floors=tuple(floors))


def _score_band_rank(routing: Routing, score: int) -> int:
    """Rank of the band whose score range holds ``score`` (0 when none does)."""
    for band in routing.bands.values():
        if (
            band.score_min is not None
            and band.score_max is not None
            and band.score_min <= score <= band.score_max
            and band.name != "B1c"
        ):
            return _BAND_RANK[band.name]
    return 0


def _route_problem(
    routing: Routing, route_text: str, declared_model: str
) -> str | None:
    """Why the ROUTE line in ``route_text`` is refused, or ``None`` when it holds."""
    start = route_text.find(_ROUTE_MARKER)
    if start == -1:
        return (
            "the ROUTE line is missing, so the task's complexity band was never "
            "scored; the model choice is unjustified"
        )
    match = _ROUTE_RE.match(route_text, start)
    if match is None:
        return (
            "the ROUTE line is unparsable (expected 'ROUTE: band=<B> score=<n> "
            "dims=S<s>A<a>R<r>V<v>N<n>C<c>J<j> dest=<d> model=<m> effort=<e>')"
        )
    band_name = match["band"]
    score = int(match["score"])
    dims = {key: int(match[key]) for key in _DIMENSION_KEYS}
    if score != sum(dims.values()):
        return f"ROUTE score={score} is not the sum of its dims ({sum(dims.values())})"
    route_model = match["model"]
    if route_model != declared_model:
        return (
            f"ROUTE model={route_model} does not match declared model "
            f"{declared_model!r}"
        )
    band = routing.bands[band_name]
    rank = _BAND_RANK[band_name]
    for floor in routing.hard_floors:
        if dims[floor.dimension] >= floor.value and rank < _BAND_RANK[floor.min_band]:
            return (
                f"hard floor: {floor.dimension}={dims[floor.dimension]} needs "
                f"band {floor.min_band} or above, but ROUTE says band {band_name}"
            )
    if rank < _score_band_rank(routing, score):
        return (
            f"band {band_name} is below the band score {score} implies; "
            "a task is never routed beneath its score"
        )
    if not band.models:
        return (
            f"band {band_name} dispatches no Claude agent (destination: "
            f"{band.destination}); an agent() or Agent call needs band B2 to B5"
        )
    if route_model not in band.models:
        return (
            f"band {band_name} allows only: {_allowed(band.models)}; "
            f"ROUTE model {route_model!r} is not in that set"
        )
    if match["effort"] not in band.efforts:
        return (
            f"ROUTE effort={match['effort']} is not allowed for band "
            f"{band_name} (allowed: {_allowed(band.efforts)})"
        )
    return None


# ---------------------------------------------------------------------------
# Masking scanner
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Desync:
    """A place where the scanner could not tell one construct from another.

    Its presence voids the whole scan of that source. A desynchronised mask
    does not merely lose the construct it tripped on -- it silently reclassifies
    every byte after it, which is exactly how an ``agent(`` token disappears
    from a script that contains one (OMN-17499 follow-up, gaps 1 and 2).
    """

    offset: int
    reason: str


@dataclass(slots=True)
class _Frame:
    """One nesting level of the mask walk: code, a template, or a ``${}``."""

    kind: str
    depth: int
    start: int


@dataclass(frozen=True, slots=True)
class _Masked:
    text: str
    desyncs: tuple[_Desync, ...]


def _mask_line_comment(source: str, out: list[str], i: int) -> int:
    n = len(source)
    while i < n and source[i] != "\n":
        out[i] = " "
        i += 1
    return i


def _mask_block_comment(
    source: str, out: list[str], i: int, desyncs: list[_Desync]
) -> int:
    n = len(source)
    start = i
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
    desyncs.append(
        _Desync(
            offset=start,
            reason=(
                "a /* block comment opened here is never closed, so every byte "
                "after it was read as comment text"
            ),
        )
    )
    return i


def _mask_quoted(source: str, out: list[str], i: int, desyncs: list[_Desync]) -> int:
    """Blank a ``'``- or ``"``-delimited literal, keeping both delimiters.

    A single- or double-quoted JavaScript string cannot contain a raw newline;
    only a backslash line-continuation carries one across. So a scan that walks
    off the end of the line looking for the closing quote has proved one of two
    things -- the source is not valid JavaScript, or this quote was never a
    string delimiter at all (a quote inside a regular-expression literal the
    slash classifier got wrong). Either way the mask from here on is fiction,
    so the newline is recorded as a desync and the scan resumes at it rather
    than blanking whole lines of real code on the way to some distant quote.
    """
    n = len(source)
    quote = source[i]
    start = i
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
        if ch == "\n":
            desyncs.append(
                _Desync(
                    offset=start,
                    reason=(
                        f"a {quote}-quoted string opened here is not closed on "
                        "its own line, which no valid JavaScript string does; "
                        "the scanner cannot tell a string from a quote "
                        "character inside some other literal"
                    ),
                )
            )
            return i
        out[i] = " "
        i += 1
    desyncs.append(
        _Desync(
            offset=start,
            reason=(
                f"a {quote}-quoted string opened here is never closed, so every "
                "byte after it was read as string text"
            ),
        )
    )
    return i


def _scan_regex(source: str, i: int) -> tuple[int, int] | None:
    """Parse a regular-expression literal starting at the ``/`` at ``i``.

    Returns ``(close_slash_index, index_past_flags)``, or ``None`` when no
    closing ``/`` is reached before the end of the line -- a regex literal
    cannot span a newline, so that is proof this ``/`` was not one.

    Character classes are tracked because ``/`` is literal inside ``[...]``
    (``/[a/b]/`` is one regex, not two divisions), and backslash escapes are
    skipped because ``\\/`` is a literal slash, not the terminator. Those two
    rules are the whole reason the shipped scanner mis-read
    ``/^https?:\\/\\//`` as a line comment.
    """
    n = len(source)
    j = i + 1
    in_class = False
    while j < n:
        ch = source[j]
        if ch == "\n":
            return None
        if ch == "\\":
            j += 2
            continue
        if in_class:
            if ch == "]":
                in_class = False
        elif ch == "[":
            in_class = True
        elif ch == "/":
            close = j
            j += 1
            while j < n and source[j] in _IDENT_CHARS:
                j += 1
            return close, j
        j += 1
    return None


def _slash_context(source: str, prev: int) -> str:
    """Classify a ``/`` as ``regex``, ``division`` or ``ambiguous``.

    The classification is the standard one every JavaScript lexer uses: a
    ``/`` in *expression* position opens a regular-expression literal, and a
    ``/`` after a *value* is division. ``prev`` is the offset of the last
    significant character (whitespace and comments are not significant).

    ``)``, ``]`` and ``}`` are reported ``ambiguous`` rather than guessed at.
    They end a value (``(a + b) / 2``) but also end a control head or a block
    (``if (ok) /x/.test(s)``), and nothing local decides which. The caller
    refuses when -- and only when -- the two readings would actually disagree
    about the structure of the rest of the file.
    """
    if prev < 0:
        return "regex"
    ch = source[prev]
    if ch in ")]}":
        return "ambiguous"
    if ch in _IDENT_CHARS:
        start = prev
        while start > 0 and source[start - 1] in _IDENT_CHARS:
            start -= 1
        word = source[start : prev + 1]
        return "regex" if word in _REGEX_AFTER_KEYWORD else "division"
    if ch in _QUOTES:
        return "division"
    return "regex"


def _mask(source: str) -> _Masked:
    """Blank comment, string and regex *contents*, preserving every offset.

    The returned text has exactly the same length and the same newline
    positions as ``source``, so an index computed on the mask indexes the
    original. Delimiters survive so a later pass can still tell that a value is
    a string; the bytes between them do not, so no brace, paren, comma, quote
    or slash inside a prompt, a comment or a pattern is ever counted as
    structure.

    ``${...}`` substitutions inside a template literal re-enter code mode, with
    their own brace depth, so a nested template cannot terminate the outer scan
    early. The ``${`` and its matching ``}`` are themselves blanked, which
    keeps brace balance intact for the caller.

    Anything the walk cannot resolve is recorded in ``desyncs`` instead of
    being guessed at. The caller turns a non-empty ``desyncs`` into a refusal
    of the entire script: a mask that desynchronised does not lose one
    construct, it reclassifies every byte after it.
    """
    out = list(source)
    n = len(source)
    i = 0
    desyncs: list[_Desync] = []
    stack: list[_Frame] = [_Frame(kind="code", depth=0, start=0)]
    # Offset of the last significant character in the current expression, or
    # -1 at the start of one. Comments and whitespace never update it.
    prev = -1

    while i < n:
        frame = stack[-1]
        ch = source[i]

        if frame.kind == "tmpl":
            if ch == "\\":
                out[i] = " "
                if i + 1 < n and source[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if ch == "`":
                stack.pop()
                prev = i
                i += 1
                continue
            if ch == "$" and i + 1 < n and source[i + 1] == "{":
                out[i] = " "
                out[i + 1] = " "
                stack.append(_Frame(kind="sub", depth=0, start=i))
                prev = -1
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
            i = _mask_block_comment(source, out, i, desyncs)
            continue
        if ch == "/":
            i = _mask_slash(source, out, i, prev, desyncs)
            prev = i - 1
            continue
        if ch in ("'", '"'):
            i = _mask_quoted(source, out, i, desyncs)
            prev = i - 1
            continue
        if ch == "`":
            stack.append(_Frame(kind="tmpl", depth=0, start=i))
            i += 1
            continue
        if frame.kind == "sub":
            if ch == "{":
                frame.depth += 1
            elif ch == "}":
                if frame.depth == 0:
                    stack.pop()
                    out[i] = " "
                    prev = i
                    i += 1
                    continue
                frame.depth -= 1
        if not ch.isspace():
            prev = i
        i += 1

    for frame in stack[1:]:
        desyncs.append(
            _Desync(
                offset=frame.start,
                reason=(
                    "a template literal opened here is never closed, so every "
                    "byte after it was read as template text"
                    if frame.kind == "tmpl"
                    else "a ${ substitution opened here is never closed"
                ),
            )
        )

    return _Masked(text="".join(out), desyncs=tuple(desyncs))


def _mask_slash(
    source: str, out: list[str], i: int, prev: int, desyncs: list[_Desync]
) -> int:
    """Handle one ``/`` that is neither ``//`` nor ``/*``.

    Returns the offset to continue the walk at. Division advances one
    character and changes nothing; a regular-expression literal has its body
    blanked between surviving delimiters, exactly like a string.
    """
    context = _slash_context(source, prev)
    if context == "division":
        return i + 1

    parsed = _scan_regex(source, i)
    if parsed is None:
        if context == "regex":
            desyncs.append(
                _Desync(
                    offset=i,
                    reason=(
                        "a '/' in expression position does not close as a "
                        "regular-expression literal on its own line, so the "
                        "scanner cannot tell a pattern from a division here"
                    ),
                )
            )
        # Ambiguous with no same-line close is a division: no regex reading
        # exists at all.
        return i + 1

    close, end = parsed
    body = source[i + 1 : close]
    if context == "ambiguous" and (
        _SLASH_AMBIGUITY_CHARS.intersection(body) or "//" in body
    ):
        desyncs.append(
            _Desync(
                offset=i,
                reason=(
                    "this '/' follows ')', ']' or '}', where a division and a "
                    "regular-expression literal are both grammatical, and the "
                    "two readings disagree about the rest of the file (the "
                    f"candidate pattern {source[i:end]!r} carries a quote, a "
                    "backslash, a bracket or a comment opener). The guard "
                    "refuses rather than pick one"
                ),
            )
        )
        return i + 1

    for j in range(i + 1, close):
        out[j] = " "
    return end


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


def _source_snippet(source: str, offset: int, *, width: int = 60) -> str:
    """The source line containing ``offset``, squeezed and trimmed.

    Used as the label of a finding that has no options object to read a
    ``label:`` out of, so the refusal still names the line it is about.
    """
    line_start = source.rfind("\n", 0, offset) + 1
    line_end = source.find("\n", offset)
    if line_end == -1:
        line_end = len(source)
    text = " ".join(source[line_start:line_end].split())
    return text[:width] if text else "<no source>"


@dataclass(frozen=True, slots=True)
class _Reference:
    """One occurrence of the bare global ``agent`` identifier in masked code.

    ``open_paren`` is the offset of the ``(`` that calls it, or ``None`` when
    the helper is referenced without being called -- bound to another name,
    passed as a value, destructured. That form is invisible to a scanner that
    only looks for ``agent(``, which is how ``const a = agent; a('t', {...})``
    dispatched an unmodelled background agent past the shipped guard.
    """

    name_start: int
    name_end: int
    open_paren: int | None


def _agent_references(masked: str) -> list[_Reference]:
    """Every use of the bare global ``agent`` identifier, called or not.

    ``subagent(``, ``x.agent(`` and ``agents`` are excluded: the first two are
    a different callable and the third a different identifier.
    """
    references: list[_Reference] = []
    for match in _AGENT_IDENT.finditer(masked):
        start = match.start()
        if start > 0 and (
            masked[start - 1] in _IDENT_CHARS or masked[start - 1] == "."
        ):
            continue
        cursor = match.end()
        while cursor < len(masked) and masked[cursor].isspace():
            cursor += 1
        open_paren = cursor if cursor < len(masked) and masked[cursor] == "(" else None
        references.append(
            _Reference(name_start=start, name_end=match.end(), open_paren=open_paren)
        )
    return references


def check_workflow_script(
    source: str,
    allowlist: frozenset[str],
    *,
    filename: str = "<workflow script>",
    routing: Routing | None = None,
) -> list[Finding]:
    """Refusal-worthy facts about every ``agent()`` call in a workflow script.

    An empty list means every call named an allowed model explicitly. Anything
    else is a block. With ``routing`` supplied, every call must also carry a
    ROUTE line in its prompt or label that the contract accepts.
    """
    scan = _mask(source)
    if scan.desyncs:
        desync = scan.desyncs[0]
        return [
            Finding(
                file=filename,
                line=_line_of(source, desync.offset),
                label="<unparsed source>",
                reason=(
                    f"{desync.reason}. A desynchronised scan does not lose one "
                    "construct, it silently reclassifies every byte after it -- "
                    "an agent( call among them -- so the whole script is "
                    "refused rather than scanned"
                ),
            )
        ]
    masked = scan.text
    findings: list[Finding] = []

    for reference in _agent_references(masked):
        if reference.open_paren is None:
            findings.append(
                Finding(
                    file=filename,
                    line=_line_of(source, reference.name_start),
                    label=_source_snippet(source, reference.name_start),
                    reason=(
                        "the agent() helper is referenced here without being "
                        "called -- bound to another name, passed as a value, or "
                        "destructured. Every dispatch made through that binding "
                        "is invisible to this guard, so the model it runs on "
                        "cannot be verified before it runs"
                    ),
                )
            )
            continue

        open_paren = reference.open_paren
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
                        "resolved: its brackets do not balance. The guard "
                        "fails closed rather than assume a model was chosen"
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
            continue

        if routing is not None:
            label_prop = [prop for prop in props if prop.key == "label"]
            route_text = source[spans[0][0] : spans[0][1]] + "".join(
                source[prop.value_start : prop.value_end] for prop in label_prop
            )
            problem = _route_problem(routing, route_text, literal)
            if problem is not None:
                findings.append(
                    Finding(file=filename, line=line, label=label, reason=problem)
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
    *,
    routing: Routing | None = None,
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

    if routing is not None:
        route_text = "\n".join(
            value
            for value in (tool_input.get("prompt"), description)
            if isinstance(value, str)
        )
        problem = _route_problem(routing, route_text, model.strip())
        if problem is not None:
            return [Finding(file=_AGENT_TOOL_FILE, line=0, label=label, reason=problem)]

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
            ROUTE_FIX_LINE,
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


def _resolve_script_sources(
    tool_input: dict[str, object],
) -> list[tuple[str, str]]:
    """Every script body this Workflow call could execute, as (name, text).

    Both ``script`` and ``scriptPath`` are read when both are present. The
    shipped guard preferred the inline ``script`` and never opened the path,
    so a payload carrying a clean inline script alongside a ``scriptPath``
    whose ``agent()`` calls name no model passed. Which of the two the harness
    would actually run is not knowable from inside a PreToolUse hook, and a
    guard does not need to know: it checks every body the call carries, and
    refuses if any of them is unverifiable.

    Raises on anything unreadable. The caller converts that into a block: a
    script the guard cannot read is a script whose model choices are unknown.
    """
    sources: list[tuple[str, str]] = []

    script = tool_input.get("script")
    if isinstance(script, str) and script.strip():
        sources.append(("<inline script>", script))

    script_path = tool_input.get("scriptPath")
    if isinstance(script_path, str) and script_path.strip():
        candidate = Path(script_path).expanduser()
        try:
            sources.append((str(candidate), candidate.read_text(encoding="utf-8")))
        except OSError as exc:
            msg = f"scriptPath {candidate} is not readable: {exc}"
            raise AllowlistError(msg) from exc

    if not sources:
        msg = "the Workflow call carries neither an inline 'script' nor a 'scriptPath'"
        raise AllowlistError(msg)

    return sources


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
    parser.add_argument(
        "--routing-contract",
        type=Path,
        default=None,
        help="override the shipped routing contract (tests only)",
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
        routing = load_routing(args.routing_contract)
    except AllowlistError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    if tool_name == "Agent":
        findings = check_agent_input(tool_input, allowlist, routing=routing)
    else:
        try:
            sources = _resolve_script_sources(tool_input)
        except AllowlistError as exc:
            return _block(
                "BLOCKED: the Workflow script could not be read, so its "
                f"agent() model choices cannot be verified ({exc}). "
                "An unverifiable dispatch is refused, never assumed clean."
            )
        findings = []
        for filename, source in sources:
            findings.extend(
                check_workflow_script(
                    source, allowlist, filename=filename, routing=routing
                )
            )

    if findings:
        return _block(render_block_reason(findings, allowlist))
    return 0


if __name__ == "__main__":
    sys.exit(main())
