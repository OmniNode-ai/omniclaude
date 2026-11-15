#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Fail-closed background-agent model guard (OMN-17499).

Decision core of the ``PreToolUse`` hook that REFUSES a Workflow or Agent
dispatch whose background agent does not name its own model (CLAUDE.md,
"Background-agent model guard", holds the history, the allowlist and the
measurements). No wrapper supplies a default: the author chooses per call.

Parsing is structural. ``_mask()`` blanks the contents of comments, strings,
templates and regular-expression literals (length and newlines kept); every
structural decision is made on the masked text, every value read from the
source. A scan that cannot be trusted (an ambiguous ``/``, an unterminated
string, template or comment) voids the whole script, and a reference to the
``agent`` helper that is not a call is refused. Each call also carries a
``ROUTE:`` line checked against contract_agent_routing.yaml (OMN-17427).

Lab-host work (OMN-24618): an ``agent()`` prompt that runs ssh, docker or
systemctl against a lab host is refused unless it declares a placement. Lab
hosts are the pool rows or lab host table the placement code reads, the ssh
config names and any address on a configured lab subnet. A prompt passed by
name is followed to its const; one that cannot be read is refused.

``meta.phases[].model`` is informational only and is not inspected.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
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
    "'opus' | 'sonnet'. Trivial text work goes to `onex delegate` (local lab models)."
)

#: Appended to a refusal whose offending value names haiku.
HAIKU_REMOVED_NOTE: Final[str] = (
    "haiku is removed from the background-agent allowlist (OMN-17427); "
    "trivial text work goes to `onex delegate` (local lab models) instead"
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

LAB_HOST_FIX_LINE: Final[str] = (
    "Fix: this prompt does lab-host work; declare one line in the prompt or "
    "label: `PLACEMENT: remote-lane`, `PLACEMENT: fable-review` or "
    "`LOCAL-ONLY: <reason>` (a real reason of at least three words, not a "
    "placeholder)."
)
_LAB_FIXED: Final = re.compile(r"PLACEMENT:[ \t]*(?:remote-lane|fable-review)\b", re.I)
_LAB_LOCAL: Final = re.compile(r"LOCAL-ONLY:([^\r\n]*)", re.I)
_LAB_SPLIT: Final = re.compile(r"\r?\n|\\n")
_LAB_CMD: Final = re.compile(r"(?<![\w-])(?:ssh|docker|systemctl)(?![\w-])", re.I)
_LAB_IPV4: Final = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w]|\.\d)")
_LAB_FILLER: Final = frozenset(
    re.findall(
        r"\w+",
        "tbd todo na none unknown reason placeholder fixme xxx because just this that it the a an for to of and or no why here later",
    )
)
_LAB_IDENT: Final = re.compile(r"(?<![\w$.])[A-Za-z_$][\w$]*")
_LAB_SKIP: Final = frozenset(
    re.findall(
        r"\w+",
        "await async new typeof void null undefined true false this return if else const let var function",
    )
)


def _lab_reason_ok(reason: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", reason)
    kept = [w for w in words if w.lower() not in _LAB_FILLER]
    return len(words) >= 3 and len(kept) >= 2 and not reason.strip().startswith("<")


def _lab_declared(text: str) -> bool:
    return bool(_LAB_FIXED.search(text)) or any(
        _lab_reason_ok(_LAB_SPLIT.split(m[1], maxsplit=1)[0])
        for m in _LAB_LOCAL.finditer(text)
    )


def _lab_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _lab_table_text(env: Mapping[str, str]) -> str:
    """The lab host table the placement code reads: ``ONEX_LAB_RUN_HOSTS``, else
    the ``lab_hosts`` overlay under the overlay store reader's ``snapshot_root``."""
    if env.get("ONEX_LAB_RUN_HOSTS"):
        return _lab_read(Path(env["ONEX_LAB_RUN_HOSTS"]))
    roots = [Path(p) for p in env.get("ONEX_SKILL_OVERLAY_ROOTS", "").split(":") if p]
    if env.get("OMNI_HOME"):
        beside = Path(env["OMNI_HOME"]).resolve().parent
        roots += [
            beside / d / "overlays" / "overlays"
            for d in ("overlays", "overlay-store-reader")
        ]
    for root in roots:
        text = _lab_read(root / "node_overlay_store_read_effect" / "overlay.yaml")
        line = re.search(r"^snapshot_root:\s*(.+)$", text, re.M)
        if line:
            home = env.get("HOME") or str(Path.home())
            snap = line[1].split(" #")[0].strip().strip("'\"")
            return _lab_read(
                Path(snap.replace("~", home, 1)) / "lab_hosts" / "overlay.yaml"
            )
    return ""


def _lab_hostnames(env: Mapping[str, str] | None = None) -> set[str]:
    """Lab host names: pool rows (``LANDING_POOL_HOSTS``, else the table) and ssh config names."""
    env = os.environ if env is None else env
    names: set[str] = set()
    if env.get("LANDING_POOL_HOSTS") is not None:
        try:
            rows = json.loads(env["LANDING_POOL_HOSTS"] or "[]")
        except ValueError:
            rows = []
        names |= (
            {
                str(r[k])
                for r in rows
                if isinstance(r, dict)
                for k in ("name", "target")
                if r.get(k)
            }
            if isinstance(rows, list)
            else set()
        )
    else:
        in_hosts = False
        for raw in _lab_table_text(env).splitlines():
            if raw and not raw[0].isspace() and raw[0] != "-":
                in_hosts = raw.split(":")[0].strip() == "hosts"
            row = re.match(
                r"\s*(?:-\s*)?(?:name|target|fallback_targets):\s*(.*)$", raw
            )
            if in_hosts and row:
                names |= {
                    v.split(" #")[0].strip(" '\"")
                    for v in row[1].strip("[] ").split(",")
                }
    ssh = _lab_read(Path(env.get("HOME") or str(Path.home())) / ".ssh" / "config")
    names |= {
        t
        for m in re.finditer(r"^\s*(?:Host|HostName)\s+(.+)$", ssh, re.I | re.M)
        for t in m[1].split()
        if not set(t) & set("*?!")
    }
    return {n.rsplit("@", 1)[-1].lower() for n in names if n} - {
        "github.com",
        "localhost",
    }


def _lab_end(masked: str, pos: int) -> int:
    """End of the declaration whose initializer starts at ``pos``."""
    depth, joiners = 0, "+-*/%,=([{?:&|.<>!"
    for i in range(pos, len(masked)):
        depth += (masked[i] in "([{") - (masked[i] in ")]}")
        done = masked[i] == ";" or (
            masked[i] == "\n"
            and masked.count("`", pos, i) % 2 == 0
            and masked[pos:i].strip()[-1:] not in joiners
            and masked[i:].lstrip()[:1] not in joiners + ")"
        )
        if depth < 0 or (depth == 0 and done):
            return i
    return len(masked)


def _lab_prompt(source: str, masked: str, span: tuple[int, int]) -> tuple[str, bool]:
    """The prompt argument with every const, let, var or function it names in this
    script expanded (depth six); ``False`` when no literal prompt text was reached."""
    parts, literal, seen, queue = [source[span[0] : span[1]]], 0, set(), [(*span, 0)]
    while queue:
        lo, hi, depth = queue.pop()
        literal += sum(
            1
            for c, m in zip(source[lo:hi], masked[lo:hi], strict=True)
            if c != m and c not in " \t\r\n'\"`${}"
        )
        for ident in _LAB_IDENT.finditer(masked, lo, hi):
            name = ident[0]
            decl = re.search(
                rf"(?<![\w$.])(?:(?:const|let|var)\s+{re.escape(name)}\s*=|function\s*\*?\s+{re.escape(name)}\s*\()",
                masked,
            )
            if name in seen or name in _LAB_SKIP or decl is None or depth >= 6:
                continue
            seen.add(name)
            start = decl.end()
            if masked[start - 1] == "(":
                start = max(masked.find("{", start), start)
            end = _lab_end(masked, start)
            parts.append(source[start:end])
            queue.append((start, end, depth + 1))
    return "\n".join(parts), literal > 0


def _lab_host_work_problem(text: str, readable: bool = True) -> str | None:
    """Why ``text`` does undeclared lab-host work, or ``None`` when it does not."""
    if _lab_declared(text):
        return None
    if not readable:
        return "the prompt of this agent() call cannot be read (not a literal, nor a const in the script), so lab-host work cannot be ruled out and no placement is declared"
    names = _lab_hostnames()
    prefixes = {n.rsplit(".", 1)[0] + "." for n in names if _LAB_IPV4.fullmatch(n)} | {
        f"{192}.{168}."
    }
    for line in _LAB_SPLIT.split(text):
        cmd = _LAB_CMD.search(line)
        if cmd is None:
            continue
        hit = [
            a[0] for a in _LAB_IPV4.finditer(line) if a[0].startswith(tuple(prefixes))
        ]
        hit += [
            n
            for n in sorted(names)
            if re.search(rf"(?<![\w.-]){re.escape(n)}(?![\w-]|\.\w)", line, re.I)
        ]
        if hit:
            return f"{cmd[0].lower()} on lab host {hit[0]!r} with no declared placement"
    return None


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
    """The configured allowlist could not be resolved."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One refusal-worthy fact about a single dispatch site."""

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
    """Read the allowed background models from config."""
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


def _removed_note(value: str) -> str:
    """Name the haiku removal when the refused value is a haiku spelling."""
    return f"; {HAIKU_REMOVED_NOTE}" if "haiku" in value.lower() else ""


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
    """Parse the contract's YAML subset with the standard library only."""
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
    """Read the routing contract (``contract_agent_routing.yaml``)."""
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
    """A place where the scanner could not tell one construct from another."""

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
    """Blank a ``'``- or ``"``-delimited literal, keeping both delimiters."""
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
    """Parse a regular-expression literal starting at the ``/`` at ``i``."""
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
    """Classify a ``/`` as ``regex``, ``division`` or ``ambiguous``."""
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
    """Blank comment, string and regex *contents*, preserving every offset."""
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
    """Handle one ``/`` that is neither ``//`` nor ``/*``."""
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
    """Split a call's argument list into ``(start, end)`` spans."""
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
    """Return the text of a single plain string literal, else ``None``."""
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
    """Top-level ``key:"""
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
    """The source line containing ``offset``, squeezed and trimmed."""
    line_start = source.rfind("\n", 0, offset) + 1
    line_end = source.find("\n", offset)
    if line_end == -1:
        line_end = len(source)
    text = " ".join(source[line_start:line_end].split())
    return text[:width] if text else "<no source>"


@dataclass(frozen=True, slots=True)
class _Reference:
    """One occurrence of the bare global ``agent`` identifier in masked code."""

    name_start: int
    name_end: int
    open_paren: int | None


def _agent_references(masked: str) -> list[_Reference]:
    """Every use of the bare global ``agent`` identifier, called or not."""
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
    """Refusal-worthy facts about every ``agent()`` call in a workflow script."""
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
                        f"{_removed_note(literal)}"
                    ),
                )
            )
            continue

        label_prop = [prop for prop in props if prop.key == "label"]
        prompt, readable = _lab_prompt(source, masked, spans[0])
        route_text = prompt + "".join(
            source[prop.value_start : prop.value_end] for prop in label_prop
        )
        lab = _lab_host_work_problem(route_text, readable)
        if lab is not None:
            findings.append(Finding(file=filename, line=line, label=label, reason=lab))
            continue

        if routing is not None:
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
    """Refusal-worthy facts about a single ``Agent`` tool call."""
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
                    f"{_removed_note(model)}"
                ),
            )
        ]

    route_text = "\n".join(
        value
        for value in (tool_input.get("prompt"), description)
        if isinstance(value, str)
    )
    lab = _lab_host_work_problem(route_text)
    if lab is not None:
        return [Finding(file=_AGENT_TOOL_FILE, line=0, label=label, reason=lab)]

    if routing is not None:
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
            *(
                [LAB_HOST_FIX_LINE]
                if any(
                    "lab host" in f.reason or "cannot be read" in f.reason
                    for f in findings
                )
                else []
            ),
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
    """Every script body this Workflow call could execute, as (name, text)."""
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
    """Hook entry point."""
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
