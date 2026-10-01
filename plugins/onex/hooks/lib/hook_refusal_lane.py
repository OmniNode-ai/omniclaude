# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Name the lane a hook refusal belongs to, from honest operands only (OMN-19381).

THE FAILURE THIS REMOVES. The OMN-18946 recorder wrote 584 refusal rows to
the live ledger and 579 said ``lane=unresolved``. Its caller handed it the
transcript path, session id and agent id from the ENVIRONMENT, which no
PreToolUse guard sets, and the hook's cwd, which on this fleet is the
workspace root, where the registry walk stops by design. The facts that name
a lane were all in the hook's stdin payload, and nothing passed it on.

THE ORDER, first hit wins, each with its own ``lane_source``:

1. ``sidecar``  -- the harness's ``agent-<agent id>.meta.json``, found from the
   payload's transcript path and agent id, Workflow locations included. Its
   ``name`` counts; its ``agentType`` or ``description`` count only when they
   are not a generic agent TYPE (``general-purpose``, ``workflow-subagent``,
   ...), which names a kind of agent, not a lane.
2. ``env``      -- the session's lane variables, and ONLY when the payload has
   no agent id: a subagent inherits its session's environment, so for a
   child's refusal the env names the parent lane.
3. ``registry`` -- the lane registry (OMN-18260) for the payload cwd and for
   every worktree path the tool call names.
4. ``claim``    -- an open CLAIM row in a bounded tail of the ledger whose
   ``worktree=`` names that worktree, or failing that whose ``ticket=``
   matches the worktree directory's ticket; used only when exactly ONE lane
   matches.
5. ``worktree`` -- ``wt:<dir>/<repo>``, spelled as ``pr_ownership_guard`` does.
6. ``unresolved``.

NEVER A GUESS. Every operand above is a fact somebody recorded: the harness,
the session that declared its lane, the lane that registered or claimed its
worktree, the worktree path itself. Two lanes claiming one worktree is an
ambiguity and names neither. An operand that cannot be read is skipped, never
filled in.

Standard library only, never raises: this runs in a process a refusing guard
backgrounded, under a bare interpreter with ``env -u PYTHONPATH``.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from types import ModuleType

__all__ = [
    "GENERIC_AGENT_TYPES",
    "LANE_ENV_VARS",
    "LANE_SOURCE_CLAIM",
    "LANE_SOURCE_ENV",
    "LANE_SOURCE_REGISTRY",
    "LANE_SOURCE_SIDECAR",
    "LANE_SOURCE_UNRESOLVED",
    "LANE_SOURCE_WORKTREE",
    "LEDGER_TAIL_BYTES",
    "candidate_paths",
    "claim_lane",
    "resolve_refusal_lane",
    "sidecar_lane",
    "worktree_of",
]

LANE_SOURCE_SIDECAR = "sidecar"
LANE_SOURCE_ENV = "env"
LANE_SOURCE_REGISTRY = "registry"
LANE_SOURCE_CLAIM = "claim"
LANE_SOURCE_WORKTREE = "worktree"
LANE_SOURCE_UNRESOLVED = "unresolved"

#: Values the harness writes into ``agentType`` (and the Workflow runner into
#: nothing more specific) that name a KIND of agent, never a lane. Compared
#: case-insensitively. A plugin agent type is spelled ``<plugin>:<agent>`` and
#: is treated as a type too.
GENERIC_AGENT_TYPES = frozenset(
    {
        "general-purpose",
        "workflow-subagent",
        "explore",
        "plan",
        "claude",
        "fork",
        "statusline-setup",
        "output-style-setup",
        "agent-parallel-dispatcher",
    }
)

#: The session's declared lane, in the order the plugin's other readers use
#: (``scripts/user-bin/gh`` reads ``ONEX_LANE`` first; ``pr_ownership_guard``
#: then the id and the agent names).
LANE_ENV_VARS = ("ONEX_LANE", "ONEX_LANE_ID", "ONEX_AGENT_NAME", "CLAUDE_AGENT_NAME")

#: At most this much of the ledger's tail is read for CLAIM rows. The live
#: ledger is tens of megabytes; an open claim for a worktree in use is recent.
LEDGER_TAIL_BYTES = 2 * 1024 * 1024

_LANE_CHARS = 120
_MAX_COMMAND_CHARS = 65536
_MAX_CANDIDATES = 16
#: Same sanitiser as ``pr_ownership_guard._LANE_SANITIZE_RE``.
_LANE_SANITIZE = re.compile(r"[^A-Za-z0-9._:@/-]+")
_TICKET = re.compile(r"(?i)\bomn-?(\d+)")
_VAR = re.compile(r"\$\{?(OMNI_HOME|HOME|ONEX_WORKTREES_ROOT|OMNI_WORKTREES_DIR)\}?")
_TRAILING_SHELL = ";&|)"
_SIDECAR_KEYS = ("name", "agentType", "description")


# ---------------------------------------------------------------------------
# 1. sidecar
# ---------------------------------------------------------------------------


def _is_generic(value: str, key: str) -> bool:
    lowered = value.strip().lower()
    if lowered in GENERIC_AGENT_TYPES:
        return True
    return key == "agentType" and ":" in lowered


def sidecar_lane(meta: Mapping[str, object] | None) -> str:
    """The lane a sidecar names, or ``""``.

    ``name`` always counts. ``agentType`` and ``description`` count only when
    they are not a generic type -- the precedence is the close-time guard's,
    the filter is this module's.
    """
    if not meta:
        return ""
    for key in _SIDECAR_KEYS:
        value = meta.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        if key != "name" and _is_generic(value, key):
            continue
        return value.strip()[:_LANE_CHARS]
    return ""


# ---------------------------------------------------------------------------
# 3 and 5. paths the tool call names, and the worktree each one is in
# ---------------------------------------------------------------------------


def _worktree_roots(env: Mapping[str, str]) -> list[Path]:
    roots: list[Path] = []
    for name in ("ONEX_WORKTREES_ROOT", "OMNI_WORKTREES_DIR"):
        value = env.get(name, "").strip()
        if value:
            roots.append(Path(value))
    home = env.get("OMNI_HOME", "").strip()
    if home:
        roots.append(Path(home) / "omni_worktrees")
    return roots


def _expand(token: str, env: Mapping[str, str]) -> str:
    def sub(match: re.Match[str]) -> str:
        return env.get(match.group(1), match.group(0))

    expanded = _VAR.sub(sub, token)
    if expanded.startswith("~/") and env.get("HOME"):
        expanded = env["HOME"] + expanded[1:]
    return expanded


def _as_path(raw: str, cwd: Path | None, env: Mapping[str, str]) -> Path | None:
    raw = _expand(raw.strip().rstrip(_TRAILING_SHELL), env)
    if not raw or "$" in raw or "\x00" in raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        if cwd is None:
            return None
        path = cwd / path
    return Path(os.path.normpath(path))


def worktree_of(path: Path, env: Mapping[str, str]) -> tuple[str, ...]:
    """``(dir, repo)`` -- or ``(dir,)`` -- when *path* is under a worktree root."""
    for root in _worktree_roots(env):
        for a, b in ((path, root), (_resolved(path), _resolved(root))):
            try:
                parts = a.relative_to(b).parts
            except ValueError:
                continue
            if parts:
                return tuple(parts[:2])
    return ()


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def _command_tokens(command: str) -> list[str]:
    command = command[:_MAX_COMMAND_CHARS]
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return command.split()


def _command_paths(
    command: str, cwd: Path | None, env: Mapping[str, str]
) -> Iterator[Path]:
    """Directories a shell command acts in: ``git -C <p>``, ``cd <p>``, and any
    argument under a worktree root (``--flag=<p>`` included)."""
    tokens = _command_tokens(command)
    for index, token in enumerate(tokens):
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if token in ("-C", "cd", "pushd") and following:
            path = _as_path(following, cwd, env)
            if path is not None:
                yield path
            continue
        for piece in (token, token.split("=", 1)[1] if "=" in token else ""):
            if not piece or "/" not in piece:
                continue
            path = _as_path(piece, None, env)
            if path is not None and worktree_of(path, env):
                yield path


def candidate_paths(
    payload: Mapping[str, object], cwd: str | None, env: Mapping[str, str]
) -> list[Path]:
    """The cwd first, then every path the tool input names, de-duplicated."""
    found: list[Path] = []
    base = _as_path(cwd, None, env) if cwd else None
    if base is not None:
        found.append(base)
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, Mapping):
        for key in ("file_path", "notebook_path", "path"):
            value = tool_input.get(key)
            if isinstance(value, str):
                path = _as_path(value, base, env)
                if path is not None:
                    found.append(path)
        command = tool_input.get("command")
        if isinstance(command, str):
            found.extend(_command_paths(command, base, env))
    unique: list[Path] = []
    for path in found:
        if path not in unique:
            unique.append(path)
    return unique[:_MAX_CANDIDATES]


def _attribution() -> ModuleType | None:
    """The sibling ``hook_lane_attribution`` module, or ``None``.

    Imported from this file's own directory at call time: hooks run under a
    bare interpreter with ``env -u PYTHONPATH``, where only a sibling resolves.
    """
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import hook_lane_attribution  # type: ignore[import-not-found,unused-ignore] # noqa: PLC0415
    except Exception:  # noqa: BLE001 - never raise on the refusal path
        return None
    module: ModuleType = hook_lane_attribution
    return module


def _registry_lane(paths: Iterable[Path]) -> str:
    hook_lane_attribution = _attribution()
    if hook_lane_attribution is None:
        return ""
    for path in paths:
        try:
            lane, source, _ticket = hook_lane_attribution.resolve_lane(path)
        except Exception:  # noqa: BLE001
            continue
        if source == hook_lane_attribution.LANE_SOURCE_REGISTRY and lane:
            return str(lane)
    return ""


# ---------------------------------------------------------------------------
# 4. claim
# ---------------------------------------------------------------------------


def _ledger_tail(ledger: Path) -> list[str]:
    try:
        with ledger.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            start = max(0, size - LEDGER_TAIL_BYTES)
            fh.seek(start)
            data = fh.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if start > 0 and lines:
        lines = lines[1:]  # a partial first line
    return lines


def _row(line: str) -> tuple[str, dict[str, str]] | None:
    cells = [cell.strip() for cell in line.split(" | ")]
    if len(cells) < 3 or cells[1] not in ("CLAIM", "TERMINAL"):
        return None
    fields: dict[str, str] = {}
    for cell in cells[2:]:
        key, sep, value = cell.partition("=")
        if sep and key and " " not in key and key not in fields:
            fields[key] = value.strip()
    return cells[1], fields


def _open_claims(lines: Iterable[str]) -> list[dict[str, str]]:
    """CLAIM rows with no later TERMINAL for the same lane, oldest first."""
    open_by_lane: dict[str, list[dict[str, str]]] = {}
    for line in lines:
        parsed = _row(line)
        if parsed is None:
            continue
        kind, fields = parsed
        lane = fields.get("lane", "")
        if not lane:
            continue
        if kind == "TERMINAL":
            open_by_lane.pop(lane, None)
        else:
            open_by_lane.setdefault(lane, []).append(fields)
    return [claim for claims in open_by_lane.values() for claim in claims]


def _claim_worktree(cell: str, env: Mapping[str, str]) -> tuple[str, ...] | None:
    """The worktree a CLAIM's ``worktree=`` cell names, ``()`` for none, or
    ``None`` when the cell names a path this module cannot place."""
    value = cell.strip().strip("`'\"").rstrip("/")
    if not value or value.lower() in ("none", "n/a", "-"):
        return ()
    marker = "omni_worktrees/"
    if not value.startswith(("/", "$", "~")) and value.startswith(marker):
        parts = tuple(p for p in value[len(marker) :].split("/") if p)
        return parts[:2] or None
    path = _as_path(value, None, env)
    if path is None:
        home = env.get("OMNI_HOME", "").strip()
        path = _as_path(value, Path(home), env) if home else None
    if path is None:
        return None
    return worktree_of(path, env) or None


def _ticket_of(directory: str) -> str:
    match = _TICKET.search(directory)
    return f"OMN-{match.group(1)}" if match else ""


def claim_lane(
    worktree: tuple[str, ...], claims: list[dict[str, str]], env: Mapping[str, str]
) -> tuple[str, bool]:
    """``(lane, ambiguous)`` for one worktree against the open claims."""
    by_path: set[str] = set()
    by_ticket: set[str] = set()
    ticket = _ticket_of(worktree[0])
    for claim in claims:
        named = _claim_worktree(claim.get("worktree", ""), env)
        if named:
            same_dir = named[0] == worktree[0]
            same_repo = len(named) < 2 or len(worktree) < 2 or named[1] == worktree[1]
            if same_dir and same_repo:
                by_path.add(claim["lane"])
            # a claim that names ANOTHER worktree is positively elsewhere
            continue
        claimed = {t.strip().upper() for t in claim.get("ticket", "").split(",")}
        if ticket and ticket in claimed:
            by_ticket.add(claim["lane"])
    if by_path:
        return (next(iter(by_path)), False) if len(by_path) == 1 else ("", True)
    if len(by_ticket) == 1:
        return next(iter(by_ticket)), False
    return "", len(by_ticket) > 1


def _ledger_path(explicit: str | None, env: Mapping[str, str]) -> Path | None:
    if explicit:
        return Path(explicit)
    value = env.get("ONEX_LEDGER_PATH", "").strip()
    if value:
        return Path(value)
    home = env.get("OMNI_HOME", "").strip()
    if home:
        return Path(home) / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md"
    return None


# ---------------------------------------------------------------------------
# the chain
# ---------------------------------------------------------------------------


def resolve_refusal_lane(
    payload: Mapping[str, object] | None,
    *,
    cwd: str | None = None,
    transcript_path: str | None = None,
    session_id: str | None = None,
    agent_id: str | None = None,
    env: Mapping[str, str] | None = None,
    ledger: str | None = None,
) -> tuple[str, str]:
    """``(lane, lane_source)`` for one refusal. Payload values win over the
    keyword fallbacks. ``lane`` is ``""`` exactly when the source is
    :data:`LANE_SOURCE_UNRESOLVED`. Never raises."""
    environment: Mapping[str, str] = os.environ if env is None else env
    data: Mapping[str, object] = payload or {}

    def pick(key: str, fallback: str | None) -> str:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return (fallback or "").strip()

    t_path = pick("transcript_path", transcript_path)
    s_id = pick("session_id", session_id)
    a_id = pick("agent_id", agent_id)
    where = pick("cwd", cwd)

    attribution = _attribution() if a_id else None
    if attribution is not None:
        try:
            lane = sidecar_lane(
                attribution.read_sidecar(t_path or None, s_id or None, a_id)
            )
        except Exception:  # noqa: BLE001 - an unreadable operand is skipped
            lane = ""
        if lane:
            return lane, LANE_SOURCE_SIDECAR

    if not a_id:
        for name in LANE_ENV_VARS:
            value = environment.get(name, "").strip()
            if value:
                return value[:_LANE_CHARS], LANE_SOURCE_ENV

    try:
        paths = candidate_paths(data, where or None, environment)
    except Exception:  # noqa: BLE001
        paths = []

    lane = _registry_lane(paths)
    if lane:
        return lane, LANE_SOURCE_REGISTRY

    worktrees: list[tuple[str, ...]] = []
    for path in paths:
        tree = worktree_of(path, environment)
        if tree and tree not in worktrees:
            worktrees.append(tree)
    if not worktrees:
        return "", LANE_SOURCE_UNRESOLVED

    ledger_file = _ledger_path(ledger, environment)
    claims = _open_claims(_ledger_tail(ledger_file)) if ledger_file else []
    for tree in worktrees:
        lane, ambiguous = claim_lane(tree, claims, environment)
        if lane:
            return lane[:_LANE_CHARS], LANE_SOURCE_CLAIM
        if ambiguous:
            break

    label = "wt:" + "/".join(worktrees[0])
    return _LANE_SANITIZE.sub("-", label)[:96], LANE_SOURCE_WORKTREE
