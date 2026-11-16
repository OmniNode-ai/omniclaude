# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lab-host work check of the Workflow/Agent dispatch guard (OMN-24618).

The guard (``plugins/onex/hooks/lib/workflow_model_guard.py``) loads this file by
path, so it imports only the standard library. It lives here, not beside the
guard, because the guard file is on the canonical-file-shape baseline and only
shrinks, and a new code file may not sit in a hook directory.

A background agent that runs ``ssh``, ``scp``, ``sftp``, ``rsync``, ``docker`` or
``systemctl`` against a lab host is doing lab work from the operator Mac, off the
lab's placement and load bar. Such a prompt is refused unless it declares one line:
``PLACEMENT: remote-lane``, ``PLACEMENT: fable-review`` or ``LOCAL-ONLY: <reason>``
(a reason of at least three words that is not a placeholder).

What the check is, and is not:

* It is a **shape check**, not a truth check, in the posture of the actor-line
  guard. Any text holding the placement phrase admits, a quotation of the fix
  line included, and ``LOCAL-ONLY: foo bar baz`` admits. It stops the omission,
  not a determined author.
* Lab hosts are the pool rows (``LANDING_POOL_HOSTS``) or, with that unset, the lab
  host table the placement code reads (``ONEX_LAB_RUN_HOSTS``, else the
  ``lab_hosts`` overlay under the store reader's ``snapshot_root``, resolved as
  ``handler_host_capability.table_path`` resolves it), the ssh config names, and
  the /24 of any configured lab address. No address range is spelt here: an
  address nothing configures is not a lab address.
* Once a command word is present the WHOLE prompt is searched for a host name
  (a host on a later line than its command counts, and so does a dotted name such
  as ``<host>.example.org``). A command whose host is a shell variable (``ssh $HOST``,
  ``ssh user@${H}``) is lab-host work unless declared, since the name cannot be
  read.
* A prompt passed by name is followed to its consts and functions in the script
  (depth six). An identifier in the prompt that no const or function in the script
  defines (``args.x``, a loop variable, a parameter) is an unresolved substitution:
  the prompt cannot be read, lab-host work cannot be ruled out, and it is refused
  unless it declares a placement.
* The check does not run on a lab host: a dispatching host that is itself a row of
  the table is where lab work belongs.

The ROUTE check never reads what this check expands; the guard hands each its own text.
"""

from __future__ import annotations

import json
import os
import re
import socket
from collections.abc import Mapping
from pathlib import Path
from typing import Final

__all__ = ["declared", "expand", "fix_lines", "hostnames", "problem"]

FIX_LINE: Final[str] = (
    "Fix: this prompt does lab-host work; declare one line in the prompt or "
    "label: `PLACEMENT: remote-lane`, `PLACEMENT: fable-review` or "
    "`LOCAL-ONLY: <reason>` (a real reason of at least three words, not a "
    "placeholder)."
)
_FIXED: Final = re.compile(r"PLACEMENT:[ \t]*(?:remote-lane|fable-review)\b", re.I)
_LOCAL: Final = re.compile(r"LOCAL-ONLY:([^\r\n]*)", re.I)
_SPLIT: Final = re.compile(r"\r?\n|\\n")
_CMD: Final = re.compile(
    r"(?<![\w-])(?:ssh|scp|sftp|rsync|docker|systemctl)(?![\w-])", re.I
)
_SSH_FAMILY: Final = frozenset({"ssh", "scp", "sftp", "rsync"})
_SHELL_VAR: Final = r"\$(?:\{[A-Za-z_]|\(|[A-Za-z_])"
_VAR_AFTER_SSH: Final = re.compile(rf"(?:^|[\s@='\"])({_SHELL_VAR}\w*\}}?)")
_VAR_AFTER_KEY: Final = re.compile(
    rf"(?:^|\s)(?:-H|--host|on|at)[ =]+['\"]?({_SHELL_VAR}\w*\}}?)"
)
_IPV4: Final = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w]|\.\d)")
_FILLER: Final = frozenset(
    [
        "tbd",
        "todo",
        "na",
        "none",
        "unknown",
        "reason",
        "placeholder",
        "fixme",
        "xxx",
        "because",
        "just",
        "this",
        "that",
        "it",
        "the",
        "a",
        "an",
        "for",
        "to",
        "of",
        "and",
        "or",
        "no",
        "why",
        "here",
        "later",
    ]
)
_IDENT: Final = re.compile(r"(?<![\w$.])[A-Za-z_$][\w$]*")
_SKIP: Final = frozenset(
    [
        "await",
        "async",
        "new",
        "typeof",
        "void",
        "null",
        "undefined",
        "true",
        "false",
        "this",
        "return",
        "if",
        "else",
        "const",
        "let",
        "var",
        "function",
        "JSON",
        "Math",
        "String",
        "Number",
        "Boolean",
        "Object",
        "Array",
        "Date",
    ]
)
_NO_LITERAL: Final[str] = "<no literal text>"
_UNREADABLE: Final[str] = "cannot be read"
_REFUSED: Final[str] = "no declared placement"


def fix_lines(reasons: list[str]) -> list[str]:
    """The fix line when any of ``reasons`` is a lab-host refusal, else nothing."""
    return [FIX_LINE] if any(_REFUSED in r or _UNREADABLE in r for r in reasons) else []


def _reason_ok(reason: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", reason)
    kept = [w for w in words if w.lower() not in _FILLER]
    return len(words) >= 3 and len(kept) >= 2 and not reason.strip().startswith("<")


def declared(text: str) -> bool:
    """Whether ``text`` carries a placement declaration (shape only, see the docstring)."""
    return bool(_FIXED.search(text)) or any(
        _reason_ok(_SPLIT.split(m[1], maxsplit=1)[0]) for m in _LOCAL.finditer(text)
    )


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _scalar(text: str) -> str:
    return text.split(" #", 1)[0].strip().strip("'\"")


def _table_text(env: Mapping[str, str]) -> str:
    """The lab host table, resolved as ``handler_host_capability.table_path`` does:
    ``ONEX_LAB_RUN_HOSTS``, else ``lab_hosts/overlay.yaml`` under the ``snapshot_root`` of
    the first store reader overlay in ``ONEX_SKILL_OVERLAY_ROOTS`` and then the overlays
    clone beside the resolved registry root, then the ``overlay-store-reader`` checkout."""
    if env.get("ONEX_LAB_RUN_HOSTS"):
        return _read(Path(env["ONEX_LAB_RUN_HOSTS"])) or ""
    roots = [
        Path(p).expanduser()
        for p in env.get("ONEX_SKILL_OVERLAY_ROOTS", "").split(os.pathsep)
        if p.strip()
    ]
    if env.get("OMNI_HOME"):
        beside = Path(env["OMNI_HOME"]).resolve().parent
        roots += [
            beside / "overlays" / "overlays",
            beside / "overlay-store-reader" / "overlays" / "overlays",
        ]
    for root in roots:
        text = _read(root / "node_overlay_store_read_effect" / "overlay.yaml")
        if text is None:
            continue
        line = next(
            (r for r in text.splitlines() if r.startswith("snapshot_root:")), ""
        )
        value = _scalar(line.partition(":")[2])
        if value in ("~",) or value.startswith("~/"):
            value = (env.get("HOME") or str(Path.home())) + value[1:]
        if not value:
            return ""
        return _read(Path(value) / "lab_hosts" / "overlay.yaml") or ""
    return ""


def hostnames(env: Mapping[str, str] | None = None) -> set[str]:
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
        for raw in _table_text(env).splitlines():
            if raw and not raw[0].isspace() and raw[0] != "-":
                in_hosts = raw.split(":")[0].strip() == "hosts"
            row = re.match(
                r"\s*(?:-\s*)?(?:name|target|fallback_targets):\s*(.*)$", raw
            )
            if in_hosts and row:
                names |= {_scalar(v) for v in row[1].strip("[] ").split(",")}
    ssh = _read(Path(env.get("HOME") or str(Path.home())) / ".ssh" / "config") or ""
    names |= {
        t
        for m in re.finditer(r"^\s*(?:Host|HostName)\s+(.+)$", ssh, re.I | re.M)
        for t in m[1].split()
        if not set(t) & set("*?!")
    }
    names = {n.rsplit("@", 1)[-1].lower() for n in names if n}
    return names - {"github.com", "localhost", ""}


def _end(masked: str, pos: int) -> int:
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


def expand(
    source: str, masked: str, span: tuple[int, int]
) -> tuple[str, str, list[str]]:
    """The prompt argument with every const, let, var or function it names in this script expanded
    (depth six), as ``(text, literal, unresolved)``.

    ``text`` is the source of every range reached. ``literal`` is the same with each character
    of code (not of a string, a template's text or a comment) replaced by NUL, so a shell
    ``$VAR`` in a string shows and a JS ``${VAR}`` does not. ``unresolved`` lists the
    expressions that no const or function in the script defines, or ``<no literal text>`` when
    no literal character was reached; either makes the prompt unreadable."""
    ranges, literal, seen, queue = [span], 0, set(), [(*span, 0)]
    unresolved: list[str] = []
    while queue:
        lo, hi, depth = queue.pop()
        literal += sum(
            1
            for c, m in zip(source[lo:hi], masked[lo:hi], strict=True)
            if c != m and c not in " \t\r\n'\"`${}"
        )
        for ident in _IDENT.finditer(masked, lo, hi):
            name = ident[0]
            if name in seen or name in _SKIP:
                continue
            decl = re.search(
                rf"(?<![\w$.])(?:(?:const|let|var)\s+{re.escape(name)}\s*=|function\s*\*?\s+{re.escape(name)}\s*\()",
                masked,
            )
            if decl is None or depth >= 6:
                expr = re.match(r"[\w$.]+", masked[ident.start() : hi])
                shown = expr[0] if expr else name
                if shown not in unresolved:
                    unresolved.append(shown)
                continue
            seen.add(name)
            start = decl.end()
            if masked[start - 1] == "(":
                # A parameter is what the call passes, and the call is in the span scanned.
                seen.update(_IDENT.findall(masked[start : masked.find(")", start)]))
                start = max(masked.find("{", start), start)
            end = _end(masked, start)
            ranges.append((start, end))
            queue.append((start, end, depth + 1))
    if literal == 0:
        unresolved.append(_NO_LITERAL)
    text = "\n".join(source[a:b] for a, b in ranges)
    lit = "\n".join(
        "".join(
            c if c != m or c.isspace() else "\0"
            for c, m in zip(source[a:b], masked[a:b], strict=True)
        )
        for a, b in ranges
    )
    return text, lit, unresolved


def _own_host(names: set[str], hostname: str | None) -> bool:
    """Whether the dispatching host is itself a lab host (a row of the table)."""
    own = (socket.gethostname() if hostname is None else hostname).lower()
    short = {n.split(".")[0] for n in names if not _IPV4.fullmatch(n)}
    return bool(own) and (own in names or own.split(".")[0] in short)


def _variable_host(literal: str) -> tuple[str, str] | None:
    for cmd in _CMD.finditer(literal):
        word = cmd[0].lower()
        rest = _SPLIT.split(literal[cmd.end() :], maxsplit=1)[0]
        var = (_VAR_AFTER_SSH if word in _SSH_FAMILY else _VAR_AFTER_KEY).search(rest)
        if var:
            return word, var[1]
    return None


def problem(
    text: str,
    literal: str,
    unresolved: list[str],
    env: Mapping[str, str] | None = None,
    hostname: str | None = None,
) -> str | None:
    """Why ``text`` does undeclared lab-host work, or ``None`` when it does not."""
    if declared(text):
        return None
    text, literal = _SPLIT.sub("\n", text), _SPLIT.sub("\n", literal)
    names = hostnames(env)
    if _own_host(names, hostname):
        return None
    cmd = _CMD.search(text)
    if cmd is not None:
        prefixes = tuple(n.rsplit(".", 1)[0] + "." for n in names if _IPV4.fullmatch(n))
        hit = [
            a[0] for a in _IPV4.finditer(text) if prefixes and a[0].startswith(prefixes)
        ]
        hit += [
            n
            for n in sorted(names)
            if re.search(rf"(?<![\w.-]){re.escape(n)}(?![\w-])", text, re.I)
        ]
        if hit:
            return f"{cmd[0].lower()} on lab host {hit[0]!r} with {_REFUSED}"
        var = _variable_host(literal)
        if var is not None:
            return (
                f"{var[0]} to a host held in the variable {var[1]!r}, which cannot "
                f"be read, with {_REFUSED}"
            )
    if unresolved:
        return (
            f"the prompt of this agent() call {_UNREADABLE}: {unresolved[0]!r} is not a "
            "literal nor a const in the script, so lab-host work cannot be ruled out "
            "and no placement is declared"
        )
    return None
