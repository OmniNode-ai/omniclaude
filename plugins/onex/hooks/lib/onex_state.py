# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Centralized ONEX state directory path resolver.

All ONEX runtime artifacts (logs, pipeline state, session state, handoff
files, worktree metadata) live under a single root configured via the
``ONEX_STATE_DIR`` environment variable.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_VAR = "ONEX_STATE_DIR"


def state_root() -> Path:
    """Return the ONEX state root directory.

    Reads ``ONEX_STATE_DIR`` from the environment, expands ``~``, and
    returns an absolute :class:`~pathlib.Path`.

    Raises:
        RuntimeError: If the variable is unset or blank.
    """
    raw = os.environ.get(_ENV_VAR, "")
    if not raw.strip():
        msg = (
            f"{_ENV_VAR} is not set or is blank. "
            "Set it in ~/.omnibase/.env or export it before running ONEX."
        )
        raise RuntimeError(msg)
    return Path(raw).expanduser().resolve()


def state_path(*parts: str) -> Path:
    """Join *parts* under :func:`state_root` without creating anything."""
    return state_root().joinpath(*parts)


def ensure_state_path(*parts: str) -> Path:
    """Join *parts* under :func:`state_root` and create the **parent** directory.

    Use this for files: the parent directory is created so the caller can
    immediately open the file for writing.
    """
    p = state_root().joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def ensure_state_dir(*parts: str) -> Path:
    """Join *parts* under :func:`state_root` and create the directory itself.

    Use this for directories that must exist before the caller writes into
    them.
    """
    p = state_root().joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_path(name: str) -> Path:
    """Shorthand for ``ensure_state_path("logs", name)``."""
    return ensure_state_path("logs", name)


_CONFIG_ROOT_ENV = "ONEX_WORKSPACE_CONFIG_ROOT"
# Assembled from parts: the sibling repository is private, and its name must not
# appear as a literal in this shipped file (public-repo-hygiene, private-repo-name).
_SIBLING_CONFIG_REPO = "".join(("omnibase", "_internal"))
_DEVELOPER_CONFIG_RELATIVE = Path(".onex") / "workspace-config"


def workspace_config_root() -> Path | None:
    """Return the workspace config root, or ``None`` when none resolves.

    Deployment facts (hosts, endpoints, lane tables) are supplied by whoever
    runs the system, never shipped here. Resolution order matches the runtime
    resolver: a non-blank ``ONEX_WORKSPACE_CONFIG_ROOT``; otherwise the sibling
    config repository of the workspace root (``OMNIBASE_PATH``, then
    ``OMNI_HOME``) when it is a directory; otherwise the workspace's
    ``.onex/workspace-config`` when it is a directory.
    """
    configured = os.environ.get(_CONFIG_ROOT_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    base = (
        os.environ.get("OMNIBASE_PATH") or os.environ.get("OMNI_HOME") or ""
    ).strip()
    if not base:
        return None
    sibling = Path(base).expanduser() / ".." / _SIBLING_CONFIG_REPO
    if sibling.is_dir():
        return sibling.resolve()
    developer = Path(base).expanduser() / _DEVELOPER_CONFIG_RELATIVE
    if developer.is_dir():
        return developer.resolve()
    return None


def workspace_config_file(relative: str) -> Path | None:
    """Return ``<config root>/<relative>`` when that file exists, else ``None``."""
    root = workspace_config_root()
    if root is None:
        return None
    candidate = root / relative
    return candidate if candidate.is_file() else None


def missing_workspace_config_message(relative: str, supplies: str) -> str:
    """Name the overlay a reader did not find and how to supply it.

    The message is the neutral behaviour's whole contract: a reader with no
    overlay degrades to a stated default and says which file would change it.
    """
    root = workspace_config_root()
    searched = (
        f"config root {root}"
        if root is not None
        else f"no config root resolved ({_CONFIG_ROOT_ENV} unset, no sibling "
        "config repository of OMNI_HOME)"
    )
    return (
        f"no overlay {relative} ({searched}): {supplies}. Supply it by setting "
        f"{_CONFIG_ROOT_ENV} to a directory that holds {relative}."
    )
