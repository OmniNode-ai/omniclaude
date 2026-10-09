# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lane and run identity for the PR ownership gate and the claim CLI (OMN-16485, OMN-19699).

The hook and ``scripts/pr_claim_registry_cli.py`` must resolve the SAME lane and
run, or the lane that claims a PR is not the lane the gate lets close it. This
module is that one resolver. It is standard library only and imports nothing from
``omniclaude``: the claim CLI is the escape hatch every refusal names, it runs
under whatever ``python3`` the lane has, and it loads this file by path.

Everything here is local: no network, no subprocess. The session resolver is a
plugin hook-library sibling (``session_id.py``) reached through ``use_hooks_lib``.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path
from types import ModuleType

__all__ = [
    "claim_cli_path",
    "hooks_lib",
    "resolve_lane_id",
    "resolve_run_id",
    "resolve_session_id",
    "sanitize_lane",
    "sibling",
    "source_hooks_lib",
    "use_hooks_lib",
]

_LANE_ENV_VARS = (
    "ONEX_LANE_ID",
    "ONEX_LANE",
    "ONEX_AGENT_NAME",
    "CLAUDE_AGENT_NAME",
    "CLAUDE_SUBAGENT_NAME",
)

_LANE_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._:@/-]+")

#: The plugin hook library directory, set by the process entry (``--hooks-lib``).
_hooks_lib: Path | None = None


def use_hooks_lib(path: str | Path) -> None:
    """Name the hook library whose siblings hold the registry and session resolver."""
    global _hooks_lib
    _hooks_lib = Path(path).resolve()
    if str(_hooks_lib) not in sys.path:
        sys.path.insert(0, str(_hooks_lib))


def source_hooks_lib() -> Path:
    """The hook library of a source checkout: ``<repo>/plugins/onex/hooks/lib``."""
    return Path(__file__).resolve().parents[5] / "plugins" / "onex" / "hooks" / "lib"


def sibling(name: str) -> ModuleType:
    """A plugin hook-library sibling, on sys.path through ``use_hooks_lib``.

    A caller that never named the library (a test, a source checkout) gets the
    checkout's own.
    """
    if _hooks_lib is None and source_hooks_lib().is_dir():
        use_hooks_lib(source_hooks_lib())
    return importlib.import_module(name)


def resolve_session_id(env: dict[str, str] | None) -> str | None:
    """The canonical Claude Code session id, or None."""
    session: str | None = sibling("session_id").resolve_session_id(
        env=env, default=None
    )
    return session


def hooks_lib() -> Path:
    """The hook library in use: the one named, else the checkout's own."""
    return _hooks_lib or source_hooks_lib()


# ---------------------------------------------------------------------------
# Lane identity
# ---------------------------------------------------------------------------


def sanitize_lane(raw: str) -> str:
    return _LANE_SANITIZE_RE.sub("-", raw.strip())[:96]


def resolve_lane_id(
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
) -> str | None:
    """Resolve this lane's identity, deterministically and without network I/O.

    Resolution order, most explicit first:

    1. ``ONEX_LANE_ID``, ``ONEX_LANE`` (what the remote-lane runner exports) or an
       agent-name env var — an explicitly declared lane.
    2. The worktree the caller is standing in (``<ticket>/<repo>``).  Per
       Operating Rule #9 every lane gets its own worktree, so this is a real
       per-lane discriminator, not a guess.
    3. ``CLAUDE_CODE_SESSION_ID`` — a stable per-session fallback.

    Returns ``None`` when nothing is resolvable, which every caller must treat
    as INDETERMINATE and therefore refusing.

    This is the caller's local lane label. When it falls back to a session,
    the verdict may use a claim's readable lane if its full session and run
    both match. Explicit peer lanes still refuse even with shared identities.
    """
    environment = dict(os.environ) if env is None else env

    for name in _LANE_ENV_VARS:
        value = environment.get(name, "").strip()
        if value:
            return sanitize_lane(value)

    worktree_lane = _lane_from_worktree(environment, cwd)
    if worktree_lane:
        return worktree_lane

    session = resolve_session_id(environment)
    if session:
        return sanitize_lane(f"session:{session[:16]}")

    return None


def resolve_run_id(env: dict[str, str] | None = None) -> str | None:
    """Resolve the full mutation run, shared by the CLI and hook (OMN-19699)."""
    environment = dict(os.environ) if env is None else env
    return environment.get("ONEX_RUN_ID", "").strip() or resolve_session_id(environment)


def _lane_from_worktree(
    environment: dict[str, str], cwd: str | Path | None
) -> str | None:
    raw_cwd = Path(cwd) if cwd is not None else Path(environment.get("PWD", "") or ".")
    try:
        resolved = raw_cwd.resolve()
    except OSError:
        return None

    roots: list[Path] = []
    for name in ("ONEX_WORKTREES_ROOT", "OMNI_WORKTREES_DIR"):
        value = environment.get(name, "").strip()
        if value:
            roots.append(Path(value))
    registry_root = environment.get("OMNI_HOME", "").strip()
    if registry_root:
        roots.append(Path(registry_root) / "omni_worktrees")

    for root in roots:
        try:
            relative = resolved.relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        parts = relative.parts
        if len(parts) >= 2:
            return sanitize_lane(f"wt:{parts[0]}/{parts[1]}")
        if len(parts) == 1:
            return sanitize_lane(f"wt:{parts[0]}")

    return None


def claim_cli_path() -> str:
    """Absolute path of ``pr_claim_registry_cli.py``, independent of the cwd.

    Resolved from the hook library in use (source layout
    ``<omniclaude>/plugins/onex/hooks/lib``).  The plugin cache has no
    ``scripts/`` dir, so there it falls back to the canonical clone under
    ``$OMNI_HOME``.
    """
    relative = Path("scripts") / "pr_claim_registry_cli.py"
    source = hooks_lib().parents[3] / relative
    if source.is_file():
        return str(source)
    workspace = os.environ.get("OMNI_HOME", "").strip()
    if workspace:
        return str(Path(workspace) / "omniclaude" / relative)
    return str(source)
