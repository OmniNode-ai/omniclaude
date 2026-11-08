# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The FRICTION row for a refusal no interpreter could record (OMN-20883, OMN-23017).

``hook_refusal.sh`` runs the recorder under each interpreter it can find. When
every one of them fails to import the recorder's row module, the refusal would
reach no ledger at all, so the shell runs THIS file, by path, under any
interpreter that starts: it is standard-library only and imports nothing from
this package, because the interpreters that failed are exactly the ones that
cannot import the package's dependencies.

The row carries the refusal's own text (credentials redacted by the plugin hook
library's ``secret_redactor`` sibling, which is standard-library only too), the
interpreters that failed and the first line the last one printed, so the cause
is readable from the ledger row alone. The recorder's hourly rate limit is not
available here, so this path writes one row per refusal: a broken recorder is
the loud case, and a loud row is the point.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol, cast

#: The ledger's cell separator and quote never reach a cell value.
_CELL_UNSAFE = re.compile(r"[|\"\\\x00-\x1f]")
_PATH_UNSAFE = re.compile(r"[^A-Za-z0-9._:@/,+-]")
_ID_UNSAFE = re.compile(r"[^A-Za-z0-9._:@/-]")
_TEXT_WITHHELD = "refusal text unavailable: the redactor could not run, see hooks.log"
_LANE_VARIABLES = ("ONEX_LANE", "ONEX_LANE_ID", "ONEX_AGENT_NAME", "CLAUDE_AGENT_NAME")


class ProtocolFallbackFacts(Protocol):
    """What this handler reads of ``ModelHookRefusalFallbackRequest``.

    The model is pydantic; this file must start under an interpreter that has
    no packages, so it names the attributes it reads and the process entry
    builds a plain stand-in.
    """

    guard: str
    reason: str
    detail: str
    hooks_lib: str
    import_error: str
    interpreters: tuple[str, ...]


def _redactor(hooks_lib: str) -> Callable[[str], str] | None:
    """The plugin hook library's ``redact_secrets``, or None when it cannot load."""
    sys.path.insert(0, hooks_lib)
    try:
        return cast(
            "Callable[[str], str]",
            importlib.import_module("secret_redactor").redact_secrets,
        )
    except ImportError:
        return None
    finally:
        sys.path.remove(hooks_lib)


def cell_text(text: str, redact: Callable[[str], str] | None, limit: int = 240) -> str:
    """The first non-blank line, redacted BEFORE it is cut, safe for a ledger cell."""
    if redact is None:
        return _TEXT_WITHHELD
    line = next((ln for ln in text.splitlines() if ln.strip()), "")
    return " ".join(_CELL_UNSAFE.sub(" ", redact(line)).split())[:limit]


def lane_from_env(env: Mapping[str, str]) -> str:
    """The lane variable, without a dispatch ROUTE line, or '' when none is set."""
    for name in _LANE_VARIABLES:
        value = re.sub(r"ROUTE:.*", "", env.get(name, ""))
        line = next((ln for ln in value.splitlines() if ln.strip()), "")
        if line:
            return _ID_UNSAFE.sub("-", line)[:120]
    return ""


def build_row(
    request: ProtocolFallbackFacts,
    env: Mapping[str, str],
    stamp: str,
    redact: Callable[[str], str] | None,
) -> str:
    """The FRICTION row, in the grammar the recorder's own rows use."""
    lane = lane_from_env(env)
    guard = _ID_UNSAFE.sub("-", request.guard)[:120]
    return " | ".join(
        [
            stamp,
            "FRICTION",
            f"lane={lane or 'unresolved'}",
            "actor=hook",
            "model=none",
            "class=refusal",
            f"guard={guard}",
            "reason=recorder-import-failure",
            f"lane_source={'fallback-env' if lane else 'unresolved'}",
            f"dedupe=fallback-{guard}",
            "refusal_count=1",
            "suppressed_since_last_row=0",
            "interpreter="
            + (_PATH_UNSAFE.sub("-", ",".join(request.interpreters))[:400] or "none"),
            f'import_error="{cell_text(request.import_error, lambda t: t, 200)}"',
            f'detail="{cell_text(request.detail or request.reason, redact)}"',
            "existing=OMN-20883",
            "cost=~1 lane-minute",
            "This row exists because the hook refusal recorder could not run "
            "(OMN-20883): no interpreter listed could import its row module (OMN-23017)",
        ]
    )


def write_fallback_row(
    request: ProtocolFallbackFacts,
    env: Mapping[str, str] | None = None,
) -> int:
    """Append the row through the ledger writer; 0 when written or nothing can be."""
    env = os.environ if env is None else env
    root = env.get("OMNI_HOME") or env.get("ONEX_REGISTRY_ROOT") or ""
    if not root.startswith("/"):
        return 0
    # The writer is deployment configuration, not a repository-name default.
    project = env.get("OMNIBASE_INTERNAL_HOME", "")
    if not project.startswith("/"):
        sys.stderr.write(
            "hook refusal fallback: set OMNIBASE_INTERNAL_HOME to the absolute "
            "ledger writer project\n"
        )
        return 0
    ledger = (
        env.get("ONEX_LEDGER_PATH") or f"{root}/docs/tracking/ROLLING_WORK_LEDGER.md"
    )
    if not (Path(project, "pyproject.toml").is_file() and Path(ledger).is_file()):
        return 0
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    row = build_row(request, env, stamp, _redactor(request.hooks_lib))
    subprocess.run(
        ["uv", "run", "--quiet", "--project", project, "onex-ledger", ledger]
        + ["--append", row, "--timeout", "120s"],
        check=False,
    )
    return 0


class HandlerHookRefusalFallback:
    """Writes the row for a refusal no interpreter could record."""

    def handle(self, request: ProtocolFallbackFacts) -> int:
        """Append the fallback row for ``request``; 0 when written or nothing can be."""
        return write_fallback_row(request)
