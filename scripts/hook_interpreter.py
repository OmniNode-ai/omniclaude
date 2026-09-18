#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Resolve the interpreter the hooks actually run on, and assert the orphan is gone.

OMN-18746. The two venv reconcilers in this repo
(``check_daemon_venv_skew.py``, ``check_omnimarket_dispatch_drift.py``) each
resolved exactly one interpreter — ``CLAUDE_PLUGIN_DATA/.venv`` — and each
returned no findings when it was absent. On a developer machine that is usually
NOT the interpreter the hooks run on. ``find_python()``
(``plugins/onex/hooks/scripts/common.sh``) walks a priority chain whose first
entry is ``PLUGIN_PYTHON_BIN``, and on a host that sets it every PreToolUse and
UserPromptSubmit hook executes there. No readback covered that interpreter, so a
skew in it was invisible to both gates.

This module is the resolution half of that gap: it walks the SAME chain, in the
same order, and reports which entry answered. It reads the environment and the
repo layout only — there is deliberately no machine-specific absolute path
anywhere in it (CLAUDE.md rule 6), and a test asserts that.

It also carries the orphan assertion. ``plugins/onex/lib/.venv`` left
``find_python()``'s chain in ``035707dd2ca8d1d295ed1790ad8a82dcd9abcbde``
(OMN-7310, 2026-04-02) — *"The plugin lib/.venv was empty/broken, causing all
hook event emission to fail. Instead of maintaining a separate plugin venv, all
hook and skill scripts now resolve Python from the repo's main .venv."* Nothing
has built it since, no pin file under ``plugins/onex/`` declares it, and the copy
found on the operator's machine on 2026-09-18 carried ``omnimarket==0.2.0``,
2023 commits behind, in which ``node_event_emit_effect`` does not exist at all.

An orphan is not a surface to reconcile. Reconciling it would manufacture the
appearance of a converged venv that nothing reads, which is the same class of
false green this module exists to remove. It is asserted **absent**, and a
present one is reported by path.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "HookInterpreter",
    "ORPHAN_RELATIVE_PATH",
    "check_orphan_absent",
    "describe_hook_interpreter",
    "orphan_venv_path",
    "repo_root",
    "resolve_hook_interpreter",
    "scan_orphan_interpreter_references",
]

#: Where the orphan sits, relative to the repo root. This is the path that left
#: the resolution chain; it is named here once so every consumer agrees on it.
ORPHAN_RELATIVE_PATH = Path("plugins/onex/lib/.venv")

#: Bounded so an unreadable git tree surfaces as an error rather than a hang.
GIT_TIMEOUT_SECONDS = 30

#: A reference that RUNS the orphan. Descriptive prose that merely names the
#: directory is fine and is not matched; an interpreter path under it is not.
_ORPHAN_INTERPRETER_RE = re.compile(r"lib/\.venv[^\s\"']*/bin/python")

#: Files whose match is a fixture or a historical record rather than a live
#: instruction. Each entry is allowlisted for a stated reason, so the list is
#: auditable — it is not a place to park a real offender.
_SCAN_ALLOWLIST: dict[str, str] = {
    # Builds throwaway fake plugin roots under a temp dir; the matched paths are
    # ${FAKE_ROOT}/lib/.venv, never this repo's tree.
    "tests/hooks/test_venv_auto_repair.sh": "fixture paths under a temp fake root",
    # Points at plugins/onex/hooks/lib/.venv — a `hooks/lib` path that has never
    # existed in this repo — and skips when it is absent.
    "tests/hooks/test_context_scope_auditor_smoke.py": "path that never existed; test skips",
    # A changelog entry about the pre-plugin `claude/lib/.venv` layout.
    "plugins/onex/ENVIRONMENT_VARIABLES.md": "historical changelog of an older path",
}


@dataclass(frozen=True)
class HookInterpreter:
    """An interpreter the hook chain resolved, and which entry answered."""

    path: Path
    source: str


def repo_root() -> Path:
    """This repo's root, resolved from this file's own location (rule 6)."""
    return Path(__file__).resolve().parents[1]


def orphan_venv_path(root: Path | None = None) -> Path:
    """Absolute path of the orphan hooks venv under ``root``."""
    return (root if root is not None else repo_root()) / ORPHAN_RELATIVE_PATH


def _usable(candidate: Path) -> bool:
    """A chain entry counts only when it is a file AND executable.

    ``find_python()`` tests ``-f`` and ``-x`` together on every entry. A present
    but non-executable interpreter falls through there, so it falls through here.
    """
    try:
        return candidate.is_file() and candidate.stat().st_mode & 0o111 != 0
    except OSError:
        return False


def resolve_hook_interpreter(
    env: Mapping[str, str] | None = None,
    root: Path | None = None,
) -> HookInterpreter | None:
    """Walk ``find_python()``'s chain and return the entry that answers.

    Mirrors ``plugins/onex/hooks/scripts/common.sh`` ``find_python()`` entries 1
    through 5, in order. The chain's final lite-mode fallback to the system
    ``python3`` is deliberately NOT walked: a bare system interpreter is not a
    reconciled surface, and reading it back against ``uv.lock`` would report
    drift that no repair could clear.

    Returns None when no entry answers. That is the ordinary state of a CI
    runner with no venv built, and the caller reports it rather than treating it
    as either a pass or a failure.
    """
    if env is None:
        import os

        env = os.environ
    base = root if root is not None else repo_root()

    override = env.get("PLUGIN_PYTHON_BIN", "")
    if override and _usable(Path(override)):
        return HookInterpreter(Path(override), "PLUGIN_PYTHON_BIN")

    plugin_data = env.get("CLAUDE_PLUGIN_DATA", "")
    if plugin_data:
        candidate = Path(plugin_data) / ".venv" / "bin" / "python3"
        if _usable(candidate):
            return HookInterpreter(candidate, "CLAUDE_PLUGIN_DATA/.venv")

    candidate = base / ".venv" / "bin" / "python3"
    if _usable(candidate):
        return HookInterpreter(candidate, "<repo>/.venv")

    registry_root = env.get("ONEX_REGISTRY_ROOT", "")
    if registry_root:
        candidate = Path(registry_root) / "omniclaude" / ".venv" / "bin" / "python3"
        if _usable(candidate):
            return HookInterpreter(candidate, "ONEX_REGISTRY_ROOT/omniclaude/.venv")

    project_root = env.get("OMNICLAUDE_PROJECT_ROOT", "")
    if project_root:
        candidate = Path(project_root) / ".venv" / "bin" / "python3"
        if _usable(candidate):
            return HookInterpreter(candidate, "OMNICLAUDE_PROJECT_ROOT/.venv")

    return None


def describe_hook_interpreter(
    env: Mapping[str, str] | None = None,
    root: Path | None = None,
) -> str:
    """One line naming the resolved interpreter, or saying none resolved.

    Printed unconditionally by both gates. A readback that is silent about what
    it looked at cannot be told apart from one that looked at nothing
    (OMN-18663).
    """
    resolved = resolve_hook_interpreter(env, root)
    if resolved is None:
        return (
            "hook interpreter: none resolved on this host "
            "(find_python() chain answered nothing — expected on a CI runner "
            "with no venv built; nothing was read back)"
        )
    return f"hook interpreter: {resolved.path} (via {resolved.source})"


def check_orphan_absent(root: Path | None = None) -> list[str]:
    """Return a finding when the orphan hooks venv exists; empty list when not."""
    orphan = orphan_venv_path(root)
    if not orphan.exists():
        return []
    return [
        f"orphan hooks venv present at {orphan} — it left find_python()'s "
        "resolution chain in 035707dd2 (OMN-7310, 2026-04-02), no builder "
        "rebuilds it and no pin file declares it, so whatever it carries is "
        "unreconcilable. Remove it: rm -rf the path above (it is gitignored "
        "and nothing reads it). Do NOT rebuild or bump it."
    ]


def _tracked_files(root: Path) -> list[str]:
    """Repo-relative paths of tracked files. Raises on an unreadable tree."""
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    return [entry for entry in result.stdout.split("\0") if entry]


def scan_orphan_interpreter_references(root: Path | None = None) -> list[str]:
    """Tracked files that RUN the orphan venv as an interpreter.

    Naming the directory in prose is fine — its removal is a fact worth
    recording. Executing it is not: ``verify_plugin/SKILL.md`` instructed a probe
    through it, and ``user_prompt_session_phase_enforcement.sh`` preferred it
    ahead of the resolved interpreter, five months after it stopped being built.

    Returns ``path:line`` strings, sorted. Allowlisted fixtures and historical
    records are excluded by exact path, with a reason recorded beside each.
    """
    base = root if root is not None else repo_root()
    offenders: list[str] = []
    for relative in _tracked_files(base):
        if relative in _SCAN_ALLOWLIST:
            continue
        path = base / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if _ORPHAN_INTERPRETER_RE.search(line):
                offenders.append(f"{relative}:{number}")
    return sorted(offenders)
